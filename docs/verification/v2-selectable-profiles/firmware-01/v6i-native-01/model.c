/* Logical elapsed-time/MMIO witness, not CPU timing or an ADC/USB model.
 * Full pinned TIME and ADC driver are linked separately. The runtime CEN
 * callback is inserted verbatim; USB admission is an explicit injected gate. */
#include "adc_timer_dma.h"
#include "mt_timebase.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while(0)

typedef struct {
    uint32_t (*read32)(void *,uint32_t);
    void (*write32)(void *,uint32_t,uint32_t);
    void *context;
} mt_live_runtime_mmio;
typedef struct { mt_timebase *clock; mt_live_runtime_mmio mmio; } mt_live_runtime;
static struct { uint32_t address,value; } regs[80];
static unsigned reg_count,mask,initial_mask,cen_seen,quiesced,inside,ncnt;
static unsigned width,deny_after,clock_after,bad_order,change_actor;
static uint32_t actor,raw_before,raw_after,initial_time_us,initial_counter;
static uint32_t observed_before,observed_after;
static uint64_t ticks,outer_start,outer_end;
static mt_timebase clock_state;
static mt_adc_dma_t driver;
static mt_live_runtime runtime;

static uint32_t *reg(uint32_t address) {
    for(unsigned i=0;i<reg_count;i++)if(regs[i].address==address)return &regs[i].value;
    CHECK(reg_count<80);
    regs[reg_count].address=address;
    return &regs[reg_count++].value;
}
static uint32_t read32(void *unused,uint32_t address) {
    (void)unused;
    if(address==0x40000024u) {
        if(inside) {
            ++ncnt;
            if(ncnt==1)outer_start=ticks;
            if(ncnt==2)raw_before=(uint32_t)ticks;
            if(ncnt==3) {
                CHECK(ticks<=raw_before+width);
                ticks=raw_before+width;
                raw_after=(uint32_t)ticks;
                if(bad_order)return (raw_before-1u)&65535u;
            }
            if(ncnt==4)outer_end=ticks;
        }
        return (uint32_t)ticks++&65535u;
    }
    ++ticks;
    if(clock_after && cen_seen && address==0x40021004u)return *reg(address)^16u;
    return *reg(address);
}
static void write32(void *unused,uint32_t address,uint32_t value) {
    (void)unused;
    ++ticks;
    if(address==0x40000400u) {
        if(value==1u) { CHECK(mask==1u); ++cen_seen; }
        else if(cen_seen) { CHECK(mask==initial_mask); quiesced=1; }
    }
    if(address==0x40000024u)ticks=value;
    /* Instant calibration is intentional: only commit, not analogue settling,
     * is tested. The driver's stabilization path still uses full TIME. */
    if(address==0x40012408u)value&=~12u;
    *reg(address)=value;
}
static uint32_t adc_now(void *unused) {
    (void)unused;
    return mt_timebase_now_us(&clock_state);
}
static uint32_t mt_usb_bridge_actor(void) {
    return change_actor && cen_seen ? actor+1u : actor;
}
static int usable(mt_live_runtime *r) {
    ticks+=17; /* Deliberately expensive permission work outside the bracket. */
    return mt_timebase_healthy(r->clock) && !(deny_after && cen_seen);
}
static uint32_t enter(void *unused) {
    (void)unused; uint32_t previous=mask;mask=1;return previous;
}
static void leave(void *unused,uint32_t previous) { (void)unused;mask=previous; }

static uint32_t adc_read(void *context, uint32_t address) {
    mt_live_runtime *r=context; return r->mmio.read32(r->mmio.context,address);
}

static void adc_write(void *context, uint32_t address, uint32_t value) {
    mt_live_runtime *r=context; r->mmio.write32(r->mmio.context,address,value);
}

static int commit_allowed(void *context) {
    mt_live_runtime *r=context;
    return mt_usb_bridge_actor() && mt_timebase_update(r->clock) && usable(r);
}

static int commit_timed(void *context,uint32_t *us) {
    mt_live_runtime *r=context; uint32_t observed_us,observed_ms;
    if(!mt_usb_bridge_actor() || !mt_timebase_snapshot(r->clock,&observed_us,&observed_ms) ||
       !usable(r))return 0;
    *us=observed_us; return 1;
}

static int commit_timer(void *context, uint32_t *before_us, uint32_t *after_us) {
    mt_live_runtime *r=context;
    uint32_t first_us, last_us, ignored_ms, span, actor=mt_usb_bridge_actor();
    uint16_t first_counter, before_counter, after_counter, last_counter;
    uint16_t before_delta, after_delta;
    if(!actor || !mt_timebase_snapshot(r->clock,&first_us,&ignored_ms))return 0;
    first_counter=r->clock->last_counter;
    if(!usable(r))return 0;
    before_counter=(uint16_t)r->clock->io.read32(r->clock->io.context,0x40000024u);
    adc_write(r,0x40000400u,1u);
    /* Read back the APB write inside the physical bracket. */
    if(adc_read(r,0x40000400u)!=1u)return 0;
    after_counter=(uint16_t)r->clock->io.read32(r->clock->io.context,0x40000024u);
    if(!mt_timebase_snapshot(r->clock,&last_us,&ignored_ms) ||
       mt_usb_bridge_actor()!=actor || !usable(r))return 0;
    last_counter=r->clock->last_counter;
    span=(uint32_t)(last_us-first_us);
    before_delta=(uint16_t)(before_counter-first_counter);
    after_delta=(uint16_t)(after_counter-first_counter);
    /* Both CNT samples must lie, in order, inside the SAME validated interval.
     * This handles TIM2's 16-bit rollover and the published us 32-bit rollover.
     * The pre-existing <one-counter-wrap service assumption is unchanged. */
    if(span>MT_TIMEBASE_MAX_DELTA || span!=(uint16_t)(last_counter-first_counter) ||
       before_delta>span || after_delta<before_delta || after_delta>span)return 0;
    *before_us=first_us+before_delta;
    *after_us=first_us+after_delta;
    return 1;
}


static int transaction(void *context,uint32_t *before,uint32_t *after) {
    uint32_t previous_before=*before,previous_after=*after;
    inside=1;ncnt=0;
    /* Seed immediately before the transaction. The actual full TIME reads
     * validate the state; the fixture chooses an arbitrary prior counter epoch. */
    ticks=initial_counter;
    clock_state.last_counter=(uint16_t)ticks;
    clock_state.us=initial_time_us;
    int ok=commit_timer(context,before,after);
    inside=0;
    if(!ok)CHECK(*before==previous_before && *after==previous_after);
    else { observed_before=*before; observed_after=*after; }
    return ok;
}
static mt_adc_dma_start_guard guard;
static void setup(unsigned requested_width) {
    memset(regs,0,sizeof regs);reg_count=0;
    memset(&clock_state,0,sizeof clock_state);
    memset(&driver,0,sizeof driver);
    mask=initial_mask=0;cen_seen=quiesced=inside=ncnt=0;
    deny_after=clock_after=bad_order=change_actor=0;
    actor=3;width=requested_width;ticks=0;
    observed_before=observed_after=0;
    initial_counter=65490u;initial_time_us=UINT32_MAX-45u;
    *reg(0x40021000u)=0x03037783u;
    *reg(0x40021004u)=0x001d840au;
    *reg(0x4002101cu)=3u;
    mt_timebase_io time_io={read32,write32,NULL};
    CHECK(mt_timebase_init(&clock_state,&time_io,72000000u));
    runtime=(mt_live_runtime){&clock_state,{read32,write32,NULL}};
    mt_adc_dma_io_t io={read32,write32,adc_now,NULL};
    CHECK(mt_adc_dma_init(&driver,&io,8000000u)==MT_ADC_DMA_OK);
    CHECK(mt_adc_dma_enable_stream(&driver)==MT_ADC_DMA_OK);
    driver.start_before_us=0x1234u;driver.start_after_us=0x5678u;
    guard=(mt_adc_dma_start_guard){enter,commit_allowed,leave,&runtime,commit_timed};
}
static void is_off(void) {
    CHECK(*reg(0x40000400u)==0 && *reg(0x40012408u)==0);
    CHECK((*reg(0x40020008u)&1u)==0);
    CHECK(!driver.owns_peripherals && !driver.stream_history_valid);
    CHECK(mask==initial_mask && quiesced);
}

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
