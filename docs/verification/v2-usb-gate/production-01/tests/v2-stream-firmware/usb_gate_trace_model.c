/* One SK transition/freeze/working-read-order model. Actual N64/G24 C and
 * extracted DCD publishers/grant/timer/continuation bodies execute. Clock/USB
 * register storage, PMA transfer and legacy136 setup are synthetic seams. */
#include "platform/mt_stream_progress.h"
#include "platform/mt_stream_diag.h"
#include "platform/mt_usb_gate.h"
#include "transport/mt_usb_bridge.h"
#include "tusb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL gate line%d: %s\n",__LINE__,#x);exit(1);}}while(0)
volatile mt_stream_diag_record mt_stream_diagnostics;
static mt_live_device device;
static uint32_t stamp,depth,actor;
static unsigned refused,skew,held;
static uint32_t reads[64];static unsigned read_count;
uint32_t mt_progress_native_cycle(void) { return stamp; }
static void late_calls(void) {
    mt_gate_invalidate(1);mt_gate_submit_begin(0x82);
    mt_gate_submit_done(0x82,1,384,64,64,2,0);
    mt_gate_note(MT_G_HOLD_TIME,384,64,5,501,1);
}
uint32_t mt_usb_bridge_lock(void) {
    if(skew && (mt_stream_progress.flags&MT_N_PHASE_MASK)==MT_N_CLOSING) {
        mt_usb_gate_record before=mt_usb_gate;skew=0;held=0;late_calls();
        mt_usb_gate_record after=mt_usb_gate;CHECK(!memcmp(&before,&after,sizeof before));
    }
    return depth++;
}
void mt_usb_bridge_unlock(uint32_t p) { CHECK(depth>p);depth=p; }
int mt_usb_bridge_app_enter(mt_usb_scope*s) {
    if((mt_stream_progress.flags&MT_N_PHASE_MASK)==MT_N_CLOSING)
        CHECK((mt_usb_gate.flags&MT_G_PHASE_MASK)==MT_G_FROZEN);
    s->entered=0;if(refused)return 0;s->entered=1;s->previous=actor;actor=3;return 1;
}
void mt_usb_bridge_leave(mt_usb_scope*s) { CHECK(s->entered);actor=s->previous;s->entered=0; }
uint32_t tud_cdc_n_write_available(uint8_t n) { CHECK(!n);return 128; }
bool tud_task_event_ready(void) { return true; }
bool mt_usb_fsdev_irq_held(void) { return held!=0; }
bool mt_usb_fsdev_ctr_deferred(void) { return true; }

enum {U_ISTR_RESET=1u,U_ISTR_PMAOVR=2u,U_ISTR_SUSP=4u,U_ISTR_WKUP=8u,
 U_ISTR_ERR=16u,U_ISTR_DIR=32u,U_CNTR_FRES=1u,U_CNTR_PDWN=2u,
 U_CNTR_FSUSP=4u,U_CNTR_CTRM=8u,U_DADDR_EF=128u};
typedef uint32_t fsdev_bus_t;
typedef struct {volatile uint32_t ISTR,CNTR,DADDR;} fake_usb;
static fake_usb usb;
static fake_usb*read_usb(void){CHECK(read_count<64);reads[read_count++]=0x40005c00u;return &usb;}
#define FSDEV_REG read_usb()
static uint16_t mt_tx_burst_counter;
static unsigned mt_tx_burst_left;
static bool mt_ctr_deferred,mt_irq_held;
static unsigned bad_timer,enabled;
static uint16_t counter;
static uint32_t mt_tx_timer_read(uint32_t address) {
    CHECK(read_count<64);reads[read_count++]=address;
    switch(address){case 0x4002101cu:return 1;case 0x40021010u:return 0;
    case 0x40000000u:return 1;case 0x40000028u:return bad_timer?70:71;
    case 0x4000002cu:return 65535;case 0x40000024u:return counter;default:CHECK(0);return 0;}
}
static void fsdev_int_enable(unsigned n) { CHECK(!n && depth);++enabled; }
bool mt_usb_fsdev_lifecycle_pending(void) {
    return (FSDEV_REG->ISTR&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP))!=0;
}
typedef struct {uint8_t*buffer;tu_fifo_t*ff;uint16_t total_len,queued_len,max_packet_size;} xfer_ctl_t;
typedef unsigned tusb_dir_t;
static xfer_ctl_t xfer;static unsigned submit_success;
static unsigned tu_edpt_number(unsigned ep){return ep&15u;}
static unsigned tu_edpt_dir(unsigned ep){return ep>>7;}
static xfer_ctl_t*xfer_ctl_ptr(unsigned n,unsigned dir){CHECK(n==2 && dir==1);return &xfer;}
static bool edpt_xfer(uint8_t rh,unsigned n,unsigned dir){
    CHECK(!rh && n==2 && dir==1 && depth);
    xfer.queued_len=xfer.total_len<64?xfer.total_len:64;return submit_success!=0;
}
/* DCD_BODIES */
/* OLD_CONTINUATION */
enum {U_EP_T_FIELD=0x600u,U_EP_BULK=0u,U_EP_CTR_RX=0x8000u,U_EP_SETUP=0x800u};
static unsigned metadata_decision(unsigned mixed,unsigned backing_mutation,unsigned zero) {
    static uint8_t other[64];
    const uint32_t ep_reg=2u|(mixed?U_EP_CTR_RX:0u);
    const uint8_t ep_num=2u;
    xfer_ctl_t*mt_xfer=&xfer;
    xfer.queued_len=zero?0:384;
    const uint16_t mt_queued=xfer.queued_len,mt_total=xfer.total_len;
    uint8_t*const mt_buffer=xfer.buffer;const void*const mt_fifo=xfer.ff;
    bool gate_seen=false,gate_meta=false;
    unsigned gate_total=65535,gate_queued=65535,gate_initial=MT_G_HOLD_OTHER;
    /* ACTUAL_METADATA_PRE */
    if(backing_mutation)mt_xfer->buffer=other;
    const uint32_t mt_remaining=(uint16_t)(mt_total-mt_queued);
    const uint16_t mt_next=(uint16_t)((uint32_t)mt_queued+(mt_remaining<64u?mt_remaining:64u));
    /* ACTUAL_METADATA_POST */
    CHECK(gate_seen && gate_total==mt_total && gate_queued==mt_queued);
    unsigned decision=0,age=UINT32_MAX;
    CHECK(!mt_gate_continue(&decision,&age,gate_initial,false,5,0));
    mt_gate_note(decision,gate_total,gate_queued,5,age,gate_meta);
    return mt_usb_gate.decision;
}

static void setup(void) {
    device=(mt_live_device){.nonce=UINT64_C(0x0123456789abcdef),.generation=7,.want_start=1};
    mt_stream_progress=(mt_stream_progress_record){0};mt_usb_gate=(mt_usb_gate_record){0};
    mt_stream_diagnostics=(mt_stream_diag_record){.magic=UINT32_C(0x4d544447),.version=1,.bytes=136,
        .firmware_build=MT_FIRMWARE_BUILD,.phase=2,.generation=7,
        .nonce_low=UINT32_C(0x89abcdef),.nonce_high=UINT32_C(0x01234567)};
    stamp=1000;depth=actor=refused=skew=0;held=1;
    usb=(fake_usb){.DADDR=128};counter=501;mt_tx_burst_counter=0;mt_tx_burst_left=6;
    bad_timer=read_count=enabled=0;submit_success=1;xfer=(xfer_ctl_t){.max_packet_size=64};
    mt_progress_begin(&device);
    CHECK(MT_FIRMWARE_BUILD==UINT32_C(0x5632534b));
    CHECK((mt_stream_progress.flags&MT_N_PHASE_MASK)==MT_N_ACTIVE);
    CHECK(mt_usb_gate.magic==MT_G_MAGIC && mt_usb_gate.flags==(MT_G_LIVE|MT_G_UNOBSERVED_INITIAL));
    CHECK(!mt_usb_gate.publication_serial && !mt_usb_gate.event_cycle &&
          mt_usb_gate.total==65535 && mt_usb_gate.queued==65535 && mt_usb_gate.age==65535 && mt_usb_gate.budget==255);
}
static void publish(unsigned n,unsigned fifo) {
    static uint8_t storage[384];static tu_fifo_t ff;
    uint32_t key=mt_usb_bridge_lock();
    CHECK(fifo?dcd_edpt_xfer_fifo(0,0x82,&ff,(uint16_t)n,false):
               dcd_edpt_xfer(0,0x82,n?storage:NULL,(uint16_t)n,false));
    mt_usb_bridge_unlock(key);
}
static void note(unsigned decision,unsigned total,unsigned queued,unsigned left,unsigned age,unsigned valid) {
    uint32_t key=mt_usb_bridge_lock();mt_gate_note(decision,total,queued,left,age,valid);mt_usb_bridge_unlock(key);
}
static void close_trace(unsigned reason) { mt_progress_close(&device,reason,reason==MT_N_CLOSE_QUEUE?1:0); }
static void save(const char*p,const volatile void*data,size_t size) {
    FILE*f=fopen(p,"wb");CHECK(f);CHECK(fwrite((const void*)data,1,size,f)==size);CHECK(!fclose(f));
}
static void fixture_and_lifecycle(const char*gate_path,const char*progress_path,const char*legacy_path) {
    setup();stamp=1100;uint32_t token=mt_progress_prepare_begin();stamp=1500;mt_progress_prepare_end(token);
    stamp=1600;mt_progress_write_begin();mt_progress_write_end(100,100);
    stamp=2400;mt_progress_write_begin();mt_progress_write_end(301,301);
    mt_progress_write_begin();mt_progress_zero_space();mt_progress_write_end(384,0);
    mt_progress_write_begin();mt_progress_write_end(384,0);
    stamp=2600;publish(384,1);stamp=3000;note(MT_G_HOLD_TIME,384,64,5,501,1);
    CHECK(mt_usb_gate.publication_serial==1 && mt_usb_gate.event_cycle==3000 && mt_usb_gate.decision==MT_G_HOLD_TIME);
    CHECK((mt_usb_gate.flags&(MT_G_APPLICABLE|MT_G_TRANSFER_ACTIVE|MT_G_AGE_VALID))==(MT_G_APPLICABLE|MT_G_TRANSFER_ACTIVE|MT_G_AGE_VALID));
    device.want_start=0;device.tx_offset=384;device.tx_length=1335;device.batch.count=1024;
    device.batch.phase=MT_BATCH1024_READY;device.queue.used=8;stamp=5000;close_trace(MT_N_CLOSE_QUEUE);
    mt_stream_diagnostics.phase=3;
    CHECK((mt_usb_gate.flags&MT_G_PHASE_MASK)==MT_G_FROZEN && mt_usb_gate.flags==63);
    CHECK(mt_stream_progress.prepare_count==1 && mt_stream_progress.prepare_cycles==400 &&
        mt_stream_progress.positive_bytes==401 && mt_stream_progress.positive_count==2 &&
        mt_stream_progress.last_positive_cycle==2400 && mt_stream_progress.max_positive_gap_cycles==2600);
    save(gate_path,&mt_usb_gate,24);save(progress_path,&mt_stream_progress,64);save(legacy_path,&mt_stream_diagnostics,136);
    mt_usb_gate_record frozen=mt_usb_gate;mt_stream_progress_record n=mt_stream_progress;
    late_calls();mt_gate_begin();mt_gate_freeze();mt_progress_prepare_end(token);mt_progress_checkpoint(&device);
    mt_usb_gate_record after=mt_usb_gate;mt_stream_progress_record na=mt_stream_progress;
    CHECK(!memcmp(&frozen,&after,24) && !memcmp(&n,&na,64));
    setup();note(MT_G_HOLD_FINAL,0,0,5,UINT32_MAX,1);CHECK(!mt_usb_gate.publication_serial && !mt_usb_gate.event_cycle);
    close_trace(MT_N_CLOSE_QUEUE);CHECK(mt_usb_gate.decision==MT_G_UNKNOWN && mt_usb_gate.budget==255);
    setup();publish(384,1);note(MT_G_HOLD_TIME,384,64,5,65535,1);CHECK(mt_usb_gate.age==65535 && (mt_usb_gate.flags&MT_G_AGE_VALID));
    uint32_t cookie=mt_usb_gate.publication_serial,cycle=mt_usb_gate.event_cycle;
    uint32_t key=mt_usb_bridge_lock();CHECK(mt_usb_fsdev_irq_grant(true));mt_usb_bridge_unlock(key);
    CHECK(!(mt_usb_gate.flags&MT_G_APPLICABLE) && mt_usb_gate.age==65535 && mt_usb_gate.event_cycle==cycle);
    submit_success=0;key=mt_usb_bridge_lock();CHECK(!dcd_edpt_xfer(0,0x82,NULL,0,false));mt_usb_bridge_unlock(key);
    CHECK(mt_usb_gate.publication_serial==cookie && !(mt_usb_gate.flags&(MT_G_APPLICABLE|MT_G_TRANSFER_ACTIVE)));
    submit_success=1;publish(183,1);CHECK(mt_usb_gate.publication_serial==cookie+1 && mt_usb_gate.queued==64 && mt_usb_gate.age==65535 && !(mt_usb_gate.flags&MT_G_AGE_VALID));
    setup();publish(0,0);CHECK((mt_usb_gate.flags&MT_G_ZLP) && mt_usb_gate.total==0);note(MT_G_HOLD_FINAL,0,0,0,UINT32_MAX,1);
    CHECK(!(mt_usb_gate.flags&MT_G_TRANSFER_ACTIVE) && (mt_usb_gate.flags&MT_G_APPLICABLE));
    publish(0,1);CHECK(mt_usb_gate.publication_serial==2 && (mt_usb_gate.flags&MT_G_TRANSFER_ACTIVE));
    note(MT_G_HOLD_OTHER,0,0,5,UINT32_MAX,1);CHECK(mt_usb_gate.decision==MT_G_HOLD_OTHER && !(mt_usb_gate.flags&MT_G_METADATA_INVALID));
    setup();publish(384,1);note(MT_G_HOLD_OTHER,384,64,5,UINT32_MAX,0);CHECK(mt_usb_gate.flags&MT_G_METADATA_INVALID);
    frozen=mt_usb_gate;publish(384,1);after=mt_usb_gate;CHECK(!memcmp(&frozen,&after,24));
    setup();publish(384,1);mt_usb_gate.publication_serial=UINT32_MAX;publish(384,1);
    CHECK(mt_usb_gate.flags&MT_G_SERIAL_SATURATED);CHECK(mt_usb_gate.publication_serial==UINT32_MAX);
    CHECK(!(mt_usb_gate.flags&(MT_G_APPLICABLE|MT_G_TRANSFER_ACTIVE)));
    setup();publish(384,1);CHECK(metadata_decision(0,0,0)==MT_G_HOLD_FINAL);
    CHECK(!(mt_usb_gate.flags&MT_G_TRANSFER_ACTIVE));
    setup();publish(384,1);CHECK(metadata_decision(1,0,0)==MT_G_HOLD_OTHER);
    CHECK(!(mt_usb_gate.flags&MT_G_METADATA_INVALID));
    setup();publish(384,1);CHECK(metadata_decision(0,1,0)==MT_G_HOLD_OTHER);
    CHECK(mt_usb_gate.flags&MT_G_METADATA_INVALID);
    setup();publish(0,0);CHECK(metadata_decision(0,0,1)==MT_G_HOLD_FINAL);
    setup();publish(0,1);CHECK(metadata_decision(0,0,1)==MT_G_HOLD_FINAL);
    puts("PASS actual SK publishers/N64 binding/24B lifecycle: first unknown, sentinel/modulo-age, new serial, failed submit, ZLP/final/mixed/metadata/saturation; frozen24/64 immutable; C fixtures written");
}
static void read_order(void) {
    for(unsigned variant=0;variant<13;variant++) {
        setup();unsigned can=1,left=5,status=0;counter=499;mt_tx_burst_counter=0;
        if(variant==1)can=0;if(variant==2)left=0;if(variant==3)status=U_ISTR_RESET;
        if(variant==4)usb.ISTR=U_ISTR_DIR;if(variant==5)usb.ISTR=U_ISTR_SUSP;
        if(variant==6)bad_timer=1;if(variant==7)counter=500;
        if(variant==8)usb.CNTR=U_CNTR_FSUSP;if(variant==9)usb.DADDR=0;
        if(variant==10){mt_tx_burst_counter=65530;counter=493;}
        if(variant==11){mt_tx_burst_counter=65530;counter=494;}
        if(variant==12)counter=65535;
        uint32_t old_reads[64];read_count=0;bool old=se_continue(can,left,status);
        unsigned count=read_count;memcpy(old_reads,reads,count*sizeof *reads);
        read_count=0;unsigned decision=0,age=UINT32_MAX;
        bool current=mt_gate_continue(&decision,&age,MT_G_HOLD_FINAL,can,left,status);
        CHECK(current==old && read_count==count && !memcmp(old_reads,reads,count*sizeof *reads));
        if(current)decision=MT_G_RESUMED;
        if(variant==1)CHECK(decision==MT_G_HOLD_FINAL && age==UINT32_MAX && !read_count);
        if(variant==2)CHECK(decision==MT_G_HOLD_BUDGET && age==UINT32_MAX && !read_count);
        if(variant==6)CHECK(decision==MT_G_TIMER_UNAVAILABLE && age==UINT32_MAX);
        if(variant==7 || variant==11 || variant==12)CHECK(decision==MT_G_HOLD_TIME && age>=500);
        if(variant==0 || variant==10)CHECK(current && age==499);
        if(variant==8 || variant==9)CHECK(decision==MT_G_HOLD_LIFECYCLE && age==499);
        CHECK(decision && decision<=MT_G_HOLD_STATUS);
    }
    puts("PASS extracted exact DCD continuation vs frozen SJ expression: same BOOL and register-read trace for early false, all later guards, ready failure,499/500/wrap65535; no downstream TIME fabrication");
}
static void close_boundaries(void) {
    setup();publish(384,1);note(MT_G_HOLD_BUDGET,384,64,0,UINT32_MAX,1);
    mt_usb_gate_record before=mt_usb_gate;uint32_t key=mt_usb_bridge_lock();mt_gate_invalidate(0);mt_usb_bridge_unlock(key);
    CHECK(mt_usb_gate.event_cycle==before.event_cycle && mt_usb_gate.decision==before.decision && !(mt_usb_gate.flags&MT_G_APPLICABLE));
    note(MT_G_HOLD_TIME,384,64,5,500,1);refused=1;close_trace(MT_N_CLOSE_QUEUE);
    CHECK((mt_usb_gate.flags&MT_G_PHASE_MASK)==MT_G_FROZEN && !(mt_stream_progress.snapshot_bits&MT_N_USB_VALID));
    setup();publish(384,1);note(MT_G_HOLD_TIME,384,64,5,500,1);skew=1;close_trace(MT_N_CLOSE_QUEUE);
    CHECK((mt_usb_gate.flags&MT_G_APPLICABLE) && (mt_stream_progress.snapshot_bits&MT_N_USB_VALID) && !(mt_stream_progress.snapshot_bits&MT_N_USB_HELD));
    setup();publish(384,1);mt_gate_invalidate(1);before=mt_usb_gate;publish(384,1);
    mt_usb_gate_record after=mt_usb_gate;CHECK(!memcmp(&before,&after,24));CHECK(mt_usb_gate.flags&MT_G_LIFECYCLE_INVALID);
    setup();publish(384,1);note(MT_G_HOLD_TIME,384,64,5,500,1);stamp=1000+MT_N_CAP_CYCLES;mt_progress_checkpoint(&device);
    CHECK(mt_usb_gate.flags&MT_G_CAP);CHECK((mt_usb_gate.flags&MT_G_PHASE_MASK)==MT_G_FROZEN);
    before=mt_usb_gate;mt_progress_close(&device,MT_N_CLOSE_QUEUE,1);late_calls();after=mt_usb_gate;CHECK(!memcmp(&before,&after,24));
    setup();mt_stream_progress=(mt_stream_progress_record){0};mt_usb_gate=(mt_usb_gate_record){0};
    mt_stream_diagnostics.flags=16;mt_progress_begin(&device);
    CHECK((mt_stream_progress.flags&MT_N_NO_ACTIVE_START) && (mt_usb_gate.flags&MT_G_NO_ACTIVE));
    CHECK(mt_usb_gate.publication_serial==0 && mt_usb_gate.event_cycle==0 && mt_usb_gate.total==65535 && mt_usb_gate.queued==65535 && mt_usb_gate.age==65535 && mt_usb_gate.budget==255);
    setup();mt_stream_progress=(mt_stream_progress_record){0};mt_usb_gate=(mt_usb_gate_record){0};mt_stream_diagnostics.firmware_build=0x5632534a;
    mt_progress_begin(&device);CHECK(!mt_stream_progress.magic && !mt_usb_gate.magic);
    CHECK(!depth && !actor);
    puts("PASS actual first-close under existing snapshot guard even refused scope; late ISR/FG suppressed,24/64 skew retained, lifecycle invalidity/CAP/noactive and old-build rejection explicit");
}
int main(int argc,char**argv) {
    CHECK(argc==4);fixture_and_lifecycle(argv[1],argv[2],argv[3]);read_order();close_boundaries();
    printf("build=0x%08lx;static_gate_bytes=%lu;hardware_executed=0;throughput_claim=0\n",(unsigned long)MT_FIRMWARE_BUILD,(unsigned long)sizeof(mt_usb_gate_record));return 0;
}
