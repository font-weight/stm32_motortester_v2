/* Actual64-byte progress module with synthetic cycles and read-only USB seams.
 * Runner inserts actual offer/fail bodies; the cleanup stubs prove ordering,
 * not physical timing, USB delivery, IRQ exclusion or ADC correctness. */
#include "mt_stream_progress.h"
#include "mt_stream_diag.h"
#include "mt_usb_ctr.h"
#include "adc_timer_dma.h"
#include "transport/mt_usb_bridge.h"
#include "tusb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
volatile mt_stream_diag_record mt_stream_diagnostics;
static mt_live_device device;
static uint32_t clock_value,usb_free;
static unsigned usb_allowed,usb_held,usb_deferred,usb_pending,locked,entered;
static unsigned terminate_calls,quiesce_calls,late_in_snapshot;
static uint32_t open_prepare;
static mt_sample_queue_result queue_result;
static const uint64_t nonce=UINT64_C(0x0123456789abcdef);

static unsigned phase(void){return mt_stream_progress.flags&MT_N_PHASE_MASK;}
static unsigned primary(void){return mt_stream_progress.flags>>MT_N_PRIMARY_SHIFT;}
static mt_stream_progress_record copy_record(void){return mt_stream_progress;}
static void equal_record(const mt_stream_progress_record *expected){
    mt_stream_progress_record got=copy_record();CHECK(!memcmp(expected,&got,sizeof got));
}
uint32_t mt_progress_native_cycle(void){return clock_value;}
uint32_t mt_usb_bridge_lock(void){CHECK(!locked);locked=1;return UINT32_C(0x12345678);}
void mt_usb_bridge_unlock(uint32_t previous){CHECK(locked && !entered && previous==UINT32_C(0x12345678));locked=0;}
int mt_usb_bridge_app_enter(mt_usb_scope *scope){
    CHECK(locked && !entered && phase()==MT_N_CLOSING);
    if(late_in_snapshot){
        mt_stream_progress_record saved=copy_record();
        /* Actual module must reject epilogues immediately at CLOSING, before
         * USB snapshot publication has finished and FROZEN is visible. */
        mt_progress_prepare_end(open_prepare);mt_progress_write_begin();
        mt_progress_zero_space();mt_progress_write_end(384,384);
        mt_progress_close(&device,MT_N_CLOSE_STOP,0);mt_progress_checkpoint(&device);
        equal_record(&saved);
    }
    if(!usb_allowed)return 0;
    scope->previous=17;scope->entered=1;entered=1;return 1;
}
void mt_usb_bridge_leave(mt_usb_scope *scope){CHECK(locked && entered && scope->entered && scope->previous==17);scope->entered=0;entered=0;}
uint32_t tud_cdc_n_write_available(uint8_t index){CHECK(!index && locked && entered);return usb_free;}
bool tud_task_event_ready(void){CHECK(locked && entered);return usb_pending!=0;}
bool mt_usb_fsdev_irq_held(void){CHECK(locked && entered);return usb_held!=0;}
bool mt_usb_fsdev_ctr_deferred(void){CHECK(locked && entered);return usb_deferred!=0;}

/* Minimal environment for the extracted actual core offer and ADC fail. */
static int now(mt_live_device *d,uint64_t *value){CHECK(d==&device);*value=5;return 1;}
static int expire(mt_live_device *d,uint64_t value){CHECK(d==&device && value==5);return 1;}
static unsigned discarded_lsb(const mt_live_device *d){CHECK(d==&device);return 2;}
mt_sample_queue_result mt_sample_queue_push_quantized(mt_sample_queue *q,uint64_t first,
    const uint16_t *samples,uint16_t count,unsigned final,unsigned discarded){
    CHECK(q==&device.queue && first==8192 && samples && count==128 && !final && discarded==2);
    CHECK(phase()==MT_N_ACTIVE);q->first_fault=queue_result;q->sealed=1;return queue_result;
}
static void terminate(mt_live_device *d,uint16_t reason,uint64_t value){
    CHECK(d==&device && reason==1 && value==5 && phase()==MT_N_FROZEN);
    CHECK(mt_stream_progress.close_kind==MT_N_CLOSE_QUEUE && primary()==1);
    CHECK(mt_stream_progress.queue_used==8 && mt_stream_progress.tx_offset==384);
    ++terminate_calls;d->queue.used=0;d->tx_offset=d->tx_length=0;
    d->batch.count=0;d->batch.phase=MT_BATCH1024_EMPTY;
}
static void invalidate_history(mt_adc_dma_t *d,mt_adc_dma_fault_t fault){
    CHECK(d->state==MT_ADC_DMA_FAULTED && d->fault==fault);
    d->stream_history_valid=false;d->first_fault=fault;
}
static bool quiesce(mt_adc_dma_t *d){
    CHECK(phase()==MT_N_FROZEN && mt_stream_progress.close_kind==MT_N_CLOSE_ADC);
    CHECK(primary()==(unsigned)d->fault);++quiesce_calls;
    return false; /* Cleanup's later STOP fault must not replace the cause. */
}

int mt_live_device_offer(mt_live_device *d,uint64_t first_index,const uint16_t *codes,uint16_t count) {
    uint64_t n; mt_sample_queue_result q;
    if(!d || !now(d,&n) || !expire(d,n))return 0;
    if(d->state!=MT_LIVE_STARTING && d->state!=MT_LIVE_STREAMING)return 0;
    q=mt_sample_queue_push_quantized(&d->queue,first_index,codes,count,0,discarded_lsb(d));
    if(q!=MT_SAMPLE_QUEUE_OK) {
#if CFG_MT_PROGRESS_TRACE /* N_PROGRESS */
        mt_progress_close(d,q==MT_SAMPLE_QUEUE_FULL?MT_N_CLOSE_QUEUE:MT_N_CLOSE_SOURCE,q==MT_SAMPLE_QUEUE_FULL?1u:2u);
#endif
        terminate(d,q==MT_SAMPLE_QUEUE_FULL?1u:2u,n); return 0; }
    return 1;
}


static mt_adc_dma_result_t fail(mt_adc_dma_t *d, mt_adc_dma_fault_t fault)
{
    d->state = MT_ADC_DMA_FAULTED;
    d->fault = fault;
    if (d->stream_mode) invalidate_history(d, fault);
#if CFG_MT_PROGRESS_TRACE /* N_PROGRESS */
    mt_progress_close(NULL,MT_N_CLOSE_ADC,(unsigned)fault);
#endif
    if (!quiesce(d)) { d->fault = MT_ADC_DMA_FAULT_STOP; }
    return MT_ADC_DMA_ERROR;
}


static void reset(void){
    CHECK(!locked && !entered);
    mt_stream_progress=(mt_stream_progress_record){0};
    mt_stream_diagnostics=(mt_stream_diag_record){.firmware_build=MT_N_BUILD,
        .phase=2,.generation=7,.nonce_low=(uint32_t)nonce,.nonce_high=(uint32_t)(nonce>>32)};
    memset(&device,0,sizeof device);device.nonce=nonce;device.generation=7;
    device.state=MT_LIVE_STREAMING;device.tx_offset=384;device.tx_length=1335;
    device.batch.count=1024;device.batch.phase=MT_BATCH1024_READY;device.queue.used=8;
    clock_value=1000;usb_free=128;usb_allowed=1;usb_held=usb_deferred=usb_pending=1;
    terminate_calls=quiesce_calls=late_in_snapshot=0;open_prepare=0;queue_result=MT_SAMPLE_QUEUE_FULL;
}
static void begin(void){mt_progress_begin(&device);CHECK(phase()==MT_N_ACTIVE && mt_stream_progress.begin_cycle==clock_value);}
static void no_active_values(void){
    CHECK(mt_stream_progress.flags&MT_N_NO_ACTIVE_START);
    CHECK(!mt_stream_progress.begin_cycle && !mt_stream_progress.end_cycle &&
        !mt_stream_progress.prepare_cycles && !mt_stream_progress.prepare_count &&
        !mt_stream_progress.positive_bytes && !mt_stream_progress.positive_count &&
        !mt_stream_progress.last_positive_cycle && !mt_stream_progress.max_positive_gap_cycles &&
        !mt_stream_progress.zero_space_count && !mt_stream_progress.zero_other_count);
    CHECK(!(mt_stream_progress.flags&(MT_N_HAVE_POSITIVE|MT_N_PREPARE_OPEN|MT_N_PARTIAL_PREPARE)));
}
static void late_immutable(const mt_stream_progress_record *saved){
    clock_value+=100000;mt_progress_prepare_end(open_prepare);
    CHECK(mt_progress_prepare_begin()==0);mt_progress_write_begin();mt_progress_zero_space();
    mt_progress_write_end(384,384);mt_progress_write_end(384,SIZE_MAX);
    mt_progress_close(&device,MT_N_CLOSE_TRANSPORT,MT_LIVE_ERR_TRANSPORT);
    mt_progress_checkpoint(&device);mt_progress_begin(&device);equal_record(saved);
}
static void first_fault_fixture(const char *path){
    uint16_t samples[128]={0};FILE *out;mt_stream_progress_record frozen;
    reset();begin();CHECK(mt_stream_progress.flags&MT_N_START_ACK_PENDING);
    clock_value=1100;open_prepare=mt_progress_prepare_begin();
    clock_value=1500;mt_progress_prepare_end(open_prepare);
    clock_value=2000;mt_progress_write_begin();mt_progress_write_end(384,384);
    mt_progress_write_begin();mt_progress_zero_space();mt_progress_write_end(384,0);
    mt_progress_write_begin();mt_progress_write_end(384,0);
    clock_value=2400;mt_progress_write_begin();mt_progress_write_end(384,17);
    mt_progress_write_begin();mt_progress_write_end(384,SIZE_MAX);
    mt_progress_write_begin();mt_progress_write_end(8,9);
    clock_value=2600;open_prepare=mt_progress_prepare_begin();
    mt_progress_write_begin();mt_progress_zero_space(); /* frozen transient marker */
    late_in_snapshot=1;clock_value=5000;
    CHECK(mt_live_device_offer(&device,8192,samples,128)==0 && terminate_calls==1);
    frozen=copy_record();CHECK(phase()==MT_N_FROZEN && frozen.magic==MT_N_MAGIC);
    CHECK(frozen.generation==7 && frozen.nonce_low==(uint32_t)nonce && frozen.nonce_high==(uint32_t)(nonce>>32));
    CHECK(frozen.begin_cycle==1000 && frozen.end_cycle==5000 && frozen.prepare_cycles==400 && frozen.prepare_count==1);
    CHECK(frozen.positive_bytes==401 && frozen.positive_count==2 && frozen.last_positive_cycle==2400);
    CHECK(frozen.max_positive_gap_cycles==2600 && frozen.zero_space_count==1 && frozen.zero_other_count==1);
    CHECK((frozen.flags&(MT_N_HAVE_POSITIVE|MT_N_PARTIAL_WRITE|MT_N_UNKNOWN_WRITE|MT_N_PARTIAL_PREPARE|
        MT_N_PREPARE_OPEN|MT_N_WRITE_SPACE_MARK|MT_N_CORE_SNAPSHOT))==
        (MT_N_HAVE_POSITIVE|MT_N_PARTIAL_WRITE|MT_N_UNKNOWN_WRITE|MT_N_PARTIAL_PREPARE|
        MT_N_PREPARE_OPEN|MT_N_WRITE_SPACE_MARK|MT_N_CORE_SNAPSHOT));
    CHECK(!(frozen.flags&(MT_N_START_ACK_PENDING|MT_N_DWT_INVALID|MT_N_METADATA_INVALID|MT_N_SATURATED)));
    CHECK(frozen.tx_offset==384 && frozen.tx_length==1335 && frozen.stage_count==1024 && frozen.stage_phase==MT_BATCH1024_READY);
    CHECK(frozen.queue_used==8 && frozen.fifo_free==128 && frozen.snapshot_bits==15);
    usb_free=0;device.want_start=1;late_immutable(&frozen);
    /* Write the actual module's64-byte output, never a reconstructed fixture. */
    out=fopen(path,"wb");CHECK(out);CHECK(fwrite(&frozen,1,sizeof frozen,out)==sizeof frozen);CHECK(!fclose(out));
    puts("PASS actual OFFER freezes queue cause before cleanup; prepare/acceptance classes; inclusive gaps; immutable CLOSING/FROZEN; actual64B fixture");
}
static void gaps_cap_and_typed(void){
    mt_stream_progress_record frozen;mt_adc_dma_t adc;
    static const unsigned kinds[]={MT_N_CLOSE_SOURCE,MT_N_CLOSE_RECOVERY,MT_N_CLOSE_STOP,
        MT_N_CLOSE_TRANSPORT,MT_N_CLOSE_HELLO,MT_N_CLOSE_TIME};
    static const unsigned reasons[]={6,7,0,MT_LIVE_ERR_TRANSPORT,0,MT_LIVE_ERR_CLOCK};
    unsigned i;
    reset();begin();clock_value=1400;mt_progress_close(&device,MT_N_CLOSE_STOP,0);
    CHECK(!(mt_stream_progress.flags&MT_N_HAVE_POSITIVE) && mt_stream_progress.last_positive_cycle==1000);
    CHECK(mt_stream_progress.max_positive_gap_cycles==400);
    reset();clock_value=UINT32_C(0xfffffff0);begin();clock_value=8;
    mt_progress_write_begin();mt_progress_write_end(1,1);clock_value=40;
    mt_progress_close(&device,MT_N_CLOSE_STOP,0);CHECK(mt_stream_progress.max_positive_gap_cycles==32);
    reset();begin();clock_value=1000+MT_N_CAP_CYCLES-1;mt_progress_checkpoint(&device);CHECK(phase()==MT_N_ACTIVE);
    clock_value=1000+MT_N_CAP_CYCLES+19;mt_progress_checkpoint(&device);
    CHECK(phase()==MT_N_FROZEN && mt_stream_progress.close_kind==MT_N_CLOSE_CAP && primary()==0);
    CHECK(mt_stream_progress.flags&MT_N_CAP_OVERSHOOT);CHECK(mt_stream_progress.end_cycle==clock_value);
    frozen=copy_record();late_immutable(&frozen);
    for(i=0;i<sizeof kinds/sizeof kinds[0];i++){
        reset();begin();clock_value=1300;mt_progress_close(&device,kinds[i],reasons[i]);
        CHECK(phase()==MT_N_FROZEN && mt_stream_progress.close_kind==kinds[i] && primary()==reasons[i]);
    }
    reset();begin();memset(&adc,0,sizeof adc);adc.stream_mode=true;clock_value=1700;
    CHECK(fail(&adc,MT_ADC_DMA_FAULT_DEADLINE)==MT_ADC_DMA_ERROR && quiesce_calls==1);
    CHECK(primary()==MT_ADC_DMA_FAULT_DEADLINE && adc.fault==MT_ADC_DMA_FAULT_STOP);
    CHECK(!(mt_stream_progress.flags&MT_N_CORE_SNAPSHOT) && mt_stream_progress.tx_length==UINT16_MAX);
    CHECK(mt_stream_progress.queue_used==UINT8_MAX && mt_stream_progress.fifo_free==128);
    puts("PASS initial/no-positive and unfinished gaps; modulo cycles; cap with overshoot; typed first causes; actual ADC failure freezes before cleanup");
}
static void unavailable_and_saturation(void){
    uint32_t token;mt_stream_progress_record frozen;unsigned flag;
    reset();mt_stream_diagnostics.nonce_low^=1;mt_progress_begin(&device);CHECK(phase()==MT_N_EMPTY);
    reset();device.want_start=1;mt_progress_close(&device,MT_N_CLOSE_NO_START,0);
    CHECK(phase()==MT_N_FROZEN && mt_stream_progress.close_kind==MT_N_CLOSE_NO_START && primary()==0);no_active_values();
    reset();device.want_start=1;mt_progress_close(&device,MT_N_CLOSE_TIME,MT_LIVE_ERR_CLOCK);
    CHECK(mt_stream_progress.close_kind==MT_N_CLOSE_TIME && primary()==MT_LIVE_ERR_CLOCK);no_active_values();
    for(flag=1;flag<=16;flag*=16){
        reset();mt_stream_diagnostics.flags=flag;mt_progress_begin(&device);
        CHECK(phase()==MT_N_FROZEN && mt_stream_progress.close_kind==MT_N_CLOSE_UNAVAILABLE);
        CHECK(mt_stream_progress.flags&MT_N_DWT_INVALID);no_active_values();
    }
    reset();begin();mt_stream_diagnostics.flags=16;clock_value=1400;mt_progress_close(&device,MT_N_CLOSE_SOURCE,2);
    CHECK(mt_stream_progress.flags&MT_N_DWT_INVALID);
    reset();begin();usb_allowed=0;clock_value=1400;mt_progress_close(&device,MT_N_CLOSE_STOP,0);
    CHECK(!mt_stream_progress.snapshot_bits && mt_stream_progress.fifo_free==UINT16_MAX);
    CHECK(mt_stream_progress.flags&MT_N_CORE_SNAPSHOT);
    reset();begin();device.tx_offset=1336;usb_free=385;clock_value=1400;
    mt_progress_close(&device,MT_N_CLOSE_STOP,0);CHECK(mt_stream_progress.flags&MT_N_METADATA_INVALID);
    CHECK(!(mt_stream_progress.flags&MT_N_CORE_SNAPSHOT) && !mt_stream_progress.snapshot_bits);
    CHECK(mt_stream_progress.tx_offset==UINT16_MAX && mt_stream_progress.fifo_free==UINT16_MAX);
    reset();begin();mt_stream_progress.prepare_cycles=UINT32_MAX-2;mt_stream_progress.prepare_count=UINT16_MAX;
    clock_value=1100;token=mt_progress_prepare_begin();clock_value=1110;mt_progress_prepare_end(token);
    CHECK(mt_stream_progress.prepare_cycles==UINT32_MAX && mt_stream_progress.prepare_count==UINT16_MAX);
    mt_stream_progress.positive_bytes=UINT32_MAX-2;mt_stream_progress.positive_count=UINT16_MAX;
    mt_progress_write_begin();mt_progress_write_end(10,5);
    CHECK(mt_stream_progress.positive_bytes==UINT32_MAX && mt_stream_progress.positive_count==UINT16_MAX);
    mt_stream_progress.zero_space_count=mt_stream_progress.zero_other_count=UINT16_MAX;
    mt_progress_write_begin();mt_progress_zero_space();mt_progress_write_end(1,0);
    mt_progress_write_begin();mt_progress_write_end(1,0);
    CHECK(mt_stream_progress.zero_space_count==UINT16_MAX && mt_stream_progress.zero_other_count==UINT16_MAX);
    CHECK(mt_stream_progress.flags&MT_N_SATURATED);clock_value=1500;mt_progress_close(&device,MT_N_CLOSE_STOP,0);
    frozen=copy_record();late_immutable(&frozen);
    puts("PASS paired identity; no-active preserves typed cause; legacy clock invalidity; unavailable snapshot sentinels; saturating32/16 counters");
}
int main(int argc,char **argv){
    CHECK(sizeof(mt_stream_progress_record)==64 && sizeof(mt_stream_diag_record)==136);
    first_fault_fixture(argc>1?argv[1]:"actual-progress.bin");
    gaps_cap_and_typed();unavailable_and_saturation();
    puts("record_bytes=64; legacy_bytes=136; synthetic_cycles=1; hardware_executed=0; throughput_claim=0");
    return 0;
}
