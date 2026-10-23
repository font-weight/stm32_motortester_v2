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
int cen_regression_main(void) {
    setup(MT_ADC_DMA_SAMPLE_US);
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    CHECK(driver.state==MT_ADC_DMA_RUNNING && driver.stream_history_valid);
    CHECK(driver.start_after_us-driver.start_before_us==MT_ADC_DMA_SAMPLE_US);
    CHECK(driver.start_before_us>UINT32_MAX-100u && driver.start_after_us<100u);
    CHECK(outer_end-outer_start>MT_ADC_DMA_SAMPLE_US && mask==0 && cen_seen==1u);
    uint32_t wrap_counter=65534u-(raw_before-initial_counter);
    setup(MT_ADC_DMA_SAMPLE_US);initial_counter=wrap_counter;
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    CHECK(raw_before<65536u && raw_after>=65536u);
    /* Negative control: the old full-validation timestamp path includes the
     * same deliberately expensive work and must fail its one-period gate. */
    setup(MT_ADC_DMA_SAMPLE_US);
    CHECK(mt_adc_dma_start_guarded(&driver,&guard)==MT_ADC_DMA_ERROR);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_TIMEBASE);
    CHECK(driver.start_after_us-driver.start_before_us>MT_ADC_DMA_SAMPLE_US);
    is_off();
    puts("PASS expensive full guards / one-period CEN / old path rejects");

    setup(MT_ADC_DMA_SAMPLE_US+1u);initial_mask=mask=1;
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_ERROR);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_TIMEBASE);
    CHECK(observed_after-observed_before==MT_ADC_DMA_SAMPLE_US+1u);
    CHECK(driver.start_before_us==0x1234u && driver.start_after_us==0x5678u);
    is_off();
    puts("PASS period+1us rejection / original PRIMASK restored / verified quiesce");

    for(unsigned fault=0;fault<4;fault++) {
        setup(4);
        clock_after=fault==0;deny_after=fault==1;
        change_actor=fault==2;bad_order=fault==3;
        CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_ERROR);
        CHECK(driver.first_fault==MT_ADC_DMA_FAULT_ADMISSION);
        CHECK(driver.start_before_us==0x1234u && driver.start_after_us==0x5678u);
        CHECK(cen_seen==1);
        if(clock_after)CHECK(clock_state.state==MT_TIMEBASE_FAULTED);
        is_off();
    }
    puts("PASS post-CEN TIME / lifecycle / original actor / counter-order denial");
    return 0;
}

/* Included after the exact-CEN logical model. This exercises real ADC/adapter/
 * queue/core code with logical DMA registers; it never models CPU throughput. */
#include "mt_live_adc.h"
static mt_live_adc binding;
static mt_live_device device;
static unsigned stop_calls;
static unsigned char wire_bytes[16384];
static size_t wire_used;
static size_t write_limit,write_calls,maximum_offer;
static bool write_unknown;
static uint64_t core_clock(void *p) { (void)p; return 1; }
static int core_start(void *p,uint32_t generation) { (void)p;(void)generation;return 1; }
static void core_stop(void *p,mt_live_snapshot *out) {
    (void)p;++stop_calls;mt_live_adc_quiesce(&binding,out);
}
static size_t core_write(void *p,const uint8_t *bytes,size_t n) {
    (void)p;++write_calls;if(n>maximum_offer)maximum_offer=n;
    if(write_unknown)return SIZE_MAX;
    if(n>write_limit)n=write_limit;
    CHECK(wire_used+n<=sizeof wire_bytes);
    memcpy(wire_bytes+wire_used,bytes,n);wire_used+=n;return n;
}
static int core_isolate(void *p) { (void)p;return 1; }
static void active(void) {
    setup(4);
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    CHECK(*reg(0x40000428u)==71 && *reg(0x4000042cu)==4);
    CHECK(*reg(0x40012410u)==4 && *reg(0x4002000cu)==1024);
    CHECK(MT_ADC_DMA_RATE_HZ==200000 && MT_ADC_DMA_SAMPLE_US==5);
    CHECK(MT_ADC_DMA_BLOCK_SAMPLES==512 && MT_ADC_DMA_BLOCK_US==2560);
    CHECK(MT_SAMPLE_QUEUE_SLOTS==8 && MT_SAMPLE_QUEUE_BLOCK==128);
    /* Align logical acquisition history; no wall-clock claim is made. */
    driver.last_poll_us=adc_now(NULL);
    driver.last_progress_us=driver.last_poll_us;
    for(unsigned i=0;i<1024;i++) driver.dma_samples[i]=(uint16_t)(i&4095);
    memset(&binding,0,sizeof binding);
    binding.driver=&driver;binding.clock=&clock_state;binding.device=&device;
    binding.initialized=1;
    mt_live_io io={.clock_ms=core_clock,.start=core_start,.quiesce=core_stop,
        .write=core_write,.isolate_tx=core_isolate,.transaction_bound_ms=1,
        .firmware_build=
#ifdef MT_TEST_FIRMWARE_BUILD
          MT_TEST_FIRMWARE_BUILD
#else
          0x56325335u
#endif
        };
    CHECK(mt_live_device_init(&device,&io));
    device.state=MT_LIVE_STREAMING;device.generation=1;device.nonce=7;
    device.hardware_off=0;device.tx_next=1;device.rx_next=1;
    stop_calls=0;wire_used=0;write_calls=maximum_offer=0;
    write_limit=SIZE_MAX;write_unknown=false;
}
static void first_half(unsigned remaining) {
    *reg(0x40020000u)=4u; /* HT */
    *reg(0x4002000cu)=remaining;
}
static void check_queue(unsigned blocks,unsigned first) {
    CHECK(device.queue.used==blocks);
    for(unsigned b=0;b<blocks;b++) {
        unsigned slot=(device.queue.head+b)%MT_SAMPLE_QUEUE_SLOTS;
        CHECK(device.queue.counts[slot]==128);
        for(unsigned j=0;j<128;j++)
            CHECK(device.queue.samples[slot][j]==first+b*128+j);
    }
}
static void stop_command(void) {
    mt_wire_message m={.type=5,.session=7,.sequence=1,.request=2,.payload_length=4};
    m.payload[0]=1;
    uint8_t frame[MT_WIRE_FRAME_MAX];size_t n;
    CHECK(mt_wire_encode_revision(&m,0,2,frame,sizeof frame,&n)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&device,frame,n));
}
int main(void) {
    CHECK(cen_regression_main()==0);
    active();first_half(500);
    CHECK(mt_live_adc_service(&binding)==1);
    CHECK(driver.first_sample_index==512 && device.queue.next_index==512);
    check_queue(4,0);
    /* Logical IFCR effects are applied between calls, as hardware would. */
    *reg(0x40020000u)=2u;*reg(0x4002000cu)=1000;
    CHECK(mt_live_adc_service(&binding)==1);
    CHECK(driver.first_sample_index==1024 && device.queue.next_index==1024);
    check_queue(8,0);
    puts("PASS 200k config / ADC41.5 / DMA1024 / ordered two halves to DATA128");

    for(unsigned half=0;half<2;half++) {
        active();driver.next_half=half!=0;driver.first_sample_index=half?512:0;
        /* Both states retain 1023 pending transfers across the circular end. */
        *reg(0x40020000u)=half?2u:4u;
        *reg(0x4002000cu)=half?513u:1u;
        mt_live_snapshot out;
        mt_live_adc_quiesce(&binding,&out);
        CHECK(out.hardware_off==1 && out.produced_known==0 && out.produced_end==0);
        CHECK(out.acquisition_reason==0 && out.tail_count==8);
        for(unsigned b=0;b<8;b++) {
            CHECK(out.tail[b].first_index==(half?512u:0u)+b*128);
            CHECK(out.tail[b].count==(b==7?127u:128u));
            for(unsigned j=0;j<out.tail[b].count;j++)
                CHECK(out.tail[b].codes[j]==((half?512u:0u)+b*128+j)%1024);
        }
        mt_live_snapshot again;mt_live_adc_quiesce(&binding,&again);
        CHECK(!memcmp(&out,&again,sizeof out));
    }
    puts("PASS frozen Stop tail1023 / eight DATA chunks / both circular halves / unknown produced");

    active();first_half(1);stop_command();
    CHECK(device.state==MT_LIVE_DRAINING && device.first_reason==0 && stop_calls==1);
    CHECK(device.queue.used==8 && device.queue.next_index==1023 && device.queue.sealed);
    CHECK(device.hardware_off==1 && device.produced_known==0);
    for(unsigned i=0;i<100 && !device.end_complete;i++)CHECK(mt_live_device_step(&device));
    CHECK(device.end_complete && device.prefix_end==1023 && device.terminal_flags==3);
    size_t cursor=0;unsigned frame_count=0,code_count=0;
    while(cursor<wire_used) {
        size_t end=cursor;while(end<wire_used && wire_bytes[end])++end;
        CHECK(end<wire_used);
        mt_wire_message m;
        CHECK(mt_wire_decode_revision(wire_bytes+cursor,end-cursor,0,2,&m)==MT_WIRE_OK);
        if(m.type==152) {
            unsigned count=(unsigned)m.payload[16]|((unsigned)m.payload[17]<<8);
            for(unsigned j=0;j<count;j++) {
                unsigned code=m.payload[20+2*j]|((unsigned)m.payload[21+2*j]<<8);
                CHECK(code==code_count++);
            }
            ++frame_count;
        }
        cursor=end+1;
    }
    CHECK(code_count==1023 && frame_count==8);
    puts("PASS real core Stop validation / serialization / raw order / END unknown tail");

    for(unsigned free_slots=0;free_slots<4;free_slots++) {
        active();uint16_t filler[128]={0};
        unsigned existing=8-free_slots;
        for(unsigned b=0;b<8;b++)CHECK(mt_live_device_offer(&device,b*128,filler,128));
        for(unsigned b=0;b<free_slots;b++)
            CHECK(mt_sample_queue_pop(&device.queue,b*128)==MT_SAMPLE_QUEUE_OK);
        device.prefix_end=free_slots*128;
        CHECK(device.queue.used==existing && device.queue.head_index==free_slots*128);
        driver.first_sample_index=1024;
        first_half(500);
        CHECK(mt_live_adc_service(&binding)==-1);
        CHECK(device.queue.sealed && device.queue.first_fault==MT_SAMPLE_QUEUE_FULL);
        CHECK(device.first_reason==1 && stop_calls==1 && device.queue.used==8);
        CHECK(device.queue.next_index==1024+free_slots*128);
        CHECK(device.hardware_off==1);
    }
    puts("PASS queue full at each of four split chunks / no offer across a gap");

    active();first_half(500);*reg(0x40020000u)=6; /* HT and TC: history lost. */
    CHECK(mt_live_adc_service(&binding)==-1);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_DEADLINE && !driver.stream_history_valid);
    CHECK(device.queue.used==0 && device.first_reason==2);
    active();first_half(500);
    ticks+=2560;
    CHECK(mt_live_adc_service(&binding)==-1);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_DEADLINE && device.queue.used==0);
    puts("PASS missed DMA boundary and late service reject without invented samples");

    active();device.state=MT_LIVE_STOPPED;device.hardware_off=1;device.want_caps=1;
    device.caps_request=1;
    for(unsigned i=0;i<10 && device.want_caps;i++)CHECK(mt_live_device_step(&device));
    CHECK(wire_used>0 && wire_bytes[wire_used-1]==0);
    mt_wire_message caps;
    CHECK(mt_wire_decode_revision(wire_bytes,wire_used-1,0,2,&caps)==MT_WIRE_OK);
    CHECK(caps.type==130 && caps.payload_length==24);
    uint32_t rate=(uint32_t)caps.payload[8]|((uint32_t)caps.payload[9]<<8)|
        ((uint32_t)caps.payload[10]<<16)|((uint32_t)caps.payload[11]<<24);
    CHECK(rate==200000 && caps.payload[16]==128 && caps.payload[17]==0);
    puts("PASS exact 200000/1 CAPS with unchanged DATA128 wire envelope");
#ifdef MT_TEST_BULK_OFFER
    active();first_half(500);CHECK(mt_live_adc_service(&binding)==1);
    CHECK(mt_live_device_step(&device));
    CHECK(write_calls==1 && maximum_offer>=306 && maximum_offer<=307);
    CHECK(device.prefix_end==128 && device.queue.used==3 && device.tx_next==2);
    CHECK(mt_wire_decode_revision(wire_bytes,wire_used-1,0,2,&caps)==MT_WIRE_OK);
    CHECK(caps.type==152 && caps.sequence==1);
    puts("PASS exact core DATA128 serializes/commits in one bulk write");
    active();first_half(500);CHECK(mt_live_adc_service(&binding)==1);
    write_limit=17;CHECK(mt_live_device_step(&device));
    CHECK(device.tx_offset==17 && device.tx_next==2 && device.prefix_end==0 && device.queue.used==4);
    write_limit=0;CHECK(mt_live_device_step(&device));
    CHECK(device.tx_offset==17 && device.tx_next==2 && device.prefix_end==0 && device.queue.used==4);
    write_limit=SIZE_MAX;CHECK(mt_live_device_step(&device));
    CHECK(device.prefix_end==128 && device.queue.used==3 && device.tx_next==2);
    CHECK(mt_wire_decode_revision(wire_bytes,wire_used-1,0,2,&caps)==MT_WIRE_OK);
    CHECK(caps.type==152 && caps.sequence==1);
    active();first_half(500);CHECK(mt_live_adc_service(&binding)==1);
    write_unknown=true;CHECK(!mt_live_device_step(&device));
    CHECK(device.prefix_end==0 && device.local_error==MT_LIVE_ERR_TRANSPORT);
    CHECK(device.queue.sealed && device.needs_delimiter && device.hardware_off);
    puts("PASS partial/zero acceptance keeps sequence/prefix; unknown acceptance fences source");
    extern void check_bulk_live_write(void);
    check_bulk_live_write();
    extern void check_fifo_payload(void);
    check_fifo_payload();
#endif
    return 0;
}
