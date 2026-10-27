#include "mt_live_runtime.h"
#include "../platform/mt_stream_diag.h"
#include "../platform/mt_stream_progress.h" /* N_PROGRESS_INCLUDE */
#include "../platform/mt_usb_ctr.h"
#include "tusb.h"
#include <stddef.h>
#if !CFG_MT_USB_BRIDGE || !CFG_MT_USB_CTR_FAIRNESS
#error "Stream runtime requires guarded USB and opt-in CTR fairness"
#endif
#if CFG_TUD_CDC != 1 || CFG_TUD_CDC_TX_OVERWRITABLE_IF_NOT_CONNECTED != 0 || \
    CFG_TUD_CDC_RX_PERSISTENT != 0 || CFG_TUD_CDC_TX_PERSISTENT != 0
#error "Stream runtime requires one non-overwritable, nonpersistent CDC interface"
#endif
static uint32_t adc_read(void *context, uint32_t address) {
    mt_live_runtime *r=context; return r->mmio.read32(r->mmio.context,address);
}
static void adc_write(void *context, uint32_t address, uint32_t value) {
    mt_live_runtime *r=context; r->mmio.write32(r->mmio.context,address,value);
}
static uint32_t adc_time(void *context) {
    mt_live_runtime *r=context; return mt_timebase_now_us(r->clock);
}
static uint64_t live_time(void *context) {
    mt_live_runtime *r=context; return mt_live_clock_now(&r->clock64);
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
static uint32_t commit_enter(void *context) { (void)context; return mt_usb_bridge_lock(); }
static void commit_leave(void *context,uint32_t key) { (void)context; mt_usb_bridge_unlock(key); }
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
/* The two expensive validated snapshots surround a narrow physical CEN bracket.
 * PRIMASK is already held by the driver; no ISR or foreground writer can alter
 * TIME state, its callbacks or the original USB actor within this transaction.
 * Hardware lifecycle flags remain live and usable() checks them on both sides.
 * Raw CNT values are NEVER published without the final full validation. */
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
static int live_start(void *context,uint32_t generation) {
    mt_live_runtime *r=context;
    return usable(r) && mt_usb_bridge_actor() &&
        mt_live_adc_start_transaction(&r->acquisition,generation,commit_timer);
}
static void live_stop(void *context,mt_live_snapshot *snapshot) {
    mt_live_runtime *r=context;
#if CFG_MT_STREAM_DIAGNOSTICS
    /* The core reserves a validated START before its preliminary quiesce.
     * Bind here so a failed barrier cannot hide the first attempted run. */
    if(r->device.state==MT_LIVE_STOPPED && r->device.want_start)
        MT_DIAG_BEGIN(r->device.generation,r->device.nonce);
#endif
    mt_live_adc_quiesce(&r->acquisition,snapshot);
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
#if CFG_MT_PROGRESS_TRACE /* N_PROGRESS */
        if(r->device.tx_type==152u)mt_progress_zero_space();
#endif
        mt_usb_bridge_leave(&scope); return 0;
    }
    r->writer_active=1;
    accepted=tud_cdc_n_write(0,bytes,(uint32_t)length);
    r->writer_active=0;
    mt_usb_bridge_leave(&scope);
    /* An epoch loss after the copy never erases a known positive acceptance. */
    return accepted;
}
static int live_isolate(void *context) {
    mt_live_runtime *r=context;
    /* Sole synchronous foreground writer; accepted FIFO bytes remain ordered.
     * No clearing here: hard-loss quarantine is a separate lifecycle action. */
    return r && r->initialized && r->in_step && !r->writer_active && usable(r);
}
/* Called only within the pre-existing write/commit IRQ guard. Preparing
 * bytes never certifies transport identity: hardware flags remain live. */
static int prepared_tx_step(mt_live_runtime *r,const mt_live_tx_ticket *ticket,
                             uint32_t prepared_epoch,uint32_t prepared_soft_serial) {
    if(r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial || !usable(r))return 1;
    return mt_live_device_step_prepared(&r->device,ticket);
}
static int prepare_adc(mt_live_runtime *r) {
    const uint32_t ahb=0x40021014u,apb2=0x40021018u,apb1=0x4002101cu;
    adc_write(r,ahb,adc_read(r,ahb)|1u);
    adc_write(r,apb2,adc_read(r,apb2)|(1u<<2)|(1u<<9));
    adc_write(r,apb1,adc_read(r,apb1)|(1u<<1));
    return (adc_read(r,ahb)&1u) &&
        (adc_read(r,apb2)&((1u<<2)|(1u<<9)))==((1u<<2)|(1u<<9)) &&
        (adc_read(r,apb1)&(1u<<1)) && !(adc_read(r,0x4002100cu)&(1u<<9)) &&
        !(adc_read(r,0x40021010u)&(1u<<1)) &&
        !(adc_read(r,0x40000400u)&1u) && adc_read(r,0x40012408u)==0u &&
        !(adc_read(r,0x40020008u)&1u);
}
mt_live_runtime_result mt_live_runtime_init(mt_live_runtime *r,mt_timebase *clock,
    const mt_live_runtime_mmio *mmio,uint32_t hse_hz,mt_usb_lock_fn enter,
    mt_usb_unlock_fn leave,uint32_t build,unsigned require_dtr,uint32_t bound_ms) {
    mt_live_runtime_mmio saved; mt_adc_dma_io_t adc_io; mt_adc_dma_start_guard guard;
    mt_live_io io;
    if(!r || r->initialized || !clock || !mmio || !mmio->read32 || !mmio->write32 ||
       !enter || !leave || require_dtr>1u || !bound_ms || bound_ms>=500u || tud_inited())
        return MT_LIVE_RUNTIME_ARGUMENT;
    if(!mt_timebase_update(clock))return MT_LIVE_RUNTIME_TIME_FAULT;
    saved=*mmio; *r=(mt_live_runtime){0}; r->clock=clock; r->mmio=saved;
    r->require_dtr=require_dtr;
    if(!prepare_adc(r))return MT_LIVE_RUNTIME_ADC_UNSAFE;
    adc_io=(mt_adc_dma_io_t){adc_read,adc_write,adc_time,r};
    if(mt_adc_dma_init(&r->adc,&adc_io,hse_hz)!=MT_ADC_DMA_OK ||
       !mt_live_clock_init(&r->clock64,clock))return MT_LIVE_RUNTIME_ARGUMENT;
    guard=(mt_adc_dma_start_guard){.enter=commit_enter,.allowed=commit_allowed,
        .leave=commit_leave,.context=r,.timed_allowed=commit_timed};
    if(!mt_live_adc_init(&r->acquisition,&r->adc,clock,&r->device,&guard))
        return MT_LIVE_RUNTIME_ARGUMENT;
    io=(mt_live_io){.context=r,.clock_ms=live_time,.start=live_start,.quiesce=live_stop,
        .write=live_write,.isolate_tx=live_isolate,.transaction_bound_ms=bound_ms,
        .firmware_build=build};
    if(!mt_live_device_init(&r->device,&io))return MT_LIVE_RUNTIME_ARGUMENT;
    mt_usb_bridge_init(enter,leave); r->initialized=1; return MT_LIVE_RUNTIME_OK;
}
static int quiescent(const mt_live_runtime *r) {
    return r->device.hardware_off && !r->adc.owns_peripherals &&
        r->adc.state==MT_ADC_DMA_STOPPED;
}
static mt_live_runtime_result time_fault(mt_live_runtime *r);
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
#if CFG_MT_PROGRESS_TRACE /* N_PROGRESS */
    mt_progress_close(&r->device,MT_N_CLOSE_TIME,MT_LIVE_ERR_CLOCK);
#endif
    r->clock_fault=1; r->open=0; r->pending=2;
    r->carry_offset=r->carry_used=0;
    mt_adc_dma_invalidate_stream_history(&r->adc,MT_ADC_DMA_FAULT_CLOCK);
    mt_live_device_transport_lost(&r->device);
    (void)tud_cdc_n_write_clear(0);
    return MT_LIVE_RUNTIME_TIME_FAULT;
}
/* Sole grant opportunity, after actual ADC service or on an early-return
 * fallback. The caller's attempt marker prevents a second6/<500us reset.
 * Keep the original epoch/task/lifecycle gating exactly the same. */
static void grant_irq(mt_live_runtime *r) {
    uint32_t key;
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
}
/* Invoked only AFTER the existing flush and its final clock/loss barrier.
 * No new grant or task dispatch: an already armed tail may overlap collect.
 * The observer span includes this ownership work; it is not CPU-only time. */
static mt_live_runtime_result prefetch_after_tx(mt_live_runtime *r,mt_live_tx_ticket *ticket,
        uint32_t prepared_epoch,uint32_t prepared_soft_serial) {
    mt_usb_scope scope;uint32_t key;
    mt_live_prepare_result result;int ok;
    if(!mt_live_device_prefetch_ready(&r->device,ticket))return MT_LIVE_RUNTIME_OK;
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(!usable(r) || r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial)
        return MT_LIVE_RUNTIME_IDLE;
    if(!mt_usb_bridge_app_enter(&scope))return MT_LIVE_RUNTIME_IDLE;
    if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
    if(r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial) {
        mt_usb_bridge_leave(&scope);return MT_LIVE_RUNTIME_IDLE;
    }
#if CFG_MT_PROGRESS_TRACE /* Q_PREFETCH_SPAN */
    uint32_t progress_prepare=mt_progress_prepare_begin();
#endif
    result=mt_live_device_prefetch_tx(&r->device,ticket);
#if CFG_MT_PROGRESS_TRACE /* Q_PREFETCH_SPAN */
    mt_progress_prepare_end(progress_prepare);
#endif
    if(live_time(r)==UINT64_MAX) { mt_usb_bridge_leave(&scope); return time_fault(r); }
    if(!stable(r) || r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial) {
        mt_usb_bridge_leave(&scope);(void)synchronize_loss(r);return loss_result(r);
    }
    mt_usb_bridge_leave(&scope);
    if(result!=MT_LIVE_TX_ERROR)return MT_LIVE_RUNTIME_OK;
    /* A second guarded call is allowed ONLY for this matching deferred error.
     * EMPTY/COLLECT can never enter another DATA submit in this pass. */
    key=mt_usb_bridge_lock();
    ok=prepared_tx_step(r,ticket,prepared_epoch,prepared_soft_serial);
    mt_usb_bridge_unlock(key);
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    return ok?MT_LIVE_RUNTIME_OK:MT_LIVE_RUNTIME_RECOVERY;
}
/* Scheduling hint only: the existing prepare and guarded ticket remain the
 * authority. Delay no cached/collect-only/control or modes1..4 opportunity.
 * Streaming queue blocks have128 samples; malformed metadata cannot grant TX. */
static int defer_data_grant(const mt_live_runtime *r) {
    const mt_live_device *d=&r->device;
    unsigned count=d->batch.count,blocks=(unsigned)d->queue.used;
    if(d->mode!=5u || d->state!=MT_LIVE_STREAMING || d->tx_length ||
       d->want_start || d->want_caps || d->want_error || d->want_end || d->want_ack ||
       d->stop_seen || d->queue.sealed || d->queue.used>MT_SAMPLE_QUEUE_SLOTS ||
       count>1024u || (count&127u))return 0;
    if(d->batch.phase==MT_BATCH1024_EMPTY) {
        if(count)return 0;
    } else if(d->batch.phase!=MT_BATCH1024_COLLECT)return 0;
    if(blocks>4u)blocks=4u;
    return count+128u*blocks>=1024u;
}
static int new_data_ticket(const mt_live_tx_ticket *t) {
    return t->result==MT_LIVE_TX_PREPARED && !t->error &&
        t->state==MT_LIVE_STREAMING && t->mode==5u && t->tx_mode==5u &&
        t->tx_type==152u && !t->tx_offset && t->tx_count==1024u &&
        t->batch.phase==MT_BATCH1024_READY && t->batch.count==t->tx_count &&
        t->batch.length==t->tx_length && t->tx_length && t->tx_length<=1335u;
}
static mt_live_runtime_result step(mt_live_runtime *r,unsigned *grant_attempted) {
    mt_usb_scope scope; uint32_t key,prepared_epoch,prepared_soft_serial; int serviced,tx_ok;
    mt_live_tx_ticket ticket; unsigned deferred_grant;
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
    /* A task completion can already have armed the next IN transfer. Release
     * it after validated ADC service, before expensive RX/TX preparation.
     * The scope's actor remains owned; ISR may invalidate epoch/clock state. */
    deferred_grant=(unsigned)defer_data_grant(r);
    if(!deferred_grant) { *grant_attempted=1u; grant_irq(r); }
    /* New preemption boundary: no old RX FIFO read/rearm, core consumption or
     * TX is permitted before a fresh clock/epoch/lifecycle observation. */
    if(live_time(r)==UINT64_MAX) { mt_usb_bridge_leave(&scope); return time_fault(r); }
    if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
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
    /* Pure staging runs with the previous interrupt mask restored. The same
     * foreground owner retains queue/core bytes; ISR may only change USB epoch.
     * No new frame buffer, callbacks, or irreversible acceptance occurs here. */
    prepared_epoch=r->epoch; prepared_soft_serial=r->soft_serial;
#if CFG_MT_PROGRESS_TRACE /* N_PROGRESS */
    uint32_t progress_prepare=mt_progress_prepare_begin();
#endif
    (void)mt_live_device_prepare_tx(&r->device,&ticket);
#if CFG_MT_PROGRESS_TRACE /* N_PROGRESS */
    mt_progress_prepare_end(progress_prepare);
#endif
    if(deferred_grant) {
        /* Consume this opportunity even if its fresh admission is refused.
         * A failed app scope must not cause a second ordinary wrapper grant.
         * The next runtime pass retains the normal early-return fallback. */
        *grant_attempted=1u;
        if(live_time(r)==UINT64_MAX)return time_fault(r);
        if(!synchronize_loss(r))return loss_result(r);
        if(!usable(r))return MT_LIVE_RUNTIME_IDLE;
        if(!mt_usb_bridge_app_enter(&scope))return MT_LIVE_RUNTIME_IDLE;
        if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
        grant_irq(r);
        /* New IRQ boundary: restore the actor on every failure, then the old
         * guarded submit revalidates the pre-prepare epoch and full ticket. */
        if(live_time(r)==UINT64_MAX) { mt_usb_bridge_leave(&scope); return time_fault(r); }
        if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
        mt_usb_bridge_leave(&scope);
        /* Stop/HELLO may cancel the hint during RX. Preserve any newly staged
         * DATA bytes and send them via the ordinary cached path next pass;
         * EMPTY/control/deferred errors retain the original guarded handling. */
        if(ticket.result==MT_LIVE_TX_PREPARED && ticket.tx_type==152u &&
           !new_data_ticket(&ticket))return MT_LIVE_RUNTIME_IDLE;
    }
    MT_DIAG_STAMP(diag_tx);
    key=mt_usb_bridge_lock();
    tx_ok=prepared_tx_step(r,&ticket,prepared_epoch,prepared_soft_serial);
    mt_usb_bridge_unlock(key);
    MT_DIAG_TX_END(diag_tx);
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(mt_usb_bridge_app_enter(&scope)) {
        if(usable(r))(void)tud_cdc_n_write_flush(0);
        mt_usb_bridge_leave(&scope);
    }
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(tx_ok && ticket.tx_mode==5u && ticket.tx_type==152u &&
       ticket.tx_count==1024u && ticket.tx_offset && !r->device.tx_length &&
       r->device.batch.phase==MT_BATCH1024_EMPTY)
        return prefetch_after_tx(r,&ticket,prepared_epoch,prepared_soft_serial);
    return tx_ok ? MT_LIVE_RUNTIME_OK : MT_LIVE_RUNTIME_RECOVERY;
}
mt_live_runtime_result mt_live_runtime_step(mt_live_runtime *r) {
    mt_live_runtime_result result; unsigned grant_attempted=0u;
    if(!r || !r->initialized || r->in_step || !tud_inited())return MT_LIVE_RUNTIME_ARGUMENT;
    MT_DIAG_STAMP(diag_step);
    r->in_step=1; result=step(r,&grant_attempted);
    if(!grant_attempted)grant_irq(r);
#if CFG_MT_PROGRESS_TRACE /* N_PROGRESS */
    mt_progress_checkpoint(&r->device);
#endif
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
