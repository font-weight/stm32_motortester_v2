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
#define U_EP_CTR_RX        0x8000u
#define U_EP_DTOG_RX       0x4000u
#define U_EPRX_STAT        0x3000u
#define U_EP_SETUP         0x0800u
#define U_EP_T_FIELD       0x0600u
#define U_EP_KIND          0x0100u
#define U_EP_CTR_TX        0x0080u
#define U_EP_DTOG_TX       0x0040u
#define U_EPTX_STAT        0x0030u
#define U_EPADDR_FIELD     0x000Fu
#define U_EP_ERRRX         0x04000000u
#define U_EP_ERRTX         0x02000000u
#define U_EP_LSEP          0x01000000u
#define U_EP_NAK           0x00800000u
#define U_EP_DEVADDR       0x007F0000u
#define U_EP_DEVADDR_Pos   16u
#define U_EP_BULK          0x0000u
#define U_EP_CONTROL       0x0200u
#define U_EP_ISOCHRONOUS   0x0400u
#define U_EP_INTERRUPT     0x0600u
#define U_EP_TYPE_MASK     (U_EP_T_FIELD)
#define U_EPREG_MASK_16    (U_EP_CTR_RX | U_EP_SETUP | U_EP_T_FIELD | U_EP_KIND | U_EP_CTR_TX | U_EPADDR_FIELD)
#define U_EPREG_MASK_32    (U_EP_ERRRX | U_EP_ERRTX | U_EP_LSEP | U_EP_NAK | U_EP_DEVADDR | U_EPREG_MASK_16)
#define U_EPKIND_MASK      ((uint32_t)(~U_EP_KIND) & U_EPREG_MASK)
#define U_EPTX_DTOGMASK    (U_EPTX_STAT | U_EPREG_MASK)
#define U_EPRX_DTOGMASK    (U_EPRX_STAT | U_EPREG_MASK)
#define U_EPTX_STAT_Pos    4u
#define U_EP_DTOG_TX_Pos   6u
#define U_EP_CTR_TX_Pos    7u
#define U_EPTX_DTOG1       0x0010u
#define U_EPTX_DTOG2       0x0020u
#define U_EPRX_DTOG1       0x1000u
#define U_EPRX_DTOG2       0x2000u
#define U_CNTR_CTRM       0x8000u
#define U_CNTR_PMAOVRM    0x4000u
#define U_CNTR_ERRM       0x2000u
#define U_CNTR_WKUPM      0x1000u
#define U_CNTR_SUSPM      0x0800u
#define U_CNTR_RESETM     0x0400u
#define U_CNTR_SOFM       0x0200u
#define U_CNTR_ESOFM      0x0100u
#define U_CNTR_RESUME     0x0010u
#define U_CNTR_FSUSP      0x0008u
#define U_CNTR_LPMODE     0x0004u
#define U_CNTR_PDWN       0x0002u
#define U_CNTR_FRES       0x0001u
#define U_CNTR_HOST       0x80000000u   // DRD: enable host mode
#define U_CNTR_DCON       0x0400u       // DRD host: same bit as RESETM
#define U_ISTR_CTR        0x8000u
#define U_ISTR_PMAOVR     0x4000u
#define U_ISTR_ERR        0x2000u
#define U_ISTR_WKUP       0x1000u
#define U_ISTR_SUSP       0x0800u
#define U_ISTR_RESET      0x0400u
#define U_ISTR_SOF        0x0200u
#define U_ISTR_ESOF       0x0100u
#define U_ISTR_DIR        0x0010u
#define U_ISTR_EP_ID      0x000Fu
#define U_ISTR_LS_DCONN   0x40000000u   // DRD: low-speed device connected
#define U_ISTR_DCON_STAT  0x20000000u   // DRD: device connection status
#define U_ISTR_DCON       0x0400u       // DRD host: same bit as RESET
#define U_FNR_RXDP        0x8000u
#define U_FNR_RXDM        0x4000u
#define U_FNR_FN          0x07FFu
#define U_DADDR_EF        0x80u
#define U_LPMCSR_LMPEN     0x0001u
#define U_LPMCSR_LPMACK    0x0002u
#define U_LPMCSR_REMWAKE   0x0008u
#define U_LPMCSR_BESL      0x00F0u
#define U_BCDR_BCDEN       0x0001u
#define U_BCDR_DCDEN       0x0002u
#define U_BCDR_PDEN        0x0004u
#define U_BCDR_SDEN        0x0008u
#define U_BCDR_DCDET       0x0010u
#define U_BCDR_PDET        0x0020u
#define U_BCDR_SDET        0x0040u
#define U_BCDR_PS2DET      0x0080u
#define U_BCDR_DPPU        0x8000u
#define U_CH_TX_STTX       0x0030u
#define U_CH_TX_ACK_SBUF   0x0000u
#define U_CH_TX_STALL      0x0010u
#define U_CH_TX_NAK        0x0020u
#define U_CH_RX_STRX       0x3000u
#define U_CH_RX_ACK_SBUF   0x0000u
#define U_CH_RX_STALL      0x1000u
#define U_CH_RX_NAK        0x2000u
#define U_CH_RX_VALID      0x3000u

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
static volatile bool mt_ctr_deferred, mt_irq_held;
static unsigned mt_tx_burst_left;
static uint16_t mt_tx_burst_counter;

bool mt_usb_fsdev_irq_held(void);

TU_ATTR_ALWAYS_INLINE static inline void fsdev_int_enable(uint8_t rhport) {
  (void)rhport;
#if CFG_MT_USB_CTR_FAIRNESS
  /* Covers direct ep_write helpers as well as OSAL's dcd_int_enable wrapper.
   * Only the foreground grant clears this hold; nested enables cannot do so. */
  extern bool mt_usb_fsdev_irq_held(void);
  if (mt_usb_fsdev_irq_held()) return;
#endif

  // forces write to RAM before allowing ISR to execute
  __DSB(); __ISB();

  #if CFG_TUSB_MCU == OPT_MCU_STM32F3 && defined(SYSCFG_CFGR1_USB_IT_RMP)
  // Some STM32F302/F303 devices allow to remap the USB interrupt vectors from
  // shared USB/CAN IRQs to separate CAN and USB IRQs.
  // This dynamically checks if this remap is active to enable the right IRQs.
  if (SYSCFG->CFGR1 & SYSCFG_CFGR1_USB_IT_RMP) {
    NVIC_EnableIRQ(USB_HP_IRQn);
    NVIC_EnableIRQ(USB_LP_IRQn);
    //NVIC_EnableIRQ(USBWakeUp_RMP_IRQn);
  } else
  #endif
  {
    for (uint8_t i = 0; i < FSDEV_IRQ_NUM; i++) {
      NVIC_EnableIRQ(fsdev_irq[i]);
    }
  }
}

TU_ATTR_ALWAYS_INLINE static inline void fsdev_int_disable(uint8_t rhport) {
  (void)rhport;

  #if CFG_TUSB_MCU == OPT_MCU_STM32F3 && defined(SYSCFG_CFGR1_USB_IT_RMP)
  // Some STM32F302/F303 devices allow to remap the USB interrupt vectors from
  // shared USB/CAN IRQs to separate CAN and USB IRQs.
  // This dynamically checks if this remap is active to enable the right IRQs.
  if (SYSCFG->CFGR1 & SYSCFG_CFGR1_USB_IT_RMP) {
    NVIC_DisableIRQ(USB_HP_IRQn);
    NVIC_DisableIRQ(USB_LP_IRQn);
    //NVIC_DisableIRQ(USBWakeUp_RMP_IRQn);
  } else
  #endif
  {
    for (uint8_t i = 0; i < FSDEV_IRQ_NUM; i++) {
      NVIC_DisableIRQ(fsdev_irq[i]);
    }
  }

  // CMSIS has a membar after disabling interrupts
}

TU_ATTR_ALWAYS_INLINE static inline void ep_write(uint32_t ep_id, uint32_t value, bool need_exclusive) {
  if (need_exclusive) {
    fsdev_int_disable(0);
  }

  FSDEV_REG->ep[ep_id].reg = (fsdev_bus_t)value;

  if (need_exclusive) {
    fsdev_int_enable(0);
  }
}

static bool mt_tx_timer_ready(void) {
  return (mt_tx_timer_read(0x4002101cu)&1u) &&
      !(mt_tx_timer_read(0x40021010u)&1u) &&
      mt_tx_timer_read(0x40000000u)==1u &&
      mt_tx_timer_read(0x40000028u)==71u &&
      mt_tx_timer_read(0x4000002cu)==65535u;
}

static bool mt_tx_burst_time_ok(void) {
  /* TIM2 is fully validated by the foreground owner before grant. These
   * checks only bound continuation; no wraps, debugger halt or WCET inferred. */
  return mt_tx_timer_ready() &&
      (uint16_t)((uint16_t)mt_tx_timer_read(0x40000024u)-mt_tx_burst_counter)<500u;
}

static void handle_ctr_tx(uint32_t ep_id) {
  uint32_t ep_reg = ep_read(ep_id) | U_EP_CTR_TX | U_EP_CTR_RX;

  const uint8_t ep_num = ep_reg & U_EPADDR_FIELD;
  xfer_ctl_t   *xfer   = xfer_ctl_ptr(ep_num, TUSB_DIR_IN);

  if (ep_is_iso(ep_reg)) {
    // Ignore spurious interrupts that we don't schedule
    // host can send IN token while there is no data to send, since ISO does not have NAK
    // this will result to zero length packet --> trigger interrupt (which cannot be masked)
    if (!xfer->iso_in_sending) {
      return;
    }
    xfer->iso_in_sending = false;
  #if FSDEV_USE_SBUF_ISO == 0
    uint8_t buf_id = (ep_reg & U_EP_DTOG_TX) ? 0 : 1;
  #else
    uint8_t buf_id = BTABLE_BUF_TX;
  #endif
    btable_set_count(ep_id, buf_id, 0);
  }

  if (xfer->total_len != xfer->queued_len) {
    dcd_transmit_packet(xfer, (uint16_t)ep_id);
  } else {
#if defined(TUP_USBIP_FSDEV_CH32)
    // Control read: block unsolicited EP0 OUT ACK.
    if ((ep_num == 0u) && ep0_ctrl_dir_in && ep0_ctrl_has_data) {
      ep0_set_type(U_EP_BULK, false);
    }
#endif
    dcd_event_xfer_complete(0, ep_num | TUSB_DIR_IN_MASK, xfer->queued_len, XFER_RESULT_SUCCESS, true);
  }
}

bool mt_usb_fsdev_ctr_deferred(void) { return mt_ctr_deferred; }

bool mt_usb_fsdev_irq_held(void) { return mt_irq_held; }

bool mt_usb_fsdev_lifecycle_pending(void) {
  /* No flag is consumed here. Until ISR publishes its epoch/soft loss, neither
   * foreground dispatch nor application I/O may use the earlier observation. */
  return (model_istr_read() & (U_ISTR_RESET | U_ISTR_PMAOVR |
                            U_ISTR_SUSP | U_ISTR_WKUP)) != 0;
}

static void mt_usb_fsdev_irq_hold(void) {
  /* RM0008: dedicated endpoint interrupt is independent of CNTR.CTRM.
   * Mask both NVIC lines before any event/EP helper can re-enable them. */
  mt_irq_held = true;
  fsdev_int_disable(0);
}

bool mt_usb_fsdev_irq_grant(bool allow_ctr) {
  /* Sole foreground owner, under the save/restore IRQ guard, after TIME/ADC.
   * Grant lifecycle even with held task work or pending_soft. Otherwise a
   * masked RESET/RESUME could never release the condition blocking CTR. */
  if (FSDEV_REG->CNTR & (U_CNTR_FRES | U_CNTR_PDWN)) return false;
  bool ctr = allow_ctr && !mt_usb_fsdev_lifecycle_pending() &&
      !(FSDEV_REG->CNTR & U_CNTR_FSUSP) && (FSDEV_REG->DADDR & U_DADDR_EF);
  mt_tx_burst_left=ctr && mt_tx_timer_ready() ? 6u : 0u;
  mt_tx_burst_counter=(uint16_t)mt_tx_timer_read(0x40000024u);
  mt_ctr_deferred = !ctr;
  if (ctr) FSDEV_REG->CNTR |= U_CNTR_CTRM;
  else FSDEV_REG->CNTR &= (fsdev_bus_t)~U_CNTR_CTRM;
  mt_irq_held = false;
  fsdev_int_enable(0);
  return true;
}

void dcd_int_enable(uint8_t rhport) {
  fsdev_int_enable(rhport);
}

void dcd_int_disable(uint8_t rhport) {
  fsdev_int_disable(rhport);
}

void dcd_int_handler(uint8_t rhport) {
#if CFG_MT_USB_CTR_FAIRNESS
  /* Every entry consumes the foreground grant, including RESET-only entries.
   * Pending endpoint flags survive; only bounded CDC IN continuation may rearm. */
  /* missing IRQ hold */
#endif
  uint32_t int_status = model_istr_read();

  /* Put SOF flag at the beginning of ISR in case to get least amount of jitter if it is used for timing purposes */
  if ((int_status & U_ISTR_SOF) && (FSDEV_REG->CNTR & U_CNTR_SOFM)) {
    model_istr_write((fsdev_bus_t)~U_ISTR_SOF);
    dcd_event_sof(0, FSDEV_REG->FNR & U_FNR_FN, true);
  }

  if (int_status & U_ISTR_RESET) {
    // USBRST is start of reset.
#if CFG_MT_USB_BRIDGE
    // Discard overrun already observed with this physical reset. A stale flag
    // must not be reported by a later ISR as a fault of the new reset epoch.
    model_istr_write((fsdev_bus_t)~(U_ISTR_RESET | (int_status & U_ISTR_PMAOVR)));
#else
    model_istr_write((fsdev_bus_t)~U_ISTR_RESET);
#endif
    handle_bus_reset(rhport);
    dcd_event_bus_reset(0, TUSB_SPEED_FULL, true);
    return; // Don't do the rest of the things here; perhaps they've been cleared?
  }

#if CFG_MT_USB_BRIDGE
  if (int_status & U_ISTR_PMAOVR) {
    // Quarantine before servicing CTR: integrity of pending PMA is unknown.
    // Foreground runtime owns confirmed ADC Stop and cleanup.
    extern void mt_usb_bridge_pma_overrun(void);
    mt_usb_bridge_pma_overrun();
    model_istr_write((fsdev_bus_t)~U_ISTR_PMAOVR);
    return;
  }
#endif

  if (int_status & U_ISTR_WKUP) {
    FSDEV_REG->CNTR &= ~U_CNTR_LPMODE;
    FSDEV_REG->CNTR &= ~U_CNTR_FSUSP;

    model_istr_write((fsdev_bus_t)~U_ISTR_WKUP);
    dcd_event_bus_signal(0, DCD_EVENT_RESUME, true);
  }

  if (int_status & U_ISTR_SUSP) {
    /* Suspend is asserted for both suspend and unplug events. without Vbus monitoring,
     * these events cannot be differentiated, so we only trigger suspend. */

    /* Force low-power mode in the macrocell */
    FSDEV_REG->CNTR |= U_CNTR_FSUSP;
    FSDEV_REG->CNTR |= U_CNTR_LPMODE;

    /* clear of the ISTR bit must be done after setting of CNTR_FSUSP */
    model_istr_write((fsdev_bus_t)~U_ISTR_SUSP);
    dcd_event_bus_signal(0, DCD_EVENT_SUSPEND, true);
  }

  if (int_status & U_ISTR_ESOF) {
    if (remoteWakeCountdown == 1u) {
      FSDEV_REG->CNTR &= ~U_CNTR_RESUME;
    }
    if (remoteWakeCountdown > 0u) {
      remoteWakeCountdown--;
    }
    model_istr_write((fsdev_bus_t)~U_ISTR_ESOF);
  }

  // One endpoint iteration may enqueue both RX and TX events. Defer further
  // CTR entries until foreground grants another quantum; a loop cap alone
  // would allow immediate IRQ tail-chaining to starve the ADC foreground.
#if CFG_MT_USB_CTR_FAIRNESS
  unsigned mt_ctr_budget = 1u;
  bool mt_ctr_serviced = false;
  bool mt_continue_tx = false;
  while (!mt_ctr_deferred && mt_ctr_budget && (model_istr_read() & U_ISTR_CTR)) {
    --mt_ctr_budget;
    mt_ctr_serviced = true;
    if(mt_tx_burst_left) --mt_tx_burst_left;
#else
  while (model_istr_read() & U_ISTR_CTR) {
#endif
    // skip DIR bit, and use CTR TX/RX instead, since there is chance we have both TX/RX completed in one interrupt
    const uint32_t ep_id  = model_istr_read() & U_ISTR_EP_ID;
    const uint32_t ep_reg = ep_read(ep_id);

    if (ep_reg & U_EP_CTR_RX) {
  #if defined(TUP_USBIP_FSDEV_STM32) && defined(CFG_TUSB_FSDEV_32BIT)
      fsdev_btable_workaround_delay(false);
  #endif

      if (ep_reg & U_EP_SETUP) {
        handle_ctr_setup(ep_id); // CTR will be clear after copied setup packet
      } else {
        ep_write_clear_ctr(ep_id, TUSB_DIR_OUT);
        handle_ctr_rx(ep_id);
      }
    }

    if (ep_reg & U_EP_CTR_TX) {
#if CFG_MT_USB_CTR_FAIRNESS
      const uint8_t ep_num=(uint8_t)(ep_reg & U_EPADDR_FIELD);
      xfer_ctl_t *mt_xfer=xfer_ctl_ptr(ep_num,TUSB_DIR_IN);
      const uint16_t mt_queued=mt_xfer->queued_len;
      const uint16_t mt_total=mt_xfer->total_len;
      uint8_t *const mt_buffer=mt_xfer->buffer;
      const void *const mt_fifo=mt_xfer->ff;
      const bool mt_candidate=ep_num==2u && !(ep_reg&U_EP_CTR_RX) &&
          !(ep_reg&U_EP_SETUP) && (ep_reg&U_EP_T_FIELD)==U_EP_BULK &&
          ((mt_buffer && !mt_fifo) || (!mt_buffer && mt_fifo)) &&
          mt_xfer->max_packet_size==64u &&
          mt_total<=384u && mt_queued && mt_queued<mt_total && !(mt_queued&63u);
#endif
      ep_write_clear_ctr(ep_id, TUSB_DIR_IN);
      handle_ctr_tx(ep_id);
#if CFG_MT_USB_CTR_FAIRNESS
      const uint32_t mt_remaining=(uint16_t)(mt_total-mt_queued);
      const uint16_t mt_next=(uint16_t)((uint32_t)mt_queued+
          (mt_remaining<64u ? mt_remaining : 64u));
      mt_continue_tx=mt_candidate && mt_xfer->buffer==mt_buffer &&
          mt_xfer->ff==mt_fifo && mt_xfer->total_len==mt_total &&
          mt_xfer->queued_len==mt_next;
#endif
    }
  }

#if CFG_MT_USB_CTR_FAIRNESS
  if (mt_ctr_serviced) {
    mt_ctr_deferred = true;
    FSDEV_REG->CNTR &= (fsdev_bus_t)~U_CNTR_CTRM;
    /* Only an intermediate data-IN packet may spend the remaining grant.
     * Final/RX/SETUP/control/lifecycle/error paths stay held for foreground.
     * Check hardware lifecycle again: it may arrive during PMA publication. */
    if(mt_continue_tx && mt_tx_burst_left &&
        !(int_status&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP|U_ISTR_ERR)) &&
        !(model_istr_read()&(U_ISTR_DIR|U_ISTR_ERR)) &&
        !mt_usb_fsdev_lifecycle_pending() && mt_tx_burst_time_ok() &&
        !(FSDEV_REG->CNTR&(U_CNTR_FRES|U_CNTR_PDWN|U_CNTR_FSUSP)) &&
        (FSDEV_REG->DADDR&U_DADDR_EF)) {
      mt_ctr_deferred=false;
      FSDEV_REG->CNTR|=U_CNTR_CTRM;
      mt_irq_held=false;
      fsdev_int_enable(0);
    }
  }
#endif

  if (int_status & U_ISTR_PMAOVR) {
    TU_BREAKPOINT();
    model_istr_write((fsdev_bus_t)~U_ISTR_PMAOVR);
  }
}

static int permitted(void) {
    return lock_fn && unlock_fn && !mt_usb_fsdev_lifecycle_pending() &&
        mt_usb_epoch_core_io(&state, actor);
}

unsigned mt_usb_bridge_dispatch(uint32_t token, unsigned reset, mt_usb_scope *scope) {
    unsigned verdict = MT_USB_DROP;
    uint32_t key = mt_usb_bridge_lock();
    *scope = (mt_usb_scope){0};
    if (lock_fn && unlock_fn && !actor && token && token == state.current &&
        !state.exhausted && !state.faults) {
        if (mt_usb_fsdev_lifecycle_pending() || state.cleaned != token ||
            (!reset && state.pending_soft)) verdict = MT_USB_DEFER;
        else if (mt_usb_epoch_dispatch(&state, token, reset)) {
            scope->previous = actor; scope->entered = 1;
            actor = token; verdict = MT_USB_DISPATCH;
        }
    }
    mt_usb_bridge_unlock(key); return verdict;
}

int mt_usb_bridge_app_enter(mt_usb_scope *scope) {
    uint32_t key = mt_usb_bridge_lock();
    uint32_t token = actor ? actor : state.current;
    *scope = (mt_usb_scope){0};
    if (lock_fn && unlock_fn && !mt_usb_fsdev_lifecycle_pending() &&
        mt_usb_epoch_app_io(&state, token)) {
        scope->previous = actor; scope->entered = 1; actor = token;
    }
    mt_usb_bridge_unlock(key); return (int)scope->entered;
}

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
