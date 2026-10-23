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
/* STREAM_WRITE */
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
