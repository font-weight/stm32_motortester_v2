/* One actual-runtime order model. Runner inserts frozen runtime bodies and
 * links the actual epoch module. ADC/core/USB/clock are logical seams: no
 * physical IRQ timing, USB throughput or accepted-prefix qualification. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "app/mt_live_runtime.h"
#include "platform/mt_stream_diag.h"
#include "platform/mt_usb_ctr.h"
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL deferred line%d: %s trace=%s\n",__LINE__,#x,trace);exit(1);}}while(0)
static mt_live_runtime owner;
static mt_timebase clock_source;
static mt_usb_epoch epoch;
static char trace[2048];
static unsigned traced,depth,actor,time_calls,pending_time,healthy_late,decline_health,declined_health;
static unsigned adc_calls,task_calls,rx_reads,core_rx,prepare_calls,tx_calls;
static unsigned fifo_calls,flush_calls,cleaned_calls,lost_calls,clear_calls;
static unsigned grant_calls,grant_allow,grant_actor,grant_unlock_armed,grant_result;
static unsigned task_pending,completed_events,adc_argument,ready,lifecycle;
static unsigned pending_command,rx_done,deny_late_scope,late_scope_denied;
static unsigned inject_prepare,inject_grant,inject_late_enter,prepared_form;
static unsigned prepare_time_call,grant_time_call,grant_rx_reads;
static size_t fifo_free,accepted;
enum { INJECT_NONE,INJECT_EPOCH,INJECT_TIME,INJECT_LIFECYCLE,INJECT_SOFT,INJECT_FINAL };
enum { FORM_NORMAL,FORM_EMPTY,FORM_ERROR,FORM_CONTROL,FORM_SHORT,FORM_BAD_TICKET };

static void mark(char c){CHECK(traced+1<sizeof trace);trace[traced++]=c;trace[traced]=0;}
static void inject(unsigned what){
    if(what==INJECT_EPOCH){CHECK(mt_usb_epoch_reset(&epoch));task_pending=1;}
    if(what==INJECT_TIME)pending_time=1; /* healthy() alone cannot detect it. */
    if(what==INJECT_LIFECYCLE)lifecycle=1;
    if(what==INJECT_SOFT)CHECK(mt_usb_epoch_suspend(&epoch,epoch.current));
    if(what==INJECT_FINAL)task_pending=1;
}
static uint64_t live_time(void *p){
    mt_live_runtime *r=p;mark('t');++time_calls;
    if(pending_time || r->clock64.failed){r->clock64.failed=1;return UINT64_MAX;}
    return time_calls;
}
int mt_timebase_healthy(const mt_timebase *p){
    if(decline_health && prepare_calls && actor==owner.epoch && !grant_calls &&
       ++healthy_late==2){++declined_health;return 0;}
    return p && p->state==MT_TIMEBASE_RUNNING && !p->fault;
}
uint32_t mt_usb_bridge_lock(void){uint32_t old=depth;++depth;return old;}
void mt_usb_bridge_unlock(uint32_t old){
    CHECK(depth>old);depth=old;
    if(!depth && grant_unlock_armed){grant_unlock_armed=0;inject(inject_grant);}
}
mt_usb_epoch mt_usb_bridge_snapshot(void){return epoch;}
uint32_t mt_usb_bridge_actor(void){return actor;}
bool mt_usb_fsdev_lifecycle_pending(void){return lifecycle!=0;}
int mt_usb_bridge_app_enter(mt_usb_scope *s){
    s->previous=actor;s->entered=0;
    if(deny_late_scope && prepare_calls && !grant_calls){deny_late_scope=0;++late_scope_denied;mark('d');return 0;}
    if(lifecycle || !mt_usb_epoch_app_io(&epoch,epoch.current))return 0;
    actor=epoch.current;s->entered=1;
    if(prepare_calls && !grant_calls && inject_late_enter){unsigned event=inject_late_enter;inject_late_enter=0;inject(event);}
    return 1;
}
void mt_usb_bridge_leave(mt_usb_scope *s){CHECK(s->entered);actor=s->previous;s->entered=0;}
void mt_usb_bridge_cleaned(uint32_t token){mark('c');++cleaned_calls;CHECK(mt_usb_epoch_cleaned(&epoch,token));}
bool mt_usb_fsdev_irq_grant(bool allow){
    CHECK(depth);mark('g');++grant_calls;grant_allow=allow;grant_actor=actor;
    grant_time_call=time_calls;grant_rx_reads=rx_reads;
    grant_unlock_armed=1;return grant_result!=0;
}
bool tud_inited(void){return true;}
bool tud_task_event_ready(void){return task_pending!=0;}
void tud_task_ext(uint32_t timeout,bool in_isr){
    CHECK(!timeout && !in_isr && !actor);mark('u');++task_calls;
    if(task_pending){task_pending=0;++completed_events;mark('e');}
}
bool tud_cdc_n_ready(uint8_t itf){CHECK(!itf);return ready!=0;}
bool tud_cdc_n_connected(uint8_t itf){CHECK(!itf);return true;}
uint32_t tud_cdc_n_read(uint8_t itf,void *bytes,uint32_t n){
    CHECK(!itf && n && actor==owner.epoch && !lifecycle && !owner.clock64.failed);
    mark('q');++rx_reads;
    if(pending_command && !rx_done){*(uint8_t*)bytes=(uint8_t)pending_command;return 1;}
    return 0;
}
void tud_cdc_n_read_flush(uint8_t itf){CHECK(!itf);}
uint32_t tud_cdc_n_write_available(uint8_t itf){CHECK(!itf);return (uint32_t)fifo_free;}
uint32_t tud_cdc_n_write(uint8_t itf,const void *bytes,uint32_t n){
    CHECK(!itf && bytes && n<=fifo_free && owner.writer_active && depth);
    CHECK(actor==owner.epoch && !owner.clock64.failed && !lifecycle);
    mark('w');fifo_free-=n;++fifo_calls;return n;
}
uint32_t tud_cdc_n_write_flush(uint8_t itf){CHECK(!itf);mark('f');++flush_calls;return 0;}
bool tud_cdc_n_write_clear(uint8_t itf){CHECK(!itf);mark('z');++clear_calls;return true;}
void mt_adc_dma_invalidate_stream_history(mt_adc_dma_t *d,mt_adc_dma_fault_t f){mark('i');d->stream_history_valid=false;if(!d->first_fault)d->first_fault=f;}
void mt_live_device_transport_lost(mt_live_device *d){
    mark('l');++lost_calls;owner.adc.owns_peripherals=false;owner.adc.state=MT_ADC_DMA_STOPPED;
    d->hardware_off=1;d->state=MT_LIVE_NEEDS_HELLO;d->tx_length=0;
}
int mt_live_adc_service(mt_live_adc *a){CHECK(a==&owner.acquisition);mark('a');++adc_calls;return adc_argument?-2:1;}
int mt_live_device_receive(mt_live_device *d,const uint8_t *b,size_t n){
    CHECK(d==&owner.device && n==1 && actor==owner.epoch);mark('r');++core_rx;rx_done=1;
    if(*b==5){d->stop_seen=1;d->state=MT_LIVE_DRAINING;prepared_form=FORM_SHORT;}
    else {CHECK(*b==1);d->state=MT_LIVE_HELLO_PENDING;d->pending_nonce=99;prepared_form=FORM_CONTROL;}
    return 1;
}
static int stable(mt_live_runtime *r);
static int usable(mt_live_runtime *r);
static int quiescent(const mt_live_runtime *r);
static mt_live_runtime_result time_fault(mt_live_runtime *r);
static mt_live_runtime_result loss_result(const mt_live_runtime *r);
static int synchronize_loss(mt_live_runtime *r);
static size_t live_write(void *context,const uint8_t *bytes,size_t length);
mt_live_prepare_result mt_live_device_prepare_tx(mt_live_device *d,mt_live_tx_ticket *t){
    unsigned form=prepared_form;CHECK(d==&owner.device && !depth && !actor);
    mark('p');++prepare_calls;prepare_time_call=time_calls;
    memset(t,0,sizeof *t);
    if(form==FORM_EMPTY)t->result=MT_LIVE_TX_EMPTY;
    else if(form==FORM_ERROR){t->result=MT_LIVE_TX_ERROR;t->error=MT_LIVE_ERR_ARGUMENT;}
    else {
        t->result=MT_LIVE_TX_PREPARED;
        if(!d->tx_length){
            d->tx_type=form==FORM_CONTROL?129:152;d->tx_mode=d->mode;
            d->tx_revision=d->revision;d->tx_nonce=d->nonce;d->tx_offset=0;
            d->tx_count=form==FORM_SHORT?512:d->mode==5?1024:128;
            d->tx_length=form==FORM_CONTROL?46:d->mode==5?(form==FORM_SHORT?692:1335):307;
            d->batch.phase=MT_BATCH1024_READY;d->batch.count=d->tx_count;
            d->batch.length=(uint16_t)d->tx_length;d->queue.used=0;
        }
    }
    t->state=d->state;t->mode=d->mode;t->tx_mode=d->tx_mode;t->revision=d->revision;
    t->tx_revision=d->tx_revision;t->nonce=d->nonce;t->generation=d->generation;
    t->tx_type=d->tx_type;t->tx_offset=d->tx_offset;t->tx_length=d->tx_length;
    t->tx_count=d->tx_count;t->batch=d->batch;
    if(form==FORM_BAD_TICKET)t->batch.length--;
    inject(inject_prepare);return t->result;
}
int mt_live_device_step_prepared(mt_live_device *d,const mt_live_tx_ticket *t){
    CHECK(d==&owner.device && t && depth);mark('x');++tx_calls;
    CHECK(!owner.clock64.failed && !lifecycle && owner.epoch==epoch.current && owner.soft_serial==epoch.soft_serial);
    if(t->result==MT_LIVE_TX_ERROR){CHECK(t->error==MT_LIVE_ERR_ARGUMENT);return 0;}
    if(t->result==MT_LIVE_TX_EMPTY)return 1;
    CHECK(t->state==d->state && t->nonce==d->nonce && t->tx_length==d->tx_length && t->tx_offset==d->tx_offset);
    if(t->tx_type==152){
        uint8_t bytes[384]={0};size_t n=d->tx_length-d->tx_offset;if(n>sizeof bytes)n=sizeof bytes;
        accepted=live_write(&owner,bytes,n);
        if(accepted && accepted!=SIZE_MAX)d->tx_offset+=accepted;
    }
    return 1;
}
/* BODIES */

static void setup(void){
    memset(&owner,0,sizeof owner);memset(&clock_source,0,sizeof clock_source);
    memset(&epoch,0,sizeof epoch);memset(trace,0,sizeof trace);
    traced=depth=actor=time_calls=pending_time=healthy_late=decline_health=declined_health=0;
    adc_calls=task_calls=rx_reads=core_rx=prepare_calls=tx_calls=0;
    fifo_calls=flush_calls=cleaned_calls=lost_calls=clear_calls=0;
    grant_calls=grant_allow=grant_actor=grant_unlock_armed=0;grant_result=1;
    task_pending=completed_events=adc_argument=lifecycle=0;ready=1;
    pending_command=rx_done=deny_late_scope=late_scope_denied=0;
    inject_prepare=inject_grant=inject_late_enter=0;prepared_form=FORM_NORMAL;
    prepare_time_call=grant_time_call=grant_rx_reads=0;fifo_free=384;accepted=SIZE_MAX;
    epoch.current=epoch.processed_reset=epoch.cleaned=epoch.configured=3;
    owner.initialized=owner.open=owner.require_dtr=1;owner.epoch=3;
    owner.clock=&clock_source;clock_source.state=MT_TIMEBASE_RUNNING;
    owner.adc.state=MT_ADC_DMA_RUNNING;owner.adc.owns_peripherals=true;owner.adc.stream_history_valid=true;
    owner.device.state=MT_LIVE_STREAMING;owner.device.mode=5;owner.device.revision=3;
    owner.device.nonce=503;owner.device.generation=3;
    owner.device.batch.phase=MT_BATCH1024_COLLECT;owner.device.batch.count=512;
    owner.device.queue.used=4;
    for(unsigned i=0;i<8;i++)owner.device.queue.counts[i]=128;
}
static unsigned pos(char c){char *p=strchr(trace,c);CHECK(p);return (unsigned)(p-trace);}
static void settled(void){CHECK(!depth && !actor && !owner.in_step && !owner.writer_active);}
static void early(void){
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(grant_calls==1 && pos('a')<pos('g') && pos('g')<pos('q') && pos('g')<pos('p'));settled();
}
static void order_and_selection(void){
    unsigned mode;
    setup();CHECK(defer_data_grant(&owner));CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(grant_calls==1 && grant_actor==3 && grant_allow && fifo_calls==1 && accepted==384);
    CHECK(pos('a')<pos('q') && pos('q')<pos('p') && pos('p')<pos('g') && pos('g')<pos('x'));
    CHECK(grant_time_call>prepare_time_call && time_calls>grant_time_call);settled();
    for(mode=1;mode<=4;mode++){setup();owner.device.mode=(uint16_t)mode;CHECK(!defer_data_grant(&owner));early();}
    setup();owner.device.tx_length=1335;owner.device.tx_type=152;owner.device.tx_count=1024;
    owner.device.tx_mode=5;owner.device.batch.phase=MT_BATCH1024_READY;owner.device.batch.count=1024;
    owner.device.batch.length=1335;CHECK(!defer_data_grant(&owner));early();
    setup();owner.device.queue.used=3;prepared_form=FORM_EMPTY;CHECK(!defer_data_grant(&owner));early();CHECK(!fifo_calls);
    setup();owner.device.want_caps=1;prepared_form=FORM_CONTROL;CHECK(!defer_data_grant(&owner));early();CHECK(!fifo_calls);
    setup();owner.device.batch.phase=MT_BATCH1024_EMPTY;owner.device.batch.count=0;
    owner.device.queue.used=8;CHECK(!defer_data_grant(&owner));
    setup();owner.device.batch.count=513;CHECK(!defer_data_grant(&owner));
    setup();owner.device.queue.used=9;CHECK(!defer_data_grant(&owner));
    setup();owner.device.queue.sealed=1;CHECK(!defer_data_grant(&owner));
    puts("PASS narrow hint; ordinary modes/cached/collect/control early; new full1024 prepare before one fresh deferred grant and guarded submit");
}
static void new_boundaries(void){
    const unsigned faults[]={INJECT_TIME,INJECT_EPOCH,INJECT_SOFT,INJECT_LIFECYCLE};
    unsigned i;
    for(i=0;i<sizeof faults/sizeof faults[0];i++){
        mt_live_runtime_result result;setup();inject_prepare=faults[i];result=mt_live_runtime_step(&owner);
        CHECK(result==(faults[i]==INJECT_TIME?MT_LIVE_RUNTIME_TIME_FAULT:MT_LIVE_RUNTIME_IDLE));
        CHECK(prepare_calls==1 && !grant_calls && !tx_calls && !fifo_calls && rx_reads==1);settled();
        if(faults[i]==INJECT_TIME)CHECK(owner.clock_fault && !owner.adc.stream_history_valid);
        setup();inject_grant=faults[i];result=mt_live_runtime_step(&owner);
        CHECK(result==(faults[i]==INJECT_TIME?MT_LIVE_RUNTIME_TIME_FAULT:MT_LIVE_RUNTIME_RECOVERY));
        CHECK(prepare_calls==1 && grant_calls==1 && !tx_calls && !fifo_calls && rx_reads==grant_rx_reads);settled();
    }
    setup();deny_late_scope=1;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);
    CHECK(late_scope_denied==1 && !grant_calls && !tx_calls && owner.device.tx_length==1335);settled();
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK && grant_calls==1 && fifo_calls==1);settled();
    setup();inject_prepare=INJECT_LIFECYCLE;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);
    CHECK(lifecycle && !grant_calls && !tx_calls && !fifo_calls);settled();
    /* Raw RESET/lifecycle is still pending, without a processed epoch change.
     * This pass used its deferred opportunity; the next pass must retain the
     * original fallback so the DCD can service lifecycle. allow_ctr is only
     * the runtime argument: the actual DCD independently checks raw flags. */
    {
        unsigned old_rx=rx_reads,old_prepare=prepare_calls;
        CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);
        CHECK(lifecycle && grant_calls==1 && !grant_actor);
        CHECK(rx_reads==old_rx && prepare_calls==old_prepare && !tx_calls && !fifo_calls);settled();
    }
    setup();inject_late_enter=INJECT_EPOCH;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(!grant_calls && !tx_calls && !fifo_calls && cleaned_calls==1);settled();
    /* Original early boundary still prevents old RX entirely. */
    setup();owner.device.mode=2;inject_grant=INJECT_EPOCH;pending_command=5;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(grant_calls==1 && !rx_reads && !core_rx && !prepare_calls && !tx_calls);settled();
    puts("PASS fresh TIME/epoch/soft/lifecycle before and after deferred IRQ boundary; scope refusal and actor restoration; no stale RX/TX or duplicate grant");
}
static void cancellation_denial_and_fallback(void){
    setup();pending_command=5;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);
    CHECK(core_rx==1 && owner.device.stop_seen && owner.device.tx_count==512 && grant_calls==1 && !tx_calls && !fifo_calls);
    CHECK(pos('r')<pos('p') && pos('p')<pos('g'));settled();
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK && grant_calls==2 && tx_calls==1 && fifo_calls==1);settled();
    setup();pending_command=1;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(core_rx==1 && owner.device.state==MT_LIVE_HELLO_PENDING && grant_calls==1 && tx_calls==1 && !fifo_calls);settled();
    setup();prepared_form=FORM_EMPTY;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(grant_calls==1 && tx_calls==1 && !fifo_calls);settled();
    setup();prepared_form=FORM_ERROR;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(grant_calls==1 && tx_calls==1 && !fifo_calls);settled();
    setup();prepared_form=FORM_BAD_TICKET;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);
    CHECK(grant_calls==1 && !tx_calls && !fifo_calls && owner.device.tx_length==1335);settled();
    setup();grant_result=0;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK && grant_calls==1);settled();
    setup();decline_health=1;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(declined_health==1 && !grant_calls);settled();
    setup();inject_prepare=INJECT_FINAL;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(grant_calls==1 && !grant_allow && task_pending);settled();
    setup();adc_argument=1;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_ARGUMENT);
    CHECK(adc_calls==1 && grant_calls==1 && !grant_actor && !rx_reads && !prepare_calls);settled();
    setup();ready=0;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);
    CHECK(!adc_calls && grant_calls==1 && !grant_actor);settled();
    setup();fifo_free=383;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);
    CHECK(grant_calls==1 && accepted==0 && !fifo_calls && !owner.device.tx_offset);settled();
    puts("PASS Stop/HELLO/EMPTY/ERROR cancellation; invalid DATA ticket cached; zero-space/false grant/health refusal consume attempt; prior early returns keep fallback");
}
int main(void){
    order_and_selection();new_boundaries();cancellation_denial_and_fallback();
    puts("PASS focused actual-runtime deferred grant model; logical boundary seams; hardware_executed=0; throughput_claim=0");return 0;
}
