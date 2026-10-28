/* Native logical MMIO/NVIC model. Extracted gate/ISR/bridge bodies are inserted
 * below. Endpoint payload copy/PHY and actual CPU time are deliberately absent. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mt_usb_epoch.h"
#define CFG_MT_USB_CTR_FAIRNESS 1
#define CFG_MT_USB_BRIDGE 1
#define CFG_TUSB_MCU 1
#define OPT_MCU_STM32F1 1
#define OPT_MCU_STM32F3 3
#define TU_ATTR_ALWAYS_INLINE
#define FSDEV_IRQ_NUM 2
#define __DSB() ((void)0)
#define __ISB() ((void)0)
#define TU_BREAKPOINT() abort()
enum {TUSB_DIR_OUT, TUSB_DIR_IN, TUSB_SPEED_FULL, DCD_EVENT_RESUME, DCD_EVENT_SUSPEND};
typedef uint16_t fsdev_bus_t;
static const unsigned fsdev_irq[] = {19, 20};
static bool nvic[32];
static void NVIC_EnableIRQ(unsigned n) { nvic[n] = true; }
static void NVIC_DisableIRQ(unsigned n) { nvic[n] = false; }
/* CONSTANTS */
static struct {
    struct {uint16_t reg;} ep[8];
    uint16_t CNTR, FNR, DADDR;
} regs;
#define FSDEV_REG (&regs)
static uint16_t flags;
static unsigned irq_entries, ctr_events, reset_events, soft_events;
static unsigned remoteWakeCountdown;
static mt_usb_epoch state;
static uint32_t actor;
typedef uint32_t (*mt_usb_lock_fn)(void);
typedef void (*mt_usb_unlock_fn)(uint32_t);
typedef struct {uint32_t previous; unsigned entered;} mt_usb_scope;
enum {MT_USB_DROP, MT_USB_DEFER, MT_USB_DISPATCH};
static uint32_t mt_usb_bridge_lock(void) { return 0; }
static void mt_usb_bridge_unlock(uint32_t key) { (void)key; }
static mt_usb_lock_fn lock_fn = mt_usb_bridge_lock;
static mt_usb_unlock_fn unlock_fn = mt_usb_bridge_unlock;
#define CHECK(x) do { if (!(x)) {fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);exit(1);} } while(0)
static uint16_t model_istr_read(void) {
    for (unsigned i=0; i<8; ++i)
        if (regs.ep[i].reg & (U_EP_CTR_RX|U_EP_CTR_TX)) return flags|U_ISTR_CTR|i;
    return flags;
}
static void model_istr_write(uint16_t value) { flags &= value; }
static uint32_t ep_read(uint32_t ep) { return regs.ep[ep].reg; }
static void ep_write_clear_ctr(uint32_t ep, unsigned dir) {
    regs.ep[ep].reg &= (uint16_t)~(dir==TUSB_DIR_IN ? U_EP_CTR_TX : U_EP_CTR_RX);
}
static void handle_ctr_setup(unsigned ep) { ep_write_clear_ctr(ep,TUSB_DIR_OUT); ++ctr_events; }
static void handle_ctr_rx(unsigned ep) { (void)ep; ++ctr_events; }
static void handle_ctr_tx(unsigned ep) { (void)ep; ++ctr_events; }
static void handle_bus_reset(uint8_t port);
static void dcd_event_sof(unsigned port, unsigned frame, bool isr) {(void)port;(void)frame;(void)isr;}
static void dcd_event_bus_reset(unsigned port, unsigned speed, bool isr) {
    (void)port;(void)speed; CHECK(isr); ++reset_events;
    uint32_t token=mt_usb_epoch_reset(&state);
    CHECK(mt_usb_epoch_enqueued(&state,token,1,1));
}
static void mt_usb_bridge_pma_overrun(void) {
    CHECK(mt_usb_epoch_fail(&state,state.current,MT_USB_EPOCH_PMA_OVERRUN));
}
static void dcd_event_bus_signal(unsigned port,unsigned signal,bool isr) {
    (void)port; CHECK(isr); ++soft_events;
    if(signal==DCD_EVENT_SUSPEND) CHECK(mt_usb_epoch_suspend(&state,state.current));
    else CHECK(mt_usb_epoch_resume(&state,state.current,state.pending_soft));
}
/* BODIES */
static void handle_bus_reset(uint8_t port) {
    (void)port;
    /* Model the existing F103 reset barrier's hardware effect; not a payload
     * model of edpt0_open or PMA. The extracted ISR still controls its order. */
    memset(regs.ep,0,sizeof regs.ep);
    regs.DADDR=U_DADDR_EF;
    mt_ctr_deferred=false;
    regs.CNTR|=U_CNTR_CTRM;
}
static bool deliver_irq(void) {
    /* Endpoint request is independent of CTRM, the original bug's trigger. */
    if (!(nvic[19]||nvic[20]) || !model_istr_read()) return false;
    ++irq_entries; dcd_int_handler(0); return true;
}
static void initialized(void) {
    memset(&regs,0,sizeof regs); memset(nvic,0,sizeof nvic);
    flags=0; irq_entries=ctr_events=reset_events=soft_events=0;
    mt_irq_held=mt_ctr_deferred=false;
    regs.DADDR=U_DADDR_EF; regs.CNTR=U_CNTR_CTRM;
    mt_usb_epoch_init(&state);
    CHECK(mt_usb_epoch_reset(&state)==1);
    CHECK(mt_usb_epoch_enqueued(&state,1,1,1));
    CHECK(mt_usb_epoch_cleaned(&state,1));
    CHECK(mt_usb_epoch_reset_done(&state,1));
    CHECK(mt_usb_epoch_configured(&state,1));
    actor=1;
}
static void stale_lifecycle_denied(void) {
    mt_usb_scope scope;
    CHECK(mt_usb_fsdev_lifecycle_pending());
    CHECK(!permitted());
    CHECK(!mt_usb_bridge_app_enter(&scope));
    actor=0;
    CHECK(mt_usb_bridge_dispatch(state.current,0,&scope)==MT_USB_DEFER);
    CHECK(!scope.entered);
    actor=state.current;
}
static void ctr_quantum(void) {
    initialized();
    regs.ep[1].reg=U_EP_CTR_RX; regs.ep[2].reg=U_EP_CTR_RX;
    CHECK(mt_usb_fsdev_irq_grant(true)); CHECK(deliver_irq());
    CHECK(ctr_events==1 && mt_irq_held && mt_ctr_deferred);
    CHECK(!nvic[19] && !nvic[20]);
    CHECK(model_istr_read() & U_ISTR_CTR);
    dcd_int_enable(0); ep_write(3,0,true); /* OSAL and direct EP helper */
    CHECK(!nvic[19] && !nvic[20] && !deliver_irq());
    /* Task work still queued: one lifecycle-only grant may take the dedicated
     * CTR IRQ but must neither clear CTR nor produce another data event. */
    CHECK(mt_usb_fsdev_irq_grant(false)); CHECK(deliver_irq());
    CHECK(irq_entries==2 && ctr_events==1 && (model_istr_read()&U_ISTR_CTR));
    CHECK(!deliver_irq()); /* foreground has an unconditional opportunity */
    CHECK(mt_usb_fsdev_irq_grant(true)); CHECK(deliver_irq());
    CHECK(ctr_events==2 && !(model_istr_read()&U_ISTR_CTR));
    CHECK(!nvic[19] && !nvic[20]);
    puts("PASS pending CTR / one IRQ / OSAL and ep_write enable hold");
}
static void reset_and_overrun(void) {
    initialized(); regs.ep[1].reg=U_EP_CTR_RX;
    CHECK(mt_usb_fsdev_irq_grant(true));
    flags=U_ISTR_RESET|U_ISTR_PMAOVR; /* arrives after grant, before ISR */
    stale_lifecycle_denied();
    CHECK(deliver_irq());
    CHECK(reset_events==1 && state.current==2 && !state.faults && ctr_events==0);
    CHECK(!nvic[19] && !nvic[20] && !permitted());
    CHECK(mt_usb_epoch_cleaned(&state,2)); CHECK(mt_usb_epoch_reset_done(&state,2));
    CHECK(mt_usb_epoch_configured(&state,2)); actor=2; CHECK(permitted());
    flags=U_ISTR_PMAOVR; stale_lifecycle_denied();
    CHECK(mt_usb_fsdev_irq_grant(false)); CHECK(deliver_irq());
    CHECK(state.faults==MT_USB_EPOCH_PMA_OVERRUN && !permitted());
    CHECK(!nvic[19] && !nvic[20]);
    puts("PASS RESET dominates stale CTR / PMAOVR quarantines before publication");
}
static void soft_lifecycle(void) {
    initialized(); regs.ep[1].reg=U_EP_CTR_RX;
    mt_usb_fsdev_irq_hold();
    flags=U_ISTR_SUSP; stale_lifecycle_denied();
    CHECK(mt_usb_fsdev_irq_grant(false)); CHECK(deliver_irq());
    CHECK(state.pending_soft==1 && state.soft_serial==1 && ctr_events==0);
    CHECK(regs.CNTR & U_CNTR_FSUSP); CHECK(!permitted());
    flags=U_ISTR_WKUP; stale_lifecycle_denied();
    CHECK(mt_usb_fsdev_irq_grant(false)); CHECK(deliver_irq());
    CHECK(!state.pending_soft && soft_events==2 && ctr_events==0);
    CHECK(!(regs.CNTR&U_CNTR_FSUSP) && permitted());
    CHECK(model_istr_read()&U_ISTR_CTR);
    CHECK(!nvic[19] && !nvic[20]);
    CHECK(mt_usb_fsdev_irq_grant(true)); CHECK(deliver_irq()); CHECK(ctr_events==1);
    puts("PASS SUSP/WKUP with held task work / no hidden CTR consumption");
}
int main(void) { ctr_quantum(); reset_and_overrun(); soft_lifecycle(); return 0; }
