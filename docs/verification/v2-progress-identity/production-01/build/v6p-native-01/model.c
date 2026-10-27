/* Actual observer with the exact ARM-generated identity header. USB/DWT and
 * legacy setup are synthetic native seams, not a physical runtime session. */
#include "mt_stream_progress.h"
#include "mt_stream_diag.h"
#include "mt_usb_ctr.h"
#include "transport/mt_usb_bridge.h"
#include "tusb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL binding line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
volatile mt_stream_diag_record mt_stream_diagnostics;
static mt_live_device device;
static uint32_t tick;
static unsigned locked,entered,try_late;
static const uint64_t nonce=UINT64_C(0x0123456789abcdef);

static unsigned phase(void){return mt_stream_progress.flags&MT_N_PHASE_MASK;}
static mt_stream_progress_record record(void){return mt_stream_progress;}
static void unchanged(const mt_stream_progress_record *saved){mt_stream_progress_record got=record();CHECK(!memcmp(saved,&got,sizeof got));}
uint32_t mt_progress_native_cycle(void){return tick;}
uint32_t mt_usb_bridge_lock(void){CHECK(!locked);locked=1;return 17;}
void mt_usb_bridge_unlock(uint32_t key){CHECK(key==17 && locked && !entered);locked=0;}
int mt_usb_bridge_app_enter(mt_usb_scope *s){
    CHECK(locked && !entered && phase()==MT_N_CLOSING);
    if(try_late){
        mt_stream_progress_record saved=record();
        CHECK(!mt_progress_prepare_begin());mt_progress_prepare_end(0);
        mt_progress_write_begin();mt_progress_zero_space();mt_progress_write_end(384,384);
        mt_progress_close(&device,MT_N_CLOSE_STOP,0);mt_progress_checkpoint(&device);
        unchanged(&saved);
    }
    s->previous=3;s->entered=1;entered=1;return 1;
}
void mt_usb_bridge_leave(mt_usb_scope *s){CHECK(locked && entered && s->entered && s->previous==3);s->entered=0;entered=0;}
uint32_t tud_cdc_n_write_available(uint8_t n){CHECK(!n && locked && entered);return 128;}
bool tud_task_event_ready(void){CHECK(locked && entered);return true;}
bool mt_usb_fsdev_irq_held(void){CHECK(locked && entered);return true;}
bool mt_usb_fsdev_ctr_deferred(void){CHECK(locked && entered);return true;}

static void setup(uint32_t build,uint32_t generation,uint64_t legacy_nonce){
    CHECK(!locked && !entered);mt_stream_progress=(mt_stream_progress_record){0};
    mt_stream_diagnostics=(mt_stream_diag_record){.magic=UINT32_C(0x4d544447),
        .version=1,.bytes=sizeof(mt_stream_diag_record),.firmware_build=build,
        .phase=2,.generation=generation,.nonce_low=(uint32_t)legacy_nonce,
        .nonce_high=(uint32_t)(legacy_nonce>>32)};
    memset(&device,0,sizeof device);device.io.firmware_build=MT_FIRMWARE_BUILD;
    device.generation=7;device.nonce=nonce;device.want_start=1;
    device.mode=device.tx_mode=5;device.state=MT_LIVE_STREAMING;
    device.tx_offset=384;device.tx_length=1335;device.batch.count=1024;
    device.batch.phase=MT_BATCH1024_READY;device.queue.used=8;
    tick=1000;try_late=0;
}
static void rejected(void){
    mt_stream_progress_record empty={0};
    mt_progress_begin(&device);CHECK(phase()==MT_N_EMPTY);unchanged(&empty);
    CHECK(!mt_progress_prepare_begin());mt_progress_prepare_end(1);
    mt_progress_write_begin();mt_progress_zero_space();mt_progress_write_end(384,384);
    tick=5000;mt_progress_close(&device,MT_N_CLOSE_QUEUE,1);mt_progress_checkpoint(&device);
    unchanged(&empty);CHECK(!locked && !entered);
}
static void binding_negatives(void){
    const uint32_t wrong[]={UINT32_C(0x56325347),UINT32_C(0x56325348),UINT32_C(0xf00db001)};
    CHECK(MT_FIRMWARE_BUILD==UINT32_C(0x56325349) && MT_N_BUILD==MT_FIRMWARE_BUILD);
    for(unsigned i=0;i<sizeof wrong/sizeof wrong[0];i++){
        CHECK(wrong[i]!=MT_FIRMWARE_BUILD);setup(wrong[i],7,nonce);rejected();
    }
    setup(MT_FIRMWARE_BUILD,8,nonce);rejected();
    setup(MT_FIRMWARE_BUILD,7,nonce+1);rejected();
    puts("PASS actual paired/bind rejects SG, SH, foreign build, generation and nonce mismatches; no default record or late writes");
}
static void save(const char *path,const void *data,size_t bytes){
    FILE *f=fopen(path,"wb");CHECK(f);CHECK(fwrite(data,1,bytes,f)==bytes);CHECK(!fclose(f));
}
static void correct_fixture(const char *progress_path,const char *legacy_path){
    uint32_t start;mt_stream_progress_record frozen;mt_stream_diag_record legacy;
    setup(MT_FIRMWARE_BUILD,7,nonce);mt_progress_begin(&device);
    CHECK(phase()==MT_N_ACTIVE && mt_stream_progress.magic==MT_N_MAGIC);
    CHECK(mt_stream_progress.begin_cycle==1000 && mt_stream_progress.generation==7);
    tick=1100;start=mt_progress_prepare_begin();tick=1500;mt_progress_prepare_end(start);
    tick=2000;mt_progress_write_begin();mt_progress_write_end(384,384);
    tick=2400;mt_progress_write_begin();mt_progress_write_end(17,17);
    tick=2600;mt_progress_write_begin();mt_progress_zero_space();mt_progress_write_end(384,0);
    tick=2800;mt_progress_write_begin();mt_progress_write_end(384,0);
    device.want_start=0;tick=5000;try_late=1;
    mt_progress_close(&device,MT_N_CLOSE_QUEUE,1);frozen=record();
    CHECK(phase()==MT_N_FROZEN && frozen.close_kind==MT_N_CLOSE_QUEUE);
    CHECK(frozen.flags==(MT_N_FROZEN|MT_N_HAVE_POSITIVE|MT_N_CORE_SNAPSHOT|(UINT32_C(1)<<16)));
    CHECK(frozen.prepare_cycles==400 && frozen.prepare_count==1);
    CHECK(frozen.positive_bytes==401 && frozen.positive_count==2);
    CHECK(frozen.zero_space_count==1 && frozen.zero_other_count==1);
    CHECK(frozen.last_positive_cycle==2400 && frozen.max_positive_gap_cycles==2600);
    CHECK(frozen.tx_offset==384 && frozen.tx_length==1335 && frozen.stage_count==1024);
    CHECK(frozen.stage_phase==MT_BATCH1024_READY && frozen.queue_used==8);
    CHECK(frozen.fifo_free==128 && frozen.snapshot_bits==15);
    tick=9999;mt_progress_begin(&device);mt_progress_prepare_end(1100);
    mt_progress_write_begin();mt_progress_zero_space();mt_progress_write_end(384,384);
    mt_progress_close(&device,MT_N_CLOSE_STOP,0);mt_progress_checkpoint(&device);unchanged(&frozen);
    CHECK(!locked && !entered);
    /* Explicit synthetic legacy setup, not execution of legacy136 module. */
    mt_stream_diagnostics.phase=3;mt_stream_diagnostics.flags=4;
    mt_stream_diagnostics.start_cycle=1000;mt_stream_diagnostics.last_cycle=5000;
    mt_stream_diagnostics.freeze_cycle=5000;mt_stream_diagnostics.first_acquisition_reason=1;
    mt_stream_diagnostics.final_core_state=7;mt_stream_diagnostics.final_hardware_off=1;
    legacy=mt_stream_diagnostics;
    CHECK(((const unsigned char*)&frozen.magic)[0]==0x31); /* This native witness is LE. */
    save(progress_path,&frozen,sizeof frozen);save(legacy_path,&legacy,sizeof legacy);
    puts("PASS exact SI generated identity reaches ACTIVE/FROZEN; known FIFO bytes and zero classes; CLOSING/FROZEN immutable; actual64 plus synthetic companion136 written");
}
static void partial_unknown(void){
    mt_stream_progress_record frozen;
    setup(MT_FIRMWARE_BUILD,7,nonce);mt_progress_begin(&device);
    tick=1200;mt_progress_write_begin();mt_progress_write_end(384,17);
    tick=1400;mt_progress_write_begin();mt_progress_write_end(384,SIZE_MAX);
    CHECK(mt_stream_progress.positive_bytes==17 && mt_stream_progress.positive_count==1);
    CHECK((mt_stream_progress.flags&(MT_N_PARTIAL_WRITE|MT_N_UNKNOWN_WRITE))==(MT_N_PARTIAL_WRITE|MT_N_UNKNOWN_WRITE));
    tick=1700;mt_progress_close(&device,MT_N_CLOSE_TRANSPORT,MT_LIVE_ERR_TRANSPORT);frozen=record();
    tick=1800;mt_progress_write_end(384,384);unchanged(&frozen);
    puts("PASS partial known acceptance counted once; unknown acceptance never fabricated as bytes; late positive cannot mutate first frozen cause");
}
int main(int argc,char **argv){
    binding_negatives();correct_fixture(argc>1?argv[1]:"actual-progress.bin",argc>2?argv[2]:"actual-legacy.bin");
    partial_unknown();printf("build=0x%08lx; record_bytes=%zu; legacy_bytes=%zu; synthetic_native=1; hardware_executed=0; throughput_claim=0\n",(unsigned long)MT_FIRMWARE_BUILD,sizeof(mt_stream_progress_record),sizeof(mt_stream_diag_record));
    return 0;
}
