/* Exact runtime bodies; boundary callbacks are logical scheduling seams.
 * No DMA/USB execution, CPU timing or replacement for pinned core tests. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "app/mt_live_runtime.h"
#include "platform/mt_stream_diag.h"
#include "platform/mt_usb_ctr.h"
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL schedule line%d: %s trace=%s\n",__LINE__,#x,trace); exit(1); } } while(0)
static mt_live_runtime owner;
static mt_timebase time_source;
static mt_usb_epoch epoch;
static char trace[512];
static unsigned traced,depth,actor,time_calls,fail_time,adc_calls,task_calls,tx_calls;
static unsigned fifo_calls,flush_calls,cleaned_calls,lost_calls,grant_calls,grant_ctr;
static unsigned adc_ready,adc_fault,epoch_at_adc,epoch_at_task,epoch_at_tx,epoch_at_flush;
static unsigned fail_stop,pending_stop,rx_done,lifecycle,task_pending;
static size_t fifo_free,accepted;
static void mark(char c) { CHECK(traced+1<sizeof trace);trace[traced++]=c;trace[traced]=0; }
static void lose_epoch(void) { ++epoch.current;epoch.cleaned=0;epoch.configured=0;task_pending=1; }
static uint64_t live_time(void *p) {
    mt_live_runtime *r=p;mark('t');++time_calls;
    if(fail_time && time_calls>=fail_time) { r->clock64.failed=1;return UINT64_MAX; }
    return time_calls;
}
int mt_timebase_healthy(const mt_timebase *p) { return p && p->state==MT_TIMEBASE_RUNNING && !p->fault; }
uint32_t mt_usb_bridge_lock(void) { uint32_t previous=depth;++depth;return previous; }
void mt_usb_bridge_unlock(uint32_t previous) { CHECK(depth>previous);depth=previous; }
mt_usb_epoch mt_usb_bridge_snapshot(void) { return epoch; }
uint32_t mt_usb_bridge_actor(void) { return actor; }
bool mt_usb_fsdev_lifecycle_pending(void) { return lifecycle!=0; }
int mt_usb_bridge_app_enter(mt_usb_scope *s) {
    s->previous=actor;s->entered=0;
    if(lifecycle || !mt_usb_epoch_app_io(&epoch,epoch.current))return 0;
    actor=epoch.current;s->entered=1;return 1;
}
void mt_usb_bridge_leave(mt_usb_scope *s) { CHECK(s->entered);actor=s->previous;s->entered=0; }
void mt_usb_bridge_cleaned(uint32_t token) { mark('c');++cleaned_calls;epoch.cleaned=token; }
bool mt_usb_fsdev_irq_grant(bool allow) { CHECK(depth);mark('g');++grant_calls;grant_ctr=allow;return true; }
bool tud_inited(void) { return true; }
bool tud_task_event_ready(void) { return task_pending!=0; }
void tud_task_ext(uint32_t timeout,bool is_isr) {
    CHECK(!timeout && !is_isr);mark('u');++task_calls;if(epoch_at_task)lose_epoch();
}
bool tud_cdc_n_ready(uint8_t itf) { CHECK(itf==0);return true; }
bool tud_cdc_n_connected(uint8_t itf) { CHECK(itf==0);return true; }
uint32_t tud_cdc_n_read(uint8_t itf,void *bytes,uint32_t n) {
    CHECK(itf==0 && n);if(pending_stop && !rx_done) { *(uint8_t *)bytes=4;return 1; }return 0;
}
void tud_cdc_n_read_flush(uint8_t itf) { CHECK(itf==0); }
uint32_t tud_cdc_n_write_available(uint8_t itf) { CHECK(itf==0);return (uint32_t)fifo_free; }
uint32_t tud_cdc_n_write(uint8_t itf,const void *bytes,uint32_t n) {
    CHECK(itf==0 && bytes && n<=fifo_free && owner.writer_active && depth);
    mark('w');fifo_free-=n;++fifo_calls;return n;
}
uint32_t tud_cdc_n_write_flush(uint8_t itf) {
    CHECK(itf==0);mark('f');++flush_calls;if(epoch_at_flush)lose_epoch();return 0;
}
bool tud_cdc_n_write_clear(uint8_t itf) { CHECK(itf==0);mark('z');return true; }
void mt_adc_dma_invalidate_stream_history(mt_adc_dma_t *d,mt_adc_dma_fault_t fault) {
    mark('i');d->stream_history_valid=false;if(!d->first_fault)d->first_fault=fault;
}
void mt_live_device_transport_lost(mt_live_device *d) {
    mark('l');++lost_calls;
    /* Logical physical-stop seam: failure must not be a cleanup receipt. */
    if(fail_stop) { d->hardware_off=0;return; }
    owner.adc.owns_peripherals=false;owner.adc.state=MT_ADC_DMA_STOPPED;
    d->hardware_off=1;d->state=MT_LIVE_NEEDS_HELLO;
}
int mt_live_adc_service(mt_live_adc *b) {
    CHECK(b==&owner.acquisition);mark('a');++adc_calls;
    if(epoch_at_adc)lose_epoch();
    if(adc_fault) {
        if(!owner.device.first_reason)owner.device.first_reason=2;
        owner.adc.first_fault=MT_ADC_DMA_FAULT_TRANSFER;
        owner.device.state=MT_LIVE_DRAINING;return -1;
    }
    if(adc_ready)owner.device.queue.used+=4;
    return adc_ready ? 1 : 0;
}
int mt_live_device_receive(mt_live_device *d,const uint8_t *bytes,size_t n) {
    CHECK(d==&owner.device && n==1 && *bytes==4);mark('r');rx_done=1;
    /* Stop cannot erase an earlier acquisition fault. Core semantics are pinned. */
    d->stop_seen=1;d->state=MT_LIVE_DRAINING;return 1;
}
static int stable(mt_live_runtime *r);
static int usable(mt_live_runtime *r);
static int quiescent(const mt_live_runtime *r);
static mt_live_runtime_result time_fault(mt_live_runtime *r);
static mt_live_runtime_result loss_result(const mt_live_runtime *r);
static int synchronize_loss(mt_live_runtime *r);
static size_t live_write(void *context,const uint8_t *bytes,size_t length);
int mt_live_device_step(mt_live_device *d) {
    CHECK(d==&owner.device && depth);mark('x');++tx_calls;
    /* Do not manufacture DATA after the ADC source fault/Stop. The real core
     * may drain its retained prefix; this seam exercises runtime order only. */
    if(d->state==MT_LIVE_STREAMING) {
        uint8_t bytes[307]={0};accepted=live_write(&owner,bytes,sizeof bytes);
        if(accepted && accepted!=SIZE_MAX) { d->tx_offset+=accepted;d->prefix_end+=128; }
    }
    if(epoch_at_tx)lose_epoch();
    return 1;
}
static int stable(mt_live_runtime *r) {
    uint32_t key,token; int ok;
    if(!r || !r->initialized || r->pending || r->clock_fault || r->clock64.failed ||
       !mt_timebase_healthy(r->clock))return 0;
    key=mt_usb_bridge_lock();
    mt_usb_epoch s=mt_usb_bridge_snapshot(); token=mt_usb_bridge_actor();
    if(!token)token=s.current;
    ok=!mt_usb_fsdev_lifecycle_pending() && token==r->epoch &&
        s.soft_serial==r->soft_serial && mt_usb_epoch_app_io(&s,token);
    mt_usb_bridge_unlock(key); return ok;
}

static int usable(mt_live_runtime *r) {
    return r->open && stable(r) && tud_cdc_n_ready(0) &&
        (!r->require_dtr || tud_cdc_n_connected(0));
}

static int quiescent(const mt_live_runtime *r) {
    return r->device.hardware_off && !r->adc.owns_peripherals &&
        r->adc.state==MT_ADC_DMA_STOPPED;
}

static mt_live_runtime_result loss_result(const mt_live_runtime *r) {
    return r->clock_fault ? MT_LIVE_RUNTIME_TIME_FAULT : MT_LIVE_RUNTIME_RECOVERY;
}

static int synchronize_loss(mt_live_runtime *r) {
    mt_usb_epoch s=mt_usb_bridge_snapshot();
    if(s.current!=r->epoch || s.faults!=r->faults || s.exhausted!=r->exhausted) {
        r->epoch=s.current; r->faults=s.faults; r->exhausted=s.exhausted;
        r->soft_serial=s.soft_serial; r->pending=2;
    } else if(s.soft_serial!=r->soft_serial) {
        r->soft_serial=s.soft_serial; if(!r->pending)r->pending=1;
    }
    if(!r->pending)return 1;
    r->open=0; r->carry_offset=r->carry_used=0;
    r->rx_flush_pending=(r->pending==1u);
    mt_live_device_transport_lost(&r->device);
    if(r->pending==2u)(void)tud_cdc_n_write_clear(0);
    /* Stop callbacks can themselves discover a TIME failure. Never publish a
     * cleanup receipt or dispatch queued RESET using an earlier healthy read. */
    if(live_time(r)==UINT64_MAX || r->clock_fault) { (void)time_fault(r); return 0; }
    if(!quiescent(r))return 0;
    r->pending=0;
    /* Receipt only after actual off, not merely a software stop request. */
    mt_usb_bridge_cleaned(r->epoch); return 1;
}

static mt_live_runtime_result time_fault(mt_live_runtime *r) {
    r->clock_fault=1; r->open=0; r->pending=2;
    r->carry_offset=r->carry_used=0;
    mt_adc_dma_invalidate_stream_history(&r->adc,MT_ADC_DMA_FAULT_CLOCK);
    mt_live_device_transport_lost(&r->device);
    (void)tud_cdc_n_write_clear(0);
    return MT_LIVE_RUNTIME_TIME_FAULT;
}

static size_t live_write(void *context,const uint8_t *bytes,size_t length) {
    mt_live_runtime *r=context; mt_usb_scope scope; size_t accepted;
    if(!r || !r->initialized || !r->in_step || r->writer_active ||
       (!bytes && length) || length>384u)return SIZE_MAX;
    if(!length || !mt_usb_bridge_app_enter(&scope))return 0;
    if(!usable(r)) { mt_usb_bridge_leave(&scope); return 0; }
    /* The sole foreground writer already holds the core's IRQ/epoch guard.
     * Do not publish a partial next frame: a CDC completion could otherwise
     * arm that fragment before its remainder is admitted. Insufficient room
     * means known zero acceptance and leaves FIFO/core prefix unchanged. */
    if(tud_cdc_n_write_available(0)<length) {
        mt_usb_bridge_leave(&scope); return 0;
    }
    r->writer_active=1;
    accepted=tud_cdc_n_write(0,bytes,(uint32_t)length);
    r->writer_active=0;
    mt_usb_bridge_leave(&scope);
    /* An epoch loss after the copy never erases a known positive acceptance. */
    return accepted;
}

static mt_live_runtime_result step(mt_live_runtime *r) {
    mt_usb_scope scope; uint32_t key; int serviced,tx_ok;
    if(live_time(r)==UINT64_MAX || r->clock_fault)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    tud_task_ext(0,false);
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(!stable(r))return MT_LIVE_RUNTIME_IDLE;
    if(!tud_cdc_n_ready(0) || (r->require_dtr && !tud_cdc_n_connected(0))) {
        if(r->open) { r->pending=1; if(!synchronize_loss(r))return loss_result(r); }
        return MT_LIVE_RUNTIME_IDLE;
    }
    if(!mt_usb_bridge_app_enter(&scope))return MT_LIVE_RUNTIME_IDLE;
    if(!stable(r)) { mt_usb_bridge_leave(&scope); return MT_LIVE_RUNTIME_IDLE; }
    if(!r->open) {
        if(r->rx_flush_pending) {
            tud_cdc_n_read_flush(0);
            if(!stable(r)) { mt_usb_bridge_leave(&scope); return MT_LIVE_RUNTIME_RECOVERY; }
            r->rx_flush_pending=0;
        }
        r->open=1;
    }
    serviced=mt_live_adc_service(&r->acquisition);
    if(live_time(r)==UINT64_MAX) { mt_usb_bridge_leave(&scope); return time_fault(r); }
    if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
    if(serviced==-2) { mt_usb_bridge_leave(&scope); return MT_LIVE_RUNTIME_ARGUMENT; }
    if(r->carry_offset==r->carry_used) {
        r->carry_offset=0; r->carry_used=tud_cdc_n_read(0,r->carry,sizeof r->carry);
    }
    while(r->carry_offset<r->carry_used) {
        if(!usable(r))break;
        if(!mt_live_device_receive(&r->device,r->carry+r->carry_offset,1u))break;
        ++r->carry_offset;
    }
    mt_usb_bridge_leave(&scope);
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(!usable(r))return MT_LIVE_RUNTIME_IDLE;
    /* Preserve epoch and forbid USB ISR preemption through the core's final
     * post-write observation and state publication. Bound still needs proof. */
#if CFG_MT_STREAM_DIAGNOSTICS
    /* Preserve pre-TX causes and queue peak before HELLO commit or DATA pop. */
    mt_stream_diag_note(UINT32_MAX,r->epoch,(uint32_t)r->device.queue.used,
        r->device.local_error,r->device.first_reason,(uint32_t)r->adc.first_fault);
    if(quiescent(r) && r->device.state==MT_LIVE_HELLO_PENDING)
        mt_stream_diag_replaced((uint32_t)r->device.state,r->epoch,(uint32_t)r->adc.state);
#endif
    MT_DIAG_STAMP(diag_tx);
    key=mt_usb_bridge_lock(); tx_ok=mt_live_device_step(&r->device); mt_usb_bridge_unlock(key);
    MT_DIAG_TX_END(diag_tx);
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(mt_usb_bridge_app_enter(&scope)) {
        if(usable(r))(void)tud_cdc_n_write_flush(0);
        mt_usb_bridge_leave(&scope);
    }
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    return tx_ok ? MT_LIVE_RUNTIME_OK : MT_LIVE_RUNTIME_RECOVERY;
}

mt_live_runtime_result mt_live_runtime_step(mt_live_runtime *r) {
    mt_live_runtime_result result; uint32_t key;
    if(!r || !r->initialized || r->in_step || !tud_inited())return MT_LIVE_RUNTIME_ARGUMENT;
    MT_DIAG_STAMP(diag_step);
    r->in_step=1; result=step(r);
    if(!r->clock_fault && mt_timebase_healthy(r->clock)) {
        key=mt_usb_bridge_lock();
        mt_usb_epoch s=mt_usb_bridge_snapshot();
        /* One IRQ opportunity after foreground service. Old cleanup/queue
         * conditions still gate CTR; lifecycle must progress in quarantine. */
        int allow_ctr=!r->pending && !r->faults && !r->exhausted &&
           s.current==r->epoch && s.soft_serial==r->soft_serial &&
           s.cleaned==s.current && !s.pending_soft && !s.faults && !s.exhausted &&
           !tud_task_event_ready();
        (void)mt_usb_fsdev_irq_grant(allow_ctr != 0);
        mt_usb_bridge_unlock(key);
    }
#if CFG_MT_STREAM_DIAGNOSTICS
    if(quiescent(r) && (r->device.state==MT_LIVE_HELLO_PENDING || r->device.state==MT_LIVE_STOPPED)) {
        mt_stream_diag_note((uint32_t)result,r->epoch,(uint32_t)r->device.queue.used,
            r->device.local_error,r->device.first_reason,(uint32_t)r->adc.first_fault);
        mt_stream_diag_replaced((uint32_t)r->device.state,r->epoch,(uint32_t)r->adc.state);
    }
    mt_stream_diag_observe(diag_step,(uint32_t)result,(uint32_t)r->device.state,
        r->epoch,(uint32_t)r->adc.state,r->adc.owns_peripherals?1u:0u,
        r->device.hardware_off,(uint32_t)r->device.queue.used,r->device.local_error,
        r->device.first_reason,(uint32_t)r->adc.first_fault,
        quiescent(r) && (r->device.state==MT_LIVE_NEEDS_HELLO || r->device.state==MT_LIVE_FAULT));
#endif
    r->in_step=0; return result;
}

static void setup(void) {
    memset(&owner,0,sizeof owner);memset(&time_source,0,sizeof time_source);
    memset(&epoch,0,sizeof epoch);memset(trace,0,sizeof trace);
    traced=depth=actor=time_calls=fail_time=adc_calls=task_calls=tx_calls=0;
    fifo_calls=flush_calls=cleaned_calls=lost_calls=grant_calls=grant_ctr=0;
    adc_ready=adc_fault=epoch_at_adc=epoch_at_task=epoch_at_tx=epoch_at_flush=0;
    fail_stop=pending_stop=rx_done=lifecycle=task_pending=0;fifo_free=384;accepted=SIZE_MAX;
    epoch.current=epoch.processed_reset=epoch.cleaned=epoch.configured=3;
    owner.initialized=owner.open=owner.require_dtr=1;owner.epoch=3;
    owner.clock=&time_source;time_source.state=MT_TIMEBASE_RUNNING;
    owner.adc.state=MT_ADC_DMA_RUNNING;owner.adc.owns_peripherals=true;
    owner.adc.stream_history_valid=true;owner.device.state=MT_LIVE_STREAMING;
}
static unsigned position(char c) { char *p=strchr(trace,c);CHECK(p);return (unsigned)(p-trace); }
static void healthy_and_ready(void) {
    setup();adc_ready=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(adc_calls==1 && owner.device.queue.used==4 && rx_done && !fifo_calls);
    CHECK(position('u')<position('a') && position('a')<position('r') && position('r')<position('x'));
    CHECK(position('x')<position('f') && position('f')<position('g'));
    CHECK(time_calls==6 && grant_calls==1 && grant_ctr && !depth && !owner.in_step);
    setup();adc_ready=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(adc_calls==1 && accepted==307 && fifo_calls==1 && owner.device.prefix_end==128);
    puts("PASS exact runtime order: task/one ready ADC/RX Stop/TX/flush/IRQ; six TIME barriers");
}
static void known_zero_and_adc_fault(void) {
    setup();fifo_free=306;owner.device.tx_offset=17;owner.device.prefix_end=64;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(accepted==0 && !fifo_calls && fifo_free==306 && !owner.writer_active);
    CHECK(owner.device.tx_offset==17 && owner.device.prefix_end==64);
    setup();adc_fault=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(adc_calls==1 && rx_done && owner.device.stop_seen && !fifo_calls && !owner.device.prefix_end);
    CHECK(owner.device.first_reason==2 && owner.adc.first_fault==MT_ADC_DMA_FAULT_TRANSFER);
    CHECK(position('a')<position('r') && position('r')<position('x'));
    puts("PASS known-zero preserves prefix; ADC -1 then pending Stop retains first reason/no new DATA");
}
static void epoch_and_failed_stop(void) {
    setup();epoch_at_adc=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(adc_calls==1 && !rx_done && !tx_calls && lost_calls==1 && cleaned_calls==1 && !grant_ctr);
    setup();epoch_at_task=1;fail_stop=1;pending_stop=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(!adc_calls && !rx_done && !tx_calls && lost_calls==1 && !cleaned_calls && owner.pending);
    CHECK(!owner.device.hardware_off && owner.adc.owns_peripherals && grant_calls==1 && !grant_ctr);
    setup();epoch_at_tx=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(fifo_calls==1 && owner.device.prefix_end==128 && lost_calls==1 && cleaned_calls==1);
    CHECK(!flush_calls && !grant_ctr);
    setup();epoch_at_flush=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(fifo_calls==1 && flush_calls==1 && lost_calls==1 && cleaned_calls==1 && !grant_ctr);
    puts("PASS epoch loss during ADC/task/TX/flush; failed Stop blocks cleanup/CTR; accepted bytes retained");
}
static void time_and_irq(void) {
    for(unsigned boundary=1;boundary<=6;++boundary) {
        setup();fail_time=boundary;
        CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_TIME_FAULT);
        CHECK(owner.clock_fault && owner.pending==2 && !owner.open && !owner.adc.stream_history_valid);
        CHECK(!grant_calls && !depth && !owner.in_step);
        CHECK(owner.device.prefix_end==(boundary>=5 ? 128u : 0u));
    }
    setup();task_pending=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK && grant_calls==1 && !grant_ctr);
    setup();lifecycle=1;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE && !adc_calls && !tx_calls && !fifo_calls);
    puts("PASS TIME failure at all six barriers is sticky/no IRQ grant; pending task and lifecycle gate retained");
}
int main(void) {
    healthy_and_ready();known_zero_and_adc_fault();epoch_and_failed_stop();time_and_irq();
    puts("PASS narrow S4 schedule runtime model; logical callbacks, no physical timing claim");return 0;
}
