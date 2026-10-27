#include "mt_stream_progress.h"
#include "mt_stream_diag.h"
#include "mt_usb_ctr.h"
#include "mt_usb_gate.h" /* R_GATE_INCLUDE */
#include "../transport/mt_usb_bridge.h"
#include "tusb.h"
#if !CFG_MT_PROGRESS_TRACE || !CFG_MT_STREAM_DIAGNOSTICS
#error "Progress trace requires explicit opt-in and unchanged legacy diagnostics"
#endif

volatile mt_stream_progress_record mt_stream_progress;

static unsigned phase(void) { return mt_stream_progress.flags&MT_N_PHASE_MASK; }
static int active(void) { return phase()==MT_N_ACTIVE; }
static void state(unsigned value) {
    mt_stream_progress.flags=(mt_stream_progress.flags&~(uint32_t)MT_N_PHASE_MASK)|value;
}
static uint32_t cycle(void) {
#if defined(MT_PROGRESS_NATIVE) && MT_PROGRESS_NATIVE
    extern uint32_t mt_progress_native_cycle(void);
    return mt_progress_native_cycle();
#else
    return *(volatile uint32_t *)(uintptr_t)UINT32_C(0xe0001004);
#endif
}
static void add32(volatile uint32_t *value,uint32_t amount) {
    if(UINT32_MAX-*value<amount) {
        *value=UINT32_MAX;mt_stream_progress.flags|=MT_N_SATURATED;
    } else *value+=amount;
}
static void increment(volatile uint16_t *value) {
    if(*value==UINT16_MAX)mt_stream_progress.flags|=MT_N_SATURATED;
    else ++*value;
}
static void gap(uint32_t end) {
    uint32_t elapsed=end-mt_stream_progress.last_positive_cycle;
    if(elapsed>mt_stream_progress.max_positive_gap_cycles)
        mt_stream_progress.max_positive_gap_cycles=elapsed;
}
static int paired(const mt_live_device *d) {
    return d && d->generation && d->nonce &&
        mt_stream_diagnostics.firmware_build==MT_N_BUILD &&
        mt_stream_diagnostics.generation==d->generation &&
        mt_stream_diagnostics.nonce_low==(uint32_t)d->nonce &&
        mt_stream_diagnostics.nonce_high==(uint32_t)(d->nonce>>32);
}
static int bind(const mt_live_device *d) {
    if(phase()!=MT_N_EMPTY || !paired(d))return 0;
    mt_stream_progress=(mt_stream_progress_record){.magic=MT_N_MAGIC,
        .flags=MT_N_ARMED,.generation=d->generation,
        .nonce_low=(uint32_t)d->nonce,.nonce_high=(uint32_t)(d->nonce>>32),
        .tx_offset=UINT16_MAX,.tx_length=UINT16_MAX,.stage_count=UINT16_MAX,
        .fifo_free=UINT16_MAX,.stage_phase=UINT8_MAX,.queue_used=UINT8_MAX};
    return 1;
}
void mt_progress_begin(const mt_live_device *d) {
    uint32_t start;
    if(!bind(d))return;
    if(mt_stream_diagnostics.phase!=2u || (mt_stream_diagnostics.flags&17u)) {
        mt_stream_progress.flags|=MT_N_DWT_INVALID;
        mt_progress_close(d,MT_N_CLOSE_UNAVAILABLE,0u);return;
    }
    start=cycle();mt_stream_progress.begin_cycle=start;
    mt_stream_progress.last_positive_cycle=start;
    mt_stream_progress.flags|=MT_N_START_ACK_PENDING;
    mt_gate_begin(); /* R_GATE_INIT: before N ACTIVE, ISR hooks still forbidden. */
    state(MT_N_ACTIVE);
}
uint32_t mt_progress_prepare_begin(void) {
    if(!active())return 0u;
    if(mt_stream_progress.flags&MT_N_PREPARE_OPEN)
        mt_stream_progress.flags|=MT_N_METADATA_INVALID;
    mt_stream_progress.flags|=MT_N_PREPARE_OPEN;
    return cycle();
}
void mt_progress_prepare_end(uint32_t begin) {
    uint32_t end;
    if(!active() || !(mt_stream_progress.flags&MT_N_PREPARE_OPEN))return;
    end=cycle();add32(&mt_stream_progress.prepare_cycles,end-begin);
    increment(&mt_stream_progress.prepare_count);
    mt_stream_progress.flags&=~(uint32_t)MT_N_PREPARE_OPEN;
}
void mt_progress_write_begin(void) {
    if(active())mt_stream_progress.flags&=~(uint32_t)MT_N_WRITE_SPACE_MARK;
}
void mt_progress_zero_space(void) {
    if(active())mt_stream_progress.flags|=MT_N_WRITE_SPACE_MARK;
}
void mt_progress_write_end(size_t offered,size_t accepted) {
    uint32_t end;
    if(!active())return;
    if(!offered || offered>384u)mt_stream_progress.flags|=MT_N_METADATA_INVALID;
    if(accepted==SIZE_MAX || accepted>offered) {
        mt_stream_progress.flags|=MT_N_UNKNOWN_WRITE;
    } else if(!accepted) {
        if(mt_stream_progress.flags&MT_N_WRITE_SPACE_MARK)
            increment(&mt_stream_progress.zero_space_count);
        else increment(&mt_stream_progress.zero_other_count);
    } else {
        end=cycle();gap(end);mt_stream_progress.last_positive_cycle=end;
        mt_stream_progress.flags|=MT_N_HAVE_POSITIVE;
        if(accepted<offered)mt_stream_progress.flags|=MT_N_PARTIAL_WRITE;
        increment(&mt_stream_progress.positive_count);
        add32(&mt_stream_progress.positive_bytes,(uint32_t)accepted);
    }
    mt_stream_progress.flags&=~(uint32_t)MT_N_WRITE_SPACE_MARK;
}
static void snapshot(const mt_live_device *d) {
    mt_usb_scope scope;uint32_t key;uint32_t free_bytes;
    if(d) {
        if(d->tx_length<=1335u && d->tx_offset<=d->tx_length &&
           d->batch.count<=1024u && d->batch.phase<=MT_BATCH1024_ABORTED &&
           d->queue.used<=8u) {
            mt_stream_progress.tx_offset=(uint16_t)d->tx_offset;
            mt_stream_progress.tx_length=(uint16_t)d->tx_length;
            mt_stream_progress.stage_count=d->batch.count;
            mt_stream_progress.stage_phase=(uint8_t)d->batch.phase;
            mt_stream_progress.queue_used=(uint8_t)d->queue.used;
            mt_stream_progress.flags|=MT_N_CORE_SNAPSHOT;
        } else mt_stream_progress.flags|=MT_N_METADATA_INVALID;
        if(d->want_start)mt_stream_progress.flags|=MT_N_START_ACK_PENDING;
        else mt_stream_progress.flags&=~(uint32_t)MT_N_START_ACK_PENDING;
    }
    /* This is after the cause latch. Existing nested save/restore guards make
     * the FIFO/task/gate snapshot coherent without dispatch or new health loops.
     * app_enter may refuse stale epoch/lifecycle; then USB fields stay unknown. */
    key=mt_usb_bridge_lock();
    mt_gate_freeze(); /* R_GATE_FREEZE: even if app_enter below refuses. */
    if(mt_usb_bridge_app_enter(&scope)) {
        free_bytes=tud_cdc_n_write_available(0);
        if(free_bytes<=384u) {
            mt_stream_progress.fifo_free=(uint16_t)free_bytes;
            mt_stream_progress.snapshot_bits=(uint8_t)(MT_N_USB_VALID|
                (mt_usb_fsdev_irq_held()?MT_N_USB_HELD:0u)|
                (mt_usb_fsdev_ctr_deferred()?MT_N_USB_DEFERRED:0u)|
                (tud_task_event_ready()?MT_N_USB_TASK_READY:0u));
        } else mt_stream_progress.flags|=MT_N_METADATA_INVALID;
        mt_usb_bridge_leave(&scope);
    }
    mt_usb_bridge_unlock(key);
}
void mt_progress_close(const mt_live_device *d,unsigned kind,unsigned primary) {
    unsigned was;uint32_t end;
    if(phase()==MT_N_EMPTY && (!d || !d->want_start || !bind(d)))return;
    was=phase();if(was!=MT_N_ACTIVE && was!=MT_N_ARMED)return;
    state(MT_N_CLOSING); /* No later hot epilogue is allowed to publish. */
    if(kind>MT_N_CLOSE_TIME || !kind || primary>UINT16_MAX) {
        mt_stream_progress.flags|=MT_N_METADATA_INVALID;
        primary&=UINT16_MAX;
    }
    if(was==MT_N_ARMED) {
        /* Preserve the observed typed cause even before an ACTIVE window.
         * NO_ACTIVE_START describes telemetry scope, not another fault enum. */
        mt_stream_progress.flags|=MT_N_NO_ACTIVE_START;
    } else {
        end=cycle();mt_stream_progress.end_cycle=end;gap(end);
        if(kind==MT_N_CLOSE_CAP && end-mt_stream_progress.begin_cycle>MT_N_CAP_CYCLES)
            mt_stream_progress.flags|=MT_N_CAP_OVERSHOOT;
        if(mt_stream_progress.flags&MT_N_PREPARE_OPEN)
            mt_stream_progress.flags|=MT_N_PARTIAL_PREPARE;
    }
    if(mt_stream_diagnostics.flags&17u)mt_stream_progress.flags|=MT_N_DWT_INVALID;
    mt_stream_progress.flags=(mt_stream_progress.flags&~MT_N_PRIMARY_MASK)|
        ((uint32_t)primary<<MT_N_PRIMARY_SHIFT);
    mt_stream_progress.close_kind=(uint8_t)kind;
    snapshot(d);
#if defined(__ARM_ARCH_7M__) && defined(__thumb__)
    __asm__ volatile("dmb sy" : : : "memory");
#else
    __asm__ volatile("" : : : "memory");
#endif
    state(MT_N_FROZEN);
}
void mt_progress_checkpoint(const mt_live_device *d) {
    if(active() && (uint32_t)(cycle()-mt_stream_progress.begin_cycle)>=MT_N_CAP_CYCLES)
        mt_progress_close(d,MT_N_CLOSE_CAP,0u);
}
