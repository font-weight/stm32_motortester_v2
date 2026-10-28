/* U differential oracle: separately compiled frozen SL and candidate SN.
 * No implementation of either collect algorithm is duplicated. Check every
 * state/storage byte, then independently unpack completed frames and CRCs.
 * This is pure serializer evidence, not runtime ownership or USB timing. */
#include "mt_batch1024.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DECLARE(P) \
int P##begin(mt_batch1024_state*,uint8_t*,const mt_batch1024_identity*,uint32_t); \
int P##collect(mt_batch1024_state*,uint8_t*,uint64_t,const uint16_t*,uint16_t); \
int P##seal(mt_batch1024_state*,uint8_t*); \
int P##step(mt_batch1024_state*,uint8_t*,uint16_t); \
int P##piece(const mt_batch1024_state*,const uint8_t*,const uint8_t**,size_t*); \
int P##accepted(mt_batch1024_state*,size_t); \
int P##commit(mt_batch1024_state*,uint64_t,int,uint64_t*,uint32_t*); \
void P##abort(mt_batch1024_state*)
DECLARE(sl_);DECLARE(sn_);
typedef struct {
    int (*begin)(mt_batch1024_state*,uint8_t*,const mt_batch1024_identity*,uint32_t);
    int (*collect)(mt_batch1024_state*,uint8_t*,uint64_t,const uint16_t*,uint16_t);
    int (*seal)(mt_batch1024_state*,uint8_t*);
    int (*step)(mt_batch1024_state*,uint8_t*,uint16_t);
    int (*piece)(const mt_batch1024_state*,const uint8_t*,const uint8_t**,size_t*);
    int (*accepted)(mt_batch1024_state*,size_t);
    int (*commit)(mt_batch1024_state*,uint64_t,int,uint64_t*,uint32_t*);
    void (*abort)(mt_batch1024_state*);
} api;
#define API(P) {P##begin,P##collect,P##seal,P##step,P##piece,P##accepted,P##commit,P##abort}
static const api impl[2]={API(sl_),API(sn_)};
typedef struct {uint8_t before[8],bytes[MT_BATCH1024_CAPACITY],after[8];} guarded;
static guarded bank[2];static mt_batch1024_state state[2];
static uint16_t samples[1025];static uint8_t decoded[1328];
static unsigned calls,frames;static const char*scene="init";
static const uint32_t seed=UINT32_C(0x13579bdf);
static mt_batch1024_identity identity;
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL collect %s line%d: %s\n",scene,__LINE__,#x);exit(1);}}while(0)
static uint32_t crc_byte(uint32_t c,uint8_t b){c^=b;for(unsigned i=0;i<8;i++)c=(c>>1)^((c&1u)?UINT32_C(0xedb88320):0);return c;}
static uint16_t r16(const uint8_t*p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t r32(const uint8_t*p){uint32_t n=0;for(unsigned i=0;i<4;i++)n|=(uint32_t)p[i]<<(8*i);return n;}
static uint64_t r64(const uint8_t*p){return (uint64_t)r32(p)|((uint64_t)r32(p+4)<<32);}
static uint32_t prefix_crc(unsigned count){
    uint32_t crc=seed;for(unsigned i=0;i<count;i++){uint16_t v=samples[i]&4092u;crc=crc_byte(crc,(uint8_t)v);crc=crc_byte(crc,(uint8_t)(v>>8));}return crc;
}
static void same(int a,int b){
    ++calls;CHECK(a==b && !memcmp(state,state+1,sizeof state[0]) && !memcmp(bank,bank+1,sizeof bank[0]));
    for(unsigned k=0;k<2;k++)for(unsigned j=0;j<8;j++)CHECK(bank[k].before[j]==0xa5 && bank[k].after[j]==0x5a);
}
static void reset(unsigned pattern){
    memset(state,0,sizeof state);
    for(unsigned k=0;k<2;k++){memset(bank[k].bytes,0xc7,sizeof bank[k].bytes);memset(bank[k].before,0xa5,8);memset(bank[k].after,0x5a,8);}
    for(unsigned i=0;i<1025;i++)samples[i]=(uint16_t)(pattern==0?0:pattern==1?4095:(i*37u+3u)&4095u);
    identity=(mt_batch1024_identity){UINT64_C(0x0102030405060708),UINT64_C(0x100000011),3,5,4};
}
static void begin(void){
    int r[2];for(unsigned k=0;k<2;k++)r[k]=impl[k].begin(state+k,bank[k].bytes,&identity,seed);
    same(r[0],r[1]);CHECK(r[0]==1);
}
static void collect(unsigned offset,unsigned count){
    int r[2];for(unsigned k=0;k<2;k++)r[k]=impl[k].collect(state+k,bank[k].bytes,identity.first_index+offset,samples+offset,(uint16_t)count);
    same(r[0],r[1]);CHECK(r[0]==1 && state[0].count==offset+count && state[0].prefix_crc==prefix_crc(offset+count));
    CHECK(state[0].packed_bytes==((offset+count)*10u+7u)/8u);
}
static void verify_frame(void){
    unsigned at=0,n=0,end=state[0].length-1;
    CHECK(state[0].length<=1335 && !bank[0].bytes[end]);
    while(at<end){unsigned code=bank[0].bytes[at++];CHECK(code && code-1<=end-at && n+code-1<=sizeof decoded);
        for(unsigned i=1;i<code;i++){CHECK(bank[0].bytes[at]);decoded[n++]=bank[0].bytes[at++];}
        if(code!=255 && at<end){CHECK(n<sizeof decoded);decoded[n++]=0;}}
    CHECK(n==48u+(state[0].count*10u+7u)/8u);
    CHECK(decoded[0]==0 && decoded[1]==3 && decoded[2]==152 && !decoded[3] && !r16(decoded+6));
    CHECK(r16(decoded+4)==n-28 && r64(decoded+8)==identity.nonce && r32(decoded+16)==identity.sequence);
    CHECK(!r32(decoded+20) && r32(decoded+24)==identity.generation && r32(decoded+28)==5);
    CHECK(r64(decoded+32)==identity.first_index && r16(decoded+40)==state[0].count && !r16(decoded+42));
    uint32_t pending=0,crc=UINT32_MAX;unsigned offset=44,bits=0;
    for(unsigned i=0;i<state[0].count;i++){
        while(bits<10){pending|=(uint32_t)decoded[offset++]<<bits;bits+=8;}
        CHECK(((pending&1023u)<<2)==(samples[i]&4092u));pending>>=10;bits-=10;
    }
    CHECK(!pending && offset==n-4);
    for(unsigned i=0;i<n-4;i++)crc=crc_byte(crc,decoded[i]);
    CHECK((crc^UINT32_MAX)==r32(decoded+n-4) && state[0].prefix_crc==prefix_crc(state[0].count));
}
static void finish(unsigned budget){
    int r[2];unsigned turns=0;
    for(unsigned k=0;k<2;k++)r[k]=impl[k].seal(state+k,bank[k].bytes);
    same(r[0],r[1]);CHECK(r[0]==1);
    while(state[0].phase!=MT_BATCH1024_READY){
        for(unsigned k=0;k<2;k++)r[k]=impl[k].step(state+k,bank[k].bytes,(uint16_t)budget);
        same(r[0],r[1]);CHECK(r[0]>=0 && (unsigned)r[0]<=budget && ++turns<2700);
    }
    verify_frame();
    guarded immutable=bank[0];
    while(state[0].offset<state[0].length){
        const uint8_t*p[2]={0};size_t n[2]={0};
        for(unsigned k=0;k<2;k++)r[k]=impl[k].piece(state+k,bank[k].bytes,p+k,n+k);
        same(r[0],r[1]);CHECK(r[0]==1 && n[0]==n[1] && n[0]<=384 && p[0]-bank[0].bytes==p[1]-bank[1].bytes);
        for(unsigned k=0;k<2;k++)r[k]=impl[k].accepted(state+k,n[k]);same(r[0],r[1]);CHECK(r[0]==1);
    }
    uint64_t end[2]={identity.first_index,identity.first_index};uint32_t crc[2]={seed,seed};
    for(unsigned k=0;k<2;k++)r[k]=impl[k].commit(state+k,identity.first_index,1,end+k,crc+k);
    same(r[0],r[1]);CHECK(r[0]==1 && end[0]==identity.first_index+state[0].count && end[0]==end[1]);
    CHECK(crc[0]==prefix_crc(state[0].count) && crc[0]==crc[1] && !memcmp(&immutable,bank,sizeof immutable));++frames;
}
static void alignment_and_boundaries(void){
    scene="four start and four append-tail alignments";
    for(unsigned start=0;start<4;start++)for(unsigned tail=0;tail<4;tail++){
        reset((start+tail)%3);begin();if(start)collect(0,start);collect(start,128+tail);finish(tail?128:1);
    }
    scene="collect 1/128/512 and exact full1024";
    const unsigned counts[]={1,128,512};
    for(unsigned i=0;i<3;i++){reset(i);begin();collect(0,counts[i]);finish(512);}
    for(unsigned pattern=0;pattern<3;pattern++){
        reset(pattern);begin();collect(0,512);collect(512,512);finish(pattern==0?1:pattern==1?128:512);
    }
    for(unsigned start=1;start<4;start++){
        reset(2);begin();collect(0,start);collect(start,512);collect(start+512,512-start);finish(512);
    }
    puts("PASS all4 starting and all4 append-tail alignments; canonical0/max/mixed; 1/128/512/full1024; exact state/storage/frame/prefix CRC and immutable accepted frame");
}
static void rejected(unsigned kind){
    int r[2];mt_batch1024_state old[2];guarded old_bank[2];memcpy(old,state,sizeof old);memcpy(old_bank,bank,sizeof old_bank);
    for(unsigned k=0;k<2;k++){
        mt_batch1024_state*s=state+k;uint8_t*b=bank[k].bytes;
        const uint16_t*p=samples+(s->count<=897u?s->count:0u);
        uint64_t first=identity.first_index+s->count;uint16_t count=128;
        if(kind==0)s=NULL;if(kind==1)b=NULL;if(kind==2)p=NULL;
        if(kind==3)count=0;if(kind==4)count=513;if(kind==5)++first;
        r[k]=impl[k].collect(s,b,first,p,count);
    }
    same(r[0],r[1]);CHECK(r[0]==0 && !memcmp(old,state,sizeof old) && !memcmp(old_bank,bank,sizeof old_bank));
}
static void validation_before_any_write(void){
    scene="invalid inputs and late bad code are immutable";
    for(unsigned kind=0;kind<6;kind++){reset(2);begin();collect(0,3);rejected(kind);}
    reset(2);begin();collect(0,3);samples[3+127]=4096;rejected(6);
    reset(2);begin();collect(0,3);state[0].phase=state[1].phase=MT_BATCH1024_READY;rejected(6);
    reset(2);begin();state[0].count=state[1].count=1025;
    /* Non-NULL readable pointer; invalid state must reject before indexing it. */
    int r[2];guarded saved[2];memcpy(saved,bank,sizeof saved);
    for(unsigned k=0;k<2;k++)r[k]=impl[k].collect(state+k,bank[k].bytes,identity.first_index,samples,1);
    same(r[0],r[1]);CHECK(!r[0] && state[0].count==1025 && !memcmp(saved,bank,sizeof saved));
    reset(2);begin();collect(0,512);collect(512,512);rejected(6);
    reset(2);identity.first_index=UINT64_MAX-2;begin();collect(0,2);
    mt_batch1024_state before[2];memcpy(before,state,sizeof before);memcpy(saved,bank,sizeof saved);
    for(unsigned k=0;k<2;k++)r[k]=impl[k].collect(state+k,bank[k].bytes,UINT64_MAX,samples+2,1);
    same(r[0],r[1]);CHECK(!r[0] && !memcmp(before,state,sizeof before) && !memcmp(saved,bank,sizeof saved));
    puts("PASS null/count0/count513/phase/count1025/index/overflow/full-capacity and last-code4096 reject before any state or storage mutation");
}
static void speculative_shared_byte_retry(void){
    scene="discarded work state and shared-byte retry";
    for(unsigned alignment=1;alignment<4;alignment++){
        reset(0);begin();collect(0,alignment);collect(alignment,128);
        mt_batch1024_state expected=state[0];guarded expected_bank=bank[0];
        reset(0);begin();collect(0,alignment);
        mt_batch1024_state owned[2],work[2];memcpy(owned,state,sizeof owned);memcpy(work,state,sizeof work);
        uint16_t wrong[128];for(unsigned i=0;i<128;i++)wrong[i]=4095;
        int r[2];for(unsigned k=0;k<2;k++)r[k]=impl[k].collect(work+k,bank[k].bytes,identity.first_index+alignment,wrong,128);
        same(r[0],r[1]);CHECK(r[0]==1 && !memcmp(work,work+1,sizeof work[0]) && !memcmp(owned,state,sizeof owned));
        /* Caller rejects only the WORK state. Already written speculative high
         * bits remain, so replacement input must overwrite them deterministically. */
        collect(alignment,128);
        CHECK(!memcmp(&expected,state,sizeof expected) && !memcmp(&expected_bank,bank,sizeof expected_bank));finish(128);
    }
    puts("PASS rejected-work retry at shifts2/4/6 replaces speculative shared-byte high bits and preserves owned low bits; whole storage exactly matches clean append");
}
int main(void){
    CHECK(sizeof(mt_batch1024_state)==32 && MT_BATCH1024_CAPACITY==1336);
    alignment_and_boundaries();validation_before_any_write();speculative_shared_byte_retry();
    printf("differential_calls=%u; completed_frames=%u; hardware=0; throughput_claim=0\n",calls,frames);return 0;
}
