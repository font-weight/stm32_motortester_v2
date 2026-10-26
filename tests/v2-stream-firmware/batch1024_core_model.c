/* Actual SE core/queue/module, all submits use prepare_tx -> step_prepared.
 * Logical clock/transport/Stop seams; no physical DMA, USB or timing proof. */
#include "protocol/mt_live_device.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL core1024 line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
typedef struct {mt_live_device device;uint32_t epoch,soft_serial;} mt_live_runtime;
static mt_live_runtime owner;
#define D owner.device
static unsigned guard,transport_allowed,clocks,writes,starts,stops,tail_count,unknown_write;
static unsigned late_kind,after_write,full_write_armed,clock_prefix_check;
static size_t wire_used,write_limit;
static uint64_t clock_value,expected_old_prefix,tail_origin;
static uint8_t wire[16384],decoded[1328];
static FILE *fixture;
static uint16_t r16(const uint8_t*p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t r32(const uint8_t*p){uint32_t n=0;for(unsigned i=0;i<4;i++)n|=(uint32_t)p[i]<<(8*i);return n;}
static uint64_t r64(const uint8_t*p){return (uint64_t)r32(p)|((uint64_t)r32(p+4)<<32);}
static void w32(uint8_t*p,uint32_t n){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i));}
static void w64(uint8_t*p,uint64_t n){for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(n>>(8*i));}
static uint32_t crc_byte(uint32_t crc,uint8_t b){crc^=b;for(unsigned i=0;i<8;i++)crc=(crc>>1)^((crc&1u)?0xedb88320u:0u);return crc;}
static uint32_t crc_raw(uint32_t crc,const uint8_t*p,unsigned n){for(unsigned i=0;i<n;i++)crc=crc_byte(crc,p[i]);return crc;}
static uint16_t pattern(uint64_t i){return (uint16_t)((i*37u+3u)&4095u);}
static uint64_t now(void*p){
    CHECK(p==&owner);++clocks;
    if(full_write_armed){
        ++after_write;
        if(clock_prefix_check)CHECK(D.prefix_end==expected_old_prefix);
        if(after_write==2 && late_kind==1)return UINT64_MAX;
        if(after_write==2 && late_kind==2)return D.stop_deadline;
    }
    return clock_value;
}
static int start(void*p,uint32_t generation){CHECK(p==&owner && generation==3);++starts;return 1;}
static void stop(void*p,mt_live_snapshot*s){
    CHECK(p==&owner);++stops;*s=(mt_live_snapshot){.hardware_off=1};tail_origin=D.queue.next_index;
    for(unsigned i=0;i<tail_count;i++){
        unsigned block=i/128,at=i%128;s->tail[block].first_index=tail_origin+block*128;
        s->tail[block].codes[at]=(uint16_t)(4095u-i);s->tail[block].count=(uint16_t)(at+1);s->tail_count=block+1;
    }
}
static int isolate(void*p){CHECK(p==&owner);return 1;}
static size_t write_bytes(void*p,const uint8_t*b,size_t n){
    CHECK(p==&owner && guard==1 && n<=384);++writes;if(unknown_write)return SIZE_MAX;
    if(n>write_limit)n=write_limit;
    CHECK(wire_used+n<=sizeof wire);memcpy(wire+wire_used,b,n);wire_used+=n;
    if((late_kind || clock_prefix_check) && n && n==D.tx_length-D.tx_offset){full_write_armed=1;after_write=0;}
    return n;
}
static int usable(mt_live_runtime*r){CHECK(r==&owner && guard==1);return (int)transport_allowed;}
/* PREPARED_TX_HELPER */
static int submit(const mt_live_tx_ticket*t,uint32_t epoch,uint32_t serial){
    int result;CHECK(!guard);guard=1;result=prepared_tx_step(&owner,t,epoch,serial);guard=0;return result;
}
static int tick(void){
    mt_live_tx_ticket t;uint32_t epoch=owner.epoch,serial=owner.soft_serial;
    CHECK(!guard);(void)mt_live_device_prepare_tx(&D,&t);return submit(&t,epoch,serial);
}
static void command(unsigned rev,unsigned type,uint64_t nonce,unsigned seq,unsigned req,const uint8_t*p,unsigned n){
    mt_wire_message m={.type=(uint8_t)type,.session=nonce,.sequence=seq,.request=req,.payload_length=(uint16_t)n};
    uint8_t b[MT_WIRE_FRAME_MAX];size_t length;if(n)memcpy(m.payload,p,n);
    CHECK(mt_wire_encode_revision(&m,0,(uint8_t)rev,b,sizeof b,&length)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&D,b,length));
}
static void hello(unsigned rev,uint64_t nonce,unsigned mode){uint8_t p[12]={0};w64(p,nonce);p[8]=(uint8_t)mode;command(rev,1,0,1,1,p,rev==2?8:12);}
static unsigned decode_one(size_t at,size_t*next){
    size_t end=at;unsigned n=0;while(end<wire_used && wire[end])++end;CHECK(end<wire_used);
    while(at<end){unsigned code=wire[at++];CHECK(code && code-1<=end-at && code-1<=sizeof decoded-n);
        for(unsigned i=1;i<code;i++){CHECK(wire[at]);decoded[n++]=wire[at++];}
        if(code!=255 && at<end){CHECK(n<sizeof decoded);decoded[n++]=0;}
    }
    CHECK(n>=28 && r16(decoded+4)+28u==n && (crc_raw(UINT32_MAX,decoded,n-4)^UINT32_MAX)==r32(decoded+n-4));
    CHECK(decoded[0]==0 && decoded[3]==0 && r16(decoded+6)==0);*next=end+1;return n;
}
static void finish_frame(unsigned type){
    unsigned limit=16;do{CHECK(limit--);CHECK(tick());}while(D.tx_length);
    size_t next;decode_one(0,&next);CHECK(next==wire_used && decoded[2]==type);
}
static void active(unsigned mode){
    mt_live_io io={.context=&owner,.clock_ms=now,.start=start,.quiesce=stop,.write=write_bytes,
        .isolate_tx=isolate,.transaction_bound_ms=1,.firmware_build=0x56325345u};
    memset(&owner,0,sizeof owner);guard=clocks=writes=starts=stops=tail_count=unknown_write=0;
    late_kind=after_write=full_write_armed=clock_prefix_check=0;wire_used=0;write_limit=SIZE_MAX;
    owner.epoch=3;owner.soft_serial=4;transport_allowed=1;clock_value=1;
    CHECK(mt_live_device_init(&D,&io));hello(2,123,0);finish_frame(129);
    CHECK(r16(decoded+28)==1300 && r16(decoded+30)==1024 && r32(decoded+36)==15);
    wire_used=0;hello(3,503,mode);finish_frame(129);
    unsigned max=mode==5?1024:mode==4?256:128;
    CHECK(r16(decoded+28)==(mode==5?1300:512) && r16(decoded+30)==max && r32(decoded+36)==1);
    wire_used=0;command(3,2,503,2,2,NULL,0);finish_frame(130);
    CHECK(r32(decoded+24)==mode && r16(decoded+40)==max);
    uint8_t p[4];w32(p,mode);wire_used=0;command(3,8,503,3,3,p,4);finish_frame(136);
    CHECK(D.state==MT_LIVE_STREAMING && D.generation==3 && starts==1);wire_used=0;
}
static void offer(unsigned first,unsigned blocks){
    uint16_t p[128];for(unsigned b=0;b<blocks;b++){
        for(unsigned i=0;i<128;i++)p[i]=pattern(first+b*128+i);
        CHECK(mt_live_device_offer(&D,first+b*128,p,128));
    }
}
static void stop_request(unsigned n){uint8_t p[4]={3,0,0,0};tail_count=n;command(3,5,503,4,4,p,4);tail_count=0;}
static void drain(void){unsigned turns=0;while(D.state!=MT_LIVE_NEEDS_HELLO){CHECK(++turns<40);CHECK(tick());}CHECK(!D.queue.used && D.batch.phase==MT_BATCH1024_EMPTY && !D.tx_length);}
static unsigned check_frames(unsigned mode,uint64_t count,unsigned reason,uint64_t final_tail_start,unsigned final_tail_count){
    size_t at=0,next=0;uint64_t index=0;uint32_t crc=UINT32_MAX;unsigned datas=0,short_seen=0;
    while(at<wire_used){unsigned n=decode_one(at,&next);unsigned type=decoded[2];CHECK(decoded[1]==3 && r64(decoded+8)==503);
        if(type==152){
            unsigned amount=r16(decoded+40),max=mode==5?1024:mode==4?256:128;
            CHECK(!short_seen && amount>0 && amount<=max && r16(decoded+42)==0);
            CHECK(r32(decoded+24)==3 && r32(decoded+28)==mode && r64(decoded+32)==index);
            if(amount<max)short_seen=1;unsigned off=44,bits=0;uint32_t pending=0;
            CHECK(n==48u+(mode>=3?(amount*10u+7u)/8u:amount*2u));
            for(unsigned i=0;i<amount;i++){
                uint64_t source=index+i;uint16_t original=source>=final_tail_start && source-final_tail_start<final_tail_count?
                    (uint16_t)(4095u-(source-final_tail_start)):pattern(source);
                uint16_t expected=mode>=3?(uint16_t)(original&4092u):original,actual;
                if(mode>=3){while(bits<10){pending|=(uint32_t)decoded[off++]<<bits;bits+=8;}actual=(uint16_t)((pending&1023u)<<2);pending>>=10;bits-=10;}
                else{actual=r16(decoded+off);off+=2;}
                CHECK(actual==expected);crc=crc_byte(crc,(uint8_t)actual);crc=crc_byte(crc,(uint8_t)(actual>>8));
            }
            CHECK(!pending);index+=amount;++datas;
        }else if(type==153){CHECK(index==count && r64(decoded+32)==count && r32(decoded+52)==(crc^UINT32_MAX) && r16(decoded+56)==reason);}
        else CHECK(type==133);
        at=next;
    }
    CHECK(index==count);return datas;
}
static void ownership_and_old_modes(void){
    mt_sample_queue q,before;mt_sample_block v[4];uint16_t x[128]={0};
    mt_sample_queue_init(&q,0);
    for(unsigned i=0;i<7;i++){CHECK(mt_sample_queue_push(&q,i*128,x,128,0)==MT_SAMPLE_QUEUE_OK);CHECK(mt_sample_queue_pop(&q,i*128)==MT_SAMPLE_QUEUE_OK);}
    for(unsigned i=0;i<4;i++)CHECK(mt_sample_queue_push(&q,896+i*128,x,128,0)==MT_SAMPLE_QUEUE_OK);
    CHECK(mt_sample_queue_peek_many(&q,v,4)==MT_SAMPLE_QUEUE_OK && v[0].samples==q.samples[7] && v[3].samples==q.samples[2]);
    before=q;--v[3].count;CHECK(mt_sample_queue_pop_many(&q,v,4)==MT_SAMPLE_QUEUE_STALE && !memcmp(&q,&before,sizeof q));
    ++v[3].count;++v[3].first_index;CHECK(mt_sample_queue_pop_many(&q,v,4)==MT_SAMPLE_QUEUE_STALE && !memcmp(&q,&before,sizeof q));
    --v[3].first_index;v[3].samples=q.samples[3];CHECK(mt_sample_queue_pop_many(&q,v,4)==MT_SAMPLE_QUEUE_STALE && !memcmp(&q,&before,sizeof q));
    v[3].samples=q.samples[2];CHECK(mt_sample_queue_pop_many(&q,v,4)==MT_SAMPLE_QUEUE_OK && !q.used && q.head==3);
    active(5);offer(0,4);mt_live_tx_ticket ticket;unsigned calls=clocks+writes+stops;
    CHECK(mt_live_device_prepare_tx(&D,&ticket)==MT_LIVE_TX_EMPTY);
    CHECK(clocks+writes+stops==calls && D.batch.count==512 && !D.queue.used && D.queue.head_index==512 && !D.prefix_end);
    CHECK(submit(&ticket,3,4) && !wire_used);offer(512,4);
    write_limit=0;CHECK(tick() && D.batch.count==1024 && !D.queue.used && !D.prefix_end && D.tx_length<=1335);
    write_limit=SIZE_MAX;stop_request(129);drain();CHECK(D.prefix_end==1153 && !D.first_reason);
    CHECK(check_frames(5,1153,0,1024,129)==2);
    size_t at=0,next;while(at<wire_used){decode_one(at,&next);at=next;if(decoded[2]==153)break;}
    CHECK(fwrite(wire,1,at,fixture)==at);
    for(unsigned mode=1;mode<=4;mode++){
        active(mode);offer(0,mode==4?2:1);CHECK(tick());stop_request(0);drain();
        CHECK(check_frames(mode,mode==4?256:128,0,UINT64_MAX,0)==1);
    }
    puts("PASS prepare->step_prepared ownership512 before wireprefix / atomic fourth-view wrap7to0 / actual C1153 fixture / old1..4 bounds");
}
/* Construct legal resumable raw states with the REAL frozen serializer.
 * Current scheduler encodes in one FG prepare, so CRC/COBS Stop rows below
 * test resumability, not a claim that RX can reenter an active prepare call. */
static void resume_stage(unsigned cobs){
    mt_batch1024_identity id={D.nonce,D.tx_first_index,D.generation,D.mode,D.tx_sequence};uint16_t p[512];
    CHECK(mt_batch1024_begin(&D.batch,D.tx,&id,D.prefix_crc_state));
    for(unsigned part=0;part<2;part++){
        for(unsigned i=0;i<512;i++)p[i]=pattern(part*512+i);
        CHECK(mt_batch1024_collect(&D.batch,D.tx,part*512,p,512));
    }
    CHECK(mt_batch1024_seal(&D.batch,D.tx));D.tx_length=D.tx_offset=0;
    if(cobs){while(D.batch.phase==MT_BATCH1024_CRC)CHECK(mt_batch1024_step(&D.batch,D.tx,512)>0);CHECK(mt_batch1024_step(&D.batch,D.tx,17)==17);}
}
static void stop_fault_and_tails(void){
    for(unsigned phase=0;phase<5;phase++){
        active(5);offer(0,4);CHECK(tick() && D.batch.count==512);
        if(phase){offer(512,4);write_limit=0;CHECK(tick());if(phase==1 || phase==2)resume_stage(phase==2);}
        if(phase==4){write_limit=17;CHECK(tick() && D.tx_offset==17);}
        stop_request(129);write_limit=SIZE_MAX;drain();
        uint64_t expected=phase?1153:641;CHECK(!D.first_reason && D.prefix_end==expected);
        check_frames(5,expected,0,phase?1024:512,129);
    }
    const unsigned tails[]={1,2,3,127,128,129,1023};
    for(unsigned k=0;k<sizeof tails/sizeof tails[0];k++){
        active(5);stop_request(tails[k]);drain();CHECK(D.prefix_end==tails[k]);check_frames(5,tails[k],0,0,tails[k]);
    }
    active(5);offer(0,8);write_limit=0;CHECK(tick());CHECK(tick());
    stop_request(1);write_limit=SIZE_MAX;drain();CHECK(D.prefix_end==1025);check_frames(5,1025,0,1024,1);
    active(5);offer(0,4);CHECK(tick() && D.batch.count==512);offer(512,8);
    uint16_t p[128]={0};CHECK(!mt_live_device_offer(&D,1536,p,128));CHECK(D.first_reason==1 && D.queue.sealed);
    stop_request(0);drain();CHECK(D.first_reason==1 && D.prefix_end==1536);check_frames(5,1536,1,UINT64_MAX,0);
    puts("PASS Stop COLLECT/READY/SEND plus legal CRC/COBS resume seams / tails and1025 / source1 staged+queue drain, no bridge/earlyEND");
}
static void hello_epoch_and_invariants(void){
    for(unsigned partial=0;partial<2;partial++){
        active(5);offer(0,8);write_limit=0;CHECK(tick());CHECK(tick());
        if(partial){write_limit=17;CHECK(tick() && D.tx_offset==17);}
        hello(3,999,1);CHECK(D.state==MT_LIVE_HELLO_PENDING);
        if(!partial)CHECK(D.batch.phase==MT_BATCH1024_EMPTY && !D.tx_length && !D.prefix_end);
        write_limit=SIZE_MAX;unsigned turns=0;
        while(D.nonce!=999){CHECK(++turns<12);CHECK(tick());}
        CHECK(D.mode==1 && D.prefix_end==0 && !D.queue.used && D.batch.phase==MT_BATCH1024_EMPTY);
        if(partial){size_t next;decode_one(0,&next);CHECK(decoded[2]==152 && r64(decoded+8)==503 && r16(decoded+40)==1024);decode_one(next,&next);CHECK(decoded[2]==129 && r64(decoded+8)==999);}
    }
    for(unsigned encoded=0;encoded<2;encoded++){
        active(5);offer(0,encoded?8:4);mt_live_tx_ticket t;
        CHECK(mt_live_device_prepare_tx(&D,&t)==MT_LIVE_TX_EMPTY);CHECK(submit(&t,3,4));
        if(encoded)CHECK(mt_live_device_prepare_tx(&D,&t)==MT_LIVE_TX_PREPARED);
        unsigned prior=writes;owner.epoch=4;CHECK(submit(&t,3,4) && writes==prior && !wire_used && !D.prefix_end);
        mt_live_device_transport_lost(&D);CHECK(D.state==MT_LIVE_FAULT && D.batch.phase==MT_BATCH1024_EMPTY && !D.prefix_end && !D.tx_length);
    }
    active(5);offer(0,8);write_limit=0;CHECK(tick());CHECK(tick());
    mt_live_tx_ticket t;CHECK(mt_live_device_prepare_tx(&D,&t)==MT_LIVE_TX_PREPARED);--t.batch.length;
    unsigned prior=writes;CHECK(submit(&t,3,4) && writes==prior && !D.prefix_end);
    puts("PASS unaccepted HELLO discard / partial oldDATA completion before newACK / actual runtime epoch-admission helper+core cleanup / state-length ticket stale");
}
static void late_guards(void){
    for(unsigned kind=0;kind<3;kind++){
        active(5);offer(0,8);write_limit=0;CHECK(tick());CHECK(tick());stop_request(0);
        expected_old_prefix=0;clock_prefix_check=1;late_kind=kind;write_limit=SIZE_MAX;
        unsigned turns=0;int good=1;
        while(D.prefix_end==0 && good){CHECK(++turns<8);good=tick();}
        full_write_armed=clock_prefix_check=0;
        if(!kind){CHECK(good && D.prefix_end==1024 && after_write==2);drain();}
        else{
            CHECK(!good && after_write>=2 && !D.prefix_end && D.prefix_crc_state==UINT32_MAX && D.last_data_sequence==0);
            CHECK(D.state==MT_LIVE_FAULT && D.batch.phase==MT_BATCH1024_EMPTY && D.needs_delimiter);
            size_t next;decode_one(0,&next);CHECK(next==wire_used && decoded[2]==152); /* full escaped, NO END/ACK */
        }
    }
    active(5);offer(0,8);write_limit=0;CHECK(tick());CHECK(tick());unknown_write=1;
    CHECK(!tick() && D.state==MT_LIVE_FAULT && !D.prefix_end && !wire_used && D.batch.phase==MT_BATCH1024_EMPTY);
    active(5);offer(0,8);write_limit=0;CHECK(tick());CHECK(tick());clock_value=0;
    unsigned prior=writes;CHECK(!tick() && writes==prior && !D.prefix_end && D.state==MT_LIVE_FAULT && D.batch.phase==MT_BATCH1024_EMPTY);
    active(5);offer(0,8);write_limit=0;CHECK(tick());CHECK(tick());
    CHECK(tick() && !D.tx_offset && D.tx_next==4);write_limit=17;CHECK(tick() && D.tx_offset==17 && D.tx_next==5 && !D.prefix_end);
    write_limit=0;CHECK(tick() && D.tx_offset==17 && !D.prefix_end);
    puts("PASS prefix remains OLD at BOTH post-write and LAST now / late clock or bound after escapedFULL discards pending / no normalEND / unknown,zero,partial");
}
int main(int argc,char**argv){
    fixture=fopen(argc>1?argv[1]:"core1153-transcript.bin","wb");CHECK(fixture);
    ownership_and_old_modes();stop_fault_and_tails();hello_epoch_and_invariants();late_guards();CHECK(!fclose(fixture));return 0;
}
