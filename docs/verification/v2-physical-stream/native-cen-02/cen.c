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
int main(void) {
    setup(20);
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    CHECK(driver.state==MT_ADC_DMA_RUNNING && driver.stream_history_valid);
    CHECK(driver.start_after_us-driver.start_before_us==20u);
    CHECK(raw_before<65536u && raw_after>=65536u);
    CHECK(driver.start_before_us>UINT32_MAX-100u && driver.start_after_us<100u);
    CHECK(outer_end-outer_start>20u && mask==0 && cen_seen==1u);
    /* Negative control: the old full-validation timestamp path includes the
     * same deliberately expensive work and must fail its unchanged20us gate. */
    setup(20);
    CHECK(mt_adc_dma_start_guarded(&driver,&guard)==MT_ADC_DMA_ERROR);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_TIMEBASE);
    CHECK(driver.start_after_us-driver.start_before_us>20u);
    is_off();
    puts("PASS expensive full guards / 20us / CNT16 and us32 wrap; old path rejects");

    setup(21);initial_mask=mask=1;
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_ERROR);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_TIMEBASE);
    CHECK(observed_after-observed_before==21u);
    CHECK(driver.start_before_us==0x1234u && driver.start_after_us==0x5678u);
    is_off();
    puts("PASS 21us rejection / original PRIMASK restored / verified quiesce");

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
