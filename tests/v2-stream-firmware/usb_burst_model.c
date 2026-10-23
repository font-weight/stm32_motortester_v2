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
        if (regs.ep[i].reg & (U_EP_CTR_RX|U_EP_CTR_TX)) return flags|U_ISTR_CTR|i|((regs.ep[i].reg&U_EP_CTR_RX)?U_ISTR_DIR:0);
    return flags;
}
static void model_istr_write(uint16_t value) { flags &= value; }
static uint32_t ep_read(uint32_t ep) { return regs.ep[ep].reg; }
static void ep_write_clear_ctr(uint32_t ep, unsigned dir) {
    regs.ep[ep].reg &= (uint16_t)~(dir==TUSB_DIR_IN ? U_EP_CTR_TX : U_EP_CTR_RX);
}
static void handle_ctr_setup(unsigned ep) { ep_write_clear_ctr(ep,TUSB_DIR_OUT); ++ctr_events; }
static void handle_ctr_rx(unsigned ep) { (void)ep; ++ctr_events; }
typedef struct {
    uint8_t *buffer; void *ff;
    uint16_t queued_len,total_len,max_packet_size;
    bool iso_in_sending;
} xfer_ctl_t;
static xfer_ctl_t xfers[8][2];
static uint8_t transfer_bytes[384];
static uint32_t timer_now,inject_flags;
static unsigned tx_completions;
static bool timer_invalid,failed_progress;
static xfer_ctl_t *xfer_ctl_ptr(uint8_t ep,uint8_t dir) { return &xfers[ep][dir]; }
static uint32_t mt_tx_timer_read(uint32_t addr) {
    if(addr==0x40000024u)return timer_now;
    if(addr==0x40000028u)return 71;
    if(addr==0x4000002cu)return 65535;
    if(addr==0x40021010u)return timer_invalid?1:0;
    return 1;
}
static bool ep_is_iso(uint32_t value) { (void)value;return false; }
static void btable_set_count(unsigned ep,unsigned buf,unsigned n) {(void)ep;(void)buf;(void)n;}
static void dcd_transmit_packet(xfer_ctl_t *x,unsigned ep) {
    (void)ep;++ctr_events;
    if(!failed_progress) {
        unsigned left=x->total_len-x->queued_len;
        x->queued_len+=(uint16_t)(left<64?left:64);
    }
    flags|=(uint16_t)inject_flags;
    if(inject_flags&U_ISTR_DIR)regs.ep[0].reg=U_EP_CTR_RX|U_EP_SETUP;
}
#define TUSB_DIR_IN_MASK 128
#define FSDEV_USE_SBUF_ISO 1
#define BTABLE_BUF_TX 0
#define XFER_RESULT_SUCCESS 0
static void dcd_event_xfer_complete(unsigned port,unsigned ep,unsigned n,unsigned result,bool isr) {
    (void)port;(void)ep;(void)n;(void)result;CHECK(isr);++tx_completions;
}
static void handle_ctr_tx(uint32_t ep);

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
    mt_tx_burst_left=0;mt_tx_burst_counter=0;
    memset(xfers,0,sizeof xfers);timer_now=inject_flags=tx_completions=0;
    timer_invalid=failed_progress=false;
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
static void armed(unsigned total) {
    initialized();
    regs.ep[2].reg=2u|U_EP_BULK;
    xfers[2][TUSB_DIR_IN]=(xfer_ctl_t){.buffer=transfer_bytes,
        .queued_len=(uint16_t)(total<64?total:64),.total_len=(uint16_t)total,.max_packet_size=64};
    CHECK(mt_usb_fsdev_irq_grant(true));
}
static void packet(void) {
    regs.ep[2].reg|=U_EP_CTR_TX;CHECK(deliver_irq());
}
static void held(void) { CHECK(mt_irq_held && !nvic[19] && !nvic[20]); }
static void full_and_short(void) {
    const unsigned totals[]={0,1,64,65,307,384};
    for(unsigned t=0;t<sizeof totals/sizeof totals[0];t++) {
        unsigned total=totals[t], packets=total?(total+63)/64:1;
        armed(total);
        for(unsigned p=0;p<packets;p++) {
            timer_now+=20;packet();
            if(p+1<packets)CHECK(!mt_irq_held && nvic[19] && nvic[20]);
            else held();
        }
        CHECK(tx_completions==1 && irq_entries==packets);
    }
    armed(385);packet();held();CHECK(tx_completions==0);
    armed(384);mt_tx_burst_left=2;
    packet();CHECK(!mt_irq_held);packet();held();
    CHECK(irq_entries==2 && !tx_completions);
    puts("PASS ZLP / short / full64 / DATA307 / transfer384 / 385 boundary / bounded budget");
}
static void stop_conditions(void) {
    armed(384);timer_now=499;packet();CHECK(!mt_irq_held);
    armed(384);timer_now=500;packet();held();
    armed(384);timer_invalid=true;packet();held();
    armed(384);failed_progress=true;packet();held();
    armed(384);regs.DADDR=0;packet();held();
    armed(384);regs.CNTR|=U_CNTR_FSUSP;packet();held();
    armed(384);regs.ep[2].reg|=U_EP_CTR_RX;packet();held();
    armed(384);regs.ep[2].reg|=U_EP_CTR_RX|U_EP_SETUP;packet();held();
    armed(384);regs.ep[2].reg=(uint16_t)(1u|U_EP_BULK);packet();held();
    const unsigned injected[]={U_ISTR_PMAOVR,U_ISTR_SUSP,U_ISTR_WKUP,U_ISTR_RESET,U_ISTR_ERR,U_ISTR_DIR};
    for(unsigned i=0;i<sizeof injected/sizeof injected[0];i++) {
        armed(384);inject_flags=injected[i];packet();held();
        CHECK(tx_completions==0);
    }
    const unsigned at_entry[]={U_ISTR_SUSP,U_ISTR_WKUP,U_ISTR_ERR};
    for(unsigned i=0;i<sizeof at_entry/sizeof at_entry[0];i++) {
        armed(384);
        if(at_entry[i]==U_ISTR_WKUP) {
            CHECK(mt_usb_epoch_suspend(&state,state.current));
            regs.CNTR|=U_CNTR_FSUSP;
        }
        flags=(uint16_t)at_entry[i];packet();held();
    }
    armed(384);timer_now=65530;CHECK(mt_usb_fsdev_irq_grant(true));
    timer_now=(uint16_t)(65530u+499u);packet();CHECK(!mt_irq_held);
    armed(384);timer_now=65530;CHECK(mt_usb_fsdev_irq_grant(true));
    timer_now=(uint16_t)(65530u+500u);packet();held();
    armed(384);xfers[2][TUSB_DIR_IN].ff=transfer_bytes;
    xfers[2][TUSB_DIR_IN].buffer=NULL;
    for(unsigned p=0;p<6;p++) {
        timer_now+=20;packet();
        if(p<5)CHECK(!mt_irq_held);else held();
    }
    CHECK(tx_completions==1);
    puts("PASS dedicated FIFO source / preserved published transfer / TIM2 modulo65536 wrap");
    puts("PASS 499/500us / invalid timer / progress failure / endpoint / OUT / SETUP / lifecycle arrival / USB error");
}
int main(void) {
    ctr_quantum();reset_and_overrun();soft_lifecycle();
    full_and_short();stop_conditions();return 0;
}
