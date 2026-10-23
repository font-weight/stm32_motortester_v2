/* Exact runtime admission body; FIFO/admission are explicit logical seams. */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL whole-fit line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
typedef struct {unsigned initialized,in_step,writer_active;} mt_live_runtime;
typedef struct {unsigned entered;} mt_usb_scope;
static mt_live_runtime owner={1,1,0};
static unsigned allowed=1,write_calls,leaves,lose_after_copy;
static size_t available,accepted_total;
static uint8_t sink[384];
static int mt_usb_bridge_app_enter(mt_usb_scope *s){s->entered=allowed;return (int)allowed;}
static void mt_usb_bridge_leave(mt_usb_scope *s){CHECK(s->entered);++leaves;}
static int usable(mt_live_runtime *r){(void)r;return (int)allowed;}
static uint32_t tud_cdc_n_write_available(unsigned itf){CHECK(itf==0);return (uint32_t)available;}
static size_t tud_cdc_n_write(unsigned itf,const void *bytes,uint32_t n){
    CHECK(itf==0 && n<=available && n<=384 && owner.writer_active);
    memcpy(sink,bytes,n);available-=n;accepted_total+=n;++write_calls;
    if(lose_after_copy)allowed=0;
    return n;
}
/* LIVE_WRITE */
void whole_fit_space(size_t n){CHECK(n<=384);available=n;write_calls=0;accepted_total=0;allowed=1;lose_after_copy=0;}
unsigned whole_fit_calls(void){return write_calls;}
size_t whole_fit_accept(const uint8_t *p,size_t n){return live_write(&owner,p,n);}
void whole_fit_boundaries(void){
    uint8_t p[385]={0};whole_fit_space(383);
    CHECK(whole_fit_accept(p,384)==0 && available==383 && !write_calls && !accepted_total && !owner.writer_active);
    whole_fit_space(384);CHECK(whole_fit_accept(p,384)==384 && !available && write_calls==1);
    CHECK(whole_fit_accept(p,385)==SIZE_MAX && write_calls==1);
    whole_fit_space(384);allowed=0;
    CHECK(whole_fit_accept(p,307)==0 && !write_calls && available==384);
    whole_fit_space(384);lose_after_copy=1;
    CHECK(whole_fit_accept(p,307)==307 && write_calls==1 && available==77 && !owner.writer_active);
    CHECK(whole_fit_accept(p,1)==0 && write_calls==1);
    puts("PASS whole-fit383/384 / reject385 / epoch denial / post-copy known positive preserved");
}
