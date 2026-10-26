/* Isolated real serializer, independent wire oracle, explicit logical guards.
 * This is NOT execution of runtime Stop/HELLO/epoch/ADC or a throughput test. */
#include "mt_batch1024.h"
#include "mt_wire.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
static struct {uint8_t before[8],tx[MT_BATCH1024_CAPACITY],after[8];} bank;
static uint8_t wire[MT_BATCH1024_CAPACITY],raw[1328],saved[MT_BATCH1024_CAPACITY];
static uint16_t values[1024];
static mt_batch1024_state live;
static uint64_t committed_end;
static uint32_t committed_crc;
static FILE *fixture;
static uint16_t get16(const uint8_t*p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t get32(const uint8_t*p){uint32_t n=0;unsigned i;for(i=0;i<4;i++)n|=(uint32_t)p[i]<<(8*i);return n;}
static uint64_t get64(const uint8_t*p){return (uint64_t)get32(p)|((uint64_t)get32(p+4)<<32);}
static void put32(uint8_t*p,uint32_t n){unsigned i;for(i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i));}
static void put64(uint8_t*p,uint64_t n){unsigned i;for(i=0;i<8;i++)p[i]=(uint8_t)(n>>(8*i));}
static uint32_t byte_crc(uint32_t crc,uint8_t x){
    unsigned bit;crc^=x;for(bit=0;bit<8;bit++)crc=(crc>>1)^((crc&1u)?0xedb88320u:0u);return crc;
}
static uint32_t crc_bytes(uint32_t crc,const uint8_t*p,unsigned n){unsigned i;for(i=0;i<n;i++)crc=byte_crc(crc,p[i]);return crc;}
static uint32_t crc_codes(uint32_t crc,const uint16_t*p,unsigned n){
    unsigned i;for(i=0;i<n;i++){uint16_t c=(uint16_t)(p[i]&4092u);crc=byte_crc(crc,(uint8_t)c);crc=byte_crc(crc,(uint8_t)(c>>8));}return crc;
}
static void canaries(void){unsigned i;for(i=0;i<8;i++)CHECK(bank.before[i]==0xa5 && bank.after[i]==0x5a);}
static void start(uint64_t first,uint32_t seq){
    mt_batch1024_identity id={.nonce=503,.first_index=first,.generation=3,.config_id=5,.sequence=seq};
    memset(&bank,0xc7,sizeof bank);memset(bank.before,0xa5,8);memset(bank.after,0x5a,8);
    CHECK(mt_batch1024_begin(&live,bank.tx,&id,committed_crc));
    CHECK(live.phase==MT_BATCH1024_COLLECT && live.count==0);canaries();
}
/* Explicit ownership seam: copying a work state does not pop source slots.
 * Only a caller-provided valid admission publishes ownership. No attempt to
 * substitute this predicate for actual epoch/TIME/queue validation. */
static int collect(unsigned first,unsigned n,int valid){
    mt_batch1024_state work=live;
    CHECK(mt_batch1024_collect(&work,bank.tx,first,values+first,n));
    if(valid)live=work;
    canaries();return valid;
}
static void encode(unsigned quantum){
    unsigned turns=0;const uint8_t*p;size_t n;
    CHECK(mt_batch1024_seal(&live,bank.tx));
    CHECK(!mt_batch1024_piece(&live,bank.tx,&p,&n));
    while(live.phase!=MT_BATCH1024_READY){
        int used=mt_batch1024_step(&live,bank.tx,(uint16_t)quantum);
        CHECK(used>0 && (unsigned)used<=quantum);CHECK(++turns<2700);canaries();
    }
    CHECK(live.length<=1335 && !live.offset && bank.tx[live.length-1]==0);
}
/* COBS decode excluding delimiter; output is published only after a COMPLETE
 * bounded frame, then caller checks CRC/count/indices before using samples. */
static int decode(const uint8_t*b,unsigned n,unsigned*out){
    unsigned at=0,used=0,k,j;uint8_t code;
    if(n<2 || n>1335 || b[n-1])return 0;
    while(at<n-1){
        code=b[at++];if(!code)return 0;k=(unsigned)code-1u;
        if(k>n-1-at || k>sizeof raw-used)return 0;
        for(j=0;j<k;j++){if(!b[at])return 0;raw[used++]=b[at++];}
        if(code!=255 && at<n-1){if(used==sizeof raw)return 0;raw[used++]=0;}
    }
    *out=used;return 1;
}
static void verify(unsigned first,unsigned count,unsigned seq){
    unsigned n=0,i,at=44,bits=0;uint32_t pending=0;
    CHECK(decode(wire,live.length,&n));CHECK(n==48+(count*10+7)/8);
    CHECK(raw[0]==0 && raw[1]==3 && raw[2]==152 && raw[3]==0);
    CHECK(get16(raw+4)==20+(count*10+7)/8 && get16(raw+6)==0);
    CHECK(get64(raw+8)==503 && get32(raw+16)==seq && get32(raw+20)==0);
    CHECK(get32(raw+24)==3 && get32(raw+28)==5 && get64(raw+32)==first);
    CHECK(get16(raw+40)==count && get16(raw+42)==0);
    CHECK((crc_bytes(UINT32_MAX,raw,n-4)^UINT32_MAX)==get32(raw+n-4));
    for(i=0;i<count;i++){
        while(bits<10){pending|=(uint32_t)raw[at++]<<bits;bits+=8;}
        CHECK((pending&1023u)==(values[first+i]>>2));pending>>=10;bits-=10;
    }
    CHECK(!pending); /* all padding bits zero, no invented samples */
}
static void transmit(unsigned first,unsigned count,unsigned seq,int save){
    const uint8_t*p;size_t n,used=0;unsigned partial=1,raw_n=0;
    uint32_t expected=crc_codes(committed_crc,values+first,count),before=committed_crc;
    uint64_t endpoint=committed_end;
    CHECK(!mt_batch1024_commit(&live,first,1,&committed_end,&committed_crc));
    while(mt_batch1024_piece(&live,bank.tx,&p,&n)){
        CHECK(n>0 && n<=384 && used==live.offset);
        mt_batch1024_state snapshot=live;
        CHECK(mt_batch1024_accepted(&live,0) && !memcmp(&snapshot,&live,sizeof live));
        CHECK(!mt_batch1024_accepted(&live,SIZE_MAX) && !memcmp(&snapshot,&live,sizeof live));
        CHECK(!mt_batch1024_accepted(&live,n+1) && !memcmp(&snapshot,&live,sizeof live));
        if(partial && n>17){n=17;partial=0;}
        memcpy(wire+used,p,n);used+=n;CHECK(mt_batch1024_accepted(&live,n));
        CHECK(committed_end==endpoint && committed_crc==before);
        if(used<live.length)CHECK(!decode(wire,(unsigned)used,&raw_n));
    }
    CHECK(used==live.length);verify(first,count,seq);
    CHECK(!mt_batch1024_commit(&live,first,0,&committed_end,&committed_crc));
    CHECK(committed_end==endpoint && committed_crc==before);
    CHECK(mt_batch1024_commit(&live,first,1,&committed_end,&committed_crc));
    CHECK(committed_end==first+count && committed_crc==expected && live.phase==MT_BATCH1024_DONE);
    if(save)CHECK(fwrite(wire,1,used,fixture)==used);
    canaries();
}
static void full_and_tail_fixture(void){
    unsigned i;committed_end=0;committed_crc=UINT32_MAX;
    for(i=0;i<1024;i++)values[i]=(uint16_t)((i*37u+3u)&4095u);
    start(0,4);mt_batch1024_state before=live;
    CHECK(!collect(0,512,0) && !memcmp(&live,&before,sizeof live));
    CHECK(collect(0,512,1) && live.count==512);
    CHECK(collect(512,512,1) && live.count==1024);
    CHECK(committed_end==0 && committed_crc==UINT32_MAX);encode(512);transmit(0,1024,4,1);
    /* Keep global index1024; input pointer is local tail0, not a forged index. */
    for(i=0;i<129;i++)values[i]=(uint16_t)(4095u-i);
    uint32_t expected=crc_codes(committed_crc,values,129);start(1024,5);
    mt_batch1024_state work=live;CHECK(mt_batch1024_collect(&work,bank.tx,1024,values,129));live=work;encode(128);
    size_t used=0,n;const uint8_t*p;
    while(mt_batch1024_piece(&live,bank.tx,&p,&n)){memcpy(wire+used,p,n);used+=n;CHECK(mt_batch1024_accepted(&live,n));}
    unsigned raw_n=0;CHECK(decode(wire,(unsigned)used,&raw_n));
    CHECK(get64(raw+32)==1024 && get16(raw+40)==129 && raw_n==210);
    unsigned at=44,bits=0;uint32_t pending=0;
    for(i=0;i<129;i++){while(bits<10){pending|=(uint32_t)raw[at++]<<bits;bits+=8;}CHECK((pending&1023)==(values[i]>>2));pending>>=10;bits-=10;}
    CHECK(!pending && (crc_bytes(UINT32_MAX,raw,raw_n-4)^UINT32_MAX)==get32(raw+raw_n-4));
    CHECK(mt_batch1024_commit(&live,1024,1,&committed_end,&committed_crc));
    CHECK(committed_end==1153 && committed_crc==expected);CHECK(fwrite(wire,1,used,fixture)==used);
    mt_wire_message end={.type=153,.session=503,.sequence=6,.payload_length=40};
    put32(end.payload,3);put32(end.payload+4,5);put64(end.payload+8,1153);
    put32(end.payload+24,5);put32(end.payload+28,expected^UINT32_MAX);end.payload[34]=3;put32(end.payload+36,4);
    CHECK(mt_wire_encode_revision(&end,0,3,wire,sizeof wire,&used)==MT_WIRE_OK);
    CHECK(fwrite(wire,1,used,fixture)==used);
    puts("PASS synthetic DATA1024+tail129+END / bounded512 collection / stale prepared ownership not published / single final prefix commit");
}
static void tails_and_worst(void){
    const unsigned tails[]={1,2,3,127,128,129,1023,1024};
    const unsigned quanta[]={1,17,128,512};unsigned k,i;
    for(k=0;k<sizeof tails/sizeof tails[0];k++){
        unsigned n=tails[k],done=0;committed_end=0;committed_crc=UINT32_MAX;
        for(i=0;i<n;i++)values[i]=4095;
        start(0,4);
        while(done<n){unsigned take=n-done;if(take>512)take=512;CHECK(collect(done,take,1));done+=take;}
        encode(quanta[k%4]);if(n==1024)CHECK(live.length==1335);
        transmit(0,n,4,0);
    }
    puts("PASS tails1,2,3,127,128,129,1023 and full1024 worst1335 / quantum1,17,128,512 / canaries / independent COBS+CRC+pad oracle");
}
static void rejected_and_aborted(void){
    mt_batch1024_state before;unsigned i;committed_end=0;committed_crc=UINT32_MAX;
    for(i=0;i<1024;i++)values[i]=(uint16_t)i;
    start(0,4);before=live;memcpy(saved,bank.tx,sizeof saved);
    values[1]=4096;
    CHECK(!mt_batch1024_collect(&live,bank.tx,0,values,128));
    CHECK(!memcmp(&before,&live,sizeof live) && !memcmp(saved,bank.tx,sizeof saved));values[1]=1;
    CHECK(!mt_batch1024_collect(&live,bank.tx,1,values,128));
    CHECK(!mt_batch1024_collect(&live,bank.tx,0,values,513));
    CHECK(!mt_batch1024_seal(&live,bank.tx));CHECK(mt_batch1024_step(&live,bank.tx,0)==-1);
    CHECK(collect(0,128,1));encode(512);
    const uint8_t*p;size_t n;CHECK(mt_batch1024_piece(&live,bank.tx,&p,&n));
    CHECK(mt_batch1024_accepted(&live,17));before=live;
    CHECK(!mt_batch1024_accepted(&live,SIZE_MAX) && !memcmp(&before,&live,sizeof live));
    CHECK(!mt_batch1024_commit(&live,0,0,&committed_end,&committed_crc));
    mt_batch1024_abort(&live);
    CHECK(!mt_batch1024_commit(&live,0,1,&committed_end,&committed_crc));
    CHECK(committed_end==0 && committed_crc==UINT32_MAX);canaries();
    start(0,4);CHECK(collect(0,128,1));CHECK(mt_batch1024_seal(&live,bank.tx));
    CHECK(mt_batch1024_step(&live,bank.tx,512)>0 && live.phase==MT_BATCH1024_COBS);
    CHECK(mt_batch1024_step(&live,bank.tx,17)==17 && live.read==17);
    /* An invalidated destructive quantum is discarded, never state-rolled back. */
    mt_batch1024_abort(&live);CHECK(mt_batch1024_step(&live,bank.tx,512)==-1);
    CHECK(!mt_batch1024_piece(&live,bank.tx,&p,&n));
    CHECK(!mt_batch1024_commit(&live,0,1,&committed_end,&committed_crc));
    CHECK(committed_end==0 && committed_crc==UINT32_MAX);canaries();
    committed_end=0;committed_crc=UINT32_MAX;values[0]=values[1]=0;
    start(0,4);CHECK(collect(0,1,1));
    mt_batch1024_state speculative=live;uint16_t wrong=4095;
    CHECK(mt_batch1024_collect(&speculative,bank.tx,1,&wrong,1));
    CHECK(live.count==1); /* stale admission: discard state, not copied bytes */
    CHECK(collect(1,1,1));encode(17);transmit(0,2,4,0);
    puts("PASS invalid ADC before masking / gap and quantum513 rejected / zero-count noDATA / unknown acceptance or guard denial cannot commit / destructive COBS abort / stale shared-byte append retry");
}
int main(int argc,char**argv){
    fixture=fopen(argc>1?argv[1]:"batch1153-transcript.bin","wb");CHECK(fixture);
    CHECK(sizeof(mt_batch1024_state)==32);full_and_tail_fixture();tails_and_worst();rejected_and_aborted();
    CHECK(!fclose(fixture));printf("state_bytes=%u; tx_capacity=%u; production_runtime_executed=0\n",(unsigned)sizeof live,MT_BATCH1024_CAPACITY);return 0;
}
