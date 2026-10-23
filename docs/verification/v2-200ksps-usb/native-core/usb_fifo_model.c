/* Real TinyUSB FIFO and stream-write bodies, with transfer/claim seams. */
#include "osal/osal.h"
#include "common/tusb_fifo.h"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL fifo line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
typedef struct { tu_fifo_t ff;uint8_t *ep_buf;uint16_t xfer_len,mps; } tu_edpt_stream_t;
static bool busy;
static unsigned submitted,last_length,zlps;
static bool stream_claim(tu_edpt_stream_t *s) {(void)s;if(busy)return false;busy=true;return true;}
static bool stream_release(tu_edpt_stream_t *s) {(void)s;busy=false;return true;}
static bool stream_xfer(tu_edpt_stream_t *s,uint16_t n) {
    (void)s;CHECK(n<=384);++submitted;last_length=n;if(!n)++zlps;return true;
}
bool tu_edpt_stream_write_zlp_if_needed(tu_edpt_stream_t *s, uint32_t last_xferred_bytes) {
  // ZLP condition: no pending data, last transferred bytes is multiple of packet size
  TU_VERIFY(tu_fifo_empty(&s->ff) && last_xferred_bytes > 0 && (0 == (last_xferred_bytes & (s->mps - 1))));
  TU_VERIFY(stream_claim(s));
  TU_ASSERT(stream_xfer(s, 0));
  return true;
}

uint32_t tu_edpt_stream_write_xfer(tu_edpt_stream_t *s) {
  const uint16_t ff_count = tu_fifo_count(&s->ff);
  TU_VERIFY(ff_count > 0, 0); // skip if no data
  TU_VERIFY(stream_claim(s), 0);

  // Pull data from FIFO -> EP buf
  uint16_t count;
  if (s->ep_buf == NULL) {
    count = tu_fifo_count(&s->ff); // re-get count since fifo can be changed
  } else {
    count = tu_fifo_read_n(&s->ff, s->ep_buf, s->xfer_len);
  }

  if (count > 0) {
    TU_ASSERT(stream_xfer(s, count), 0);
    return count;
  } else {
    // Release endpoint since we don't make any transfer
    // Note: data is dropped if terminal is not connected
    stream_release(s);
    return 0;
  }
}

uint32_t tu_edpt_stream_write(tu_edpt_stream_t *s, const void *buffer, uint32_t bufsize) {
  TU_VERIFY(bufsize > 0);
  const uint16_t ret = tu_fifo_write_n(&s->ff, buffer, (uint16_t) bufsize);

  // flush if fifo has more than packet size or
  // in rare case: fifo depth is configured too small (which never reach packet size)
  if ((tu_fifo_count(&s->ff) >= s->mps) || (tu_fifo_depth(&s->ff) < s->mps)) {
    tu_edpt_stream_write_xfer(s);
  }
  return ret;
}

void check_fifo_payload(void) {
    uint8_t storage[384],first[385],second[307],out[384];
    for(unsigned i=0;i<sizeof first;i++)first[i]=(uint8_t)i;
    for(unsigned i=0;i<sizeof second;i++)second[i]=(uint8_t)(255-i);
    tu_edpt_stream_t s={.ep_buf=NULL,.xfer_len=384,.mps=64};
    CHECK(tu_fifo_config(&s.ff,storage,384,false));
    CHECK(tu_edpt_stream_write(&s,first,307)==307);
    CHECK(busy && last_length==307 && submitted==1 && tu_fifo_count(&s.ff)==307);
    /* Dedicated F103 FIFO: later appends do not extend the published transfer. */
    CHECK(tu_edpt_stream_write(&s,second,307)==77);
    CHECK(submitted==1 && last_length==307 && tu_fifo_count(&s.ff)==384);
    CHECK(tu_edpt_stream_write(&s,first,1)==0);
    CHECK(tu_fifo_read_n(&s.ff,out,307)==307 && !memcmp(out,first,307));
    busy=false;
    CHECK(!tu_edpt_stream_write_zlp_if_needed(&s,307));
    CHECK(tu_edpt_stream_write_xfer(&s)==77 && last_length==77);
    CHECK(tu_fifo_read_n(&s.ff,out,77)==77 && !memcmp(out,second,77));busy=false;
    CHECK(!tu_edpt_stream_write_zlp_if_needed(&s,77));
    CHECK(tu_edpt_stream_write(&s,first,385)==384);
    CHECK(last_length==384 && tu_fifo_count(&s.ff)==384);
    CHECK(tu_fifo_read_n(&s.ff,out,384)==384 && !memcmp(out,first,384));busy=false;
    CHECK(tu_edpt_stream_write_zlp_if_needed(&s,384) && zlps==1 && !last_length);
    busy=false;tu_fifo_clear(&s.ff);
    puts("PASS actual FIFO384 / dedicated-FIFO transfer snapshot / partial77 / full / short / ZLP / 384-overflow boundary");
}
