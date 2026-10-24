/* Real SD core/queue/wire, logical IO callbacks only. Queue API wrap coverage
 * is independent of protocol reachability; no hot mode switch is simulated. */
#include "mt_live_device.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
static mt_live_device dev;
static uint8_t sent[2048];static size_t sent_used,limit;
static uint64_t clock_ms;static unsigned starts,writes,write_kind,tail_count;
static FILE *fixture;
void whole_fit_space(size_t n);
unsigned whole_fit_calls(void);
size_t whole_fit_accept(const uint8_t *p,size_t n);
static uint16_t r16(const uint8_t*p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t r32(const uint8_t*p){uint32_t n=0;for(unsigned i=0;i<4;i++)n|=(uint32_t)p[i]<<(8*i);return n;}
static uint64_t r64(const uint8_t*p){return (uint64_t)r32(p)|((uint64_t)r32(p+4)<<32);}
static void w32(uint8_t*p,uint32_t n){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i));}
static void w64(uint8_t*p,uint64_t n){for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(n>>(8*i));}
static uint64_t now(void*p){(void)p;return clock_ms;}
static int start(void*p,uint32_t g){(void)p;CHECK(g==3 && dev.mode>=1 && dev.mode<=4);++starts;return 1;}
static void stop(void*p,mt_live_snapshot*s){
    (void)p;*s=(mt_live_snapshot){.hardware_off=1};
    for(unsigned i=0;i<tail_count;i++){
        unsigned block=i/128,at=i%128;
        s->tail[block].first_index=dev.queue.next_index+block*128;
        s->tail[block].codes[at]=(uint16_t)(4095u-i);
        s->tail[block].count=(uint16_t)(at+1);s->tail_count=block+1;
    }
}
static size_t write_bytes(void*p,const uint8_t*b,size_t n){
    (void)p;++writes;if(write_kind==2)return SIZE_MAX;
    if(write_kind==1)n=whole_fit_accept(b,n);else if(n>limit)n=limit;
    CHECK(n<=384 && sent_used+n<=sizeof sent);memcpy(sent+sent_used,b,n);sent_used+=n;
    if(write_kind==3)clock_ms=0;
    return n;
}
static int isolate(void*p){(void)p;return 1;}
static void reset(void){
    mt_live_io io={.clock_ms=now,.start=start,.quiesce=stop,.write=write_bytes,
        .isolate_tx=isolate,.transaction_bound_ms=1,.firmware_build=0x56325344u};
    CHECK(mt_live_device_init(&dev,&io));sent_used=0;limit=SIZE_MAX;clock_ms=1;
    starts=writes=write_kind=tail_count=0;
}
static void command(unsigned rev,unsigned type,uint64_t nonce,uint32_t seq,uint32_t req,
                    const uint8_t*p,uint16_t n){
    mt_wire_message m={.type=(uint8_t)type,.session=nonce,.sequence=seq,.request=req,.payload_length=n};
    uint8_t b[MT_WIRE_FRAME_MAX];size_t used;if(n)memcpy(m.payload,p,n);
    CHECK(mt_wire_encode_revision(&m,0,(uint8_t)rev,b,sizeof b,&used)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&dev,b,used));
}
static void hello(unsigned rev,uint64_t nonce,unsigned mode){
    uint8_t p[12]={0};w64(p,nonce);p[8]=(uint8_t)mode;
    command(rev,1,0,1,1,p,rev==2?8:12);
}
static mt_wire_message decoded(unsigned rev,unsigned type){
    mt_wire_message m;CHECK(sent_used && sent[sent_used-1]==0);
    CHECK(mt_wire_decode_revision(sent,sent_used-1,0,(uint8_t)rev,&m)==MT_WIRE_OK);
    CHECK(m.type==type);return m;
}
static mt_wire_message flush(unsigned rev,unsigned type){
    unsigned budget=64;sent_used=0;
    do{CHECK(budget--);CHECK(mt_live_device_step(&dev));}while(dev.tx_length);
    return decoded(rev,type);
}
static void active(unsigned mode){
    reset();hello(2,123,0);mt_wire_message m=flush(2,129);
    CHECK(r16(m.payload+6)==256 && r32(m.payload+12)==7 && starts==0);
    hello(3,503,mode);m=flush(3,129);
    unsigned max=mode==4?256:128;
    CHECK(m.payload[1]==3 && r16(m.payload+6)==max && r32(m.payload+12)==1);
    command(3,2,503,2,2,NULL,0);m=flush(3,130);
    CHECK(r32(m.payload)==mode && r16(m.payload+4)==mode && r16(m.payload+16)==max);
    CHECK(m.payload[18]==(mode>=3?10:12) && m.payload[19]==(mode>=3?2:1));
    uint8_t p[4];w32(p,mode);command(3,8,503,3,3,p,4);m=flush(3,136);
    CHECK(starts==1 && dev.state==MT_LIVE_STREAMING && r32(m.payload+4)==mode);
}
static uint32_t crc_byte(uint32_t crc,uint8_t b){
    crc^=b;for(unsigned i=0;i<8;i++)crc=(crc>>1)^((crc&1u)?0xedb88320u:0);return crc;
}
static uint32_t crc_codes(uint32_t crc,const uint16_t*p,unsigned n,unsigned mode){
    for(unsigned i=0;i<n;i++){
        uint16_t c=mode>=3?(uint16_t)(p[i]&0xffc):p[i];
        crc=crc_byte(crc,(uint8_t)c);crc=crc_byte(crc,(uint8_t)(c>>8));
    }return crc;
}
static void samples(const mt_wire_message*m,const uint16_t*original,unsigned n,unsigned mode,uint64_t first){
    CHECK(r32(m->payload)==3 && r32(m->payload+4)==mode && r64(m->payload+8)==first);
    CHECK(r16(m->payload+16)==n && r16(m->payload+18)==0);
    if(mode<3){CHECK(m->payload_length==20+2*n);for(unsigned i=0;i<n;i++)CHECK(r16(m->payload+20+2*i)==original[i]);}
    else{
        unsigned at=20,bits=0;uint32_t pending=0;CHECK(m->payload_length==20+(10*n+7)/8);
        for(unsigned i=0;i<n;i++){
            while(bits<10){pending|=(uint32_t)m->payload[at++]<<bits;bits+=8;}
            CHECK((pending&1023)==(original[i]>>2));pending>>=10;bits-=10;
        }CHECK(pending==0);
    }
}
static void stop_command(unsigned n){uint8_t p[4]={3,0,0,0};tail_count=n;command(3,5,503,4,4,p,4);}
static void queue_atomicity(void){
    mt_sample_queue q;uint16_t x[128];mt_sample_block b[2];
    for(unsigned i=0;i<128;i++)x[i]=(uint16_t)i;
    mt_sample_queue_init(&q,0);
    for(unsigned i=0;i<7;i++){
        CHECK(mt_sample_queue_push(&q,i*128,x,128,0)==MT_SAMPLE_QUEUE_OK);
        CHECK(mt_sample_queue_pop(&q,i*128)==MT_SAMPLE_QUEUE_OK);
    }
    CHECK(q.head==7 && q.head_index==896);
    CHECK(mt_sample_queue_push(&q,896,x,128,0)==MT_SAMPLE_QUEUE_OK);
    CHECK(mt_sample_queue_push(&q,1024,x,128,0)==MT_SAMPLE_QUEUE_OK);
    CHECK(mt_sample_queue_peek_offset(&q,0,&b[0])==MT_SAMPLE_QUEUE_OK);
    CHECK(mt_sample_queue_peek_offset(&q,1,&b[1])==MT_SAMPLE_QUEUE_OK);
    CHECK(b[0].samples==q.samples[7] && b[1].samples==q.samples[0]);
    mt_sample_queue before=q;--b[1].count;
    CHECK(mt_sample_queue_pop_span(&q,b,2)==MT_SAMPLE_QUEUE_STALE && memcmp(&q,&before,sizeof q)==0);
    ++b[1].count;++b[1].first_index;
    CHECK(mt_sample_queue_pop_span(&q,b,2)==MT_SAMPLE_QUEUE_STALE && memcmp(&q,&before,sizeof q)==0);
    --b[1].first_index;b[1].samples=q.samples[1];
    CHECK(mt_sample_queue_pop_span(&q,b,2)==MT_SAMPLE_QUEUE_STALE && memcmp(&q,&before,sizeof q)==0);
    b[1].samples=q.samples[0];CHECK(mt_sample_queue_pop_span(&q,b,2)==MT_SAMPLE_QUEUE_OK);
    CHECK(q.head==1 && !q.used && q.head_index==1152);
    puts("PASS bounded queue wrap7to0 / stale second count,index,slot leaves entire queue unchanged / atomic span2");
}
static void batches_and_tails(void){
    uint16_t x[256];for(unsigned i=0;i<256;i++)x[i]=4095;
    active(4);CHECK(mt_live_device_offer(&dev,0,x,128));
    sent_used=0;CHECK(mt_live_device_step(&dev));CHECK(!sent_used && dev.queue.used==1 && dev.prefix_end==0);
    CHECK(mt_live_device_offer(&dev,128,x+128,128));mt_live_tx_ticket t;
    CHECK(mt_live_device_prepare_tx(&dev,&t)==MT_LIVE_TX_PREPARED && dev.tx_length==371 && dev.tx_blocks==2);
    whole_fit_space(370);write_kind=1;sent_used=0;CHECK(mt_live_device_step_prepared(&dev,&t));
    CHECK(!sent_used && !whole_fit_calls() && dev.queue.used==2 && dev.prefix_end==0);
    whole_fit_space(371);CHECK(mt_live_device_step_prepared(&dev,&t));
    CHECK(sent_used==371 && whole_fit_calls()==1 && dev.prefix_end==256 && !dev.queue.used);
    mt_wire_message m=decoded(3,152);samples(&m,x,256,4,0);

    const unsigned tails[]={1,2,3,127,128,129,255,257};
    for(unsigned k=0;k<sizeof tails/sizeof tails[0];k++){
        unsigned n=tails[k];uint16_t tail[257];for(unsigned i=0;i<n;i++)tail[i]=(uint16_t)(4095-i);
        active(4);stop_command(n);CHECK(dev.queue.sealed && dev.state==MT_LIVE_DRAINING);
        unsigned done=0;
        while(done<n){unsigned count=n-done>=256?256:n-done;m=flush(3,152);samples(&m,tail+done,count,4,done);done+=count;}
        m=flush(3,153);CHECK(r64(m.payload+8)==n && r32(m.payload+28)==(crc_codes(0xffffffffu,tail,n,4)^0xffffffffu));
        (void)flush(3,133);CHECK(dev.state==MT_LIVE_NEEDS_HELLO);
    }
    for(unsigned mode=1;mode<=3;mode++){
        active(mode);for(unsigned i=0;i<128;i++)x[i]=(uint16_t)(i*19+3);
        CHECK(mt_live_device_offer(&dev,0,x,128));m=flush(3,152);samples(&m,x,128,mode,0);
        const mt_acquisition_profile*p=mt_acquisition_profile_get((uint16_t)mode);
        CHECK(p->max_block_samples==128);
    }
    const mt_acquisition_profile*p=mt_acquisition_profile_get(4);
    CHECK(p->rate_hz==150000 && p->timer_psc==47 && p->timer_arr==9 && p->block_deadline_us==3413);
    CHECK(p->period_num_us==20 && p->period_den==3 && p->start_bracket_max_us==5 && p->retained_bits==10);
    active(4);x[0]=4096;CHECK(!mt_live_device_offer(&dev,0,x,128));
    CHECK(!dev.queue.next_index && dev.queue.first_fault==MT_SAMPLE_QUEUE_CODE);
    puts("PASS DATA256 worst371 / actual wholefit370zero371full / terminal tails1,2,3,127,128,129,255,257 / old modes128");
}
static void fill_pair(uint16_t*x){
    for(unsigned i=0;i<256;i++)x[i]=(uint16_t)((i*37+3)&4095);
    CHECK(mt_live_device_offer(&dev,0,x,128));CHECK(mt_live_device_offer(&dev,128,x+128,128));
}
static void acceptance_and_replacement(void){
    uint16_t x[256],tail[129];mt_live_tx_ticket t,bad;mt_wire_message m;
    active(4);fill_pair(x);CHECK(mt_live_device_prepare_tx(&dev,&t)==MT_LIVE_TX_PREPARED);
    /* Alter caller-owned expected tickets, never corrupt the real queue. */
    for(unsigned which=0;which<4;which++){
        bad=t;if(which==0)--bad.second_count;else if(which==1)++bad.second_first_index;
        else if(which==2)bad.second_slot^=1;else bad.mode=3;
        unsigned prior=writes;sent_used=0;CHECK(mt_live_device_step_prepared(&dev,&bad));
        CHECK(writes==prior && !sent_used && dev.queue.used==2 && dev.prefix_end==0 && dev.prefix_crc_state==0xffffffffu);
    }
    limit=17;sent_used=0;CHECK(mt_live_device_step_prepared(&dev,&t));
    CHECK(sent_used==17 && dev.tx_offset==17 && dev.queue.used==2 && dev.prefix_end==0);
    /* Stop appends all tail synchronously; complete old pair before final129. */
    stop_command(129);CHECK(dev.queue.used==4 && dev.queue.sealed);
    limit=SIZE_MAX;CHECK(mt_live_device_step(&dev));m=decoded(3,152);samples(&m,x,256,4,0);
    CHECK(dev.prefix_end==256 && dev.queue.used==2);CHECK(fwrite(sent,1,sent_used,fixture)==sent_used);
    m=flush(3,152);for(unsigned i=0;i<129;i++)tail[i]=(uint16_t)(4095-i);samples(&m,tail,129,4,256);
    CHECK(fwrite(sent,1,sent_used,fixture)==sent_used);
    uint32_t expected=crc_codes(crc_codes(0xffffffffu,x,256,4),tail,129,4)^0xffffffffu;
    m=flush(3,153);CHECK(r64(m.payload+8)==385 && r32(m.payload+28)==expected);
    CHECK(fwrite(sent,1,sent_used,fixture)==sent_used);(void)flush(3,133);

    active(4);fill_pair(x);limit=17;sent_used=0;CHECK(mt_live_device_step(&dev));
    hello(3,999,1);CHECK(dev.state==MT_LIVE_HELLO_PENDING && dev.mode==4 && dev.pending_mode==1);
    limit=SIZE_MAX;CHECK(mt_live_device_step(&dev));m=decoded(3,152);samples(&m,x,256,4,0);
    CHECK(dev.prefix_end==256 && !dev.queue.used && dev.nonce==503 && dev.mode==4);
    m=flush(3,129);CHECK(dev.nonce==999 && dev.mode==1 && dev.prefix_end==0 && r16(m.payload+6)==128);

    for(unsigned failure=0;failure<3;failure++){
        active(4);fill_pair(x);CHECK(mt_live_device_prepare_tx(&dev,&t)==MT_LIVE_TX_PREPARED);
        if(failure==0)clock_ms=0;else write_kind=failure==1?2:3;
        sent_used=0;unsigned before=writes;CHECK(!mt_live_device_step_prepared(&dev,&t));
        CHECK(dev.prefix_end==0 && dev.prefix_crc_state==0xffffffffu && dev.queue.used==2 && dev.state==MT_LIVE_FAULT);
        if(failure==0)CHECK(writes==before && !sent_used);else CHECK(dev.needs_delimiter);
    }
    puts("PASS second-view/mode stale ticket no write/CRC/pop / partialDATA then Stop129 or freshHELLO / pre-postTIME+unknown");
}
int main(int argc,char**argv){
    fixture=fopen(argc>1?argv[1]:"batch385-transcript.bin","wb");CHECK(fixture);
    queue_atomicity();batches_and_tails();acceptance_and_replacement();CHECK(!fclose(fixture));return 0;
}
