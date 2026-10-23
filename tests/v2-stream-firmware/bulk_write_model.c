/* Exact live_write wrapper with explicit FIFO/admission seams. No USB PHY. */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define CHECK(x) do { if(!(x)){fprintf(stderr,"FAIL bulk line%d: %s\n",__LINE__,#x);exit(1);} } while(0)
typedef struct { unsigned initialized,in_step,writer_active; } mt_live_runtime;
typedef struct { unsigned entered; } mt_usb_scope;
static unsigned allowed,app_entered,leave_count,write_count,lose_after_copy;
static size_t accepted_count;
static int mt_usb_bridge_app_enter(mt_usb_scope *s) { s->entered=allowed;return (int)allowed; }
static void mt_usb_bridge_leave(mt_usb_scope *s) { CHECK(s->entered);++leave_count; }
static int usable(mt_live_runtime *r) {(void)r;return (int)allowed;}
static size_t tud_cdc_n_write(unsigned itf,const void *bytes,uint32_t n) {
    (void)bytes;CHECK(itf==0 && n<=384);++write_count;
    if(lose_after_copy)allowed=0;
    return accepted_count<n?accepted_count:n;
}
/* LIVE_WRITE */
void check_bulk_live_write(void) {
    mt_live_runtime r={1,1,0};uint8_t bytes[385]={0};
    allowed=1;accepted_count=384;leave_count=write_count=app_entered=0;
    CHECK(live_write(&r,bytes,384)==384 && write_count==1 && leave_count==1 && !r.writer_active);
    CHECK(live_write(&r,bytes,385)==SIZE_MAX && write_count==1);
    accepted_count=17;CHECK(live_write(&r,bytes,307)==17 && !r.writer_active);
    accepted_count=0;CHECK(live_write(&r,bytes,307)==0 && !r.writer_active);
    accepted_count=307;lose_after_copy=1;
    CHECK(live_write(&r,bytes,307)==307 && !r.writer_active);
    unsigned before=write_count;
    CHECK(live_write(&r,bytes,307)==0 && write_count==before);
    puts("PASS actual live_write384/385 / partial / zero / post-copy epoch loss preserves accepted prefix");
}
