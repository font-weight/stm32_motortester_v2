#ifndef MT_USB_CTR_H
#define MT_USB_CTR_H
#include <stdbool.h>
/* V2-only STM32F103 NVIC quantum. Foreground functions require the same
 * save/restore guard as the DCD ISR. Every ISR entry masks NVIC19/20; nested
 * OSAL/EP enables respect irq_held. Only the sole runtime grants the next IRQ.
 * Lifecycle always gets an opportunity with healthy TIME; CTR requires drained
 * task work and the original cleanup/epoch conditions. No pending flag is
 * cleared for fairness. No WCET, lossless transport or recovery from TIME_FAULT
 * is claimed. TIME_FAULT is sticky and requires MCU reset. */
bool mt_usb_fsdev_ctr_deferred(void);
bool mt_usb_fsdev_irq_held(void);
bool mt_usb_fsdev_lifecycle_pending(void);
bool mt_usb_fsdev_irq_grant(bool allow_ctr);
#endif
