/* One narrow actual-core harness, compiled separately with exact S8 and the
 * candidate. The runner compares emitted transcripts; no serialization or
 * commit algorithm is reproduced here. Logical callbacks are not USB timing. */
#include "protocol/mt_live_device.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef MT_TEST_BASELINE
#define MT_TEST_BASELINE 0
#endif
#define CHECK(c) do { if(!(c)) { fprintf(stderr,"FAIL TX prepare line%d: %s\n",__LINE__,#c);exit(1); } } while(0)
#define NONCE UINT64_C(0x1234567800abcdef)
#define NEW_NONCE UINT64_C(0x1234567800abcdee)
/* Declaration-only boundary for the actual runtime helper inserted below. */
typedef struct { mt_live_device device;uint32_t epoch,soft_serial; } mt_live_runtime;
static mt_live_runtime owner;
#define D owner.device
static unsigned guard_depth,transport_allowed;
static unsigned clocks,writes,starts,stops,isolates,fail_clock,after_write_clock,fail_after_write;
static unsigned unknown_write,deadline_after_write;
static size_t write_limit,wire_used;
static unsigned char wire[16384];
static uint64_t clock_value;

static uint64_t fake_clock(void *context) {
    CHECK(context==&owner);++clocks;
    if(writes && (fail_after_write || deadline_after_write)) {
        ++after_write_clock;
        if(fail_after_write && after_write_clock==fail_after_write)return UINT64_MAX;
        if(deadline_after_write && after_write_clock==deadline_after_write)return D.stop_deadline;
    }
    return fail_clock && clocks==fail_clock ? UINT64_MAX : clock_value;
}
static int fake_start(void *context,uint32_t generation) {
    CHECK(context==&owner && generation==3);++starts;return 1;
}
static void fake_stop(void *context,mt_live_snapshot *out) {
    CHECK(context==&owner);++stops;memset(out,0,sizeof *out);out->hardware_off=1;
    /* Empty certified tail, unknown produced end: no fictitious sample count. */
}
static int fake_isolate(void *context) { CHECK(context==&owner);++isolates;return 1; }
static size_t fake_write(void *context,const uint8_t *bytes,size_t count) {
    CHECK(context==&owner && guard_depth==1 && count<=384);++writes;
    if(unknown_write)return SIZE_MAX;
    if(count>write_limit)count=write_limit;
    CHECK(wire_used+count<=sizeof wire);memcpy(wire+wire_used,bytes,count);wire_used+=count;
    return count;
}
#if !MT_TEST_BASELINE
static int usable(mt_live_runtime *r) { CHECK(r==&owner && guard_depth==1);return (int)transport_allowed; }
static int prepared_tx_step(mt_live_runtime *r,const mt_live_tx_ticket *ticket,
                             uint32_t prepared_epoch,uint32_t prepared_soft_serial) {
    if(r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial || !usable(r))return 1;
    return mt_live_device_step_prepared(&r->device,ticket);
}

static int submit(const mt_live_tx_ticket *ticket,uint32_t epoch,uint32_t serial) {
    int result;CHECK(!guard_depth);guard_depth=1;
    result=prepared_tx_step(&owner,ticket,epoch,serial);guard_depth=0;return result;
}
#endif
static int run_step(void) {
#if MT_TEST_BASELINE
    int result;CHECK(!guard_depth);guard_depth=1;result=mt_live_device_step(&D);guard_depth=0;return result;
#else
    mt_live_tx_ticket ticket;uint32_t epoch=owner.epoch,serial=owner.soft_serial;
    CHECK(!guard_depth);(void)mt_live_device_prepare_tx(&D,&ticket);
    return submit(&ticket,epoch,serial);
#endif
}
static void command(unsigned type,uint64_t nonce,uint32_t sequence,uint32_t request,uint64_t payload,unsigned bytes) {
    mt_wire_message m;uint8_t frame[MT_WIRE_FRAME_MAX];size_t length;
    memset(&m,0,sizeof m);m.type=(uint8_t)type;m.session=nonce;m.sequence=sequence;m.request=request;
    m.payload_length=(uint16_t)bytes;
    for(unsigned i=0;i<bytes;++i)m.payload[i]=(uint8_t)(payload>>(8u*i));
    CHECK(mt_wire_encode_revision(&m,0,2,frame,sizeof frame,&length)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&D,frame,length));
}
static void reset(void) {
    mt_live_io io={.context=&owner,.clock_ms=fake_clock,.start=fake_start,.quiesce=fake_stop,
        .write=fake_write,.isolate_tx=fake_isolate,.transaction_bound_ms=1,.firmware_build=0x56325338u};
    memset(&owner,0,sizeof owner);memset(wire,0,sizeof wire);
    guard_depth=clocks=writes=starts=stops=isolates=fail_clock=after_write_clock=fail_after_write=0;
    unknown_write=deadline_after_write=0;transport_allowed=1;write_limit=SIZE_MAX;wire_used=0;clock_value=1;
    owner.epoch=3;owner.soft_serial=4;CHECK(mt_live_device_init(&D,&io));
}
static void session(void) {
    reset();command(1,0,1,1,NONCE,8);CHECK(run_step() && D.state==MT_LIVE_STOPPED);
    command(2,NONCE,2,2,0,0);CHECK(run_step() && D.caps_ready);
    command(8,NONCE,3,3,1,4);CHECK(run_step() && D.state==MT_LIVE_STREAMING && starts==1);
    CHECK(D.generation==3 && D.tx_next==4);
}
static void offer(unsigned first) {
    uint16_t samples[128];for(unsigned i=0;i<128;++i)samples[i]=(uint16_t)((first+i)*13u&4095u);
    CHECK(mt_live_device_offer(&D,first,samples,128));
}
static void stop_command(void) { command(5,NONCE,4,4,3,4); }
static void drain(void) {
    unsigned count=0;while(D.state!=MT_LIVE_NEEDS_HELLO) { CHECK(++count<=16);CHECK(run_step()); }
    CHECK(D.end_complete && D.hardware_off && D.first_reason==0 && D.terminal_flags==3);
}
static unsigned decode_all(mt_wire_message *last) {
    size_t at=0;unsigned count=0;
    while(at<wire_used) {
        size_t end=at;while(end<wire_used && wire[end])++end;CHECK(end<wire_used);
        CHECK(mt_wire_decode_revision(wire+at,end-at,0,2,last)==MT_WIRE_OK);++count;at=end+1;
    }
    return count;
}
static void append_transcript(FILE *out) {
    uint8_t length[4];CHECK(wire_used<=UINT32_MAX);
    for(unsigned i=0;i<4;++i)length[i]=(uint8_t)(wire_used>>(8u*i));
    CHECK(fwrite(length,1,4,out)==4 && fwrite(wire,1,wire_used,out)==wire_used);
}
static void bytes_zero_partial(FILE *out) {
    for(unsigned mode=0;mode<3;++mode) {
        mt_wire_message last;size_t before;uint32_t seq;
        session();offer(0);offer(128);before=wire_used;seq=D.tx_next;
        if(mode==1) {
            write_limit=0;CHECK(run_step());
            CHECK(wire_used==before && !D.tx_offset && D.tx_next==seq && D.prefix_end==0 && D.queue.used==2);
        } else if(mode==2) {
            write_limit=17;CHECK(run_step());CHECK(wire_used==before+17 && D.tx_offset==17);
            CHECK(D.tx_next==seq+1 && D.prefix_end==0 && D.queue.used==2);
            write_limit=0;CHECK(run_step());CHECK(D.tx_offset==17 && wire_used==before+17);
            CHECK(D.tx_next==seq+1 && D.prefix_end==0 && D.queue.used==2);
        }
        write_limit=SIZE_MAX;CHECK(run_step() && D.prefix_end==128 && D.queue.used==1);
        stop_command();drain();CHECK(D.prefix_end==256 && !D.queue.used);
        CHECK(decode_all(&last)==7 && last.type==133 && last.session==NONCE);
        append_transcript(out);
    }
    puts("PASS actual S8/candidate transcript fixtures: HELLO/CAPS/START/DATA/END/ACK; zero and partial acceptance");
}

#if !MT_TEST_BASELINE
static void prepare_only_tx(mt_live_tx_ticket *ticket,mt_live_prepare_result expected) {
    mt_live_device before,after;unsigned count=clocks+writes+starts+stops+isolates;
    memcpy(&before,&D,sizeof before);
    CHECK(!guard_depth && mt_live_device_prepare_tx(&D,ticket)==expected);
    CHECK(count==clocks+writes+starts+stops+isolates);memcpy(&after,&D,sizeof after);
    /* Exclude only the documented staging region. Compare all other device
     * bytes, including queue, prefix, CRC, reasons and accepted-byte record. */
    memcpy(after.tx,before.tx,sizeof after.tx);after.tx_length=before.tx_length;after.tx_offset=before.tx_offset;
    after.tx_type=before.tx_type;after.tx_nonce=before.tx_nonce;after.tx_first_index=before.tx_first_index;
    after.tx_count=before.tx_count;after.tx_sequence=before.tx_sequence;
    CHECK(!memcmp(&before,&after,sizeof before));
}
static void stale_no_write(const mt_live_tx_ticket *ticket) {
    mt_live_device before;unsigned count=writes;size_t bytes=wire_used;memcpy(&before,&D,sizeof before);
    CHECK(submit(ticket,owner.epoch,owner.soft_serial));
    CHECK(writes==count && wire_used==bytes && D.tx_next==before.tx_next);
    CHECK(D.prefix_end==before.prefix_end && D.prefix_crc_state==before.prefix_crc_state);
    CHECK(D.tx_length==before.tx_length && D.tx_offset==before.tx_offset);
    CHECK(!memcmp(&D.queue,&before.queue,sizeof D.queue) && D.local_error==before.local_error);
}
static void prepare_lifecycle(void) {
    mt_live_tx_ticket ticket,again;mt_live_device staged;mt_wire_message last;
    unsigned before;size_t accepted;
    session();prepare_only_tx(&ticket,MT_LIVE_TX_EMPTY);offer(0);
    prepare_only_tx(&ticket,MT_LIVE_TX_PREPARED);memcpy(&staged,&D,sizeof staged);
    prepare_only_tx(&again,MT_LIVE_TX_PREPARED);CHECK(!memcmp(&D,&staged,sizeof D));
    CHECK(submit(&again,owner.epoch,owner.soft_serial) && D.prefix_end==128);
    for(unsigned field=0;field<6;++field) {
        session();offer(0);prepare_only_tx(&ticket,MT_LIVE_TX_PREPARED);
        /* Deliberate unsupported interference only to test defensive stale
         * rejection; no legitimate concurrent foreground writer is claimed. */
        switch(field) {
        case 0:++D.nonce;break;case 1:++D.generation;break;
        case 2:++D.queue.head_index;break;case 3:++D.queue.head;break;
        case 4:++D.tx_next;break;default:++D.tx_sequence;break;
        }
        stale_no_write(&ticket);
    }
    for(unsigned boundary=0;boundary<3;++boundary) {
        uint32_t epoch,serial;session();offer(0);prepare_only_tx(&ticket,MT_LIVE_TX_PREPARED);
        epoch=owner.epoch;serial=owner.soft_serial;before=clocks+writes;memcpy(&staged,&D,sizeof staged);
        if(boundary==0)++owner.epoch;else if(boundary==1)++owner.soft_serial;else transport_allowed=0;
        CHECK(submit(&ticket,epoch,serial));CHECK(clocks+writes==before && !memcmp(&D,&staged,sizeof D));
    }
    session();offer(0);prepare_only_tx(&ticket,MT_LIVE_TX_PREPARED);stop_command();
    CHECK(D.state==MT_LIVE_DRAINING);stale_no_write(&ticket);
    CHECK(run_step() && D.prefix_end==128);drain();CHECK(decode_all(&last)==6 && last.type==133);

    session();offer(0);write_limit=17;CHECK(run_step() && D.tx_offset==17);
    prepare_only_tx(&ticket,MT_LIVE_TX_PREPARED);accepted=wire_used;
    command(1,0,1,1,NEW_NONCE,8);CHECK(D.state==MT_LIVE_HELLO_PENDING);
    stale_no_write(&ticket);CHECK(wire_used==accepted);
    write_limit=SIZE_MAX;CHECK(run_step() && D.state==MT_LIVE_HELLO_PENDING);
    CHECK(run_step() && D.state==MT_LIVE_STOPPED && D.nonce==NEW_NONCE);
    CHECK(decode_all(&last)==5 && last.type==129 && last.session==NEW_NONCE);

    session();offer(0);D.tx_next=0;before=stops;prepare_only_tx(&ticket,MT_LIVE_TX_ERROR);
    CHECK(ticket.error==MT_LIVE_ERR_PROTOCOL && D.local_error==0 && stops==before);
    CHECK(!submit(&ticket,owner.epoch,owner.soft_serial));
    CHECK(D.local_error==MT_LIVE_ERR_PROTOCOL && stops==before+1 && D.state==MT_LIVE_FAULT);
    session();offer(0);D.stop_budget=1;D.stop_deadline=10;
    prepare_only_tx(&ticket,MT_LIVE_TX_PREPARED);before=writes;accepted=wire_used;clock_value=10;
    CHECK(!submit(&ticket,owner.epoch,owner.soft_serial) && writes==before && wire_used==accepted);
    CHECK(D.local_error==MT_LIVE_ERR_DEADLINE && D.prefix_end==0);
    session();offer(0);D.tx_next=0;prepare_only_tx(&ticket,MT_LIVE_TX_ERROR);
    command(1,0,1,1,NEW_NONCE,8);stale_no_write(&ticket);
    CHECK(run_step() && D.state==MT_LIVE_STOPPED && D.nonce==NEW_NONCE && D.local_error==0);
    CHECK(decode_all(&last)==4 && last.session==NEW_NONCE);
    puts("PASS pure/cached prepare; stale core/epoch tickets; actual Stop and partial HELLO replacement; deferred error");
}
#endif
static void time_and_unknown(void) {
    size_t before;unsigned count;
    session();offer(0);before=wire_used;count=writes;clocks=0;fail_clock=3;
    CHECK(!run_step() && writes==count && wire_used==before);
    CHECK(D.local_error==MT_LIVE_ERR_CLOCK && D.prefix_end==0 && D.queue.used==1);
    for(unsigned late=1;late<=2;++late) {
        session();offer(0);before=wire_used;writes=0;fail_after_write=late;
        CHECK(!run_step() && wire_used>before && writes==1);
        CHECK(D.last_write_known && D.last_write_accepted==wire_used-before);
        CHECK(D.local_error==MT_LIVE_ERR_CLOCK);
        CHECK(D.prefix_end==(late==1?0u:128u) && D.queue.used==(late==1?1u:0u));
        if(late==1)CHECK(D.needs_delimiter);
    }
    session();offer(0);D.stop_budget=1;D.stop_deadline=10;before=wire_used;
    writes=0;write_limit=17;deadline_after_write=1;
    CHECK(!run_step() && wire_used==before+17 && D.needs_delimiter);
    CHECK(D.local_error==MT_LIVE_ERR_DEADLINE && D.prefix_end==0 && D.last_write_accepted==17);
    session();offer(0);before=wire_used;writes=0;unknown_write=1;
    CHECK(!run_step() && writes==1 && wire_used==before && !D.last_write_known);
    CHECK(D.local_error==MT_LIVE_ERR_TRANSPORT && D.needs_delimiter && D.prefix_end==0 && D.queue.sealed);
    puts("PASS TIME before/after write/final commit; late deadline retains known bytes; unknown acceptance fenced");
}
int main(int argc,char **argv) {
    FILE *out;CHECK(argc<=2);out=fopen(argc==2?argv[1]:"tx-transcript.bin","wb");CHECK(out);
    bytes_zero_partial(out);CHECK(!fclose(out));
#if !MT_TEST_BASELINE
    prepare_lifecycle();
#endif
    time_and_unknown();
    puts("PASS narrow actual-core TX model; baseline byte comparison is performed by runner, no physical timing claim");
    return 0;
}
