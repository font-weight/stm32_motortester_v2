/* S: actual adapter/driver/core/queue/serializer/wire/N64/G24 and extracted
 * runtime. The register bus, elapsed TIME, USB/epoch and IRQ effects below
 * are explicit logical seams. Native cycles are NOT performance evidence.
 * Legacy136 is synthetic common-build setup, not execution of diag.c. */
#include "app/mt_live_runtime.h"
#include "platform/mt_stream_progress.h"
#include "platform/mt_usb_gate.h"
#include "platform/mt_stream_diag.h"
#include "platform/mt_usb_ctr.h"
#include "tusb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL postcopy line%d: %s trace=%s\n",__LINE__,#x,trace);exit(1);}}while(0)
#define D owner.device
#define A owner.adc
static mt_live_runtime owner;
static mt_timebase clock_source;
static mt_usb_epoch epoch;
volatile mt_stream_diag_record mt_stream_diagnostics;
static struct {uint32_t address,value;} registers[64];
static unsigned register_count,depth,actor,scope_depth,scope_enters,deny_scope_n;
static unsigned auto_clock,time_bad,lifecycle,ready,task_pending;
static unsigned starts,stops,polls,copies,writes,flushes,grants,clears,rx_reads,task_calls,diag_tx_count;
static unsigned grant_unlock,grant_frees,grant_allow,write_kind,late_final,after_final;
static unsigned watching,inject_hook,inject_event,inject_done,prefetch_cycles,cached_prepare_cycles,after_offer_samples;
static uint32_t native_cycle,pass_origin;
static uint64_t pass_first;
static size_t fifo_free,wire_used,rx_length;
static uint8_t wire[32768],rx[64],decoded[1328];
static char trace[4096];static unsigned traced;
static mt_stream_progress_record saved_progress;
static mt_usb_gate_record saved_gate;
static mt_stream_diag_record saved_legacy;
static unsigned saved_fixture;
enum {HOOK_NONE,HOOK_AFTER_COPY,HOOK_SELECTED,HOOK_GRANT,HOOK_PREFETCH_BEGIN,HOOK_PREFETCH_END,HOOK_AFTER_OFFER};
enum {EVENT_NONE,EVENT_EPOCH,EVENT_SOFT,EVENT_LIFECYCLE,EVENT_TIME,EVENT_NONCE,
      EVENT_STOP,EVENT_HELLO,EVENT_DEADLINE,EVENT_Q_ERROR};
enum {WRITE_FULL,WRITE_PARTIAL,WRITE_UNKNOWN};
static void command(unsigned revision,unsigned type,uint64_t nonce,unsigned seq,unsigned req,const uint8_t*p,unsigned n);
static void mark(char c){CHECK(traced+1<sizeof trace);trace[traced++]=c;trace[traced]=0;}
static uint32_t *reg(uint32_t address){
    for(unsigned i=0;i<register_count;i++)if(registers[i].address==address)return &registers[i].value;
    CHECK(register_count<64);registers[register_count].address=address;return &registers[register_count++].value;
}
static uint16_t pattern(uint64_t i){return (uint16_t)((i*37u+3u)&4095u);}
static uint32_t crc_byte(uint32_t c,uint8_t b){c^=b;for(unsigned i=0;i<8;i++)c=(c>>1)^((c&1u)?0xedb88320u:0u);return c;}
static uint32_t expected_crc(uint64_t end){uint32_t c=UINT32_MAX;for(uint64_t i=0;i<end;i++){uint16_t v=pattern(i)&4092u;c=crc_byte(c,(uint8_t)v);c=crc_byte(c,(uint8_t)(v>>8));}return c;}
static void w32(uint8_t*p,uint32_t n){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i));}
static void w64(uint8_t*p,uint64_t n){for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(n>>(8*i));}
static uint16_t r16(const uint8_t*p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t r32(const uint8_t*p){uint32_t n=0;for(unsigned i=0;i<4;i++)n|=(uint32_t)p[i]<<(8*i);return n;}
static uint64_t r64(const uint8_t*p){return (uint64_t)r32(p)|((uint64_t)r32(p+4)<<32);}
static void event(unsigned e){
    if(e==EVENT_EPOCH)CHECK(mt_usb_epoch_reset(&epoch));
    if(e==EVENT_SOFT)CHECK(mt_usb_epoch_suspend(&epoch,epoch.current));
    if(e==EVENT_LIFECYCLE){lifecycle=1;mt_gate_invalidate(1);}
    if(e==EVENT_TIME)time_bad=1;
    if(e==EVENT_NONCE)++D.nonce;
    if(e==EVENT_DEADLINE)clock_source.us=pass_origin+3413u;
    if(e==EVENT_Q_ERROR)D.queue.counts[D.queue.head]=0; /* Safe malformed metadata; no out-of-bounds index. */
    if(e==EVENT_STOP){uint8_t p[4];w32(p,3);command(3,5,503,4,4,p,4);}
    if(e==EVENT_HELLO){uint8_t p[12]={0};w64(p,777);p[8]=5;command(3,1,0,1,1,p,12);}
}
static void hook(unsigned h){if(watching && !inject_done && inject_hook==h){inject_done=1;event(inject_event);}}
uint32_t mt_progress_native_cycle(void){
    native_cycle+=20;
    if(watching && copies && !D.prefix_end && D.batch.phase==MT_BATCH1024_READY &&
       (mt_stream_progress.flags&MT_N_PREPARE_OPEN))++cached_prepare_cycles;
    if(watching && D.prefix_end==1024 && !D.tx_length &&
       (mt_stream_progress.flags&MT_N_PREPARE_OPEN)){
        ++prefetch_cycles;
        hook(D.batch.count==512?HOOK_PREFETCH_END:HOOK_PREFETCH_BEGIN);
    }
    return native_cycle;
}
/* The old diagnostic API is a synthetic setup/counter seam. Actual N/G use
 * their own linked implementations and this same generated firmware identity. */
uint32_t mt_stream_diag_cycle(void){return native_cycle+=3;}
int mt_stream_diag_init(uint32_t(*r)(void*,uint32_t),void(*w)(void*,uint32_t,uint32_t),void*p,uint32_t b){(void)r;(void)w;(void)p;CHECK(b==MT_FIRMWARE_BUILD);return 1;}
void mt_stream_diag_begin(uint32_t generation,uint64_t nonce){
    mt_stream_diagnostics=(mt_stream_diag_record){.magic=0x4d544447,.version=1,.bytes=136,
        .firmware_build=MT_FIRMWARE_BUILD,.phase=2,.generation=generation,
        .nonce_low=(uint32_t)nonce,.nonce_high=(uint32_t)(nonce>>32)};
}
void mt_stream_diag_replaced(uint32_t a,uint32_t b,uint32_t c){(void)a;(void)b;(void)c;}
void mt_stream_diag_poll(uint32_t us){(void)us;++polls;mark('p');}
void mt_stream_diag_copy(uint32_t us){(void)us;++copies;mark('c');}
void mt_stream_diag_tx(uint32_t begin){(void)begin;++diag_tx_count;}
void mt_stream_diag_note(uint32_t a,uint32_t b,uint32_t c,uint32_t d,uint32_t e,uint32_t f){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;}
void mt_stream_diag_observe(uint32_t a,uint32_t b,uint32_t c,uint32_t d,uint32_t e,uint32_t f,uint32_t g,uint32_t h,uint32_t i,uint32_t j,uint32_t k,unsigned l){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;(void)i;(void)j;(void)k;(void)l;}
int mt_timebase_healthy(const mt_timebase*c){return c && !time_bad && c->state==MT_TIMEBASE_RUNNING;}
int mt_timebase_update(mt_timebase*c){return mt_timebase_healthy(c);}
int mt_timebase_snapshot(void*p,uint32_t*us,uint32_t*ms){
    mt_timebase*c=p;if(!c || !us || !ms || !mt_timebase_update(c))return 0;
    *us=c->us;*ms=c->ms;return 1;
}
uint32_t mt_timebase_now_us(void*p){mt_timebase*c=p;return c->us;}
static uint64_t live_time(void*p){
    CHECK(p==&owner);
    if(watching && copies){
        hook(HOOK_AFTER_COPY);
        if(cached_prepare_cycles>=2)hook(HOOK_SELECTED);
        if(after_offer_samples && D.queue.next_index>=pass_first+after_offer_samples)hook(HOOK_AFTER_OFFER);
    }
    if(time_bad){owner.clock64.failed=1;return UINT64_MAX;}return 10;
}
static uint64_t core_clock(void*p){
    CHECK(p==&owner);
    if(late_final && after_final && ++after_final==3)return UINT64_MAX;
    return time_bad?UINT64_MAX:10;
}
static uint32_t bus_read(void*p,uint32_t address){(void)p;return *reg(address);}
static void bus_write(void*p,uint32_t address,uint32_t value){
    (void)p;
    if(address==0x40012408u)value&=~12u; /* Instant calibration: not an analogue startup test. */
    if(address==0x40020004u)*reg(0x40020000u)&=~value;
    *reg(address)=value;
}
static uint32_t adc_now(void*p){(void)p;if(auto_clock)++clock_source.us;return clock_source.us;}
uint32_t mt_usb_bridge_lock(void){uint32_t previous=depth;++depth;return previous;}
void mt_usb_bridge_unlock(uint32_t previous){
    CHECK(depth>previous);depth=previous;
    if(!depth && grant_unlock){grant_unlock=0;if(grant_frees)fifo_free=384;hook(HOOK_GRANT);}
}
mt_usb_epoch mt_usb_bridge_snapshot(void){return epoch;}
uint32_t mt_usb_bridge_actor(void){return actor;}
bool mt_usb_fsdev_lifecycle_pending(void){return lifecycle!=0;}
int mt_usb_bridge_app_enter(mt_usb_scope*s){
    s->previous=actor;s->entered=0;++scope_enters;
    if(deny_scope_n && scope_enters==deny_scope_n)return 0;
    if(lifecycle || !mt_usb_epoch_app_io(&epoch,epoch.current))return 0;
    actor=epoch.current;s->entered=1;++scope_depth;return 1;
}
void mt_usb_bridge_leave(mt_usb_scope*s){CHECK(s->entered && scope_depth);--scope_depth;actor=s->previous;s->entered=0;}
void mt_usb_bridge_cleaned(uint32_t token){CHECK(mt_usb_epoch_cleaned(&epoch,token));}
bool mt_usb_fsdev_irq_grant(bool allow){CHECK(depth);++grants;grant_allow=allow;grant_unlock=1;mark('g');mt_gate_invalidate(0);return grant_frees!=0;}
bool mt_usb_fsdev_irq_held(void){return true;}
bool mt_usb_fsdev_ctr_deferred(void){return true;}
bool tud_inited(void){return true;}
bool tud_task_event_ready(void){return task_pending!=0;}
void tud_task_ext(uint32_t timeout,bool in_isr){CHECK(!timeout && !in_isr && !actor);++task_calls;}
bool tud_cdc_n_ready(uint8_t i){CHECK(!i);return ready!=0;}
bool tud_cdc_n_connected(uint8_t i){CHECK(!i);return true;}
uint32_t tud_cdc_n_available(uint8_t i){CHECK(!i);return (uint32_t)rx_length;}
uint32_t tud_cdc_n_read(uint8_t i,void*p,uint32_t n){
    CHECK(!i && p && actor && !lifecycle && !time_bad);++rx_reads;mark('r');
    if(watching && copies)CHECK(D.queue.next_index==pass_first+512);
    if(n>rx_length)n=(uint32_t)rx_length;memcpy(p,rx,n);rx_length-=n;return n;
}
void tud_cdc_n_read_flush(uint8_t i){CHECK(!i);rx_length=0;}
uint32_t tud_cdc_n_write_available(uint8_t i){CHECK(!i);return (uint32_t)fifo_free;}
uint32_t tud_cdc_n_write(uint8_t i,const void*p,uint32_t n){
    CHECK(!i && p && n<=fifo_free && owner.writer_active && depth && actor);
    ++writes;mark('w');
    /* On native64 this is an oversized uint32 acceptance, not SIZE_MAX from
     * io.write. Actual core classifies both as unknown; no fictitious bytes. */
    if(write_kind==WRITE_UNKNOWN)return UINT32_MAX;
    if(write_kind==WRITE_PARTIAL)n/=2;
    CHECK(wire_used+n<=sizeof wire);memcpy(wire+wire_used,p,n);wire_used+=n;fifo_free-=n;
    if(late_final && n && n==D.tx_length-D.tx_offset)after_final=1;
    return n;
}
uint32_t tud_cdc_n_write_flush(uint8_t i){CHECK(!i && actor);++flushes;mark('f');return 0;}
bool tud_cdc_n_write_clear(uint8_t i){CHECK(!i);++clears;fifo_free=384;return true;}
static uint32_t guard_enter(void*p){(void)p;return mt_usb_bridge_lock();}
static void guard_leave(void*p,uint32_t key){(void)p;mt_usb_bridge_unlock(key);}
static int guard_allowed(void*p){(void)p;return !time_bad && !lifecycle;}
static int guard_timed(void*p,uint32_t*us){(void)p;if(!guard_allowed(NULL))return 0;*us=adc_now(NULL);return 1;}
static int start_source(void*p,uint32_t generation){
    CHECK(p==&owner);++starts;mt_stream_diag_begin(generation,D.nonce);
    return mt_live_adc_start(&owner.acquisition,generation);
}
static void stop_source(void*p,mt_live_snapshot*s){
    CHECK(p==&owner);++stops;mark('s');
    if(watching && copies)CHECK((mt_stream_progress.flags&MT_N_PHASE_MASK)==MT_N_FROZEN);
    mt_live_adc_quiesce(&owner.acquisition,s);
}
static int isolate(void*p){CHECK(p==&owner);return 1;}
static mt_live_runtime_result time_fault(mt_live_runtime*r);
/* RUNTIME_BODIES */

static mt_live_prepare_result prepare(mt_live_tx_ticket*t){uint32_t stamp=mt_progress_prepare_begin();mt_live_prepare_result v=mt_live_device_prepare_tx(&D,t);mt_progress_prepare_end(stamp);return v;}
static int tick(void){
    mt_live_tx_ticket t;owner.in_step=1;fifo_free=384;(void)prepare(&t);
    uint32_t key=mt_usb_bridge_lock();int v=prepared_tx_step(&owner,&t,owner.epoch,owner.soft_serial);
    mt_usb_bridge_unlock(key);owner.in_step=0;return v;
}
static void command(unsigned revision,unsigned type,uint64_t nonce,unsigned seq,unsigned req,const uint8_t*p,unsigned n){
    mt_wire_message m={.type=(uint8_t)type,.session=nonce,.sequence=seq,.request=req,.payload_length=(uint16_t)n};
    uint8_t bytes[MT_WIRE_FRAME_MAX];size_t length;if(n)memcpy(m.payload,p,n);
    CHECK(mt_wire_encode_revision(&m,0,(uint8_t)revision,bytes,sizeof bytes,&length)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&D,bytes,length));
}
static void finish_control(void){unsigned n=16;do{CHECK(n-- && tick());}while(D.tx_length);wire_used=0;}
static void setup(unsigned mode){
    memset(&owner,0,sizeof owner);memset(&clock_source,0,sizeof clock_source);memset(&epoch,0,sizeof epoch);
    memset(registers,0,sizeof registers);register_count=0;trace[0]=0;traced=0;
    mt_stream_progress=(mt_stream_progress_record){0};mt_usb_gate=(mt_usb_gate_record){0};
    mt_stream_diagnostics=(mt_stream_diag_record){0};native_cycle=1000;
    depth=actor=scope_depth=scope_enters=deny_scope_n=time_bad=lifecycle=task_pending=0;
    starts=stops=polls=copies=writes=flushes=grants=clears=rx_reads=task_calls=diag_tx_count=0;
    grant_unlock=write_kind=late_final=after_final=watching=inject_hook=inject_event=inject_done=prefetch_cycles=cached_prepare_cycles=after_offer_samples=0;
    grant_frees=ready=auto_clock=1;wire_used=rx_length=0;fifo_free=384;
    epoch.current=epoch.cleaned=epoch.configured=epoch.processed_reset=3;
    owner.clock=&clock_source;clock_source.initialized=1;clock_source.state=MT_TIMEBASE_RUNNING;clock_source.us=1000;
    owner.epoch=3;owner.soft_serial=epoch.soft_serial;owner.initialized=owner.open=owner.require_dtr=1;
    *reg(0x40021000u)=0x03037783u;*reg(0x40021004u)=0x001d840au;
    *reg(0x40021014u)=1;*reg(0x40021018u)=(1u<<2)|(1u<<9);*reg(0x4002101cu)=3;
    mt_adc_dma_io_t adc_io={bus_read,bus_write,adc_now,NULL};
    mt_adc_dma_start_guard guard={guard_enter,guard_allowed,guard_leave,&owner,guard_timed};
    CHECK(mt_adc_dma_init(&A,&adc_io,8000000)==MT_ADC_DMA_OK);
    CHECK(mt_live_adc_init(&owner.acquisition,&A,&clock_source,&D,&guard));
    mt_live_io io={.context=&owner,.clock_ms=core_clock,.start=start_source,.quiesce=stop_source,
        .write=live_write,.isolate_tx=isolate,.transaction_bound_ms=1,.firmware_build=MT_FIRMWARE_BUILD};
    CHECK(MT_FIRMWARE_BUILD==UINT32_C(0x5632534c) && MT_N_BUILD==MT_FIRMWARE_BUILD);
    CHECK(mt_live_device_init(&D,&io));
    uint8_t p[12]={0};w64(p,123);command(2,1,0,1,1,p,8);finish_control();
    w64(p,503);p[8]=(uint8_t)mode;command(3,1,0,1,1,p,12);finish_control();
    command(3,2,503,2,2,NULL,0);finish_control();w32(p,mode);command(3,8,503,3,3,p,4);finish_control();
    CHECK(D.state==MT_LIVE_STREAMING && D.generation==3 && A.state==MT_ADC_DMA_RUNNING && starts==1);
    CHECK((mt_stream_progress.flags&MT_N_PHASE_MASK)==MT_N_ACTIVE && mt_stream_progress.prepare_count && mt_stream_progress.prepare_cycles);
    auto_clock=0;
}
static void ready_half(void){
    unsigned offset=A.next_half?512:0;
    for(unsigned i=0;i<512;i++)A.dma_samples[offset+i]=pattern(A.first_sample_index+i);
    *reg(0x40020000u)=A.next_half?2:4;*reg(0x4002000cu)=A.next_half?1024:512;
    clock_source.us=A.last_poll_us+100;
}
static void deliver_half(void){ready_half();CHECK(mt_live_adc_service(&owner.acquisition)==1);}
static void before_final(unsigned queued){
    setup(5);deliver_half();deliver_half();CHECK(D.queue.used==8);
    CHECK(tick() && D.batch.count==512 && !D.tx_length);
    CHECK(tick() && D.batch.phase==MT_BATCH1024_READY && D.tx_offset==384 && !D.queue.used);
    /* Full queue is populated through the actual driver/adapter. Other counts
     * are core fixtures with explicit stream source indices, not fake pops. */
    if(queued==8){deliver_half();deliver_half();}
    else{
        uint16_t samples[128];
        for(unsigned b=0;b<queued;b++){uint64_t first=D.queue.next_index;for(unsigned i=0;i<128;i++)samples[i]=pattern(first+i);CHECK(mt_live_device_offer(&D,first,samples,128));}
        A.first_sample_index=D.queue.next_index;A.next_half=((A.first_sample_index/512u)&1u)!=0;
    }
    while(D.tx_length-D.tx_offset>384)CHECK(tick());
    CHECK(D.tx_offset && D.tx_length-D.tx_offset<=384 && D.prefix_end==0 && D.queue.used==queued);
    ready_half();pass_first=A.first_sample_index;pass_origin=clock_source.us;
    polls=copies=writes=flushes=grants=clears=rx_reads=task_calls=diag_tx_count=scope_enters=0;
    traced=0;trace[0]=0;fifo_free=0;watching=1;
}
static void settled(void){CHECK(!depth && !actor && !scope_depth && !owner.in_step && !owner.writer_active);}
static unsigned pos(char c){char*p=strchr(trace,c);CHECK(p);return (unsigned)(p-trace);}
static void inject_at(unsigned hook_at,unsigned e){inject_hook=hook_at;inject_event=e;}
static void queue_samples(uint64_t first){
    for(unsigned b=0;b<D.queue.used;b++){
        unsigned slot=(D.queue.head+b)%MT_SAMPLE_QUEUE_SLOTS;CHECK(D.queue.counts[slot]==128);
        for(unsigned i=0;i<128;i++)CHECK(D.queue.samples[slot][i]==(pattern(first+b*128+i)&4092u));
    }
}

static void check_first_frame(void){
    size_t at=0,end=0;unsigned n=0;while(end<wire_used && wire[end])++end;CHECK(end+1==wire_used);
    while(at<end){unsigned code=wire[at++];CHECK(code && code-1<=end-at && n+code-1<=sizeof decoded);
        for(unsigned i=1;i<code;i++)decoded[n++]=wire[at++];
        if(code!=255 && at<end){CHECK(n<sizeof decoded);decoded[n++]=0;}}
    CHECK(n==1328 && decoded[0]==0 && decoded[1]==3 && decoded[2]==152 && !decoded[3]);
    CHECK(r16(decoded+4)==1300 && !r16(decoded+6) && r64(decoded+8)==503 && r32(decoded+16)==4);
    CHECK(r32(decoded+24)==3 && r32(decoded+28)==5 && !r64(decoded+32) && r16(decoded+40)==1024 && !r16(decoded+42));
    uint32_t crc=UINT32_MAX,pending=0;unsigned offset=44,bits=0;
    for(unsigned i=0;i<1024;i++){
        while(bits<10){pending|=(uint32_t)decoded[offset++]<<bits;bits+=8;}
        CHECK(((pending&1023u)<<2)==(pattern(i)&4092u));pending>>=10;bits-=10;
    }
    CHECK(!pending && offset==1324);
    for(unsigned i=0;i<n-4;i++)crc=crc_byte(crc,decoded[i]);CHECK((crc^UINT32_MAX)==r32(decoded+n-4));
}
static void save_frozen_fixture(void){
    CHECK((mt_stream_progress.flags&MT_N_PHASE_MASK)==MT_N_FROZEN);
    CHECK((mt_usb_gate.flags&MT_G_PHASE_MASK)==MT_G_FROZEN);
    saved_progress=mt_stream_progress;saved_gate=mt_usb_gate;
    saved_legacy=mt_stream_diagnostics;saved_legacy.phase=3;saved_legacy.flags=4;
    saved_legacy.first_acquisition_reason=D.first_reason;saved_fixture=1;
}
static void ownership_and_dispatch(void){
    before_final(8);CHECK(postcopy_hint(&owner));
    uint64_t source_next=A.first_sample_index;uint32_t old_crc=D.prefix_crc_state;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);settled();
    CHECK(polls==1 && copies==1 && grants==1 && grant_allow && writes==1 && flushes==1 && diag_tx_count==1);
    CHECK(rx_reads==1 && task_calls==1 && pos('c')<pos('g') && pos('g')<pos('w') && pos('w')<pos('f') && pos('f')<pos('r'));
    CHECK(D.prefix_end==1024 && old_crc==UINT32_MAX && D.prefix_crc_state==expected_crc(1024));
    CHECK(D.last_data_sequence==4 && D.tx_next==5 && !D.tx_length);
    CHECK(D.batch.phase==MT_BATCH1024_COLLECT && D.batch.count==512 && prefetch_cycles==2);
    CHECK(D.queue.used==8 && D.queue.head_index==1536 && D.queue.next_index==source_next+512);
    CHECK(A.first_sample_index==source_next+512 && A.last_poll_us==pass_origin);
    CHECK((mt_stream_progress.flags&MT_N_PHASE_MASK)==MT_N_ACTIVE && mt_stream_progress.prepare_count>2);
    queue_samples(1536);check_first_frame();
    for(unsigned i=0;i<512;i++)CHECK(A.snapshot[i]==pattern(source_next+i));

    /* EMPTY acquire takes the old cached path exactly once; no fake source half. */
    before_final(8);*reg(0x40020000u)=0;*reg(0x4002000cu)=A.next_half?512:1024;
    source_next=A.first_sample_index;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);settled();
    CHECK(polls==1 && !copies && grants==1 && writes==1 && D.prefix_end==1024 && A.first_sample_index==source_next);

    /* Real ordinary mode1 goes through unchanged service + RX + prepare. */
    setup(1);ready_half();polls=copies=writes=grants=rx_reads=0;
    CHECK(!postcopy_hint(&owner));CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_OK);settled();
    CHECK(polls==1 && copies==1 && grants==1 && writes==1 && rx_reads==1 && D.prefix_end==128);

    before_final(8);uint32_t sequence=D.tx_next;
    D.tx_next=UINT32_C(0xffffff00);CHECK(!postcopy_hint(&owner));D.tx_next=sequence;
    D.stop_seen=1;CHECK(!postcopy_hint(&owner));D.stop_seen=0;
    D.want_caps=1;CHECK(!postcopy_hint(&owner));D.want_caps=0;
    D.mode=4;CHECK(!postcopy_hint(&owner));D.mode=5;
    rx_length=1;CHECK(!postcopy_hint(&owner));rx_length=0;
    puts("PASS actual copy/cached-final/flush/Q/publish q8->4->8; source identity/raw/packed CRC preserved; bounded caller dispatch and ordinary mode/EMPTY path");
}
static void refusals_and_irreversible_prefix(void){
    before_final(8);grant_frees=0;
    mt_gate_submit_begin(0x82);mt_gate_submit_done(0x82,1,384,64,64,1,0);
    mt_gate_note(MT_G_HOLD_TIME,384,64,5,501,1);
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(grants==1 && !writes && !rx_reads && polls==1 && copies==1 && D.first_reason==1);
    CHECK(D.prefix_end==0 && D.queue.next_index==pass_first && D.hardware_off && !A.owns_peripherals);
    CHECK(mt_stream_progress.close_kind==MT_N_CLOSE_QUEUE && mt_stream_progress.zero_space_count);
    save_frozen_fixture();

    before_final(8);write_kind=WRITE_PARTIAL;size_t before_wire=wire_used,old_offset=D.tx_offset;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(grants==1 && writes==1 && !rx_reads && D.first_reason==1 && D.prefix_end==0);
    CHECK(D.tx_offset>old_offset && wire_used>before_wire && (mt_stream_progress.flags&MT_N_PARTIAL_WRITE));

    before_final(8);write_kind=WRITE_UNKNOWN;before_wire=wire_used;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(grants==1 && writes==1 && !rx_reads && !D.prefix_end && D.needs_delimiter && wire_used==before_wire);
    CHECK(D.local_error==MT_LIVE_ERR_TRANSPORT && (mt_stream_progress.flags&MT_N_UNKNOWN_WRITE));

    before_final(8);late_final=1;before_wire=wire_used;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(writes==1 && wire_used>before_wire && !D.prefix_end && D.needs_delimiter && !rx_reads);
    CHECK(D.local_error==MT_LIVE_ERR_CLOCK && mt_stream_progress.close_kind==MT_N_CLOSE_TIME);

    /* Refused nested Q admission is cancellation of collect, not a lost view:
     * original full-queue publication honestly faults, preserving committed DATA. */
    before_final(8);deny_scope_n=4;
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(D.prefix_end==1024 && D.prefix_crc_state==expected_crc(1024) && D.first_reason==1);
    CHECK(grants==1 && writes==1 && !rx_reads && D.queue.next_index==pass_first && owner.open);

    before_final(8);inject_at(HOOK_PREFETCH_BEGIN,EVENT_Q_ERROR);
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(inject_done && D.prefix_end==1024 && D.prefix_crc_state==expected_crc(1024));
    CHECK(writes==1 && grants==1 && !rx_reads && D.local_error && D.hardware_off);
    puts("PASS known zero/partial/oversized unknown/final clock preserve irreversible bytes and first cause; nested Q refusal resolves source and matching Q ERROR recovers without second DATA");
}
static void admission_and_deadlines(void){
    const unsigned faults[]={EVENT_EPOCH,EVENT_SOFT,EVENT_LIFECYCLE,EVENT_TIME,EVENT_NONCE,EVENT_STOP,EVENT_HELLO};
    for(unsigned i=0;i<sizeof faults/sizeof faults[0];i++){
        before_final(8);inject_at(HOOK_AFTER_COPY,faults[i]);
        mt_live_runtime_result v=mt_live_runtime_step(&owner);settled();
        CHECK(inject_done && v==(faults[i]==EVENT_TIME?MT_LIVE_RUNTIME_TIME_FAULT:MT_LIVE_RUNTIME_RECOVERY));
        CHECK(!writes && !rx_reads && copies==1 && D.hardware_off && !A.owns_peripherals);
        CHECK(D.queue.next_index==pass_first && owner.open==0 && D.needs_delimiter);
    }
    /* Selection occurs before this live_time seam: no current grant/fallthrough,
     * but the next wrapper still supplies the raw lifecycle opportunity. */
    before_final(8);inject_at(HOOK_SELECTED,EVENT_LIFECYCLE);
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(inject_done && cached_prepare_cycles==2 && !grants && !writes && !rx_reads && D.hardware_off);
    watching=0;CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_IDLE);settled();
    CHECK(grants==1 && !writes && !rx_reads && !actor); /* allow argument is not effective DCD CTR. */

    before_final(8);inject_at(HOOK_GRANT,EVENT_EPOCH);
    CHECK(mt_live_runtime_step(&owner)==MT_LIVE_RUNTIME_RECOVERY);settled();
    CHECK(inject_done && grants==1 && !writes && !rx_reads && D.queue.next_index==pass_first);

    for(unsigned accepted=1;accepted<=4;accepted++){
        before_final(8);after_offer_samples=accepted*128;
        inject_at(HOOK_AFTER_OFFER,accepted==1?EVENT_TIME:accepted==2?EVENT_DEADLINE:EVENT_LIFECYCLE);
        mt_live_runtime_result v=mt_live_runtime_step(&owner);settled();
        CHECK(inject_done && v==(accepted==1?MT_LIVE_RUNTIME_TIME_FAULT:MT_LIVE_RUNTIME_RECOVERY));
        CHECK(grants==1 && writes==1 && !rx_reads && D.prefix_end==1024);
        CHECK(D.queue.next_index==pass_first+accepted*128 && D.queue.used==4+accepted && D.queue.sealed);
        CHECK(A.first_sample_index==pass_first+512 && !A.owns_peripherals && D.hardware_off);
        if(accepted==2)CHECK(A.first_fault==MT_ADC_DMA_FAULT_DEADLINE && D.first_reason==2);
        if(accepted>=3)CHECK(owner.open==0 && mt_stream_progress.close_kind==MT_N_CLOSE_TRANSPORT);
    }
    /* Actual adapter receipt proves exact <deadline and modulo-wrap behavior.
     * There is no driver poll/timebase refresh between acquire and publication. */
    for(unsigned variant=0;variant<3;variant++){
        before_final(4);watching=0;
        if(variant==2){A.last_poll_us=UINT32_MAX-200;A.last_progress_us=A.last_poll_us;clock_source.us=A.last_poll_us+100;}
        mt_live_adc_pending p={0};mt_usb_scope scope;CHECK(mt_usb_bridge_app_enter(&scope));
        CHECK(mt_live_adc_acquire(&owner.acquisition,&p,owner.epoch,owner.soft_serial,actor)==MT_LIVE_ADC_SPLIT_OWNED);
        uint64_t first=p.block.first_sample_index;uint32_t origin=p.poll_origin_us;
        clock_source.us=origin+(variant==1?3413:3412);
        if(variant==1){
            CHECK(mt_live_adc_publish_next(&owner.acquisition,&p)==MT_LIVE_ADC_SPLIT_DEADLINE);
            CHECK(p.phase==MT_LIVE_ADC_PENDING_ABORTED && !p.published && D.queue.next_index==first && D.first_reason==2);
        }else{
            for(unsigned n=1;n<=4;n++)CHECK(mt_live_adc_publish_next(&owner.acquisition,&p)==(n==4?MT_LIVE_ADC_SPLIT_PUBLISHED:MT_LIVE_ADC_SPLIT_OWNED));
            CHECK(p.phase==MT_LIVE_ADC_PENDING_PUBLISHED && p.published==512 && D.queue.next_index==first+512);
            CHECK(A.last_poll_us==origin && A.first_sample_index==first+512);queue_samples(1024);
        }
        uint64_t next=D.queue.next_index;
        CHECK(mt_live_adc_publish_next(&owner.acquisition,&p)==MT_LIVE_ADC_SPLIT_BAD_ARGUMENT && D.queue.next_index==next);
        mt_usb_bridge_leave(&scope);settled();
    }
    puts("PASS original receipt deadline3412/3413/wrap and no replay; actual loss after1..4 offers; raw lifecycle/epoch/soft/Stop/HELLO quarantined; consumed refusal preserves next fallback");
}
static void write_fixture(const char*path,const void*bytes,size_t count){FILE*f=fopen(path,"wb");CHECK(f && fwrite(bytes,1,count,f)==count && fclose(f)==0);}
int main(int argc,char**argv){
    CHECK(argc==4);ownership_and_dispatch();refusals_and_irreversible_prefix();admission_and_deadlines();
    CHECK(saved_fixture && saved_legacy.firmware_build==MT_FIRMWARE_BUILD && saved_legacy.generation==3);
    write_fixture(argv[1],&saved_gate,sizeof saved_gate);write_fixture(argv[2],&saved_progress,sizeof saved_progress);write_fixture(argv[3],&saved_legacy,sizeof saved_legacy);
    printf("build=0x%08x; actual_C_fixture=24/64/136; legacy=synthetic; hardware=0; throughput_claim=0\n",(unsigned)MT_FIRMWARE_BUILD);
    return 0;
}
