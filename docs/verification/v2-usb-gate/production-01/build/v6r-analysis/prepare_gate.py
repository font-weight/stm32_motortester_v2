"""Strict SK gate observer layer over frozen SJ DCD; no hardware."""
from pathlib import Path
import difflib,hashlib,json
root=Path(__file__).resolve().parents[2];base=root/'build/v6q-fw-01/patched/dcd_stm32_fsdev.c'
over=root/'firmware/v2-stream/overlays';out=Path(__file__).resolve().parent
old=base.read_text('utf8');s=old
def once(a,b):
    global s
    assert s.count(a)==1,(a[:100],s.count(a));s=s.replace(a,b)
once('  #include "fsdev_common.h"','  #include "fsdev_common.h"\n#include "mt_usb_gate.h" /* R_GATE_INCLUDE */\nbool mt_usb_fsdev_lifecycle_pending(void); /* R_GATE_PROTO */')
once('''static bool mt_tx_burst_time_ok(void) {
  /* TIM2 is fully validated by the foreground owner before grant. These
   * checks only bound continuation; no wraps, debugger halt or WCET inferred. */
  return mt_tx_timer_ready() &&
      (uint16_t)((uint16_t)mt_tx_timer_read(0x40000024u)-mt_tx_burst_counter)<500u;
}''','''static bool mt_tx_burst_time_ok(unsigned *age) {
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
}''')
once('''  if (FSDEV_REG->CNTR & (U_CNTR_FRES | U_CNTR_PDWN)) return false;''','''  if (FSDEV_REG->CNTR & (U_CNTR_FRES | U_CNTR_PDWN)) {
    mt_gate_invalidate(1u); /* R_GATE_FRES */
    return false;
  }''')
once('''  mt_tx_burst_left=ctr && mt_tx_timer_ready() ? 6u : 0u;''','''  mt_gate_invalidate(0u); /* R_GATE_GRANT: old reason becomes historical. */
  mt_tx_burst_left=ctr && mt_tx_timer_ready() ? 6u : 0u;''')
once('''  mt_usb_fsdev_irq_hold();
#endif
  uint32_t int_status = FSDEV_REG->ISTR;''','''  mt_usb_fsdev_irq_hold();
  mt_gate_invalidate(0u); /* R_GATE_ISR_ENTRY */
#endif
  uint32_t int_status = FSDEV_REG->ISTR;
  if(int_status&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP))
    mt_gate_invalidate(1u); /* R_GATE_LIFECYCLE */''')
once('''  bool mt_continue_tx = false;
  while (!mt_ctr_deferred''','''  bool mt_continue_tx = false;
  bool gate_seen=false,gate_meta=false;
  unsigned gate_total=UINT16_MAX,gate_queued=UINT16_MAX;
  unsigned gate_initial=MT_G_HOLD_OTHER,gate_decision=0u,gate_age=UINT32_MAX;
  while (!mt_ctr_deferred''')
once('''      ep_write_clear_ctr(ep_id, TUSB_DIR_IN);
      handle_ctr_tx(ep_id);''','''      /* R_GATE_BEGIN: only existing post-RX endpoint selection/RAM tuple. */
      gate_seen=ep_num==2u;gate_total=mt_total;gate_queued=mt_queued;
      gate_meta=gate_seen && (ep_reg&U_EP_T_FIELD)==U_EP_BULK &&
          mt_xfer->max_packet_size==64u && mt_total<=384u && mt_queued<=mt_total &&
          !(mt_buffer && mt_fifo) && (!mt_total || mt_buffer || mt_fifo) &&
          (!mt_total || (mt_queued && (mt_queued==mt_total || !(mt_queued&63u))));
      if(gate_meta && !(ep_reg&(U_EP_CTR_RX|U_EP_SETUP)) && mt_queued==mt_total)
        gate_initial=MT_G_HOLD_FINAL;
      /* R_GATE_END */
      ep_write_clear_ctr(ep_id, TUSB_DIR_IN);
      handle_ctr_tx(ep_id);''')
once('''          mt_xfer->queued_len==mt_next;
#endif''','''          mt_xfer->queued_len==mt_next;
      /* R_GATE_BEGIN: extra RAM checks do not re-read endpoint/MMIO registers. */
      gate_meta=gate_meta && mt_xfer->buffer==mt_buffer && mt_xfer->ff==mt_fifo &&
          mt_xfer->total_len==mt_total &&
          mt_xfer->queued_len==(mt_queued==mt_total?mt_queued:mt_next);
      /* R_GATE_END */
#endif''')
old_condition='''mt_continue_tx && mt_tx_burst_left &&
        !(int_status&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP|U_ISTR_ERR)) &&
        !(FSDEV_REG->ISTR&(U_ISTR_DIR|U_ISTR_ERR)) &&
        !mt_usb_fsdev_lifecycle_pending() && mt_tx_burst_time_ok() &&
        !(FSDEV_REG->CNTR&(U_CNTR_FRES|U_CNTR_PDWN|U_CNTR_FSUSP)) &&
        (FSDEV_REG->DADDR&U_DADDR_EF)'''
once(old_condition,'mt_gate_continue(&gate_decision,&gate_age,gate_initial,\n                        mt_continue_tx,mt_tx_burst_left,int_status)')
once('''      fsdev_int_enable(0);
    }
  }
#endif

  if (int_status & U_ISTR_PMAOVR)''','''      fsdev_int_enable(0);
      gate_decision=MT_G_RESUMED; /* R_GATE_RESUME */
    }
    if(gate_seen)mt_gate_note(gate_decision,gate_total,gate_queued,
        mt_tx_burst_left,gate_age,gate_meta); /* R_GATE_NOTE */
  }
#endif

  if (int_status & U_ISTR_PMAOVR)''')
for name in ('dcd_edpt_stall','dcd_edpt_clear_stall'):
    at=f'void {name}(uint8_t rhport, uint8_t ep_addr) {{'
    once(at,at+'\n  if(ep_addr==0x82u)mt_gate_invalidate(1u); /* R_GATE_CANCEL */')
once('void dcd_edpt_close_all(uint8_t rhport) {','void dcd_edpt_close_all(uint8_t rhport) {\n  mt_gate_invalidate(1u); /* R_GATE_CANCEL */')
for name,field in (('dcd_edpt_xfer','buffer'),('dcd_edpt_xfer_fifo','ff')):
    start=s.index('bool '+name+'(');end=s.index('\n}',start)+2;body=s[start:end]
    target='  xfer->buffer     = '+('buffer;' if field=='buffer' else 'NULL;')
    assert body.count(target)==1
    body=body.replace(target,'  mt_gate_submit_begin(ep_addr); /* R_GATE_SUBMIT_BEGIN */\n'+target)
    ret='  return edpt_xfer(rhport, ep_num, dir);'
    assert body.count(ret)==1
    body=body.replace(ret,'''  const bool gate_ok=edpt_xfer(rhport, ep_num, dir);
  mt_gate_submit_done(ep_addr,gate_ok,total_bytes,xfer->queued_len,
      xfer->max_packet_size,(xfer->buffer?1u:0u)|(xfer->ff?2u:0u),is_isr);
  return gate_ok; /* R_GATE_SUBMIT_DONE */''')
    once(s[start:end],body)
raw=s.encode();p=out/'dcd_stm32_fsdev.c';p.write_bytes(raw)
patch=''.join(difflib.unified_diff(old.splitlines(True),s.splitlines(True),fromfile='a/dcd_stm32_fsdev.c',tofile='b/dcd_stm32_fsdev.c',n=3)).encode()
name='v2-usb-gate-dcd_stm32_fsdev.c.patch';(over/name).write_bytes(patch)
sha=lambda b:hashlib.sha256(b).hexdigest()
row={'source':'patched/dcd_stm32_fsdev.c','target':'dcd_stm32_fsdev.c','patch':name,'source_sha256':sha(old.encode()),'patch_sha256':sha(patch),'result_sha256':sha(raw)}
(over/'usb-gate.json').write_text(json.dumps({'schema':'motortester-v2-usb-gate-overlay-1','patches':[row]},indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps(row))
