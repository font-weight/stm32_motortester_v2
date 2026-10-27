#include "mt_batch1024.h"
#include "mt_v2_crc32.h"
#include <string.h>

#define RAW_BASE MT_BATCH1024_RAW_SHIFT
#define SAMPLES_BASE (RAW_BASE+44u)
static void put16(uint8_t*p,uint16_t n){p[0]=(uint8_t)n;p[1]=(uint8_t)(n>>8);}
static void put32(uint8_t*p,uint32_t n){unsigned i;for(i=0;i<4;i++)p[i]=(uint8_t)(n>>(8u*i));}
static void put64(uint8_t*p,uint64_t n){unsigned i;for(i=0;i<8;i++)p[i]=(uint8_t)(n>>(8u*i));}
static uint64_t get64(const uint8_t*p){uint64_t n=0;unsigned i;for(i=0;i<8;i++)n|=(uint64_t)p[i]<<(8u*i);return n;}

int mt_batch1024_begin(mt_batch1024_state*s,uint8_t*b,
    const mt_batch1024_identity*i,uint32_t prefix){
    if(!s || !b || !i || !i->nonce || !i->generation || !i->sequence || i->config_id!=5u)return 0;
    *s=(mt_batch1024_state){.prefix_crc=prefix,.frame_crc=UINT32_MAX,
        .phase=MT_BATCH1024_COLLECT,.prefix_seed=prefix};
    memset(b+RAW_BASE,0,44u);
    b[RAW_BASE+1u]=3u;b[RAW_BASE+2u]=152u;
    put64(b+RAW_BASE+8u,i->nonce);put32(b+RAW_BASE+16u,i->sequence);
    put32(b+RAW_BASE+24u,i->generation);put32(b+RAW_BASE+28u,i->config_id);
    put64(b+RAW_BASE+32u,i->first_index);return 1;
}

int mt_batch1024_collect(mt_batch1024_state*s,uint8_t*b,uint64_t first,
    const uint16_t*p,uint16_t count){
    uint64_t origin;uint32_t crc;unsigned i,bit,byte,shift;uint16_t canonical,q;
    if(!s || !b || !p || s->phase!=MT_BATCH1024_COLLECT || !count ||
       count>MT_BATCH1024_QUANTUM_MAX || s->count>1024u || count>1024u-s->count)return 0;
    origin=get64(b+RAW_BASE+32u);
    if(UINT64_MAX-origin<s->count || first!=origin+s->count || UINT64_MAX-first<count)return 0;
    for(i=0;i<count;i++)if(p[i]>4095u)return 0; /* BEFORE any mask/copy */
    crc=s->prefix_crc;
    for(i=0;i<count;i++){
        canonical=(uint16_t)(p[i]&4092u);q=(uint16_t)(canonical>>2);
        bit=((unsigned)s->count+i)*10u;byte=bit>>3;shift=bit&7u;
        /* shift is0/2/4/6. Preserve ONLY already-owned low bits, replacing
         * speculative high bits even after a rejected work-copy admission.
         * This makes retry with different input safe across a shared byte. */
        if(shift)b[SAMPLES_BASE+byte]&=(uint8_t)((1u<<shift)-1u);
        else b[SAMPLES_BASE+byte]=0;
        b[SAMPLES_BASE+byte]|=(uint8_t)(q<<shift);
        b[SAMPLES_BASE+byte+1u]=(uint8_t)(q>>(8u-shift));
        crc=mt_v2_crc32_byte(crc,(uint8_t)canonical);
        crc=mt_v2_crc32_byte(crc,(uint8_t)(canonical>>8));
    }
    s->count=(uint16_t)(s->count+count);
    s->packed_bytes=(uint16_t)(((unsigned)s->count*10u+7u)/8u);
    s->prefix_crc=crc;return 1;
}

int mt_batch1024_seal(mt_batch1024_state*s,uint8_t*b){
    if(!s || !b || s->phase!=MT_BATCH1024_COLLECT || !s->count || s->count>1024u)return 0;
    put16(b+RAW_BASE+4u,(uint16_t)(20u+s->packed_bytes));
    put16(b+RAW_BASE+40u,s->count);
    s->raw_length=(uint16_t)(48u+s->packed_bytes);s->read=0;
    s->frame_crc=UINT32_MAX;s->phase=MT_BATCH1024_CRC;return 1;
}

int mt_batch1024_step(mt_batch1024_state*s,uint8_t*b,uint16_t budget){
    unsigned used=0,read,write,mark,raw_length;uint32_t crc;uint16_t code;uint8_t value;
    int result;
    if(!s || !b || !budget || budget>MT_BATCH1024_QUANTUM_MAX)return -1;
    if(s->phase==MT_BATCH1024_READY)return 0;
    if(s->phase==MT_BATCH1024_CRC){
        if(s->raw_length<50u || s->raw_length>1328u || s->read>s->raw_length-4u)return -1;
        /* State and byte storage are disjoint and foreground-owned. Keep the
         * running CRC/cursor local so a byte store cannot force a state reload.
         * The same bounded quantum is published before every function return. */
        raw_length=s->raw_length;read=s->read;crc=s->frame_crc;
        while(used<budget && read<raw_length-4u){
            crc=mt_v2_crc32_byte(crc,b[RAW_BASE+read]);++read;++used;
        }
        s->frame_crc=crc;s->read=(uint16_t)read;
        if(read==raw_length-4u){
            put32(b+RAW_BASE+raw_length-4u,crc^UINT32_MAX);
            s->read=0;s->write=1;s->mark=0;s->code=1;s->phase=MT_BATCH1024_COBS;
        }
        return (int)used;
    }
    if(s->phase!=MT_BATCH1024_COBS || s->read>s->raw_length || s->raw_length>1328u)return -1;
    raw_length=s->raw_length;read=s->read;write=s->write;mark=s->mark;code=s->code;
    while(used<budget && read<raw_length){
        value=b[RAW_BASE+read];++read;++used;
        /* The7-byte gap covers the worst COBS expansion, so these writes
         * cannot reach the next unread raw byte. Defensive check BEFORE write. */
        if(write>=RAW_BASE+read || write>=MT_BATCH1024_FRAME_MAX)goto cobs_invalid;
        if(!value){b[mark]=(uint8_t)code;mark=write++;code=1;}
        else{
            b[write++]=value;++code;
            if(code==255u){b[mark]=(uint8_t)code;mark=write++;code=1;}
        }
    }
    if(read==raw_length){
        if(write>=MT_BATCH1024_FRAME_MAX)goto cobs_invalid;
        b[mark]=(uint8_t)code;b[write++]=0;
        s->length=(uint16_t)write;s->offset=0;s->phase=MT_BATCH1024_READY;
    }
    result=(int)used;
    goto cobs_publish;
cobs_invalid:
    result=-1;
cobs_publish:
    /* A failed destructive step still publishes its consumed cursor exactly
     * as SE did. The caller must abort; restoring an old state is not rollback. */
    s->read=(uint16_t)read;s->write=(uint16_t)write;
    s->mark=(uint16_t)mark;s->code=(uint16_t)code;
    return result;
}

int mt_batch1024_piece(const mt_batch1024_state*s,const uint8_t*b,
    const uint8_t**p,size_t*n){
    size_t amount;
    if(!s || !b || !p || !n || s->phase!=MT_BATCH1024_READY ||
       !s->length || s->length>MT_BATCH1024_FRAME_MAX || s->offset>=s->length)return 0;
    amount=(size_t)s->length-s->offset;if(amount>MT_BATCH1024_WRITE_MAX)amount=MT_BATCH1024_WRITE_MAX;
    *p=b+s->offset;*n=amount;return 1;
}
int mt_batch1024_accepted(mt_batch1024_state*s,size_t n){
    size_t amount;
    if(!s || s->phase!=MT_BATCH1024_READY || s->offset>s->length ||
       !s->length || s->length>MT_BATCH1024_FRAME_MAX)return 0;
    amount=(size_t)s->length-s->offset;if(amount>MT_BATCH1024_WRITE_MAX)amount=MT_BATCH1024_WRITE_MAX;
    if(n>amount)return 0;
    s->offset=(uint16_t)(s->offset+n);return 1;
}
int mt_batch1024_commit(mt_batch1024_state*s,uint64_t first,int valid,
    uint64_t*end,uint32_t*crc){
    if(!s || !end || !crc || valid!=1 || s->phase!=MT_BATCH1024_READY ||
       !s->length || s->offset!=s->length || *end!=first || *crc!=s->prefix_seed ||
       UINT64_MAX-first<s->count)return 0;
    *end=first+s->count;*crc=s->prefix_crc;s->phase=MT_BATCH1024_DONE;return 1;
}
void mt_batch1024_abort(mt_batch1024_state*s){if(s)s->phase=MT_BATCH1024_ABORTED;}
