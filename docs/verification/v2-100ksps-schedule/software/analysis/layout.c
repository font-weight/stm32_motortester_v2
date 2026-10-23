#include <stddef.h>
#include "mt_live_runtime.h"
#include "tusb.h"
#include "common/tusb_private.h"
typedef struct {
  uint8_t rhport;
  uint8_t itf_num;
  uint8_t ep_notify;
  uint8_t line_state; // Bit 0: DTR, Bit 1: RTS

  /*------------- From this point, data is not cleared by bus reset -------------*/
  TU_ATTR_ALIGNED(4) cdc_line_coding_t line_coding;
  char wanted_char;

  tu_edpt_stream_t tx_stream;
  tu_edpt_stream_t rx_stream;

  uint8_t tx_ff_buf[CFG_TUD_CDC_TX_BUFSIZE];
  uint8_t rx_ff_buf[CFG_TUD_CDC_RX_BUFSIZE];
} cdcd_interface_t;
typedef struct {
  uint8_t   *buffer;
  tu_fifo_t *ff;
  uint16_t   total_len;
  uint16_t   queued_len;
  uint16_t   max_packet_size;
  uint8_t    ep_idx;         // index for USB_EPnR register
  bool       iso_in_sending; // Workaround for ISO IN EP doesn't have interrupt mask
} xfer_ctl_t;
const unsigned size__mt_live_runtime=sizeof(mt_live_runtime);
const unsigned off__mt_live_runtime__adc=offsetof(mt_live_runtime,adc);
const unsigned off__mt_live_runtime__device=offsetof(mt_live_runtime,device);
const unsigned off__mt_live_runtime__acquisition=offsetof(mt_live_runtime,acquisition);
const unsigned off__mt_live_runtime__clock64=offsetof(mt_live_runtime,clock64);
const unsigned off__mt_live_runtime__epoch=offsetof(mt_live_runtime,epoch);
const unsigned off__mt_live_runtime__pending=offsetof(mt_live_runtime,pending);
const unsigned off__mt_live_runtime__open=offsetof(mt_live_runtime,open);
const unsigned off__mt_live_runtime__in_step=offsetof(mt_live_runtime,in_step);
const unsigned off__mt_live_runtime__clock_fault=offsetof(mt_live_runtime,clock_fault);
const unsigned size__mt_adc_dma_t=sizeof(mt_adc_dma_t);
const unsigned off__mt_adc_dma_t__io=offsetof(mt_adc_dma_t,io);
const unsigned off__mt_adc_dma_t__start_before_us=offsetof(mt_adc_dma_t,start_before_us);
const unsigned off__mt_adc_dma_t__start_after_us=offsetof(mt_adc_dma_t,start_after_us);
const unsigned off__mt_adc_dma_t__last_poll_us=offsetof(mt_adc_dma_t,last_poll_us);
const unsigned off__mt_adc_dma_t__last_progress_us=offsetof(mt_adc_dma_t,last_progress_us);
const unsigned off__mt_adc_dma_t__first_sample_index=offsetof(mt_adc_dma_t,first_sample_index);
const unsigned off__mt_adc_dma_t__last_remaining=offsetof(mt_adc_dma_t,last_remaining);
const unsigned off__mt_adc_dma_t__state=offsetof(mt_adc_dma_t,state);
const unsigned off__mt_adc_dma_t__fault=offsetof(mt_adc_dma_t,fault);
const unsigned off__mt_adc_dma_t__next_half=offsetof(mt_adc_dma_t,next_half);
const unsigned off__mt_adc_dma_t__owns_peripherals=offsetof(mt_adc_dma_t,owns_peripherals);
const unsigned off__mt_adc_dma_t__stream_history_valid=offsetof(mt_adc_dma_t,stream_history_valid);
const unsigned off__mt_adc_dma_t__stop_dma_known=offsetof(mt_adc_dma_t,stop_dma_known);
const unsigned off__mt_adc_dma_t__stop_count=offsetof(mt_adc_dma_t,stop_count);
const unsigned off__mt_adc_dma_t__stop_offset=offsetof(mt_adc_dma_t,stop_offset);
const unsigned off__mt_adc_dma_t__stop_first_index=offsetof(mt_adc_dma_t,stop_first_index);
const unsigned off__mt_adc_dma_t__stop_dma_end=offsetof(mt_adc_dma_t,stop_dma_end);
const unsigned off__mt_adc_dma_t__first_fault=offsetof(mt_adc_dma_t,first_fault);
const unsigned size__mt_live_device=sizeof(mt_live_device);
const unsigned off__mt_live_device__queue=offsetof(mt_live_device,queue);
const unsigned off__mt_live_device__state=offsetof(mt_live_device,state);
const unsigned off__mt_live_device__last_time=offsetof(mt_live_device,last_time);
const unsigned off__mt_live_device__nonce=offsetof(mt_live_device,nonce);
const unsigned off__mt_live_device__generation=offsetof(mt_live_device,generation);
const unsigned off__mt_live_device__hardware_off=offsetof(mt_live_device,hardware_off);
const unsigned off__mt_live_device__local_error=offsetof(mt_live_device,local_error);
const unsigned off__mt_live_device__first_reason=offsetof(mt_live_device,first_reason);
const unsigned off__mt_live_device__prefix_end=offsetof(mt_live_device,prefix_end);
const unsigned off__mt_live_device__tx_length=offsetof(mt_live_device,tx_length);
const unsigned off__mt_live_device__tx_offset=offsetof(mt_live_device,tx_offset);
const unsigned off__mt_live_device__tx_type=offsetof(mt_live_device,tx_type);
const unsigned off__mt_live_device__tx_first_index=offsetof(mt_live_device,tx_first_index);
const unsigned off__mt_live_device__tx_count=offsetof(mt_live_device,tx_count);
const unsigned off__mt_live_device__tx_sequence=offsetof(mt_live_device,tx_sequence);
const unsigned off__mt_live_device__last_write_accepted=offsetof(mt_live_device,last_write_accepted);
const unsigned off__mt_live_device__last_write_known=offsetof(mt_live_device,last_write_known);
const unsigned size__mt_sample_queue=sizeof(mt_sample_queue);
const unsigned off__mt_sample_queue__head_index=offsetof(mt_sample_queue,head_index);
const unsigned off__mt_sample_queue__next_index=offsetof(mt_sample_queue,next_index);
const unsigned off__mt_sample_queue__head=offsetof(mt_sample_queue,head);
const unsigned off__mt_sample_queue__used=offsetof(mt_sample_queue,used);
const unsigned off__mt_sample_queue__sealed=offsetof(mt_sample_queue,sealed);
const unsigned off__mt_sample_queue__first_fault=offsetof(mt_sample_queue,first_fault);
const unsigned size__cdcd_interface_t=sizeof(cdcd_interface_t);
const unsigned off__cdcd_interface_t__line_state=offsetof(cdcd_interface_t,line_state);
const unsigned off__cdcd_interface_t__tx_stream=offsetof(cdcd_interface_t,tx_stream);
const unsigned off__cdcd_interface_t__tx_ff_buf=offsetof(cdcd_interface_t,tx_ff_buf);
const unsigned size__tu_edpt_stream_t=sizeof(tu_edpt_stream_t);
const unsigned off__tu_edpt_stream_t__ep_addr=offsetof(tu_edpt_stream_t,ep_addr);
const unsigned off__tu_edpt_stream_t__mps=offsetof(tu_edpt_stream_t,mps);
const unsigned off__tu_edpt_stream_t__xfer_len=offsetof(tu_edpt_stream_t,xfer_len);
const unsigned off__tu_edpt_stream_t__ep_buf=offsetof(tu_edpt_stream_t,ep_buf);
const unsigned off__tu_edpt_stream_t__ff=offsetof(tu_edpt_stream_t,ff);
const unsigned size__tu_fifo_t=sizeof(tu_fifo_t);
const unsigned off__tu_fifo_t__buffer=offsetof(tu_fifo_t,buffer);
const unsigned off__tu_fifo_t__depth=offsetof(tu_fifo_t,depth);
const unsigned off__tu_fifo_t__overwritable=offsetof(tu_fifo_t,overwritable);
const unsigned off__tu_fifo_t__wr_idx=offsetof(tu_fifo_t,wr_idx);
const unsigned off__tu_fifo_t__rd_idx=offsetof(tu_fifo_t,rd_idx);
const unsigned size__xfer_ctl_t=sizeof(xfer_ctl_t);
const unsigned off__xfer_ctl_t__buffer=offsetof(xfer_ctl_t,buffer);
const unsigned off__xfer_ctl_t__ff=offsetof(xfer_ctl_t,ff);
const unsigned off__xfer_ctl_t__total_len=offsetof(xfer_ctl_t,total_len);
const unsigned off__xfer_ctl_t__queued_len=offsetof(xfer_ctl_t,queued_len);
const unsigned off__xfer_ctl_t__max_packet_size=offsetof(xfer_ctl_t,max_packet_size);
const unsigned off__xfer_ctl_t__ep_idx=offsetof(xfer_ctl_t,ep_idx);
