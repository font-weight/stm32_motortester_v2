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

/* BODIES */

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
int main(void) {
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
