/* Differential oracle: frozen SE and candidate SF are separately compiled
 * actual serializers with se_/sf_ API names. No copy of either algorithm.
 * This checks observable calls/bytes, not runtime ownership or USB timing. */
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
DECLARE(se_);
DECLARE(sf_);

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
static const api impl[2]={API(se_),API(sf_)};
typedef struct {uint8_t before[8],bytes[MT_BATCH1024_CAPACITY],after[8];} guarded;
static guarded bank[2];
static mt_batch1024_state state[2];
static uint16_t samples[1024];
static unsigned calls,frames,steps,current_quantum;
static const char *scene="init";
static const mt_batch1024_identity identity={UINT64_C(0x0102030405060708),
    UINT64_C(0x100000011),3,5,4};
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %s quantum%u line%d: %s\n",scene,current_quantum,__LINE__,#x);exit(1);}}while(0)

static void same(int a,int b){
    unsigned k,j;++calls;CHECK(a==b);
    CHECK(!memcmp(state,state+1,sizeof state[0]));
    CHECK(!memcmp(bank,bank+1,sizeof bank[0]));
    for(k=0;k<2;k++)for(j=0;j<8;j++)
        CHECK(bank[k].before[j]==0xa5 && bank[k].after[j]==0x5a);
}
static void reset(void){
    unsigned k;memset(state,0,sizeof state);
    for(k=0;k<2;k++){
        memset(bank[k].bytes,0xc7,sizeof bank[k].bytes);
        memset(bank[k].before,0xa5,8);memset(bank[k].after,0x5a,8);
    }
}
static void begin(void){
    int r[2];unsigned k;reset();
    for(k=0;k<2;k++)r[k]=impl[k].begin(state+k,bank[k].bytes,&identity,0x13579bdfu);
    same(r[0],r[1]);CHECK(r[0]==1);
}
static void collect(unsigned offset,unsigned count){
    int r[2];unsigned k;
    for(k=0;k<2;k++)r[k]=impl[k].collect(state+k,bank[k].bytes,
        identity.first_index+offset,samples+offset,(uint16_t)count);
    same(r[0],r[1]);CHECK(r[0]==1);
}
static int step(unsigned budget){
    int r[2];unsigned k;
    for(k=0;k<2;k++)r[k]=impl[k].step(state+k,bank[k].bytes,(uint16_t)budget);
    ++steps;same(r[0],r[1]);return r[0];
}
static void encode(unsigned budget){
    int r[2];unsigned k,turns=0;
    for(k=0;k<2;k++)r[k]=impl[k].seal(state+k,bank[k].bytes);
    same(r[0],r[1]);CHECK(r[0]==1);
    while(state[0].phase!=MT_BATCH1024_READY){
        int used=step(budget);CHECK(used>0 && (unsigned)used<=budget);
        CHECK(++turns<2700);
    }
    CHECK(state[0].length<=MT_BATCH1024_FRAME_MAX);
    CHECK(bank[0].bytes[state[0].length-1u]==0);
    CHECK(step(budget)==0);
}
static void transmit(void){
    int r[2];unsigned k;size_t n[2];const uint8_t*p[2];
    uint64_t end[2]={identity.first_index,identity.first_index};
    uint32_t crc[2]={0x13579bdfu,0x13579bdfu};
    while(state[0].offset<state[0].length){
        for(k=0;k<2;k++){p[k]=NULL;n[k]=0;r[k]=impl[k].piece(state+k,bank[k].bytes,p+k,n+k);}
        same(r[0],r[1]);CHECK(r[0]==1 && n[0]==n[1] && n[0]<=384);
        CHECK(p[0]-bank[0].bytes==p[1]-bank[1].bytes);
        CHECK(!memcmp(p[0],p[1],n[0]));
        for(k=0;k<2;k++)r[k]=impl[k].accepted(state+k,0);
        same(r[0],r[1]);CHECK(r[0]==1);
        for(k=0;k<2;k++)r[k]=impl[k].accepted(state+k,n[k]);
        same(r[0],r[1]);CHECK(r[0]==1);
    }
    for(k=0;k<2;k++)r[k]=impl[k].commit(state+k,identity.first_index,1,end+k,crc+k);
    same(r[0],r[1]);CHECK(r[0]==1 && end[0]==end[1] && crc[0]==crc[1]);
    CHECK(end[0]==identity.first_index+state[0].count);
}
static void valid_frame(unsigned count,unsigned budget,unsigned pattern){
    unsigned i,offset=0;scene="valid frame";current_quantum=budget;
    for(i=0;i<count;i++)samples[i]=(uint16_t)(pattern==0?0:pattern==1?4095:(i*37u+3u)&4095u);
    begin();
    while(offset<count){unsigned n=count-offset;if(n>512)n=512;collect(offset,n);offset+=n;}
    encode(budget);transmit();++frames;
}
static void valid_quanta_and_tails(void){
    const unsigned tails[]={1,2,3,127,128,129,255,256,257,1023};
    const unsigned boundaries[]={1,17,127,128,254,255,256,511,512};
    unsigned q,p,i;
    for(q=1;q<=512;q++)for(p=0;p<3;p++)valid_frame(1024,q,p);
    for(i=0;i<sizeof tails/sizeof tails[0];i++)
        valid_frame(tails[i],boundaries[i%(sizeof boundaries/sizeof boundaries[0])],i%3);
    puts("PASS full1024 budgets1..512 zero/nonzero/mixed; tails1/2/3/127/128/129/255/256/257/1023; per-call return/state/all-storage equality");
}

/* Corrupt-state cases only use in-range source/mark addresses. They exercise
 * defined defensive returns, not undefined access or arbitrary-state safety. */
static void setup_cobs(unsigned length,unsigned read,unsigned write,unsigned code){
    unsigned k;reset();
    for(k=0;k<2;k++){
        memset(bank[k].bytes,0x61,sizeof bank[k].bytes);
        state[k]=(mt_batch1024_state){.phase=MT_BATCH1024_COBS,.raw_length=(uint16_t)length,
            .read=(uint16_t)read,.write=(uint16_t)write,.mark=0,.code=(uint16_t)code};
    }
}
static void transitions_and_defensive(void){
    unsigned k;scene="CRC boundary";current_quantum=1;
    reset();
    for(k=0;k<2;k++)state[k]=(mt_batch1024_state){.phase=MT_BATCH1024_CRC,
        .raw_length=50,.read=46,.frame_crc=0x89abcdefu};
    CHECK(step(1)==0 && state[0].phase==MT_BATCH1024_COBS);
    reset();
    for(k=0;k<2;k++)state[k]=(mt_batch1024_state){.phase=MT_BATCH1024_CRC,
        .raw_length=1328,.read=1323,.frame_crc=0x89abcdefu};
    CHECK(step(512)==1 && state[0].phase==MT_BATCH1024_COBS);
    scene="COBS code255 boundary";
    setup_cobs(3,0,1,254);CHECK(step(1)==1 && state[0].code==1 && bank[0].bytes[0]==255);
    bank[0].bytes[8]=bank[1].bytes[8]=0;
    CHECK(step(1)==1 && state[0].code==1);CHECK(step(1)==1 && state[0].phase==MT_BATCH1024_READY);
    scene="COBS uint16 code wrap";
    setup_cobs(2,0,1,65535);CHECK(step(1)==1 && state[0].code==0);
    CHECK(step(1)==1 && state[0].phase==MT_BATCH1024_READY);
    scene="COBS rejected consumed cursor";
    setup_cobs(10,0,8,1);CHECK(step(1)==-1 && state[0].read==1 && state[0].write==8);
    /* First byte reaches code255 and performs stores, next cursor guard fails.
     * Both implementations must publish those earlier mutations on -1. */
    setup_cobs(10,0,7,254);CHECK(step(2)==-1 && state[0].read==2 && state[0].write==9);
    CHECK(state[0].mark==8 && state[0].code==1 && bank[0].bytes[0]==255);
    setup_cobs(1328,1327,1335,1);CHECK(step(1)==-1 && state[0].read==1328);
    scene="COBS completion guards";
    setup_cobs(0,0,1335,1);CHECK(step(1)==-1);
    setup_cobs(0,0,1,1);CHECK(step(1)==0 && state[0].phase==MT_BATCH1024_READY);
    setup_cobs(10,11,1,1);CHECK(step(1)==-1);
    setup_cobs(1329,0,1,1);CHECK(step(1)==-1);
    scene="CRC rejected bounds";
    reset();state[0].phase=state[1].phase=MT_BATCH1024_CRC;
    state[0].raw_length=state[1].raw_length=49;CHECK(step(1)==-1);
    state[0].raw_length=state[1].raw_length=1329;CHECK(step(1)==-1);
    state[0].raw_length=state[1].raw_length=50;
    state[0].read=state[1].read=47;CHECK(step(1)==-1);
    puts("PASS CRC/COBS exact transitions; code255/uint16 wrap; consumed-cursor and partial-store error publication; safe-index defensive states");
}

static void invalid_and_retry(void){
    const unsigned phases[]={MT_BATCH1024_EMPTY,MT_BATCH1024_COLLECT,MT_BATCH1024_DONE,MT_BATCH1024_ABORTED,65535};
    int r[2];unsigned k,i;mt_batch1024_state before[2],speculative[2];
    uint8_t expected[MT_BATCH1024_CAPACITY];uint16_t expected_length,wrong=4095;
    uint32_t expected_crc;
    scene="step null/budget/phase";current_quantum=0;reset();
    for(k=0;k<2;k++)r[k]=impl[k].step(NULL,bank[k].bytes,1);
    same(r[0],r[1]);CHECK(r[0]==-1);
    for(k=0;k<2;k++)r[k]=impl[k].step(state+k,NULL,1);
    same(r[0],r[1]);CHECK(r[0]==-1);
    for(i=0;i<sizeof phases/sizeof phases[0];i++){
        state[0].phase=state[1].phase=(uint16_t)phases[i];CHECK(step(1)==-1);
    }
    state[0].phase=state[1].phase=MT_BATCH1024_READY;
    CHECK(step(0)==-1 && step(513)==-1 && step(65535)==-1 && step(1)==0);
    scene="shared-byte collect retry";current_quantum=17;
    samples[0]=samples[1]=0;begin();collect(0,2);encode(17);
    expected_length=state[0].length;expected_crc=state[0].prefix_crc;
    memcpy(expected,bank[0].bytes,expected_length);
    begin();collect(0,1);memcpy(before,state,sizeof state);memcpy(speculative,state,sizeof state);
    for(k=0;k<2;k++)r[k]=impl[k].collect(speculative+k,bank[k].bytes,identity.first_index+1,&wrong,1);
    same(r[0],r[1]);CHECK(r[0]==1 && !memcmp(speculative,speculative+1,sizeof speculative[0]));
    CHECK(!memcmp(before,state,sizeof state)); /* rejected work state, bytes remain */
    collect(1,1);encode(17);
    CHECK(state[0].length==expected_length && state[0].prefix_crc==expected_crc);
    CHECK(!memcmp(expected,bank[0].bytes,expected_length));
    for(k=0;k<2;k++)impl[k].abort(state+k);
    same(0,0);CHECK(step(17)==-1);
    puts("PASS null/invalid step calls; one shared-byte rejected-work retry; abort remains terminal");
}
int main(void){
    CHECK(sizeof(mt_batch1024_state)==32);
    valid_quanta_and_tails();transitions_and_defensive();invalid_and_retry();
    printf("differential_calls=%u; step_calls=%u; valid_frames=%u; hardware_executed=0; throughput_claim=0\n",calls,steps,frames);
    return 0;
}
