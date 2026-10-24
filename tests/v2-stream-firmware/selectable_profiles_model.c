/* Appended to the existing CEN scaffold (only helpers, no old regression main).
 * Real core/queue/wire/ADC driver, logical callbacks/register time only. */
#include "mt_live_device.h"
static mt_live_device dev;
static uint8_t sent[4096];static size_t sent_used,accept_limit;
static unsigned starts,stops,unknown_write;static uint16_t tail_n;
static uint64_t core_ms;static uint32_t driver_us;
static FILE *witness;
static uint16_t u16(const uint8_t *p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void p32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static void p64(uint8_t *p,uint64_t v){for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(v>>(8*i));}
static uint64_t model_clock(void *p){(void)p;return core_ms;}
static int model_start(void *p,uint32_t generation){(void)p;CHECK(generation==3 && dev.mode>=1 && dev.mode<=3);++starts;return 1;}
static void model_stop(void *p,mt_live_snapshot *s){
    (void)p;++stops;*s=(mt_live_snapshot){.hardware_off=1};
    if(tail_n){s->tail_count=1;s->tail[0].first_index=dev.queue.next_index;s->tail[0].count=tail_n;
        for(unsigned i=0;i<tail_n;i++)s->tail[0].codes[i]=(uint16_t)(4095u-i);}
}
static size_t model_write(void *p,const uint8_t *bytes,size_t n){
    (void)p;if(unknown_write)return SIZE_MAX;if(n>accept_limit)n=accept_limit;
    CHECK(sent_used+n<=sizeof sent);memcpy(sent+sent_used,bytes,n);sent_used+=n;return n;
}
static int model_isolate(void *p){(void)p;return 1;}
static void reset_core(void){
    mt_live_io io={.clock_ms=model_clock,.start=model_start,.quiesce=model_stop,
        .write=model_write,.isolate_tx=model_isolate,.transaction_bound_ms=1,.firmware_build=0x56325343u};
    CHECK(mt_live_device_init(&dev,&io));sent_used=0;accept_limit=SIZE_MAX;
    starts=stops=unknown_write=tail_n=0;core_ms=1;
}
static void command(unsigned rev,unsigned type,uint64_t nonce,uint32_t seq,uint32_t request,
                    const uint8_t *payload,uint16_t n){
    mt_wire_message m={.type=(uint8_t)type,.session=nonce,.sequence=seq,.request=request,.payload_length=n};
    uint8_t b[MT_WIRE_FRAME_MAX];size_t size;
    if(n)memcpy(m.payload,payload,n);
    CHECK(mt_wire_encode_revision(&m,0,(uint8_t)rev,b,sizeof b,&size)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&dev,b,size));
}
static void hello(unsigned rev,uint64_t nonce,unsigned mode){
    uint8_t p[12]={0};p64(p,nonce);p[8]=(uint8_t)mode;
    command(rev,1,0,1,1,p,rev==2?8:12);
}
static mt_wire_message flush(unsigned rev,unsigned type){
    mt_wire_message m;unsigned budget=64;
    sent_used=0;
    do{CHECK(budget--);CHECK(mt_live_device_step(&dev));}while(dev.tx_length);
    CHECK(sent_used && sent[sent_used-1]==0);
    CHECK(mt_wire_decode_revision(sent,sent_used-1,0,(uint8_t)rev,&m)==MT_WIRE_OK);
    CHECK(m.type==type);
    return m;
}
static void active(unsigned mode){
    reset_core();hello(3,500+mode,mode);mt_wire_message m=flush(3,129);
    CHECK(m.payload[1]==3 && u32(m.payload+12)==1 && dev.mode==mode && dev.revision==3);
    command(3,2,dev.nonce,2,2,NULL,0);m=flush(3,130);
    const mt_acquisition_profile *p=mt_acquisition_profile_get((uint16_t)mode);
    CHECK(m.payload_length==24 && u32(m.payload)==mode && u16(m.payload+4)==mode);
    CHECK(m.payload[7]==12 && u32(m.payload+8)==p->rate_hz && u32(m.payload+12)==1);
    CHECK(m.payload[18]==p->retained_bits && m.payload[19]==p->encoding && u32(m.payload+20)==1);
    uint8_t start[4];p32(start,mode);command(3,8,dev.nonce,3,3,start,4);m=flush(3,136);
    CHECK(starts==1 && dev.state==MT_LIVE_STREAMING && u32(m.payload+4)==mode);
}
static uint32_t oracle_byte(uint32_t crc,uint8_t b){
    crc^=b;for(unsigned i=0;i<8;i++)crc=(crc>>1)^((crc&1u)?UINT32_C(0xedb88320):0u);return crc;
}
static uint32_t oracle_codes(uint32_t crc,const uint16_t *codes,unsigned n,unsigned mode){
    for(unsigned i=0;i<n;i++){uint16_t c=mode==3?(uint16_t)(codes[i]&0xffc):codes[i];
        crc=oracle_byte(crc,(uint8_t)c);crc=oracle_byte(crc,(uint8_t)(c>>8));}return crc;
}
static void check_samples(const mt_wire_message *m,const uint16_t *original,unsigned n,unsigned mode){
    CHECK(u32(m->payload+4)==mode && u16(m->payload+16)==n && u16(m->payload+18)==0);
    if(mode!=3){CHECK(m->payload_length==20+2*n);for(unsigned i=0;i<n;i++)CHECK(u16(m->payload+20+2*i)==original[i]);}
    else{
        unsigned bits=0,at=20;uint32_t reservoir=0;
        CHECK(m->payload_length==20+(10*n+7)/8);
        for(unsigned i=0;i<n;i++){
            while(bits<10){reservoir|=(uint32_t)m->payload[at++]<<bits;bits+=8;}
            CHECK((reservoir&1023u)==(original[i]>>2));reservoir>>=10;bits-=10;
        }
        CHECK(reservoir==0); /* actual encoder's final unused high bits */
    }
}
static void discovery_and_identity(void){
    reset_core();hello(2,11,0);mt_wire_message m=flush(2,129);
    CHECK(u32(m.payload+12)==3 && dev.nonce==11 && dev.revision==2 && dev.mode==0 && starts==0);
    uint8_t start[4]={1,0,0,0};command(2,8,11,2,2,start,4);
    CHECK(starts==0 && dev.state==MT_LIVE_FAULT);

    reset_core();hello(2,11,0);(void)flush(2,129);
    hello(3,22,3);accept_limit=17;sent_used=0;CHECK(mt_live_device_step(&dev));
    CHECK(dev.nonce==11 && dev.mode==0 && dev.tx_offset==17);
    hello(3,33,1);CHECK(dev.pending_nonce==33 && dev.pending_mode==1 && dev.mode==0);
    accept_limit=SIZE_MAX;sent_used=0;CHECK(mt_live_device_step(&dev));
    CHECK(dev.nonce==11 && dev.mode==0 && !dev.tx_length); /* old partial ACK cannot commit */
    mt_live_tx_ticket ticket;CHECK(mt_live_device_prepare_tx(&dev,&ticket)==MT_LIVE_TX_PREPARED);
    hello(3,44,2);sent_used=0;CHECK(mt_live_device_step_prepared(&dev,&ticket));CHECK(!sent_used);
    (void)flush(3,129);CHECK(dev.nonce==44 && dev.mode==2 && dev.revision==3);
    hello(3,44,3);CHECK(dev.mode==2 && dev.pending_mode==2); /* same nonce cannot switch */
    command(2,2,999,2,2,NULL,0);CHECK(dev.state==MT_LIVE_STOPPED && dev.mode==2);
    command(2,2,44,2,2,NULL,0);CHECK(dev.state==MT_LIVE_FAULT && dev.incompatible_seen);

    reset_core();hello(3,88,3);CHECK(mt_live_device_prepare_tx(&dev,&ticket)==MT_LIVE_TX_PREPARED);
    core_ms=501;sent_used=0;CHECK(!mt_live_device_step_prepared(&dev,&ticket));
    CHECK(!sent_used && !dev.nonce && dev.mode==0 && dev.state==MT_LIVE_FAULT);
    puts("PASS discovery0.2 marker / fresh modeHELLO0.3 / old partial ACK & ticket / stale nonce & revision / prewrite TIME");
}
static void packed_and_prefix(void){
    uint16_t codes[128];for(unsigned i=0;i<128;i++)codes[i]=(uint16_t)((i*37u+3u)&4095u);
    for(unsigned mode=1;mode<=3;mode++)for(unsigned n=1;n<=3;n++){
        active(mode);CHECK(mt_live_device_offer(&dev,0,codes,128));
        mt_live_tx_ticket t;CHECK(mt_live_device_prepare_tx(&dev,&t)==MT_LIVE_TX_PREPARED);
        accept_limit=0;sent_used=0;CHECK(mt_live_device_step_prepared(&dev,&t));
        CHECK(!sent_used && dev.prefix_end==0 && dev.queue.used==1 && dev.tx_offset==0);
        accept_limit=17;CHECK(mt_live_device_step_prepared(&dev,&t));CHECK(dev.tx_offset==17 && dev.prefix_end==0);
        accept_limit=SIZE_MAX;CHECK(mt_live_device_step(&dev));
        mt_wire_message m;CHECK(mt_wire_decode_revision(sent,sent_used-1,0,3,&m)==MT_WIRE_OK);
        CHECK(m.type==152 && dev.prefix_end==128 && dev.queue.used==0);check_samples(&m,codes,128,mode);
        if(mode==3 && n==3){CHECK(sent_used==210);CHECK(fwrite(sent,1,sent_used,witness)==sent_used);}
        tail_n=(uint16_t)n;uint8_t stop[4]={3,0,0,0};command(3,5,dev.nonce,4,4,stop,4);
        m=flush(3,152);uint16_t tail[3];for(unsigned i=0;i<n;i++)tail[i]=(uint16_t)(4095u-i);
        check_samples(&m,tail,n,mode);
        if(mode==3 && n==3)CHECK(fwrite(sent,1,sent_used,witness)==sent_used);
        uint32_t crc=oracle_codes(UINT32_C(0xffffffff),codes,128,mode);crc=oracle_codes(crc,tail,n,mode)^UINT32_C(0xffffffff);
        m=flush(3,153);CHECK(u32(m.payload+4)==mode && u32(m.payload+28)==crc && dev.prefix_end==128+n);
        if(mode==3 && n==3)CHECK(fwrite(sent,1,sent_used,witness)==sent_used);
        (void)flush(3,133);CHECK(dev.state==MT_LIVE_NEEDS_HELLO && dev.hardware_off==1);
    }
    active(3);uint16_t invalid[128]={0};invalid[90]=4096;
    CHECK(!mt_live_device_offer(&dev,0,invalid,128));
    CHECK(dev.queue.next_index==0 && dev.queue.first_fault==MT_SAMPLE_QUEUE_CODE && dev.first_reason==2);
    active(3);CHECK(mt_live_device_offer(&dev,0,codes,128));unknown_write=1;
    CHECK(!mt_live_device_step(&dev) && dev.prefix_end==0 && dev.needs_delimiter && dev.state==MT_LIVE_FAULT);
    puts("PASS all3modes DATA128 + tails1/2/3 / packed padzeros / canonical ENDCRC / zero+partial+unknown / bad originalADC");
}
static uint32_t injected_us(void *p){(void)p;return driver_us;}
static void timing_and_dma(void){
    for(unsigned mode=1;mode<=3;mode++){
        const mt_acquisition_profile *p=mt_acquisition_profile_get((uint16_t)mode);
        setup(p->start_bracket_max_us);CHECK(mt_adc_dma_profile_ready(&driver,(uint16_t)mode));
        CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
        CHECK(*reg(0x40000428u)==p->timer_psc && *reg(0x4000042cu)==p->timer_arr);
        CHECK(driver.start_after_us-driver.start_before_us==p->start_bracket_max_us);
        CHECK(driver.start_before_us>UINT32_MAX-100u && driver.start_after_us<100u);
        CHECK(!mt_adc_dma_profile_ready(&driver,(uint16_t)(mode==1?2:1)) && driver.profile==p);
        driver.io.now_us=injected_us;driver_us=100000;driver.last_poll_us=driver_us;
        driver.last_progress_us=driver_us;
        for(unsigned i=0;i<1024;i++)driver.dma_samples[i]=(uint16_t)(i&4095);
        *reg(0x40020000u)=4;*reg(0x4002000cu)=500;
        mt_adc_dma_block_t b;CHECK(mt_adc_dma_read_block(&driver,&b)==MT_ADC_DMA_BLOCK);
        CHECK(b.count==512 && b.nominal_rate_hz==p->rate_hz && b.first_sample_index==0);
        CHECK(b.first_trigger_offset_num_us==p->period_num_us && b.first_trigger_offset_den==p->period_den);
        for(unsigned i=0;i<512;i++)CHECK(b.samples[i]==i);

        for(unsigned boundary=0;boundary<2;boundary++){
            setup(4);CHECK(mt_adc_dma_profile_ready(&driver,(uint16_t)mode));
            CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
            driver.io.now_us=injected_us;driver_us=100000;driver.last_progress_us=driver_us;
            driver.last_poll_us=driver_us-p->block_deadline_us+1u-boundary;
            *reg(0x40020000u)=0;*reg(0x4002000cu)=1024;
            mt_adc_dma_result_t result=mt_adc_dma_read_block(&driver,&b);
            CHECK(boundary?result==MT_ADC_DMA_ERROR:result==MT_ADC_DMA_EMPTY);
            if(boundary)CHECK(driver.first_fault==MT_ADC_DMA_FAULT_DEADLINE);
        }
    }
    setup(6);CHECK(mt_adc_dma_profile_ready(&driver,3));
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_ERROR);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_TIMEBASE);is_off();
    /* Move the same narrow observed5ticks bracket across TIM2's16bit rollover. */
    setup(5);CHECK(mt_adc_dma_profile_ready(&driver,3));
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    uint32_t wrap_counter=65534u-(raw_before-initial_counter);
    setup(5);initial_counter=wrap_counter;CHECK(mt_adc_dma_profile_ready(&driver,3));
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    CHECK(raw_before<65536 && raw_after>=65536);
    CHECK(mt_acquisition_profile_get(3)->period_num_us==20 && mt_acquisition_profile_get(3)->period_den==3);
    puts("PASS50/100/150 timer plans / DMA512 metadata / deadline3412accept3413reject / CEN5accept6reject+wrap / rational20/3");
}
int main(int argc,char **argv){
    witness=fopen(argc>1?argv[1]:"packed-tail-transcript.bin","wb");CHECK(witness);
    discovery_and_identity();packed_and_prefix();timing_and_dma();CHECK(!fclose(witness));return 0;
}
