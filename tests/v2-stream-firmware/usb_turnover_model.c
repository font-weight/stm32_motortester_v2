/* Actual runtime bodies are inserted by the runner. USB/ADC/core callbacks
 * below are logical order seams, not a USB scheduler or physical time model. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "app/mt_live_runtime.h"
#include "platform/mt_stream_diag.h"
#include "platform/mt_usb_ctr.h"
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL turnover line%d: %s trace=%s\n",__LINE__,#x,trace);exit(1); } } while(0)
static mt_live_runtime owner;
static mt_timebase clock_source;
static mt_usb_epoch epoch;
static char trace[512];
static unsigned traced,depth,actor,time_calls,fail_time,healthy_after_adc;
static unsigned adc_calls,task_calls,rx_reads,core_rx,prepare_calls,tx_calls;
static unsigned fifo_calls,flush_calls,cleaned_calls,lost_calls,clear_calls;
static unsigned grant_calls,grant_allow,grant_actor,grant_unlock_armed,grant_result;
static unsigned task_pending,completed_events,adc_ready,adc_fault,adc_argument;
static unsigned epoch_at_adc,pending_at_adc,inject_at_grant,lifecycle;
static unsigned pending_stop,ready,rx_done,decline_grant_health,declined_health_checks;
static size_t fifo_free,accepted;
enum { INJECT_NONE, INJECT_EPOCH, INJECT_TIME, INJECT_LIFECYCLE, INJECT_FINAL };

static void mark(char c) { CHECK(traced+1<sizeof trace);trace[traced++]=c;trace[traced]=0; }
static void lose_epoch(void) {
    CHECK(mt_usb_epoch_reset(&epoch));task_pending=1;
}
static uint64_t live_time(void *p) {
    mt_live_runtime *r=p;mark('t');++time_calls;
    if(r->clock64.failed || (fail_time && time_calls>=fail_time)) {
        r->clock64.failed=1;return UINT64_MAX;
    }
    return time_calls;
}
int mt_timebase_healthy(const mt_timebase *p) {
    /* A one-call refusal at the helper isolates the attempt-marker rule.
     * This seam is deliberately not a model of real sticky TIME hardware. */
    if(adc_calls && ++healthy_after_adc==2 && decline_grant_health) {
        ++declined_health_checks;return 0;
    }
    return p && p->state==MT_TIMEBASE_RUNNING && !p->fault;
}
uint32_t mt_usb_bridge_lock(void) { uint32_t old=depth;++depth;return old; }
void mt_usb_bridge_unlock(uint32_t old) {
    CHECK(depth>old);depth=old;
    if(!depth && grant_unlock_armed) {
        grant_unlock_armed=0;
        if(inject_at_grant==INJECT_EPOCH)lose_epoch();
        if(inject_at_grant==INJECT_TIME)owner.clock64.failed=1;
        if(inject_at_grant==INJECT_LIFECYCLE)lifecycle=1;
        if(inject_at_grant==INJECT_FINAL)task_pending=1;
    }
}
mt_usb_epoch mt_usb_bridge_snapshot(void) { return epoch; }
uint32_t mt_usb_bridge_actor(void) { return actor; }
bool mt_usb_fsdev_lifecycle_pending(void) { return lifecycle!=0; }
int mt_usb_bridge_app_enter(mt_usb_scope *s) {
    s->previous=actor;s->entered=0;
    if(lifecycle || !mt_usb_epoch_app_io(&epoch,epoch.current))return 0;
    actor=epoch.current;s->entered=1;return 1;
}
void mt_usb_bridge_leave(mt_usb_scope *s) { CHECK(s->entered);actor=s->previous;s->entered=0; }
void mt_usb_bridge_cleaned(uint32_t token) {
    mark('c');++cleaned_calls;CHECK(mt_usb_epoch_cleaned(&epoch,token));
}
bool mt_usb_fsdev_irq_grant(bool allow) {
    CHECK(depth);mark('g');++grant_calls;grant_allow=allow;grant_actor=actor;
    grant_unlock_armed=1;return grant_result!=0;
}
bool tud_inited(void) { return true; }
bool tud_task_event_ready(void) { return task_pending!=0; }
void tud_task_ext(uint32_t timeout,bool in_isr) {
    CHECK(!timeout && !in_isr && !actor);mark('u');++task_calls;
    /* Logical final-IN completion event: actual TinyUSB/DCD are not run. */
    if(task_pending) { task_pending=0;++completed_events;mark('e'); }
}
bool tud_cdc_n_ready(uint8_t itf) { CHECK(!itf);return ready!=0; }
bool tud_cdc_n_connected(uint8_t itf) { CHECK(!itf);return true; }
uint32_t tud_cdc_n_read(uint8_t itf,void *bytes,uint32_t n) {
    CHECK(!itf && n && actor==owner.epoch && !lifecycle && !owner.clock64.failed);
    mark('q');++rx_reads;
    if(pending_stop && !rx_done) { *(uint8_t *)bytes=4;return 1; }
    return 0;
}
void tud_cdc_n_read_flush(uint8_t itf) { CHECK(!itf); }
uint32_t tud_cdc_n_write_available(uint8_t itf) { CHECK(!itf);return (uint32_t)fifo_free; }
uint32_t tud_cdc_n_write(uint8_t itf,const void *bytes,uint32_t n) {
    CHECK(!itf && bytes && n<=fifo_free && owner.writer_active && depth);
    mark('w');fifo_free-=n;++fifo_calls;return n;
}
uint32_t tud_cdc_n_write_flush(uint8_t itf) { CHECK(!itf);mark('f');++flush_calls;return 0; }
bool tud_cdc_n_write_clear(uint8_t itf) { CHECK(!itf);mark('z');++clear_calls;return true; }
void mt_adc_dma_invalidate_stream_history(mt_adc_dma_t *d,mt_adc_dma_fault_t f) {
    mark('i');d->stream_history_valid=false;if(!d->first_fault)d->first_fault=f;
}
void mt_live_device_transport_lost(mt_live_device *d) {
    mark('l');++lost_calls;owner.adc.owns_peripherals=false;
    owner.adc.state=MT_ADC_DMA_STOPPED;d->hardware_off=1;d->state=MT_LIVE_NEEDS_HELLO;
}
int mt_live_adc_service(mt_live_adc *a) {
    CHECK(a==&owner.acquisition);mark('a');++adc_calls;
    if(epoch_at_adc)lose_epoch();
    if(pending_at_adc)task_pending=1;
    if(adc_argument)return -2;
    if(adc_fault) {
        if(!owner.device.first_reason)owner.device.first_reason=2;
        owner.adc.first_fault=MT_ADC_DMA_FAULT_TRANSFER;
        owner.device.state=MT_LIVE_DRAINING;return -1;
    }
    if(adc_ready)owner.device.queue.used+=4;
    return adc_ready ? 1 : 0;
}
int mt_live_device_receive(mt_live_device *d,const uint8_t *b,size_t n) {
    CHECK(d==&owner.device && n==1 && *b==4 && actor==owner.epoch);
    mark('r');++core_rx;rx_done=1;d->stop_seen=1;d->state=MT_LIVE_DRAINING;return 1;
}
static int stable(mt_live_runtime *r);
static int usable(mt_live_runtime *r);
static int quiescent(const mt_live_runtime *r);
static mt_live_runtime_result time_fault(mt_live_runtime *r);
static mt_live_runtime_result loss_result(const mt_live_runtime *r);
static int synchronize_loss(mt_live_runtime *r);
static size_t live_write(void *context,const uint8_t *bytes,size_t length);
mt_live_prepare_result mt_live_device_prepare_tx(mt_live_device *d,mt_live_tx_ticket *ticket) {
    CHECK(d==&owner.device && !depth && !actor);mark('p');++prepare_calls;
    memset(ticket,0,sizeof *ticket);return MT_LIVE_TX_PREPARED;
}
int mt_live_device_step_prepared(mt_live_device *d,const mt_live_tx_ticket *ticket) {
    CHECK(d==&owner.device && ticket && depth);mark('x');++tx_calls;
    /* Only runtime order/whole-fit path is exercised here. Real core commit
     * semantics remain covered by the already-pinned G actual-core model. */
    if(d->state==MT_LIVE_STREAMING) {
        uint8_t bytes[307]={0};accepted=live_write(&owner,bytes,sizeof bytes);
        if(accepted && accepted!=SIZE_MAX) { d->tx_offset+=accepted;d->prefix_end+=128; }
    }
    return 1;
}
/* BODIES */
static void setup(void) {
    memset(&owner,0,sizeof owner);memset(&clock_source,0,sizeof clock_source);
    memset(&epoch,0,sizeof epoch);memset(trace,0,sizeof trace);
    traced=depth=actor=time_calls=fail_time=healthy_after_adc=0;
    adc_calls=task_calls=rx_reads=core_rx=prepare_calls=tx_calls=0;
    fifo_calls=flush_calls=cleaned_calls=lost_calls=clear_calls=0;
    grant_calls=grant_allow=grant_actor=grant_unlock_armed=0;grant_result=1;
    task_pending=completed_events=adc_ready=adc_fault=adc_argument=0;
    epoch_at_adc=pending_at_adc=inject_at_grant=lifecycle=0;
    pending_stop=rx_done=decline_grant_health=declined_health_checks=0;ready=1;
    fifo_free=384;accepted=SIZE_MAX;
    epoch.current=epoch.processed_reset=epoch.cleaned=epoch.configured=3;
    owner.initialized=owner.open=owner.require_dtr=1;owner.epoch=3;
    owner.clock=&clock_source;clock_source.state=MT_TIMEBASE_RUNNING;
    owner.adc.state=MT_ADC_DMA_RUNNING;owner.adc.owns_peripherals=true;
    owner.adc.stream_history_valid=true;owner.device.state=MT_LIVE_STREAMING;
}
static unsigned pos(char c) { char *p=strchr(trace,c);CHECK(p);return (unsigned)(p-trace); }
static void settled(void) { CHECK(!depth && !actor && !owner.in_step && !owner.writer_active); }
static void no_old_io(void) { CHECK(!rx_reads && !core_rx && !prepare_calls && !tx_calls && !fifo_calls);settled(); }

static void order_and_event_turnover(void) {
    setup();adc_ready=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(adc_calls==1 && owner.device.queue.used==4 && rx_done && !fifo_calls);
    CHECK(pos('u')<pos('a') && pos('a')<pos('g') && pos('g')<pos('q'));
    CHECK(pos('q')<pos('r') && pos('r')<pos('p') && pos('p')<pos('x') && pos('x')<pos('f'));
    CHECK(time_calls==7 && grant_calls==1 && grant_allow && grant_actor==3);settled();
    setup();task_pending=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(completed_events==1 && !task_pending && grant_calls==1 && grant_allow);
    CHECK(pos('e')<pos('a') && pos('a')<pos('g') && pos('g')<pos('p'));settled();
    setup();pending_at_adc=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(task_pending && !completed_events && grant_calls==1 && !grant_allow);
    pending_at_adc=0;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(completed_events==1 && !task_pending && grant_calls==2 && grant_allow);settled();
    setup();inject_at_grant=INJECT_FINAL;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(task_pending && grant_calls==1 && grant_allow);
    inject_at_grant=INJECT_NONE;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(completed_events==1 && !task_pending && grant_calls==2 && grant_allow);settled();
    puts("PASS task/ADC/TIME/grant/fresh TIME/RX/prepare/TX/flush order; final events before/after task or grant; one attempt per step");
}
static void new_preemption_barrier(void) {
    setup();inject_at_grant=INJECT_EPOCH;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(grant_calls==1 && grant_actor==3 && owner.epoch==4 && lost_calls==1 && cleaned_calls==1);
    CHECK(clear_calls==1 && owner.device.hardware_off);no_old_io();
    setup();inject_at_grant=INJECT_TIME;pending_stop=1;
    owner.carry[0]=4;owner.carry_used=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_TIME_FAULT);
    CHECK(grant_calls==1 && owner.clock_fault && owner.pending==2 && lost_calls==1);
    CHECK(!owner.adc.stream_history_valid && !owner.carry_used && !cleaned_calls);no_old_io();
    setup();inject_at_grant=INJECT_LIFECYCLE;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(grant_calls==1 && lifecycle && !lost_calls);no_old_io();
    puts("PASS epoch/TIME/raw lifecycle at early-grant unlock blocks stale RX read/rearm/core/TX and restores scope; no second grant");
}
static void denial_fallback_and_first_cause(void) {
    setup();grant_result=0; /* DCD FRES/refusal seam, not another IRQ chance. */
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK && grant_calls==1);settled();
    setup();decline_grant_health=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(declined_health_checks==1 && !grant_calls);settled();
    setup();adc_argument=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_ARGUMENT);
    CHECK(adc_calls==1 && grant_calls==1 && !grant_actor);no_old_io();
    setup();ready=0;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);
    CHECK(!adc_calls && grant_calls==1 && !grant_actor && lost_calls==1);no_old_io();
    setup();epoch_at_adc=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(adc_calls==1 && grant_calls==1 && !grant_allow && !grant_actor && cleaned_calls==1);no_old_io();
    setup();fail_time=3;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_TIME_FAULT);
    CHECK(adc_calls==1 && !grant_calls && owner.clock_fault);no_old_io();
    setup();adc_fault=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(grant_calls==1 && core_rx==1 && owner.device.stop_seen && !fifo_calls);
    CHECK(owner.device.first_reason==2 && owner.adc.first_fault==MT_ADC_DMA_FAULT_TRANSFER);settled();
    setup();fifo_free=306;owner.device.prefix_end=64;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(grant_calls==1 && accepted==0 && !fifo_calls && owner.device.prefix_end==64);settled();
    setup();CHECK(mt_live_runtime_step(NULL)==MT_LIVE_RUNTIME_ARGUMENT && !grant_calls);
    puts("PASS refused/denied grant consumes marker; prior early returns retain one fallback; TIME/ADC cause and whole-fit known-zero unchanged");
}
int main(void) {
    order_and_event_turnover();new_preemption_barrier();denial_fallback_and_first_cause();
    puts("PASS narrow actual-runtime turnover model; logical seams only, no physical USB/DMA/timing claim");return 0;
}
