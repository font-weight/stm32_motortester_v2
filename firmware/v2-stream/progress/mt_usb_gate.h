#ifndef MT_USB_GATE_H
#define MT_USB_GATE_H
#include <stddef.h>
#include <stdint.h>
#define MT_G_MAGIC UINT32_C(0x4d544731)
enum { MT_G_EMPTY,MT_G_LIVE,MT_G_CLOSING,MT_G_FROZEN };
enum { MT_G_PHASE_MASK=3u,MT_G_HAS_PUBLICATION=1u<<2,MT_G_TRANSFER_ACTIVE=1u<<3,
    MT_G_APPLICABLE=1u<<4,MT_G_AGE_VALID=1u<<5,MT_G_SERIAL_SATURATED=1u<<6,
    MT_G_METADATA_INVALID=1u<<7,MT_G_LIFECYCLE_INVALID=1u<<8,
    MT_G_UNOBSERVED_INITIAL=1u<<9,MT_G_NO_ACTIVE=1u<<10,MT_G_CAP=1u<<11,
    MT_G_ZLP=1u<<12 };
#define MT_G_STICKY (MT_G_SERIAL_SATURATED|MT_G_METADATA_INVALID|MT_G_LIFECYCLE_INVALID)
enum { MT_G_UNKNOWN,MT_G_PUBLISHED,MT_G_RESUMED,MT_G_HOLD_FINAL,MT_G_HOLD_OTHER,
    MT_G_HOLD_BUDGET,MT_G_HOLD_TIME,MT_G_TIMER_UNAVAILABLE,MT_G_HOLD_LIFECYCLE,
    MT_G_HOLD_STATUS };
/* One fixed EP0x82 transition bank; ALL private persistent state is here.
 * FG calls require the existing PRIMASK guard, as does the complete DCD ISR.
 * APPLICABLE describes the last episode BEFORE N CLOSING, never current64.
 * Age is the already evaluated TIM2 modulo value, not read again at freeze. */
typedef struct {
    uint32_t magic,flags,publication_serial,event_cycle;
    uint16_t total,queued,age;
    uint8_t budget,decision;
} mt_usb_gate_record;
_Static_assert(sizeof(mt_usb_gate_record)==24u,"Gate whole static bank24B");
_Static_assert(offsetof(mt_usb_gate_record,publication_serial)==8u,"Gate serial ABI");
_Static_assert(offsetof(mt_usb_gate_record,total)==16u,"Gate tuple ABI");
_Static_assert(offsetof(mt_usb_gate_record,decision)==23u,"Gate decision ABI");
extern volatile mt_usb_gate_record mt_usb_gate;
void mt_gate_begin(void); /* Before N ACTIVE, no ISR hook admitted yet. */
void mt_gate_freeze(void); /* Existing N snapshot lock, even refused app scope. */
void mt_gate_invalidate(unsigned lifecycle);
void mt_gate_submit_begin(unsigned ep);
void mt_gate_submit_done(unsigned ep,unsigned ok,unsigned total,unsigned queued,
                         unsigned mps,unsigned backing,unsigned is_isr);
void mt_gate_note(unsigned decision,unsigned total,unsigned queued,unsigned budget,
                  unsigned age,unsigned metadata_valid);
/* Pure short-circuit annotation; no MMIO, state/queue mutation or new reads. */
int mt_gate_condition(unsigned *decision,unsigned reason,int actual);
#endif
