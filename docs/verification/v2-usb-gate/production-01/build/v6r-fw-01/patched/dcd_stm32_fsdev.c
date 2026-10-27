/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2019 Nathan Conrad
 *
 * Portions:
 * Copyright (c) 2019 Ha Thach (tinyusb.org)
 * Copyright (c) 2022 Simon Küppers (skuep)
 * Copyright (c) 2022 HiFiPhile
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 * This file is part of the TinyUSB stack.
 */

/**********************************************
 * This driver has been tested with the following MCUs:
 *  - F070, F072, L053, F042F6
 *
 * It also should work with minimal changes for any ST MCU with an "USB A"/"PCD"/"HCD" peripheral. This
 *  covers:
 *
 * F04x, F072, F078, F070x6/B     1024 byte buffer
 * F102, F103                      512 byte buffer; no internal D+ pull-up (maybe many more changes?)
 * F302xB/C, F303xB/C, F373        512 byte buffer; no internal D+ pull-up
 * F302x6/8, F302xD/E2, F303xD/E  1024 byte buffer; no internal D+ pull-up
 * C0                             2048 byte buffer; 32-bit bus; host mode
 * C5                             2048 byte buffer; 32-bit bus; host mode
 * G0                             2048 byte buffer; 32-bit bus; host mode
 * G4                             1024 byte buffer
 * H5                             2048 byte buffer; 32-bit bus; host mode
 * L0x2, L0x3                     1024 byte buffer
 * L1                              512 byte buffer
 * L4x2, L4x3                     1024 byte buffer
 * L5                             1024 byte buffer
 * U0                             1024 byte buffer; 32-bit bus
 * U535, U545                     2048 byte buffer; 32-bit bus; host mode
 * WB35, WB55                     1024 byte buffer
 *
 * To use this driver, you must:
 * - If you are using a device with crystal-less USB, set up the clock recovery system (CRS)
 * - Remap pins to be D+/D- on devices that they are shared (for example: F042Fx)
 *   - This is different to the normal "alternate function" GPIO interface, needs to go through SYSCFG->CFGRx register
 * - Enable USB clock; Perhaps use __HAL_RCC_USB_CLK_ENABLE();
 * - (Optionally configure GPIO HAL to tell it the USB driver is using the USB pins)
 * - call tusb_init();
 *
 * Assumptions of the driver:
 * - You are not using CAN (it must share the packet buffer)
 * - APB clock is >= 10 MHz
 * - On some boards, series resistors are required, but not on others.
 * - On some boards, D+ pull up resistor (1.5kohm) is required, but not on others.
 * - You don't have long-running interrupts; some USB packets must be quickly responded to.
 * - You have the ST CMSIS library linked into the project. HAL is not used.
 *
 * Current driver limitations (i.e., a list of features for you to add):
 * - STALL handled, but not tested.
 *   - Does it work? No clue.
 * - All EP BTABLE buffers are created based on max packet size of first EP opened with that address.
 * - Packet buffer memory is copied in the interrupt.
 *   - This is better for performance, but means interrupts are disabled for longer
 *   - DMA may be the best choice, but it could also be pushed to the USBD task.
 * - No double-buffering
 * - No DMA
 * - Minimal error handling
 *   - Perhaps error interrupts should be reported to the stack, or cause a device reset?
 * - Assumes a single USB peripheral; I think that no hardware has multiple so this is fine.
 * - Add a callback for enabling/disabling the D+ PU on devices without an internal PU.
 * - F3 models use three separate interrupts. I think we could only use the LP interrupt for
 *     everything?  However, the interrupts are configurable so the DisableInt and EnableInt
 *     below functions could be adjusting the wrong interrupts (if they had been reconfigured)
 * - LPM is not used correctly, or at all?
 *
 * Notes:
 * - The buffer table is allocated as endpoints are opened. The allocation is only
 *   cleared when the device is reset. This may be bad if the USB device needs
 *   to be reconfigured.
 */

#include "tusb_option.h"

#if CFG_TUD_ENABLED && defined(TUP_USBIP_FSDEV) && !(defined(TUP_USBIP_FSDEV_CH32) && CFG_TUD_WCH_USBIP_FSDEV == 0)

  #include "device/dcd.h"
  #include "fsdev_common.h"
#include "mt_usb_gate.h" /* R_GATE_INCLUDE */

//--------------------------------------------------------------------+
// MACRO CONSTANT TYPEDEF
//--------------------------------------------------------------------+

// One of these for every EP IN & OUT, uses a bit of RAM....
typedef struct {
  uint8_t   *buffer;
  tu_fifo_t *ff;
  uint16_t   total_len;
  uint16_t   queued_len;
  uint16_t   max_packet_size;
  uint8_t    ep_idx;         // index for USB_EPnR register
  bool       iso_in_sending; // Workaround for ISO IN EP doesn't have interrupt mask
} xfer_ctl_t;

// EP allocator
typedef struct {
  uint8_t ep_num;
  uint8_t ep_type;
  bool    allocated[2];
} ep_alloc_t;

static xfer_ctl_t xfer_status[CFG_TUD_ENDPPOINT_MAX][2];
static ep_alloc_t ep_alloc_status[FSDEV_EP_COUNT];
static uint8_t    remoteWakeCountdown; // When wake is requested

// Opt-in F103 single-buffer stream profile. Legacy builds retain the old loop.
#ifndef CFG_MT_USB_CTR_FAIRNESS
#define CFG_MT_USB_CTR_FAIRNESS 0
#endif
#if CFG_MT_USB_CTR_FAIRNESS != 0 && CFG_MT_USB_CTR_FAIRNESS != 1
#error "CTR fairness must be exactly zero or one"
#endif
#if CFG_MT_USB_CTR_FAIRNESS
#if !CFG_MT_USB_BRIDGE || CFG_TUSB_MCU != OPT_MCU_STM32F1 || !defined(STM32F103xB)
#error "CTR fairness requires the guarded STM32F103xB stream profile"
#endif
static volatile bool mt_ctr_deferred;
static volatile bool mt_irq_held;
/* One foreground grant can continue at most one published CDC IN transfer.
 * This is not an arbitrary USB task/event burst and never invokes app I/O. */
static unsigned mt_tx_burst_left;
static uint16_t mt_tx_burst_counter;
static uint32_t mt_tx_timer_read(uint32_t address) {
  return *(volatile uint32_t *)(uintptr_t)address;
}
static bool mt_tx_timer_ready(void) {
  return (mt_tx_timer_read(0x4002101cu)&1u) &&
      !(mt_tx_timer_read(0x40021010u)&1u) &&
      mt_tx_timer_read(0x40000000u)==1u &&
      mt_tx_timer_read(0x40000028u)==71u &&
      mt_tx_timer_read(0x4000002cu)==65535u;
}
static bool mt_tx_burst_time_ok(unsigned *age) {
  /* Same ready/CNT reads and order; expose only the already evaluated age. */
  if(!mt_tx_timer_ready())return false;
  *age=(uint16_t)((uint16_t)mt_tx_timer_read(0x40000024u)-mt_tx_burst_counter);
  return *age<500u;
}
static bool mt_gate_time(unsigned *decision,unsigned *age) {
  const bool ok=mt_tx_burst_time_ok(age);
  return mt_gate_condition(decision,*age==UINT32_MAX?MT_G_TIMER_UNAVAILABLE:MT_G_HOLD_TIME,ok)!=0;
}
static bool mt_gate_continue(unsigned *decision,unsigned *age,unsigned initial,
                            bool can,unsigned left,uint32_t int_status) {
  /* Same short-circuit hardware expression, first evaluated false only. */
  return mt_gate_condition(decision,initial,can) &&
      mt_gate_condition(decision,MT_G_HOLD_BUDGET,left!=0u) &&
      mt_gate_condition(decision,MT_G_HOLD_LIFECYCLE,!(int_status&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP|U_ISTR_ERR))) &&
      mt_gate_condition(decision,MT_G_HOLD_STATUS,!(FSDEV_REG->ISTR&(U_ISTR_DIR|U_ISTR_ERR))) &&
      mt_gate_condition(decision,MT_G_HOLD_LIFECYCLE,!mt_usb_fsdev_lifecycle_pending()) &&
      mt_gate_time(decision,age) &&
      mt_gate_condition(decision,MT_G_HOLD_LIFECYCLE,!(FSDEV_REG->CNTR&(U_CNTR_FRES|U_CNTR_PDWN|U_CNTR_FSUSP))) &&
      mt_gate_condition(decision,MT_G_HOLD_LIFECYCLE,(FSDEV_REG->DADDR&U_DADDR_EF)!=0u);
}

bool mt_usb_fsdev_ctr_deferred(void) { return mt_ctr_deferred; }
bool mt_usb_fsdev_irq_held(void) { return mt_irq_held; }

bool mt_usb_fsdev_lifecycle_pending(void) {
  /* No flag is consumed here. Until ISR publishes its epoch/soft loss, neither
   * foreground dispatch nor application I/O may use the earlier observation. */
  return (FSDEV_REG->ISTR & (U_ISTR_RESET | U_ISTR_PMAOVR |
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
  if (FSDEV_REG->CNTR & (U_CNTR_FRES | U_CNTR_PDWN)) {
    mt_gate_invalidate(1u); /* R_GATE_FRES */
    return false;
  }
  bool ctr = allow_ctr && !mt_usb_fsdev_lifecycle_pending() &&
      !(FSDEV_REG->CNTR & U_CNTR_FSUSP) && (FSDEV_REG->DADDR & U_DADDR_EF);
  mt_gate_invalidate(0u); /* R_GATE_GRANT: old reason becomes historical. */
  mt_tx_burst_left=ctr && mt_tx_timer_ready() ? 6u : 0u;
  mt_tx_burst_counter=(uint16_t)mt_tx_timer_read(0x40000024u);
  mt_ctr_deferred = !ctr;
  if (ctr) FSDEV_REG->CNTR |= U_CNTR_CTRM;
  else FSDEV_REG->CNTR &= (fsdev_bus_t)~U_CNTR_CTRM;
  mt_irq_held = false;
  fsdev_int_enable(0);
  return true;
}
#endif
#if defined(TUP_USBIP_FSDEV_CH32)
static bool       ep0_ctrl_dir_in;
static bool       ep0_ctrl_has_data;
#endif

//--------------------------------------------------------------------+
// Prototypes
//--------------------------------------------------------------------+

// into the stack.
static void handle_bus_reset(uint8_t rhport);
static void dcd_transmit_packet(xfer_ctl_t *xfer, uint16_t ep_ix);
static bool edpt_xfer(uint8_t rhport, uint8_t ep_num, tusb_dir_t dir);

// PMA allocation/access
static uint16_t ep_buf_ptr; ///< Points to first free memory location
static uint32_t dcd_pma_alloc(uint16_t len, bool dbuf);
static uint8_t  dcd_ep_alloc(uint8_t ep_addr, uint8_t ep_type);

static void edpt0_open(uint8_t rhport);

TU_ATTR_ALWAYS_INLINE static inline void edpt0_prepare_setup(void) {
  btable_set_rx_bufsize(0, BTABLE_BUF_RX, 8);
}

//--------------------------------------------------------------------+
// Inline helper
//--------------------------------------------------------------------+

TU_ATTR_ALWAYS_INLINE static inline xfer_ctl_t *xfer_ctl_ptr(uint8_t epnum, uint8_t dir) {
  return &xfer_status[epnum][dir];
}

#if defined(TUP_USBIP_FSDEV_CH32)
// CH32 EP0 workaround: gate handshakes by switching EP0 type CONTROL<->BULK.
// need_exclusive brackets the read-modify-write so the USB ISR can't race it.
TU_ATTR_ALWAYS_INLINE static inline void ep0_set_type(uint32_t ep_type, bool need_exclusive) {
  if (need_exclusive) {
    fsdev_int_disable(0);
  }
  uint32_t ep_reg = ep_read(0) | U_EP_CTR_TX | U_EP_CTR_RX;
  ep_reg &= U_EPREG_MASK;
  ep_reg = (ep_reg & ~U_EP_T_FIELD) | ep_type;
  ep_write(0, ep_reg, false);
  if (need_exclusive) {
    fsdev_int_enable(0);
  }
}
#endif

//--------------------------------------------------------------------+
// Controller API
//--------------------------------------------------------------------+
bool dcd_init(uint8_t rhport, const tusb_rhport_init_t *rh_init) {
  (void)rh_init;

  fsdev_core_reset();

  FSDEV_REG->CNTR = 0; // Enable USB

  #if !defined( CFG_TUSB_FSDEV_32BIT)
  // BTABLE register does not exist any more on 32-bit bus devices
  FSDEV_REG->BTABLE = FSDEV_BTABLE_BASE;
  #endif

  // Enable interrupts for device mode
  FSDEV_REG->CNTR |=
    U_CNTR_RESETM | U_CNTR_ESOFM | U_CNTR_CTRM | U_CNTR_SUSPM | U_CNTR_WKUPM | U_CNTR_PMAOVRM;

  handle_bus_reset(rhport);

  // Enable pull-up if supported
  dcd_connect(rhport);

  return true;
}

bool dcd_deinit(uint8_t rhport) {
  (void)rhport;

  fsdev_deinit();

  return true;
}

void dcd_sof_enable(uint8_t rhport, bool en) {
  (void)rhport;

  if (en) {
    FSDEV_REG->CNTR |= U_CNTR_SOFM;
  } else {
    FSDEV_REG->CNTR &= ~U_CNTR_SOFM;
  }
}

// Receive Set Address request, mcu port must also include status IN response
void dcd_set_address(uint8_t rhport, uint8_t dev_addr) {
  (void)dev_addr;

  // Respond with status
#if CFG_MT_USB_BRIDGE
  extern void mt_usb_bridge_address_result(bool accepted);
  mt_usb_bridge_address_result(dcd_edpt_xfer(rhport, TUSB_DIR_IN_MASK | 0x00, NULL, 0, false));
#else
  dcd_edpt_xfer(rhport, TUSB_DIR_IN_MASK | 0x00, NULL, 0, false);
#endif

  // DCD can only set address after status for this request is complete.
  // do it at dcd_edpt0_status_complete()
}

void dcd_remote_wakeup(uint8_t rhport) {
  (void)rhport;

  FSDEV_REG->CNTR |= U_CNTR_RESUME;
  remoteWakeCountdown = 4u; // required to be 1 to 15 ms, ESOF should trigger every 1ms.
}

static void handle_bus_reset(uint8_t rhport) {
  FSDEV_REG->DADDR = 0u; // disable USB Function
#if CFG_MT_USB_CTR_FAIRNESS
  mt_ctr_deferred = false;
  FSDEV_REG->CNTR |= U_CNTR_CTRM;
#endif

  for (uint32_t i = 0; i < FSDEV_EP_COUNT; i++) {
#if defined(STM32F103xB)
    // RM0008: bus/FRES reset preserves CTR flags; EA/STAT/DTOG are reset.
    // With the function disabled, discard old completions before EP0 reuse.
    // A zero write is NOT a generic disable operation for toggle-on-one STAT.
    ep_write(i, 0, false);
#endif
    // Clear EP allocation status
    ep_alloc_status[i].ep_num       = 0xFF;
    ep_alloc_status[i].ep_type      = 0xFF;
    ep_alloc_status[i].allocated[0] = false;
    ep_alloc_status[i].allocated[1] = false;
  }

#if defined(STM32F103xB)
  // No pre-reset buffer/FIFO ownership survives this hardware reset boundary.
  tu_memclr(xfer_status, sizeof(xfer_status));
#endif

  // Reset PMA allocation
  ep_buf_ptr = FSDEV_BTABLE_BASE + 8 * FSDEV_EP_COUNT;

#if defined(TUP_USBIP_FSDEV_CH32)
  ep0_ctrl_dir_in = false;
  ep0_ctrl_has_data = false;
#endif

  edpt0_open(rhport);              // open control endpoint (both IN & OUT)

  FSDEV_REG->DADDR = U_DADDR_EF; // Enable USB Function
}

// Handle CTR interrupt for the TX/IN direction
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

static void handle_ctr_setup(uint32_t ep_id) {
  uint16_t rx_count = btable_get_count(ep_id, BTABLE_BUF_RX);
  uint16_t rx_addr  = (uint16_t)btable_get_addr(ep_id, BTABLE_BUF_RX);
  uint8_t  setup_packet[8] TU_ATTR_ALIGNED(4);

  tu_hwfifo_read(PMA_BUF_AT(rx_addr), setup_packet, rx_count, NULL);

  // Clear CTR RX if another setup packet arrived before this, it will be discarded
  ep_write_clear_ctr(ep_id, TUSB_DIR_OUT);

  // Setup packet should always be 8 bytes. If not, we probably missed the packet
  if (rx_count == 8) {
#if defined(TUP_USBIP_FSDEV_CH32)
    tusb_control_request_t const *request = (tusb_control_request_t const *) (void *) setup_packet;
    ep0_ctrl_dir_in = (request->bmRequestType_bit.direction == TUSB_DIR_IN);
    ep0_ctrl_has_data = (request->wLength != 0u);

    // For control write, block unsolicited EP0 OUT ACK until transfer is armed in edpt_xfer().
    if (!ep0_ctrl_dir_in && ep0_ctrl_has_data) {
      ep0_set_type(U_EP_BULK, false);
    }
#endif
    dcd_event_setup_received(0, (uint8_t *)setup_packet, true);
    // Hardware should reset EP0 RX/TX to NAK and both toggle to 1
  } else {
    // Missed setup packet !!!
    TU_BREAKPOINT();
    edpt0_prepare_setup();
  }
}

// Handle CTR interrupt for the RX/OUT direction
static void handle_ctr_rx(uint32_t ep_id) {
  uint32_t      ep_reg = ep_read(ep_id) | U_EP_CTR_TX | U_EP_CTR_RX;
  const uint8_t ep_num = ep_reg & U_EPADDR_FIELD;
  const bool    is_iso = ep_is_iso(ep_reg);
  xfer_ctl_t   *xfer   = xfer_ctl_ptr(ep_num, TUSB_DIR_OUT);

#if defined(TUP_USBIP_FSDEV_CH32)
  // Control write: re-lock EP0 OUT after each DATA OUT packet until next edpt_xfer().
  if ((ep_num == 0u) && !ep0_ctrl_dir_in && ep0_ctrl_has_data) {
    ep0_set_type(U_EP_BULK, false);
    ep_reg = (ep_reg & ~U_EP_T_FIELD) | U_EP_BULK;
  }
#endif

  uint8_t buf_id;
  #if FSDEV_USE_SBUF_ISO == 0
  bool const dbl_buf = is_iso;
  #else
  bool const dbl_buf = false;
  #endif
  if (dbl_buf) {
    buf_id = (ep_reg & U_EP_DTOG_RX) ? 0 : 1;
  } else {
    buf_id = BTABLE_BUF_RX;
  }
  const uint16_t   rx_count = btable_get_count(ep_id, buf_id);
  uint16_t         pma_addr = (uint16_t)btable_get_addr(ep_id, buf_id);
  fsdev_pma_buf_t *pma_buf  = PMA_BUF_AT(pma_addr);

  if (xfer->ff) {
    tu_hwfifo_read_to_fifo(pma_buf, xfer->ff, rx_count, NULL);
  } else {
    tu_hwfifo_read(pma_buf, xfer->buffer + xfer->queued_len, rx_count, NULL);
  }
  xfer->queued_len += rx_count;

  if ((rx_count < xfer->max_packet_size) || (xfer->queued_len >= xfer->total_len)) {
    // all bytes received or short packet

    // For ch32v203: reset rx bufsize to mps to prevent race condition to cause PMAOVR (occurs with msc write10)
    btable_set_rx_bufsize(ep_id, BTABLE_BUF_RX, xfer->max_packet_size);

    dcd_event_xfer_complete(0, ep_num, xfer->queued_len, XFER_RESULT_SUCCESS, true);

    // ch32 seems to unconditionally accept ZLP on EP0 OUT, which can incorrectly use queued_len of previous
    // transfer. So reset total_len and queued_len to 0.
    xfer->total_len = xfer->queued_len = 0;
  } else {
    // Set endpoint active again for receiving more data. Note that isochronous endpoints stay active always
    if (!is_iso) {
      const uint16_t cnt = tu_min16(xfer->total_len - xfer->queued_len, xfer->max_packet_size);
      btable_set_rx_bufsize(ep_id, BTABLE_BUF_RX, cnt);
    }
    ep_reg &= U_EPREG_MASK | EP_STAT_MASK(TUSB_DIR_OUT); // will change RX Status, reserved other toggle bits
    ep_change_status(&ep_reg, TUSB_DIR_OUT, EP_STAT_VALID);
    ep_write(ep_id, ep_reg, false);
  }
}

void dcd_int_handler(uint8_t rhport) {
#if CFG_MT_USB_CTR_FAIRNESS
  /* Every entry consumes the foreground grant, including RESET-only entries.
   * Pending endpoint flags survive; only bounded CDC IN continuation may rearm. */
  mt_usb_fsdev_irq_hold();
  mt_gate_invalidate(0u); /* R_GATE_ISR_ENTRY */
#endif
  uint32_t int_status = FSDEV_REG->ISTR;
  if(int_status&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP))
    mt_gate_invalidate(1u); /* R_GATE_LIFECYCLE */

  /* Put SOF flag at the beginning of ISR in case to get least amount of jitter if it is used for timing purposes */
  if ((int_status & U_ISTR_SOF) && (FSDEV_REG->CNTR & U_CNTR_SOFM)) {
    FSDEV_REG->ISTR = (fsdev_bus_t)~U_ISTR_SOF;
    dcd_event_sof(0, FSDEV_REG->FNR & U_FNR_FN, true);
  }

  if (int_status & U_ISTR_RESET) {
    // USBRST is start of reset.
#if CFG_MT_USB_BRIDGE
    // Discard overrun already observed with this physical reset. A stale flag
    // must not be reported by a later ISR as a fault of the new reset epoch.
    FSDEV_REG->ISTR = (fsdev_bus_t)~(U_ISTR_RESET | (int_status & U_ISTR_PMAOVR));
#else
    FSDEV_REG->ISTR = (fsdev_bus_t)~U_ISTR_RESET;
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
    FSDEV_REG->ISTR = (fsdev_bus_t)~U_ISTR_PMAOVR;
    return;
  }
#endif

  if (int_status & U_ISTR_WKUP) {
    FSDEV_REG->CNTR &= ~U_CNTR_LPMODE;
    FSDEV_REG->CNTR &= ~U_CNTR_FSUSP;

    FSDEV_REG->ISTR = (fsdev_bus_t)~U_ISTR_WKUP;
    dcd_event_bus_signal(0, DCD_EVENT_RESUME, true);
  }

  if (int_status & U_ISTR_SUSP) {
    /* Suspend is asserted for both suspend and unplug events. without Vbus monitoring,
     * these events cannot be differentiated, so we only trigger suspend. */

    /* Force low-power mode in the macrocell */
    FSDEV_REG->CNTR |= U_CNTR_FSUSP;
    FSDEV_REG->CNTR |= U_CNTR_LPMODE;

    /* clear of the ISTR bit must be done after setting of CNTR_FSUSP */
    FSDEV_REG->ISTR = (fsdev_bus_t)~U_ISTR_SUSP;
    dcd_event_bus_signal(0, DCD_EVENT_SUSPEND, true);
  }

  if (int_status & U_ISTR_ESOF) {
    if (remoteWakeCountdown == 1u) {
      FSDEV_REG->CNTR &= ~U_CNTR_RESUME;
    }
    if (remoteWakeCountdown > 0u) {
      remoteWakeCountdown--;
    }
    FSDEV_REG->ISTR = (fsdev_bus_t)~U_ISTR_ESOF;
  }

  // One endpoint iteration may enqueue both RX and TX events. Defer further
  // CTR entries until foreground grants another quantum; a loop cap alone
  // would allow immediate IRQ tail-chaining to starve the ADC foreground.
#if CFG_MT_USB_CTR_FAIRNESS
  unsigned mt_ctr_budget = 1u;
  bool mt_ctr_serviced = false;
  bool mt_continue_tx = false;
  bool gate_seen=false,gate_meta=false;
  unsigned gate_total=UINT16_MAX,gate_queued=UINT16_MAX;
  unsigned gate_initial=MT_G_HOLD_OTHER,gate_decision=0u,gate_age=UINT32_MAX;
  while (!mt_ctr_deferred && mt_ctr_budget && (FSDEV_REG->ISTR & U_ISTR_CTR)) {
    --mt_ctr_budget;
    mt_ctr_serviced = true;
    if(mt_tx_burst_left) --mt_tx_burst_left;
#else
  while (FSDEV_REG->ISTR & U_ISTR_CTR) {
#endif
    // skip DIR bit, and use CTR TX/RX instead, since there is chance we have both TX/RX completed in one interrupt
    const uint32_t ep_id  = FSDEV_REG->ISTR & U_ISTR_EP_ID;
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
      /* R_GATE_BEGIN: only existing post-RX endpoint selection/RAM tuple. */
      gate_seen=ep_num==2u;gate_total=mt_total;gate_queued=mt_queued;
      gate_meta=gate_seen && (ep_reg&U_EP_T_FIELD)==U_EP_BULK &&
          mt_xfer->max_packet_size==64u && mt_total<=384u && mt_queued<=mt_total &&
          !(mt_buffer && mt_fifo) && (!mt_total || mt_buffer || mt_fifo) &&
          (!mt_total || (mt_queued && (mt_queued==mt_total || !(mt_queued&63u))));
      if(gate_meta && !(ep_reg&(U_EP_CTR_RX|U_EP_SETUP)) && mt_queued==mt_total)
        gate_initial=MT_G_HOLD_FINAL;
      /* R_GATE_END */
      ep_write_clear_ctr(ep_id, TUSB_DIR_IN);
      handle_ctr_tx(ep_id);
#if CFG_MT_USB_CTR_FAIRNESS
      const uint32_t mt_remaining=(uint16_t)(mt_total-mt_queued);
      const uint16_t mt_next=(uint16_t)((uint32_t)mt_queued+
          (mt_remaining<64u ? mt_remaining : 64u));
      mt_continue_tx=mt_candidate && mt_xfer->buffer==mt_buffer &&
          mt_xfer->ff==mt_fifo && mt_xfer->total_len==mt_total &&
          mt_xfer->queued_len==mt_next;
      /* R_GATE_BEGIN: extra RAM checks do not re-read endpoint/MMIO registers. */
      gate_meta=gate_meta && mt_xfer->buffer==mt_buffer && mt_xfer->ff==mt_fifo &&
          mt_xfer->total_len==mt_total &&
          mt_xfer->queued_len==(mt_queued==mt_total?mt_queued:mt_next);
      /* R_GATE_END */
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
    if(mt_gate_continue(&gate_decision,&gate_age,gate_initial,
                        mt_continue_tx,mt_tx_burst_left,int_status)) {
      mt_ctr_deferred=false;
      FSDEV_REG->CNTR|=U_CNTR_CTRM;
      mt_irq_held=false;
      fsdev_int_enable(0);
      gate_decision=MT_G_RESUMED; /* R_GATE_RESUME */
    }
    if(gate_seen)mt_gate_note(gate_decision,gate_total,gate_queued,
        mt_tx_burst_left,gate_age,gate_meta); /* R_GATE_NOTE */
  }
#endif

  if (int_status & U_ISTR_PMAOVR) {
    TU_BREAKPOINT();
    FSDEV_REG->ISTR = (fsdev_bus_t)~U_ISTR_PMAOVR;
  }
}

//--------------------------------------------------------------------+
// Endpoint API
//--------------------------------------------------------------------+

// Invoked when a control transfer's status stage is complete.
// May help DCD to prepare for next control transfer, this API is optional.
void dcd_edpt0_status_complete(uint8_t rhport, const tusb_control_request_t *request) {
  (void)rhport;

  if (request->bmRequestType_bit.recipient == TUSB_REQ_RCPT_DEVICE &&
      request->bmRequestType_bit.type == TUSB_REQ_TYPE_STANDARD && request->bRequest == TUSB_REQ_SET_ADDRESS) {
    const uint8_t dev_addr = (uint8_t)request->wValue;
    FSDEV_REG->DADDR       = (U_DADDR_EF | dev_addr);
  }
}

/***
 * Allocate a section of PMA
 * In case of double buffering, high 16bit is the address of 2nd buffer
 * During failure, TU_ASSERT is used. If this happens, rework/reallocate memory manually.
 */
static uint32_t dcd_pma_alloc(uint16_t len, bool dbuf) {
  uint8_t  blsize, num_block;
  uint16_t aligned_len = pma_align_buffer_size(len, &blsize, &num_block);
  (void)blsize;
  (void)num_block;

  uint32_t addr = ep_buf_ptr;
  ep_buf_ptr    = (uint16_t)(ep_buf_ptr + aligned_len); // increment buffer pointer

  if (dbuf) {
    addr |= ((uint32_t)ep_buf_ptr) << 16;
    ep_buf_ptr = (uint16_t)(ep_buf_ptr + aligned_len); // increment buffer pointer
  }

  // Verify packet buffer is not overflowed
  TU_ASSERT(ep_buf_ptr <= CFG_TUSB_FSDEV_PMA_SIZE, 0xFFFF);

  return addr;
}

/***
 * Allocate hardware endpoint
 */
static uint8_t dcd_ep_alloc(uint8_t ep_addr, uint8_t ep_type) {
  const uint8_t epnum = tu_edpt_number(ep_addr);
  const uint8_t dir   = tu_edpt_dir(ep_addr);

  for (uint8_t i = 0; i < FSDEV_EP_COUNT; i++) {
    // Check if already allocated
    if (ep_alloc_status[i].allocated[dir] && ep_alloc_status[i].ep_type == ep_type &&
        ep_alloc_status[i].ep_num == epnum) {
      return i;
    }

  #if FSDEV_USE_SBUF_ISO == 0
    bool const dbl_buf = ep_type == TUSB_XFER_ISOCHRONOUS;
  #else
    bool const dbl_buf = false;
  #endif

    // If EP of current direction is not allocated
    // For double-buffered mode both directions needs to be free
    if (!ep_alloc_status[i].allocated[dir] && (!dbl_buf || !ep_alloc_status[i].allocated[dir ^ 1])) {
      // Check if EP number is the same
      if (ep_alloc_status[i].ep_num == 0xFF || ep_alloc_status[i].ep_num == epnum) {
        // One EP pair has to be the same type
        if (ep_alloc_status[i].ep_type == 0xFF || ep_alloc_status[i].ep_type == ep_type) {
          ep_alloc_status[i].ep_num         = epnum;
          ep_alloc_status[i].ep_type        = ep_type;
          ep_alloc_status[i].allocated[dir] = true;

          return i;
        }
      }
    }
  }

  // Allocation failed
  TU_ASSERT(0);
}

void edpt0_open(uint8_t rhport) {
  (void)rhport;

  dcd_ep_alloc(0x0, TUSB_XFER_CONTROL);
  dcd_ep_alloc(0x80, TUSB_XFER_CONTROL);

  xfer_status[0][0].max_packet_size = CFG_TUD_ENDPOINT0_SIZE;
  xfer_status[0][0].ep_idx          = 0;

  xfer_status[0][1].max_packet_size = CFG_TUD_ENDPOINT0_SIZE;
  xfer_status[0][1].ep_idx          = 0;

  uint16_t pma_addr0 = (uint16_t)dcd_pma_alloc(CFG_TUD_ENDPOINT0_SIZE, false);
  uint16_t pma_addr1 = (uint16_t)dcd_pma_alloc(CFG_TUD_ENDPOINT0_SIZE, false);

  btable_set_addr(0, BTABLE_BUF_RX, pma_addr0);
  btable_set_addr(0, BTABLE_BUF_TX, pma_addr1);

  uint32_t ep_reg = ep_read(0) & ~U_EPREG_MASK; // only get toggle bits
  ep_reg |= U_EP_CONTROL;
  ep_change_status(&ep_reg, TUSB_DIR_IN, EP_STAT_NAK);
  ep_change_status(&ep_reg, TUSB_DIR_OUT, EP_STAT_NAK);
  // no need to explicitly set DTOG bits since we aren't masked DTOG bit

  edpt0_prepare_setup(); // prepare for setup packet
  ep_write(0, ep_reg, false);
}

bool dcd_edpt_open(uint8_t rhport, const tusb_desc_endpoint_t *desc_ep) {
#if CFG_MT_USB_CTR_FAIRNESS
  if (!desc_ep || (desc_ep->bmAttributes.xfer != TUSB_XFER_BULK &&
                  desc_ep->bmAttributes.xfer != TUSB_XFER_INTERRUPT)) return false;
#endif
  (void)rhport;
  const uint8_t    ep_addr     = desc_ep->bEndpointAddress;
  const uint8_t    ep_num      = tu_edpt_number(ep_addr);
  const tusb_dir_t dir         = tu_edpt_dir(ep_addr);
  const uint16_t   packet_size = tu_edpt_packet_size(desc_ep);
  const uint8_t    ep_idx      = dcd_ep_alloc(ep_addr, desc_ep->bmAttributes.xfer);
  TU_ASSERT(ep_idx < FSDEV_EP_COUNT);

  uint32_t ep_reg = ep_read(ep_idx) & ~U_EPREG_MASK;
  ep_reg |= tu_edpt_number(ep_addr) | U_EP_CTR_TX | U_EP_CTR_RX;

  // Set type
  switch (desc_ep->bmAttributes.xfer) {
    case TUSB_XFER_BULK:
      ep_reg |= U_EP_BULK;
      break;
    case TUSB_XFER_INTERRUPT:
      ep_reg |= U_EP_INTERRUPT;
      break;

    default:
      // Note: ISO endpoint should use alloc / active functions
      TU_ASSERT(false);
  }

  /* Create a packet memory buffer area. */
  uint16_t pma_addr = (uint16_t)dcd_pma_alloc(packet_size, false);
  btable_set_addr(ep_idx, dir == TUSB_DIR_IN ? BTABLE_BUF_TX : BTABLE_BUF_RX, pma_addr);

  xfer_ctl_t *xfer      = xfer_ctl_ptr(ep_num, dir);
  xfer->max_packet_size = packet_size;
  xfer->ep_idx          = ep_idx;

  ep_change_status(&ep_reg, dir, EP_STAT_NAK);
  ep_change_dtog(&ep_reg, dir, 0);

  // reserve other direction toggle bits
  if (dir == TUSB_DIR_IN) {
    ep_reg &= ~(U_EPRX_STAT | U_EP_DTOG_RX);
  } else {
    ep_reg &= ~(U_EPTX_STAT | U_EP_DTOG_TX);
  }

  ep_write(ep_idx, ep_reg, true);

  return true;
}

void dcd_edpt_close_all(uint8_t rhport) {
  mt_gate_invalidate(1u); /* R_GATE_CANCEL */
  dcd_int_disable(rhport);

  for (uint32_t i = 1; i < FSDEV_EP_COUNT; i++) {
    // Reset endpoint
    ep_write(i, 0, false);
    // Clear EP allocation status
    ep_alloc_status[i].ep_num       = 0xFF;
    ep_alloc_status[i].ep_type      = 0xFF;
    ep_alloc_status[i].allocated[0] = false;
    ep_alloc_status[i].allocated[1] = false;
  }

  dcd_int_enable(rhport);

  // Reset PMA allocation
  ep_buf_ptr = FSDEV_BTABLE_BASE + 8 * FSDEV_EP_COUNT + 2 * CFG_TUD_ENDPOINT0_SIZE;
}

bool dcd_edpt_iso_alloc(uint8_t rhport, uint8_t ep_addr, uint16_t largest_packet_size) {
#if CFG_MT_USB_CTR_FAIRNESS
  (void)rhport; (void)ep_addr; (void)largest_packet_size;
  return false; // ISO/HP service is outside this single-buffer profile.
#else
  (void)rhport;

  const uint8_t ep_num = tu_edpt_number(ep_addr);
  const uint8_t dir    = tu_edpt_dir(ep_addr);
  const uint8_t ep_idx = dcd_ep_alloc(ep_addr, TUSB_XFER_ISOCHRONOUS);

  #if CFG_TUD_FSDEV_DOUBLE_BUFFERED_ISO_EP != 0
  uint32_t pma_addr  = dcd_pma_alloc(largest_packet_size, true);
  uint16_t pma_addr2 = (uint16_t)(pma_addr >> 16);
  #else
  uint32_t pma_addr  = dcd_pma_alloc(largest_packet_size, false);
  uint16_t pma_addr2 = (uint16_t)pma_addr;
  #endif

  #if FSDEV_USE_SBUF_ISO == 0
  btable_set_addr(ep_idx, 0, (uint16_t)pma_addr);
  btable_set_addr(ep_idx, 1, pma_addr2);
  #else
  btable_set_addr(ep_idx, dir == TUSB_DIR_IN ? BTABLE_BUF_TX : BTABLE_BUF_RX, (uint16_t)pma_addr);
  (void)pma_addr2;
  #endif

  xfer_ctl_t *xfer = xfer_ctl_ptr(ep_num, dir);
  xfer->ep_idx     = ep_idx;

  return true;
#endif
}

bool dcd_edpt_iso_activate(uint8_t rhport, const tusb_desc_endpoint_t *desc_ep) {
#if CFG_MT_USB_CTR_FAIRNESS
  (void)rhport; (void)desc_ep;
  return false; // ISO/HP service is outside this single-buffer profile.
#else
  (void)rhport;
  const uint8_t    ep_addr = desc_ep->bEndpointAddress;
  const uint8_t    ep_num  = tu_edpt_number(ep_addr);
  const tusb_dir_t dir     = tu_edpt_dir(ep_addr);
  xfer_ctl_t      *xfer    = xfer_ctl_ptr(ep_num, dir);

  const uint8_t ep_idx = xfer->ep_idx;

  xfer->max_packet_size = tu_edpt_packet_size(desc_ep);

  uint32_t ep_reg = ep_read(ep_idx) & ~U_EPREG_MASK;
  ep_reg |= tu_edpt_number(ep_addr) | U_EP_ISOCHRONOUS | U_EP_CTR_TX | U_EP_CTR_RX;
  #if FSDEV_USE_SBUF_ISO != 0
  ep_reg |= U_EP_KIND;

  ep_change_status(&ep_reg, dir, EP_STAT_DISABLED);
  ep_change_dtog(&ep_reg, dir, 0);

  if (dir == TUSB_DIR_IN) {
    ep_reg &= ~(U_EPRX_STAT | U_EP_DTOG_RX);
  } else {
    ep_reg &= ~(U_EPTX_STAT | U_EP_DTOG_TX);
  }
  #else
  ep_change_status(&ep_reg, TUSB_DIR_IN, EP_STAT_DISABLED);
  ep_change_status(&ep_reg, TUSB_DIR_OUT, EP_STAT_DISABLED);
  ep_change_dtog(&ep_reg, dir, 0);
  ep_change_dtog(&ep_reg, (tusb_dir_t)(1 - dir), 1);
  #endif

  ep_write(ep_idx, ep_reg, true);

  return true;
#endif
}

// Currently, single-buffered, and only 64 bytes at a time (max)
static void dcd_transmit_packet(xfer_ctl_t *xfer, uint16_t ep_ix) {
  uint16_t len    = tu_min16(xfer->total_len - xfer->queued_len, xfer->max_packet_size);
  uint32_t ep_reg = ep_read(ep_ix) | U_EP_CTR_TX | U_EP_CTR_RX; // reserve CTR

  const bool is_iso = ep_is_iso(ep_reg);

  uint8_t buf_id;
  #if FSDEV_USE_SBUF_ISO == 0
  bool const dbl_buf = is_iso;
  #else
  bool const dbl_buf = false;
  #endif
  if (dbl_buf) {
    buf_id = (ep_reg & U_EP_DTOG_TX) ? 1 : 0;
  } else {
    buf_id = BTABLE_BUF_TX;
  }
  uint16_t         addr_ptr = (uint16_t)btable_get_addr(ep_ix, buf_id);
  fsdev_pma_buf_t *pma_buf  = PMA_BUF_AT(addr_ptr);

  if (xfer->ff) {
    tu_hwfifo_write_from_fifo(pma_buf, xfer->ff, len, NULL);
  } else {
    tu_hwfifo_write(pma_buf, &(xfer->buffer[xfer->queued_len]), len, NULL);
  }
  xfer->queued_len += len;

  btable_set_count(ep_ix, buf_id, len);
  ep_change_status(&ep_reg, TUSB_DIR_IN, EP_STAT_VALID);

  if (is_iso) {
    xfer->iso_in_sending = true;
  }
  ep_reg &= U_EPREG_MASK | EP_STAT_MASK(TUSB_DIR_IN); // only change TX Status, reserve other toggle bits
  ep_write(ep_ix, ep_reg, true);
}

static bool edpt_xfer(uint8_t rhport, uint8_t ep_num, tusb_dir_t dir) {
  (void)rhport;

  xfer_ctl_t   *xfer   = xfer_ctl_ptr(ep_num, dir);
  const uint8_t ep_idx = xfer->ep_idx;
  if (dir == TUSB_DIR_IN) {
#if defined(TUP_USBIP_FSDEV_CH32)
    // Safe to restore CONTROL before arming IN: no pending OUT for the errata to blind-ACK.
    if (ep_num == 0u) {
      ep0_set_type(U_EP_CONTROL, true);
    }
#endif
    dcd_transmit_packet(xfer, ep_idx);
  } else {
    uint32_t ep_reg = ep_read(ep_idx) | U_EP_CTR_TX | U_EP_CTR_RX; // reserve CTR
    ep_reg &= U_EPREG_MASK | EP_STAT_MASK(dir);

    uint16_t cnt = tu_min16(xfer->total_len, xfer->max_packet_size);

  #if FSDEV_USE_SBUF_ISO == 0
    bool const dbl_buf = ep_is_iso(ep_reg);
  #else
    bool const dbl_buf = false;
  #endif
    if (dbl_buf) {
      btable_set_rx_bufsize(ep_idx, 0, cnt);
      btable_set_rx_bufsize(ep_idx, 1, cnt);
    } else {
      btable_set_rx_bufsize(ep_idx, BTABLE_BUF_RX, cnt);
    }

#if defined(TUP_USBIP_FSDEV_CH32)
    // Restore CONTROL in the same write as STAT_RX=VALID (after bufsize): a separate earlier
    // write would re-enable the blind OUT ACK while still NAK'd with a stale buffer.
    if (ep_num == 0u) {
      ep_reg = (ep_reg & ~U_EP_T_FIELD) | U_EP_CONTROL;
    }
#endif
    ep_change_status(&ep_reg, dir, EP_STAT_VALID);
    ep_write(ep_idx, ep_reg, true);
  }

  return true;
}

bool dcd_edpt_xfer(uint8_t rhport, uint8_t ep_addr, uint8_t *buffer, uint16_t total_bytes, bool is_isr) {
  (void)is_isr;
  const uint8_t    ep_num = tu_edpt_number(ep_addr);
  const tusb_dir_t dir    = tu_edpt_dir(ep_addr);
  xfer_ctl_t      *xfer   = xfer_ctl_ptr(ep_num, dir);

  mt_gate_submit_begin(ep_addr); /* R_GATE_SUBMIT_BEGIN */
  xfer->buffer     = buffer;
  xfer->ff         = NULL;
  xfer->total_len  = total_bytes;
  xfer->queued_len = 0;

  const bool gate_ok=edpt_xfer(rhport, ep_num, dir);
  mt_gate_submit_done(ep_addr,gate_ok,total_bytes,xfer->queued_len,
      xfer->max_packet_size,(xfer->buffer?1u:0u)|(xfer->ff?2u:0u),is_isr);
  return gate_ok; /* R_GATE_SUBMIT_DONE */
}

bool dcd_edpt_xfer_fifo(uint8_t rhport, uint8_t ep_addr, tu_fifo_t *ff, uint16_t total_bytes, bool is_isr) {
  (void)is_isr;
  const uint8_t    ep_num = tu_edpt_number(ep_addr);
  const tusb_dir_t dir    = tu_edpt_dir(ep_addr);
  xfer_ctl_t      *xfer   = xfer_ctl_ptr(ep_num, dir);

  mt_gate_submit_begin(ep_addr); /* R_GATE_SUBMIT_BEGIN */
  xfer->buffer     = NULL;
  xfer->ff         = ff;
  xfer->total_len  = total_bytes;
  xfer->queued_len = 0;

  const bool gate_ok=edpt_xfer(rhport, ep_num, dir);
  mt_gate_submit_done(ep_addr,gate_ok,total_bytes,xfer->queued_len,
      xfer->max_packet_size,(xfer->buffer?1u:0u)|(xfer->ff?2u:0u),is_isr);
  return gate_ok; /* R_GATE_SUBMIT_DONE */
}

void dcd_edpt_stall(uint8_t rhport, uint8_t ep_addr) {
  if(ep_addr==0x82u)mt_gate_invalidate(1u); /* R_GATE_CANCEL */
  (void)rhport;
  const uint8_t    ep_num = tu_edpt_number(ep_addr);
  const tusb_dir_t dir    = tu_edpt_dir(ep_addr);
  xfer_ctl_t      *xfer   = xfer_ctl_ptr(ep_num, dir);
  const uint8_t    ep_idx = xfer->ep_idx;

  uint32_t ep_reg = ep_read(ep_idx) | U_EP_CTR_TX | U_EP_CTR_RX; // reserve CTR bits
  ep_reg &= U_EPREG_MASK | EP_STAT_MASK(dir);
  ep_change_status(&ep_reg, dir, EP_STAT_STALL);

#if defined(TUP_USBIP_FSDEV_CH32)
  // Stall ends the transfer without edpt_xfer() (the only other CONTROL restore); else a rejected
  // control-write leaves EP0 typed BULK and the host's recovery SETUP is ignored until bus reset.
  if (ep_num == 0u) {
    ep_reg = (ep_reg & ~U_EP_T_FIELD) | U_EP_CONTROL;
  }
#endif

  ep_write(ep_idx, ep_reg, true);
}

void dcd_edpt_clear_stall(uint8_t rhport, uint8_t ep_addr) {
  if(ep_addr==0x82u)mt_gate_invalidate(1u); /* R_GATE_CANCEL */
  (void)rhport;

  const uint8_t    ep_num = tu_edpt_number(ep_addr);
  const tusb_dir_t dir    = tu_edpt_dir(ep_addr);
  xfer_ctl_t      *xfer   = xfer_ctl_ptr(ep_num, dir);
  const uint8_t    ep_idx = xfer->ep_idx;

  uint32_t ep_reg = ep_read(ep_idx) | U_EP_CTR_TX | U_EP_CTR_RX; // reserve CTR bits
  ep_reg &= U_EPREG_MASK | EP_STAT_MASK(dir) | EP_DTOG_MASK(dir);

  if (!ep_is_iso(ep_reg)) {
    ep_change_status(&ep_reg, dir, EP_STAT_NAK);
  }
  ep_change_dtog(&ep_reg, dir, 0); // Reset to DATA0
  ep_write(ep_idx, ep_reg, true);
}

void dcd_int_enable(uint8_t rhport) {
  fsdev_int_enable(rhport);
}

void dcd_int_disable(uint8_t rhport) {
  fsdev_int_disable(rhport);
}

  #if defined(USB_BCDR_DPPU) || defined(SYSCFG_PMC_USB_PU) || defined(EXTEN_USBD_PU_EN)
void dcd_connect(uint8_t rhport) {
  fsdev_connect(rhport);
}

void dcd_disconnect(uint8_t rhport) {
  fsdev_disconnect(rhport);
}
  #endif

#endif
