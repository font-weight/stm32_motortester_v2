#include "mt_usb_gate.h"
#include "mt_stream_progress.h"
#if !CFG_MT_PROGRESS_TRACE || !CFG_MT_STREAM_DIAGNOSTICS
#error "Gate requires explicit progress and legacy diagnostics"
#endif
volatile mt_usb_gate_record mt_usb_gate;
static unsigned nphase(void) { return mt_stream_progress.flags&MT_N_PHASE_MASK; }
static int live(void) {
    return nphase()==MT_N_ACTIVE && (mt_usb_gate.flags&MT_G_PHASE_MASK)==MT_G_LIVE;
}
static int writable(void) { return live() && !(mt_usb_gate.flags&MT_G_STICKY); }
static uint32_t cycle(void) {
#if defined(MT_PROGRESS_NATIVE) && MT_PROGRESS_NATIVE
    extern uint32_t mt_progress_native_cycle(void);
    return mt_progress_native_cycle();
#else
    return *(volatile uint32_t *)(uintptr_t)UINT32_C(0xe0001004);
#endif
}
static void initialize(void) {
    mt_usb_gate=(mt_usb_gate_record){.magic=MT_G_MAGIC,
        .flags=MT_G_LIVE|MT_G_UNOBSERVED_INITIAL,
        .total=UINT16_MAX,.queued=UINT16_MAX,.age=UINT16_MAX,.budget=UINT8_MAX};
}
void mt_gate_begin(void) {
    if(nphase()==MT_N_ARMED && !mt_usb_gate.magic)initialize();
}
void mt_gate_freeze(void) {
    uint32_t flags;
    if(nphase()!=MT_N_CLOSING || (mt_usb_gate.flags&MT_G_PHASE_MASK)==MT_G_FROZEN)return;
    if(!mt_usb_gate.magic)initialize();
    flags=(mt_usb_gate.flags&~(uint32_t)MT_G_PHASE_MASK)|MT_G_CLOSING;
    if(mt_stream_progress.flags&MT_N_NO_ACTIVE_START) {
        mt_usb_gate=(mt_usb_gate_record){.magic=MT_G_MAGIC,
            .flags=MT_G_CLOSING|MT_G_NO_ACTIVE|MT_G_UNOBSERVED_INITIAL,
            .total=UINT16_MAX,.queued=UINT16_MAX,.age=UINT16_MAX,.budget=UINT8_MAX};
        flags=mt_usb_gate.flags;
    }
    if(mt_stream_progress.close_kind==MT_N_CLOSE_CAP)flags|=MT_G_CAP;
    mt_usb_gate.flags=flags;
#if defined(__ARM_ARCH_7M__) && defined(__thumb__)
    __asm__ volatile("dmb sy" : : : "memory");
#else
    __asm__ volatile("" : : : "memory");
#endif
    mt_usb_gate.flags=(flags&~(uint32_t)MT_G_PHASE_MASK)|MT_G_FROZEN;
}
void mt_gate_invalidate(unsigned lifecycle) {
    if(!live())return;
    mt_usb_gate.flags&=~(uint32_t)MT_G_APPLICABLE;
    if(lifecycle) {
        mt_usb_gate.flags&=~(uint32_t)MT_G_TRANSFER_ACTIVE;
        mt_usb_gate.flags|=MT_G_LIFECYCLE_INVALID;
    }
}
static void bad(void) {
    mt_usb_gate.flags=(mt_usb_gate.flags|MT_G_METADATA_INVALID)&
        ~(uint32_t)(MT_G_TRANSFER_ACTIVE|MT_G_APPLICABLE|MT_G_AGE_VALID|MT_G_ZLP);
    mt_usb_gate.total=mt_usb_gate.queued=mt_usb_gate.age=UINT16_MAX;
    mt_usb_gate.budget=UINT8_MAX;
    if(mt_usb_gate.flags&MT_G_HAS_PUBLICATION) {
        mt_usb_gate.decision=MT_G_HOLD_OTHER;mt_usb_gate.event_cycle=cycle();
    }
}
void mt_gate_submit_begin(unsigned ep) {
    if(ep==0x82u && live())
        mt_usb_gate.flags&=~(uint32_t)(MT_G_TRANSFER_ACTIVE|MT_G_APPLICABLE);
}
void mt_gate_submit_done(unsigned ep,unsigned ok,unsigned total,unsigned queued,
                         unsigned mps,unsigned backing,unsigned is_isr) {
    uint32_t flags;
    if(ep!=0x82u || !ok || !writable())return;
    if(is_isr || mps!=64u || total>384u || queued!=(total<64u?total:64u) ||
       backing>2u || (total && !backing)) { bad();return; }
    if(mt_usb_gate.publication_serial==UINT32_MAX) {
        mt_usb_gate.flags=(mt_usb_gate.flags|MT_G_SERIAL_SATURATED)&
            ~(uint32_t)(MT_G_TRANSFER_ACTIVE|MT_G_APPLICABLE);return;
    }
    ++mt_usb_gate.publication_serial;
    flags=(mt_usb_gate.flags&~(uint32_t)(MT_G_UNOBSERVED_INITIAL|MT_G_APPLICABLE|
        MT_G_AGE_VALID|MT_G_ZLP))|MT_G_HAS_PUBLICATION|MT_G_TRANSFER_ACTIVE;
    if(!total)flags|=MT_G_ZLP;
    mt_usb_gate.flags=flags;mt_usb_gate.total=(uint16_t)total;
    mt_usb_gate.queued=(uint16_t)queued;mt_usb_gate.age=UINT16_MAX;
    mt_usb_gate.budget=UINT8_MAX;mt_usb_gate.decision=MT_G_PUBLISHED;
    mt_usb_gate.event_cycle=cycle();
}
void mt_gate_note(unsigned decision,unsigned total,unsigned queued,unsigned budget,
                  unsigned age,unsigned metadata_valid) {
    uint32_t flags;unsigned intermediate;
    if(!writable() || !(mt_usb_gate.flags&MT_G_TRANSFER_ACTIVE) ||
       !(mt_usb_gate.flags&MT_G_HAS_PUBLICATION))return;
    intermediate=queued && queued<total && !(queued&63u);
    if(!metadata_valid || total!=mt_usb_gate.total || queued>total || total>384u ||
       budget>5u || decision<MT_G_RESUMED || decision>MT_G_HOLD_STATUS ||
       (decision==MT_G_HOLD_FINAL && queued!=total) ||
       ((decision==MT_G_RESUMED || decision==MT_G_HOLD_BUDGET ||
         decision==MT_G_HOLD_TIME || decision==MT_G_TIMER_UNAVAILABLE ||
         decision==MT_G_HOLD_LIFECYCLE || decision==MT_G_HOLD_STATUS) && !intermediate) ||
       (decision==MT_G_HOLD_BUDGET && budget) ||
       ((decision==MT_G_RESUMED || decision==MT_G_HOLD_TIME ||
         decision==MT_G_TIMER_UNAVAILABLE || decision==MT_G_HOLD_LIFECYCLE ||
         decision==MT_G_HOLD_STATUS) && !budget) ||
       (age!=UINT32_MAX && age>UINT16_MAX) ||
       (decision==MT_G_HOLD_TIME && (age==UINT32_MAX || age<500u)) ||
       (decision==MT_G_RESUMED && (age==UINT32_MAX || age>=500u)) ||
       ((decision==MT_G_HOLD_FINAL || decision==MT_G_HOLD_OTHER ||
         decision==MT_G_HOLD_BUDGET || decision==MT_G_TIMER_UNAVAILABLE) && age!=UINT32_MAX) ||
       ((decision==MT_G_HOLD_LIFECYCLE || decision==MT_G_HOLD_STATUS) &&
         age!=UINT32_MAX && age>=500u)) { bad();return; }
    flags=mt_usb_gate.flags&~(uint32_t)(MT_G_APPLICABLE|MT_G_AGE_VALID);
    if(decision!=MT_G_RESUMED)flags|=MT_G_APPLICABLE;
    if(queued==total)flags&=~(uint32_t)MT_G_TRANSFER_ACTIVE;
    if(age!=UINT32_MAX)flags|=MT_G_AGE_VALID;
    if(decision==MT_G_HOLD_LIFECYCLE) {
        flags=(flags|MT_G_LIFECYCLE_INVALID)&~(uint32_t)(MT_G_APPLICABLE|MT_G_TRANSFER_ACTIVE);
    }
    mt_usb_gate.flags=flags;mt_usb_gate.total=(uint16_t)total;
    mt_usb_gate.queued=(uint16_t)queued;mt_usb_gate.age=(uint16_t)age;
    mt_usb_gate.budget=(uint8_t)budget;mt_usb_gate.decision=(uint8_t)decision;
    mt_usb_gate.event_cycle=cycle();
}
int mt_gate_condition(unsigned *decision,unsigned reason,int actual) {
    if(!actual && !*decision)*decision=reason;
    return actual;
}
