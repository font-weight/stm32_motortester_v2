/* Q: actual core/queue/serializer/wire and ACTIVE64 observer. The runner inserts
 * the two exact runtime helpers below and uses the ARM-generated SJ identity.
 * TIME, epoch, app scope and the preceding flush are explicit logical seams;
 * native cycle values are synthetic, not USB/DMA latency or throughput evidence. */
#include "app/mt_live_runtime.h"
#include "platform/mt_stream_progress.h"
#include "platform/mt_stream_diag.h"
#include "platform/mt_usb_ctr.h"
#include "tusb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL prefetch line%d: %s\n",__LINE__,#x);exit(1); } } while(0)
#define D owner.device
static mt_live_runtime owner;
volatile mt_stream_diag_record mt_stream_diagnostics;
static uint32_t native_cycle,env_epoch,env_soft,actor,depth;
static unsigned starts,stops,writes,core_clocks,flushes,cleanups,scope_enters;
static unsigned time_bad,lifecycle,deny_scope,transport_allowed;
static unsigned helper_active,cycle_in_helper,inject_cycle,inject_event,enter_event,leave_event,post_flush_event;
static unsigned unknown_write,late_final,final_armed,after_final,expect_guarded_cleanup;
static uint64_t old_prefix;
static size_t wire_used,write_limit;
static uint8_t wire[16384],decoded[1328];
static mt_stream_progress_record first_frozen;
static unsigned have_frozen;
enum { EVENT_NONE,EVENT_EPOCH,EVENT_SOFT,EVENT_TIME,EVENT_LIFECYCLE,EVENT_FREEZE,EVENT_NONCE };

static unsigned progress_phase(void) { return mt_stream_progress.flags&MT_N_PHASE_MASK; }
static uint16_t r16(const uint8_t*p) { return (uint16_t)(p[0]|((uint16_t)p[1]<<8)); }
static uint32_t r32(const uint8_t*p) { uint32_t n=0;for(unsigned i=0;i<4;i++)n|=(uint32_t)p[i]<<(8*i);return n; }
static uint64_t r64(const uint8_t*p) { return (uint64_t)r32(p)|((uint64_t)r32(p+4)<<32); }
static void w32(uint8_t*p,uint32_t n) { for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i)); }
static void w64(uint8_t*p,uint64_t n) { for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(n>>(8*i)); }
static uint16_t pattern(uint64_t i) { return (uint16_t)((i*37u+3u)&4095u); }
static uint32_t crc_byte(uint32_t c,uint8_t b) { c^=b;for(unsigned i=0;i<8;i++)c=(c>>1)^((c&1u)?0xedb88320u:0u);return c; }
static uint32_t crc_raw(uint32_t c,const uint8_t*p,unsigned n) { for(unsigned i=0;i<n;i++)c=crc_byte(c,p[i]);return c; }
static uint32_t expected_crc(uint64_t end) {
    uint32_t c=UINT32_MAX;
    for(uint64_t i=0;i<end;i++){uint16_t v=pattern(i)&4092u;c=crc_byte(c,(uint8_t)v);c=crc_byte(c,(uint8_t)(v>>8));}
    return c;
}
static void inject(unsigned event) {
    if(event==EVENT_EPOCH)++env_epoch;
    if(event==EVENT_SOFT)++env_soft;
    if(event==EVENT_TIME)time_bad=1;
    if(event==EVENT_LIFECYCLE)lifecycle=1;
    if(event==EVENT_NONCE)++D.nonce; /* Deliberate stale-ticket negative seam. */
    if(event==EVENT_FREEZE){
        mt_progress_close(&D,MT_N_CLOSE_ADC,1);
        first_frozen=mt_stream_progress;have_frozen=1;
    }
}
uint32_t mt_progress_native_cycle(void) {
    native_cycle+=100;
    if(helper_active && ++cycle_in_helper==inject_cycle){unsigned event=inject_event;inject_cycle=0;inject(event);}
    return native_cycle;
}
uint32_t mt_usb_bridge_lock(void) { uint32_t previous=depth;++depth;return previous; }
void mt_usb_bridge_unlock(uint32_t previous) { CHECK(depth>previous);depth=previous; }
int mt_usb_bridge_app_enter(mt_usb_scope*s) {
    s->previous=actor;s->entered=0;
    if(deny_scope){deny_scope=0;return 0;}
    if(lifecycle || time_bad || owner.epoch!=env_epoch || owner.soft_serial!=env_soft)return 0;
    actor=owner.epoch;s->entered=1;++scope_enters;
    if(helper_active && enter_event){unsigned e=enter_event;enter_event=0;inject(e);}
    return 1;
}
void mt_usb_bridge_leave(mt_usb_scope*s) {
    CHECK(s->entered);actor=s->previous;s->entered=0;
    if(helper_active && !depth && leave_event){unsigned e=leave_event;leave_event=0;inject(e);}
}
uint32_t tud_cdc_n_write_available(uint8_t itf) { CHECK(!itf);return 201; }
bool tud_task_event_ready(void) { return false; }
bool mt_usb_fsdev_irq_held(void) { return true; }
bool mt_usb_fsdev_ctr_deferred(void) { return true; }

static uint64_t now(void*p) {
    CHECK(p==&owner);++core_clocks;
    if(final_armed){++after_final;CHECK(D.prefix_end==old_prefix);if(late_final && after_final==2)return UINT64_MAX;}
    return 1;
}
static int start(void*p,uint32_t generation) {
    CHECK(p==&owner && generation==3);++starts;
    /* The legacy module is not executed by this model. Its pairing record is
     * explicitly synthetic, from the SAME generated header as actual64. */
    mt_stream_diagnostics=(mt_stream_diag_record){.magic=UINT32_C(0x4d544447),
        .version=1,.bytes=sizeof(mt_stream_diag_record),.firmware_build=MT_FIRMWARE_BUILD,
        .phase=2,.generation=generation,.nonce_low=(uint32_t)D.nonce,.nonce_high=(uint32_t)(D.nonce>>32)};
    return 1;
}
static void stop(void*p,mt_live_snapshot*s) {
    CHECK(p==&owner);++stops;
    if(expect_guarded_cleanup)CHECK(depth && progress_phase()==MT_N_FROZEN);
    *s=(mt_live_snapshot){.hardware_off=1};
}
static int isolate(void*p) { CHECK(p==&owner);return 1; }
static size_t write_bytes(void*p,const uint8_t*b,size_t n) {
    CHECK(p==&owner && depth && n<=384);++writes;
    if(unknown_write)return SIZE_MAX;
    if(n>write_limit)n=write_limit;
    if(!n)mt_progress_zero_space();
    CHECK(wire_used+n<=sizeof wire);memcpy(wire+wire_used,b,n);wire_used+=n;
    if(late_final && n && n==D.tx_length-D.tx_offset){final_armed=1;after_final=0;old_prefix=D.prefix_end;}
    return n;
}
/* Logical versions of unchanged runtime prerequisites. Cleanup invokes the
 * actual core, so owned staging and accepted prefix have production semantics. */
static int stable(mt_live_runtime*r) {
    CHECK(r==&owner);return !time_bad && !lifecycle && r->open &&
        r->epoch==env_epoch && r->soft_serial==env_soft;
}
static int usable(mt_live_runtime*r) { return transport_allowed && stable(r); }
static uint64_t live_time(void*p) { CHECK(p==&owner);return time_bad?UINT64_MAX:1; }
static mt_live_runtime_result loss_result(const mt_live_runtime*r) {
    CHECK(r==&owner);return time_bad?MT_LIVE_RUNTIME_TIME_FAULT:MT_LIVE_RUNTIME_RECOVERY;
}
static int synchronize_loss(mt_live_runtime*r) {
    CHECK(r==&owner);
    if(r->epoch!=env_epoch || r->soft_serial!=env_soft || lifecycle){
        ++cleanups;mt_live_device_transport_lost(&r->device);r->open=0;
        r->epoch=env_epoch;r->soft_serial=env_soft;return 0;
    }
    return 1;
}
static mt_live_runtime_result time_fault(mt_live_runtime*r) {
    CHECK(r==&owner);++cleanups;r->open=0;r->clock_fault=1;
    mt_progress_close(&r->device,MT_N_CLOSE_TIME,MT_LIVE_ERR_CLOCK);
    mt_live_device_transport_lost(&r->device);return MT_LIVE_RUNTIME_TIME_FAULT;
}
/* RUNTIME_BODIES */

static int submit(const mt_live_tx_ticket*t,uint32_t epoch,uint32_t serial) {
    uint32_t key=mt_usb_bridge_lock();int result=prepared_tx_step(&owner,t,epoch,serial);mt_usb_bridge_unlock(key);return result;
}
static mt_live_prepare_result prepare(mt_live_tx_ticket*t) {
    uint32_t begin=mt_progress_prepare_begin();mt_live_prepare_result result=mt_live_device_prepare_tx(&D,t);
    mt_progress_prepare_end(begin);return result;
}
static int tick(void) { mt_live_tx_ticket t;(void)prepare(&t);return submit(&t,owner.epoch,owner.soft_serial); }
static void command(unsigned revision,unsigned type,uint64_t nonce,unsigned seq,unsigned req,const uint8_t*p,unsigned n) {
    mt_wire_message m={.type=(uint8_t)type,.session=nonce,.sequence=seq,.request=req,.payload_length=(uint16_t)n};
    uint8_t b[MT_WIRE_FRAME_MAX];size_t length;if(n)memcpy(m.payload,p,n);
    CHECK(mt_wire_encode_revision(&m,0,(uint8_t)revision,b,sizeof b,&length)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&D,b,length));
}
static void hello(unsigned revision,uint64_t nonce,unsigned mode) {
    uint8_t p[12]={0};w64(p,nonce);p[8]=(uint8_t)mode;command(revision,1,0,1,1,p,revision==2?8:12);
}
static void finish_control(void) { unsigned limit=16;do{CHECK(limit-- && tick());}while(D.tx_length);wire_used=0; }
static void setup(unsigned mode) {
    mt_live_io io={.context=&owner,.clock_ms=now,.start=start,.quiesce=stop,.write=write_bytes,
        .isolate_tx=isolate,.transaction_bound_ms=1,.firmware_build=MT_FIRMWARE_BUILD};
    memset(&owner,0,sizeof owner);mt_stream_progress=(mt_stream_progress_record){0};
    mt_stream_diagnostics=(mt_stream_diag_record){0};
    starts=stops=writes=core_clocks=flushes=cleanups=scope_enters=0;
    time_bad=lifecycle=deny_scope=helper_active=cycle_in_helper=inject_cycle=inject_event=0;
    enter_event=leave_event=post_flush_event=unknown_write=late_final=final_armed=after_final=expect_guarded_cleanup=have_frozen=0;
    wire_used=0;write_limit=SIZE_MAX;native_cycle=1000;actor=depth=0;
    owner.epoch=env_epoch=3;owner.soft_serial=env_soft=4;owner.open=transport_allowed=1;
    CHECK(MT_FIRMWARE_BUILD==UINT32_C(0x5632534a) && MT_N_BUILD==MT_FIRMWARE_BUILD);
    CHECK(mt_live_device_init(&D,&io));hello(2,123,0);finish_control();
    hello(3,503,mode);finish_control();command(3,2,503,2,2,NULL,0);finish_control();
    uint8_t p[4];w32(p,mode);command(3,8,503,3,3,p,4);finish_control();
    CHECK(D.state==MT_LIVE_STREAMING && D.generation==3 && starts==1);
    CHECK(progress_phase()==MT_N_ACTIVE && mt_stream_progress.prepare_count>0 && mt_stream_progress.prepare_cycles>0);
}
static void offer(unsigned blocks) {
    uint16_t samples[128];uint64_t first=D.queue.next_index;
    for(unsigned b=0;b<blocks;b++){
        for(unsigned i=0;i<128;i++)samples[i]=pattern(first+b*128+i);
        CHECK(mt_live_device_offer(&D,first+b*128,samples,128));
    }
}
static mt_live_tx_ticket before_final(unsigned queued) {
    mt_live_tx_ticket ticket;setup(5);offer(8);CHECK(tick() && D.batch.count==512 && !D.tx_length);
    CHECK(tick() && D.batch.phase==MT_BATCH1024_READY && D.tx_offset==384 && !D.queue.used);
    offer(queued);
    while(D.tx_length-D.tx_offset>384)CHECK(tick());
    CHECK(prepare(&ticket)==MT_LIVE_TX_PREPARED && ticket.tx_offset>0 && ticket.tx_count==1024);
    CHECK(!mt_live_device_prefetch_ready(&D,&ticket));return ticket;
}
static void final_commit(mt_live_tx_ticket*t) {
    CHECK(submit(t,owner.epoch,owner.soft_serial));
    CHECK(D.prefix_end==1024 && D.prefix_crc_state==expected_crc(1024));
    CHECK(!D.tx_length && D.batch.phase==MT_BATCH1024_EMPTY && D.last_data_sequence==t->tx_sequence);
}
static mt_live_runtime_result after_flush(mt_live_tx_ticket*t) {
    /* Existing flush/final-clock barrier is a seam; the actual extracted helper
     * starts AFTER it. No stub here pretends that a USB IN has completed. */
    CHECK(!depth && !actor);++flushes;
    if(live_time(&owner)==UINT64_MAX)return time_fault(&owner);
    if(!synchronize_loss(&owner))return loss_result(&owner);
    if(post_flush_event){unsigned e=post_flush_event;post_flush_event=0;inject(e);}
    helper_active=1;cycle_in_helper=0;
    /* 3/4 are the stamps saved at the ORIGINAL prepare in this model's pass,
     * not newly captured after a cleanup or a later scope admission. */
    mt_live_runtime_result result=prefetch_after_tx(&owner,t,3,4);
    helper_active=0;CHECK(!depth && !actor);return result;
}
static unsigned decode_one(size_t at,size_t*next) {
    size_t end=at;unsigned n=0;while(end<wire_used && wire[end])++end;CHECK(end<wire_used);
    while(at<end){unsigned code=wire[at++];CHECK(code && code-1<=end-at && code-1<=sizeof decoded-n);
        for(unsigned i=1;i<code;i++){CHECK(wire[at]);decoded[n++]=wire[at++];}
        if(code!=255 && at<end){CHECK(n<sizeof decoded);decoded[n++]=0;}
    }
    CHECK(n>=28 && r16(decoded+4)+28u==n && (crc_raw(UINT32_MAX,decoded,n-4)^UINT32_MAX)==r32(decoded+n-4));
    CHECK(decoded[0]==0 && decoded[1]==3 && decoded[3]==0 && r16(decoded+6)==0);*next=end+1;return n;
}
static void check_data(uint64_t expected_end,unsigned expected_frames,unsigned last_count,unsigned expect_end) {
    size_t at=0,next;uint64_t index=0;uint32_t crc=UINT32_MAX,sequence=4;unsigned frames=0,ends=0;
    while(at<wire_used){unsigned n=decode_one(at,&next);CHECK(r64(decoded+8)==503 && r32(decoded+16)==sequence++);
        if(decoded[2]==152){
            unsigned count=r16(decoded+40),off=44,bits=0;uint32_t pending=0;
            CHECK(r32(decoded+24)==3 && r32(decoded+28)==5 && r64(decoded+32)==index && !r16(decoded+42));
            CHECK(count && count<=1024 && n==48u+(count*10u+7u)/8u);
            CHECK(count==(frames+1==expected_frames?last_count:1024));
            for(unsigned i=0;i<count;i++){
                while(bits<10){pending|=(uint32_t)decoded[off++]<<bits;bits+=8;}
                uint16_t value=(uint16_t)((pending&1023u)<<2);pending>>=10;bits-=10;
                CHECK(value==(pattern(index+i)&4092u));crc=crc_byte(crc,(uint8_t)value);crc=crc_byte(crc,(uint8_t)(value>>8));
            }
            CHECK(!pending);index+=count;++frames;
        }else if(decoded[2]==153){
            CHECK(r64(decoded+32)==index && r32(decoded+52)==(crc^UINT32_MAX) && !r16(decoded+56));++ends;
        }else CHECK(decoded[2]==133);
        at=next;
    }
    CHECK(index==expected_end && frames==expected_frames && ends==expect_end);
}
static void stop_request(void) { uint8_t p[4]={3,0,0,0};command(3,5,503,4,4,p,4); }
static void drain(void) { unsigned n=0;while(D.state!=MT_LIVE_NEEDS_HELLO){CHECK(++n<40 && tick());} }

static void ownership_and_bytes(void) {
    const unsigned queued[]={0,1,4,8};
    for(unsigned i=0;i<4;i++){
        mt_live_tx_ticket old=before_final(queued[i]);final_commit(&old);
        unsigned prior_writes=writes,prior_clocks=core_clocks,prior_stops=stops,prior_count=mt_stream_progress.prepare_count;
        uint32_t sequence=D.tx_next,crc=D.prefix_crc_state;
        CHECK(after_flush(&old)==MT_LIVE_RUNTIME_OK);
        unsigned taken=queued[i]>4?4:queued[i];
        CHECK(D.queue.used==queued[i]-taken && D.batch.count==taken*128);
        CHECK(D.batch.phase==(taken?MT_BATCH1024_COLLECT:MT_BATCH1024_EMPTY));
        CHECK(!D.tx_length && !D.tx_offset && D.prefix_end==1024 && D.prefix_crc_state==crc && D.tx_next==sequence);
        CHECK(writes==prior_writes && core_clocks==prior_clocks && stops==prior_stops);
        CHECK(mt_stream_progress.prepare_count==prior_count+(taken?1u:0u));
        if(taken){CHECK(D.batch.prefix_crc==expected_crc(1024+taken*128));CHECK(!mt_live_device_prefetch_ready(&D,&old));}
        if(queued[i]==8){
            offer(4);CHECK(D.queue.used==8 && D.queue.next_index==2560);
            CHECK(tick());while(D.tx_length)CHECK(tick());
            CHECK(D.prefix_end==2048 && D.prefix_crc_state==expected_crc(2048));
            check_data(2048,2,1024,0);
        }else{stop_request();drain();check_data(1024+taken*128,taken?2:1,taken?taken*128:1024,1);}
    }
    /* Real queue views wrap7->0; fourth stale descriptor cannot partially pop. */
    mt_sample_queue q,saved;mt_sample_block views[4];uint16_t samples[128]={0};
    mt_sample_queue_init(&q,0);
    for(unsigned i=0;i<7;i++){CHECK(mt_sample_queue_push(&q,i*128,samples,128,0)==MT_SAMPLE_QUEUE_OK);CHECK(mt_sample_queue_pop(&q,i*128)==MT_SAMPLE_QUEUE_OK);}
    for(unsigned i=0;i<4;i++)CHECK(mt_sample_queue_push(&q,896+i*128,samples,128,0)==MT_SAMPLE_QUEUE_OK);
    CHECK(mt_sample_queue_peek_many(&q,views,4)==MT_SAMPLE_QUEUE_OK && views[0].samples==q.samples[7] && views[3].samples==q.samples[2]);
    saved=q;--views[3].count;CHECK(mt_sample_queue_pop_many(&q,views,4)==MT_SAMPLE_QUEUE_STALE && !memcmp(&q,&saved,sizeof q));
    ++views[3].count;CHECK(mt_sample_queue_pop_many(&q,views,4)==MT_SAMPLE_QUEUE_OK && q.head==3 && !q.used);
    puts("PASS actual final commit/CRC -> flush seam -> collect0/128/512; q8->4 plus four offers; next wire bytes/END; atomic wrapped views; active SJ span");
}

static void reject_without_mutation(mt_live_tx_ticket*t) {
    mt_live_device saved=D;mt_live_tx_ticket saved_ticket=*t;
    unsigned prior=writes+core_clocks+stops;
    CHECK(!mt_live_device_prefetch_ready(&D,t));CHECK(mt_live_device_prefetch_tx(&D,t)==MT_LIVE_TX_EMPTY);
    CHECK(!memcmp(&saved,&D,sizeof D) && !memcmp(&saved_ticket,t,sizeof *t) && writes+core_clocks+stops==prior);
}
static void eligibility_and_terminals(void) {
    mt_live_tx_ticket old=before_final(4),valid;final_commit(&old);valid=old;mt_live_device saved=D;
#define REJECT_DEVICE(change) do { D=saved;old=valid;change;reject_without_mutation(&old); } while(0)
#define REJECT_TICKET(change) do { D=saved;old=valid;change;reject_without_mutation(&old); } while(0)
    REJECT_DEVICE(++D.nonce);REJECT_DEVICE(++D.generation);REJECT_DEVICE(++D.revision);
    REJECT_DEVICE(++D.prefix_end);REJECT_DEVICE(D.prefix_crc_state^=1u);REJECT_DEVICE(++D.last_data_sequence);
    REJECT_DEVICE(D.tx_next=UINT32_C(0xffffff00));REJECT_DEVICE(D.tx_exhausted=1);REJECT_DEVICE(D.queue.sealed=1);
    REJECT_DEVICE(D.stop_budget=1);REJECT_DEVICE(D.hello_budget=1);REJECT_DEVICE(D.inherited_budget=1);
    REJECT_DEVICE(D.want_caps=1);REJECT_DEVICE(D.want_error=1);REJECT_DEVICE(D.want_start=1);
    REJECT_DEVICE(D.want_end=1);REJECT_DEVICE(D.want_ack=1);REJECT_DEVICE(D.stop_seen=1);
    REJECT_DEVICE(D.state=MT_LIVE_HELLO_PENDING);REJECT_DEVICE(D.state=MT_LIVE_DRAINING);
    REJECT_DEVICE(D.queue.head_index+=128);REJECT_DEVICE(D.queue.next_index+=128);REJECT_DEVICE(--D.queue.used);
    REJECT_TICKET(old.tx_offset=0);REJECT_TICKET(old.batch.prefix_crc^=1u);REJECT_TICKET(++old.tx_sequence);
    REJECT_TICKET(old.tx_first_index=UINT64_MAX-512);REJECT_TICKET(old.tx_type=129);
    for(unsigned mode=1;mode<=4;mode++){D=saved;old=valid;D.mode=old.mode=(uint16_t)mode;reject_without_mutation(&old);}
#undef REJECT_DEVICE
#undef REJECT_TICKET
    /* Zero, non-final partial, unknown and last-TIME fault are real submits. */
    for(unsigned variant=0;variant<4;variant++){
        old=before_final(4);write_limit=variant==0?0:variant==1?17:SIZE_MAX;
        unknown_write=variant==2;late_final=variant==3;
        int result=submit(&old,owner.epoch,owner.soft_serial);final_armed=0;
        CHECK(result==(variant<2));CHECK(!D.prefix_end);reject_without_mutation(&old);
    }
    old=before_final(4);unsigned w=writes;
    CHECK(submit(&old,owner.epoch+1,owner.soft_serial) && writes==w);reject_without_mutation(&old);
    old=before_final(4);final_commit(&old);CHECK(after_flush(&old)==MT_LIVE_RUNTIME_OK && D.batch.count==512);
    uint64_t prefix=D.prefix_end;uint32_t crc=D.prefix_crc_state;size_t old_wire=wire_used;
    hello(3,777,5);CHECK(D.state==MT_LIVE_HELLO_PENDING && D.batch.phase==MT_BATCH1024_EMPTY && !D.tx_length);
    CHECK(D.prefix_end==prefix && D.prefix_crc_state==crc && wire_used==old_wire);
    finish_control();CHECK(D.nonce==777 && !D.prefix_end && !D.queue.used);
    puts("PASS exact completion certificate; stale/zero/partial/unknown/final-TIME/control/RESERVE/old modes rejected; Stop preserves owned tail, HELLO discards it");
}

static void runtime_boundaries_and_error(void) {
    const unsigned events[]={EVENT_EPOCH,EVENT_SOFT,EVENT_TIME,EVENT_LIFECYCLE};
    for(unsigned when=0;when<3;when++)for(unsigned i=0;i<4;i++){
        mt_live_tx_ticket old=before_final(8);final_commit(&old);
        unsigned prior_writes=writes;uint32_t crc=D.prefix_crc_state;
        if(!when)post_flush_event=events[i];else {inject_cycle=when;inject_event=events[i];}
        mt_live_runtime_result result=after_flush(&old);
        CHECK(result==(events[i]==EVENT_TIME?MT_LIVE_RUNTIME_TIME_FAULT:MT_LIVE_RUNTIME_RECOVERY));
        CHECK(cleanups==1 && writes==prior_writes && D.prefix_end==1024 && D.prefix_crc_state==crc);
        CHECK(D.batch.phase==MT_BATCH1024_EMPTY && !D.tx_length && progress_phase()==MT_N_FROZEN);
        /* begin/end are actual observer cycle seams around pure collect. */
        CHECK(D.queue.used==(when?4u:8u));CHECK(!depth && !actor);
    }
    mt_live_tx_ticket old=before_final(4);final_commit(&old);deny_scope=1;
    CHECK(after_flush(&old)==MT_LIVE_RUNTIME_IDLE && D.queue.used==4 && D.batch.phase==MT_BATCH1024_EMPTY);
    CHECK(after_flush(&old)==MT_LIVE_RUNTIME_OK && D.batch.count==512);
    /* A logically healthy NEW runtime identity cannot replace the original
     * pass stamps, even when synchronize_loss says success and usable is true. */
    for(unsigned soft=0;soft<2;soft++){
        old=before_final(4);final_commit(&old);
        if(soft){++owner.soft_serial;++env_soft;}else{++owner.epoch;++env_epoch;}
        unsigned scopes=scope_enters,writes_before=writes;
        CHECK(stable(&owner) && after_flush(&old)==MT_LIVE_RUNTIME_IDLE);
        CHECK(scope_enters==scopes && writes==writes_before && D.queue.used==4 && !D.batch.count && !cleanups);
    }
    old=before_final(4);final_commit(&old);enter_event=EVENT_EPOCH;
    CHECK(after_flush(&old)==MT_LIVE_RUNTIME_RECOVERY && D.queue.used==4 && !D.batch.count);
    /* Invalid canonical code in the last selected view: actual collect must
     * not partially pop; its current ERROR ticket alone enters guarded recovery. */
    old=before_final(4);final_commit(&old);D.queue.samples[(D.queue.head+3)%8][127]|=1u;
    unsigned w=writes,s=stops;uint32_t crc=D.prefix_crc_state;expect_guarded_cleanup=1;
    CHECK(after_flush(&old)==MT_LIVE_RUNTIME_RECOVERY);expect_guarded_cleanup=0;
    CHECK(old.result==MT_LIVE_TX_ERROR && old.error==MT_LIVE_ERR_ARGUMENT && old.batch.count==0);
    CHECK(writes==w && stops==s+1 && D.queue.used==4 && D.prefix_end==1024 && D.prefix_crc_state==crc);
    CHECK(progress_phase()==MT_N_FROZEN && mt_stream_progress.close_kind==MT_N_CLOSE_RECOVERY);
    first_frozen=mt_stream_progress;mt_progress_prepare_end(1);mt_progress_write_end(384,384);
    mt_progress_close(&D,MT_N_CLOSE_STOP,0);mt_stream_progress_record late=mt_stream_progress;
    CHECK(!memcmp(&late,&first_frozen,sizeof late));
    /* Epoch changes after collect/error scope leave but before its guard:
     * prepared_tx_step must not recover using that old error ticket. */
    old=before_final(4);final_commit(&old);D.queue.samples[D.queue.head][0]|=1u;
    leave_event=EVENT_EPOCH;s=stops;w=writes;
    CHECK(after_flush(&old)==MT_LIVE_RUNTIME_RECOVERY);
    CHECK(writes==w && stops==s+1 && D.local_error==MT_LIVE_ERR_TRANSPORT && D.prefix_end==1024);
    old=before_final(4);final_commit(&old);inject_cycle=1;inject_event=EVENT_FREEZE;
    CHECK(after_flush(&old)==MT_LIVE_RUNTIME_OK && have_frozen);
    late=mt_stream_progress;CHECK(!memcmp(&late,&first_frozen,sizeof late));
    CHECK((late.flags&MT_N_PARTIAL_PREPARE) && D.batch.count==512 && !depth && !actor);
    puts("PASS actual runtime prefetch helper: pre/begin/end epoch/soft/TIME/lifecycle, scope refusal, matching ERROR guard and stale ERROR quarantine; first-close immutable");
}
int main(void) {
    ownership_and_bytes();eligibility_and_terminals();runtime_boundaries_and_error();
    printf("build=0x%08lx; actual_core_queue_serializer_wire_progress=1; synthetic_legacy_time_usb=1; hardware_executed=0; throughput_claim=0\n",(unsigned long)MT_FIRMWARE_BUILD);
    return 0;
}
