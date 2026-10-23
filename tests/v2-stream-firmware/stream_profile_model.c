/* Narrow SYNTHETIC/native model of the actual diagnostic bank, not USB/ADC
 * throughput or interrupt-scheduling evidence. Runtime hook order is checked
 * separately by the runner against the frozen S8/S9 sources. */
#include "mt_stream_profile.h"
#include "mt_live_device.h"
#include "adc_timer_dma.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#c); exit(1); } } while (0)
#define P mt_stream_profile
#define V(i) P.private_words[(i)]
#define BUILD UINT32_C(0x56325339)
#define NONCE UINT64_C(0x0123456789abcdef)
static mt_live_device device;
static mt_adc_dma_t adc;
static uint32_t cycle;
static unsigned inject_closing, closing_checked;
static mt_profile_irq_ticket late_irq;
static unsigned char witness[sizeof(mt_stream_profile_record)];

static void snapshot(unsigned char *out) {
    const volatile unsigned char *in=(const volatile unsigned char *)&P;
    size_t i; for(i=0;i<sizeof P;++i)out[i]=in[i];
}
static void unchanged(const unsigned char *before) {
    unsigned char after[sizeof P];snapshot(after);CHECK(!memcmp(before,after,sizeof P));
}
static void late_updates(void) {
    /* An already-entered wrapper may return after close; even the private
     * tickets and raw-read counters must then remain byte-for-byte frozen. */
    mt_profile_phase_end(1);mt_profile_step_end();mt_profile_time_end();
    mt_profile_irq_end(late_irq);mt_profile_grant(1);mt_profile_transfer(0x82,128);
    mt_profile_in_packet(64,128,64);mt_profile_write_return(128,128);
    mt_profile_adc_offered(512);mt_profile_data_committed(128);
    CHECK(mt_profile_guard(MT_P_HOLD_FINAL,0)==0);mt_profile_burst_resume();
    mt_profile_phase_begin(MT_P_PHASE_TX);mt_profile_step_begin();mt_profile_time_begin();
    CHECK(mt_profile_irq_begin().active==0);mt_profile_check_cap();
    mt_profile_attempt(99,99,99);mt_profile_begin(99,99,99);
    mt_profile_init(99,&device,&adc);mt_profile_close(MT_P_CLOSE_STOP,0);
}
uint32_t mt_profile_native_read(uint32_t address) {
    if(address==UINT32_C(0xe0001004)) {
        if(inject_closing && P.state==MT_P_CLOSING) {
            unsigned char before[sizeof P];inject_closing=0;snapshot(before);
            late_updates();unchanged(before);closing_checked=1;
        }
        return cycle++;
    }
    if(address==UINT32_C(0xe0001000))return 1;
    if(address==UINT32_C(0xe000edfc))return 1u<<24;
    CHECK(0);return 0;
}
uint32_t mt_profile_native_address(const void *pointer) {
    if(pointer==&device)return 0x100u;
    if(pointer==&adc)return 0x200u;
    CHECK(0);return 0;
}
const void *mt_profile_native_pointer(uint32_t address) {
    if(address==0x100u)return &device;
    if(address==0x200u)return &adc;
    CHECK(0);return NULL;
}
static void power_cycle(void) {
    /* Only this native fixture simulates a power cycle; production never
     * clears an armed/active/frozen bank to reuse a running observation. */
    volatile unsigned char *bytes=(volatile unsigned char *)&P;
    size_t i;for(i=0;i<sizeof P;++i)bytes[i]=0;
    memset(&device,0,sizeof device);memset(&adc,0,sizeof adc);
    device.state=MT_LIVE_STREAMING;adc.state=MT_ADC_DMA_RUNNING;
    adc.owns_peripherals=true;cycle=1000;inject_closing=closing_checked=0;
    late_irq.start=late_irq.active=0;
    mt_profile_init(BUILD,&device,&adc);
    CHECK(P.state==MT_P_ARMED && P.bytes==512 && P.fg_flags==0);
}
static void begin(void) {
    mt_profile_attempt(3,NONCE,7);mt_profile_begin(3,NONCE,7);
    CHECK(P.state==MT_P_ACTIVE && P.generation==3 && P.epoch==7);
}

static void freeze_and_no_start(void) {
    uint32_t initial_start,end;unsigned char before[sizeof P];
    power_cycle();mt_profile_step_begin();mt_profile_phase_begin(MT_P_PHASE_RX);begin();
    CHECK(V(MT_P_V_STEP_OPEN)==2 && V(MT_P_V_PHASE_OPEN)==2);
    CHECK((P.fg_flags&(MT_P_FG_INITIAL_STEP|MT_P_FG_INITIAL_PHASE))==24u);
    initial_start=P.start_after;cycle+=30;mt_profile_phase_end(0);mt_profile_step_end();
    CHECK(V(MT_P_V_FIRST_PHASE_PARTIAL)>0 && V(MT_P_V_FIRST_STEP_PARTIAL)>0);
    CHECK(P.stats[MT_P_RX].count==0 && P.stats[MT_P_STEP].count==0);
    CHECK(V(MT_P_V_PHASE_START)==initial_start);
    mt_profile_step_begin();mt_profile_phase_begin(MT_P_PHASE_TX);
    mt_profile_write_return(307,307);cycle+=40;mt_profile_phase_end(0);
    CHECK(P.counters[MT_P_C_ACCEPTED_BYTES]==307 && P.counters[MT_P_C_DATA_COMMITTED]==0);
    mt_profile_data_committed(128);mt_profile_adc_offered(512);
    CHECK(P.stats[MT_P_TX_ACCEPT].count==1 && P.counters[MT_P_C_DATA_COMMITTED]==128);
    mt_profile_phase_begin(MT_P_PHASE_ADC);mt_profile_time_begin();mt_profile_grant(1);
    late_irq=mt_profile_irq_begin();cycle+=50;
    device.queue.head_index=UINT64_C(0x100000020);
    device.queue.next_index=device.queue.head_index+1024;device.queue.used=8;
    device.prefix_end=device.queue.head_index;adc.first_sample_index=device.queue.head_index+2048;
    adc.last_remaining=512;adc.last_poll_us=123456;device.tx_offset=64;device.tx_length=307;
    CHECK(device.first_reason==0);end=cycle;inject_closing=1;
    mt_profile_close(MT_P_CLOSE_FAULT,1);
    CHECK(closing_checked && P.state==MT_P_FROZEN && P.end_before==end);
    CHECK(P.close_kind_reason==((MT_P_CLOSE_FAULT<<16)|1u));
    CHECK(P.first.core_state_reason==MT_LIVE_STREAMING && P.first.adc_state_fault==MT_ADC_DMA_RUNNING);
    CHECK(P.first.indices.head_hi==1 && P.first.indices.head_lo==32);
    CHECK(P.first.indices.next_lo==1056 && P.first.indices.adc_lo==2080);
    CHECK(P.first.queue_used==8 && P.first.last_poll_us==123456);
    CHECK(P.first.tx_offset==64 && P.first.tx_length==307);
    CHECK(P.first.open_phase_cycles==end-V(MT_P_V_PHASE_START));
    CHECK(P.first.open_step_cycles==end-V(MT_P_V_STEP_START));
    CHECK(P.first.open_time_cycles==end-V(MT_P_V_TIME_START));
    CHECK(P.first.open_grant_cycles==end-V(MT_P_V_GRANT_START));
    snapshot(before);device.first_reason=1;device.state=MT_LIVE_DRAINING;adc.state=MT_ADC_DMA_STOPPED;
    late_updates();unchanged(before);memcpy(witness,before,sizeof witness);

    power_cycle();mt_profile_step_begin();mt_profile_phase_begin(MT_P_PHASE_RX);
    mt_profile_attempt(42,NONCE,9);mt_profile_close(MT_P_CLOSE_NO_START,0);
    CHECK(P.state==MT_P_FROZEN && P.generation==42 && P.epoch==9);
    CHECK(P.nonce_lo==(uint32_t)NONCE && P.nonce_hi==(uint32_t)(NONCE>>32));
    CHECK(P.start_before==0 && P.start_after==0);
    CHECK(V(MT_P_V_PHASE_OPEN)==0 && V(MT_P_V_STEP_OPEN)==0);
    CHECK(P.first.open_phase_cycles==0 && P.first.open_step_cycles==0);
    CHECK(P.first.open_time_cycles==0 && P.first.open_grant_cycles==0);
    CHECK(!(P.fg_flags&MT_P_FG_PARTIAL_END));snapshot(before);late_updates();unchanged(before);
}
static void wrap_and_cap(void) {
    power_cycle();cycle=UINT32_MAX-100u;begin();cycle=UINT32_MAX-4u;
    mt_profile_phase_begin(MT_P_PHASE_TASK);cycle=15;mt_profile_phase_end(0);
    CHECK(P.stats[MT_P_TASK].count==1 && P.stats[MT_P_TASK].cycles_sum==20);
    mt_profile_close(MT_P_CLOSE_STOP,0);
    power_cycle();begin();mt_profile_step_begin();mt_profile_phase_begin(MT_P_PHASE_TASK);
    cycle=P.start_after+MT_PROFILE_CAP_CYCLES+73u;mt_profile_check_cap();
    CHECK(P.state==MT_P_FROZEN && P.close_kind_reason==(MT_P_CLOSE_CAP<<16));
    CHECK(P.end_before-P.start_after==MT_PROFILE_CAP_CYCLES+74u);
    CHECK(P.fg_flags&MT_P_FG_CAP_OVERSHOOT);
    CHECK(P.first.open_phase_cycles==P.end_before-V(MT_P_V_PHASE_START));
    CHECK(device.state==MT_LIVE_STREAMING && adc.state==MT_ADC_DMA_RUNNING && adc.owns_peripherals);
}
static void ownership_saturation_and_packets(void) {
    uint32_t fg_reads,fg_flags,irq_flags;mt_profile_irq_ticket ticket;
    power_cycle();begin();
    mt_profile_phase_begin(MT_P_PHASE_TX);mt_profile_write_return(307,307);mt_profile_phase_end(0);
    mt_profile_phase_begin(MT_P_PHASE_TX);CHECK(V(MT_P_V_WRITE_KIND)==MT_P_WRITE_NONE);
    CHECK(V(MT_P_V_WRITE_ACCEPTED)==0);
    mt_profile_write_result(MT_P_WRITE_ZERO_SPACE,0);mt_profile_write_return(0,307);mt_profile_phase_end(0);
    CHECK(P.counters[MT_P_C_ZERO_SPACE]==1 && P.counters[MT_P_C_ZERO_OTHER]==0);
    mt_profile_phase_begin(MT_P_PHASE_TX);CHECK(V(MT_P_V_WRITE_KIND)==MT_P_WRITE_NONE);
    mt_profile_phase_end(0); /* No writer called: do not inherit a previous TX result. */
    mt_profile_phase_begin(MT_P_PHASE_TX);mt_profile_write_return(SIZE_MAX,307);mt_profile_phase_end(0);
    CHECK(V(MT_P_V_WRITE_KIND)==MT_P_WRITE_UNKNOWN && V(MT_P_V_WRITE_ACCEPTED)==0);
    CHECK(P.stats[MT_P_TX_ACCEPT].count==1 && P.stats[MT_P_TX_ZERO].count==1);
    CHECK(P.stats[MT_P_TX_OTHER].count==2 && P.counters[MT_P_C_ACCEPTED_BYTES]==307);
    CHECK(P.counters[MT_P_C_WRITE_UNKNOWN]==1);
    mt_profile_grant(1);mt_profile_transfer(0x82,128);
    mt_profile_transfer(0x81,777);fg_reads=P.counters[MT_P_C_FG_DWT_READS];fg_flags=P.fg_flags;
    ticket=mt_profile_irq_begin();mt_profile_in_packet(64,128,64);mt_profile_in_packet(128,128,64);
    mt_profile_irq_end(ticket);
    CHECK(P.counters[MT_P_C_FG_DWT_READS]==fg_reads && P.fg_flags==fg_flags);
    CHECK(P.stats[MT_P_GRANT_FIRST_IN_DELAY].count==1 && P.stats[MT_P_USB_ISR].count==1);
    CHECK(P.counters[MT_P_C_IN_PACKET_BYTES]==128 && P.counters[MT_P_C_IN_TRANSFERS]==1);
    mt_profile_grant(0);CHECK(P.stats[MT_P_GRANT_INTERVAL].count==1);
    mt_profile_transfer(0x82,129);mt_profile_transfer(0x82,0);
    mt_profile_in_packet(129,129,64);mt_profile_in_packet(0,0,64);
    CHECK(P.stats[MT_P_GRANT_FIRST_IN_DELAY].count==2);
    CHECK(P.counters[MT_P_C_IN_PACKET_BYTES]==129 && P.counters[MT_P_C_ZLP_TRANSFERS]==1);
    CHECK(P.counters[MT_P_C_IN_TRANSFER_BYTES]==257);
    mt_profile_in_packet(1,128,64);
    CHECK((P.irq_flags&MT_P_IRQ_PACKET_INVALID) && P.counters[MT_P_C_IN_PACKET_BYTES]==129);
    CHECK(P.counters[MT_P_C_IN_PACKETS]==5 && P.counters[MT_P_C_IN_GAP_MAX_CYCLES]>0);
    /* Observe the caller's existing short circuit; never reevaluate a guard. */
    CHECK(!(mt_profile_guard(MT_P_HOLD_FINAL,0)&&mt_profile_guard(MT_P_HOLD_BUDGET,0)));
    CHECK(P.counters[MT_P_C_HOLD_FINAL]==1 && P.counters[MT_P_C_HOLD_BUDGET]==0);
    CHECK(mt_profile_guard(MT_P_HOLD_TIME,1)==1 && P.counters[MT_P_C_HOLD_TIME]==0);
    irq_flags=P.irq_flags;P.counters[MT_P_C_ADC_OFFERED]=UINT32_MAX-3u;mt_profile_adc_offered(4);
    CHECK(P.counters[MT_P_C_ADC_OFFERED]==UINT32_MAX && (P.fg_flags&MT_P_FG_SATURATED));
    CHECK(P.irq_flags==irq_flags);fg_flags=P.fg_flags;
    P.counters[MT_P_C_IRQ_DWT_READS]=UINT32_MAX;P.stats[MT_P_USB_ISR].count=UINT32_MAX;
    ticket=mt_profile_irq_begin();cycle+=10;mt_profile_irq_end(ticket);
    CHECK(P.counters[MT_P_C_IRQ_DWT_READS]==UINT32_MAX && P.stats[MT_P_USB_ISR].count==UINT32_MAX);
    CHECK((P.irq_flags&MT_P_IRQ_SATURATED) && P.fg_flags==fg_flags);
}
int main(int argc,char **argv) {
    const char *path=argc>1?argv[1]:"actual-profile.bin";FILE *out;
    CHECK(argc<=2);freeze_and_no_start();wrap_and_cap();ownership_saturation_and_packets();
    out=fopen(path,"wb");CHECK(out!=NULL);CHECK(fwrite(witness,1,sizeof witness,out)==sizeof witness);
    CHECK(fclose(out)==0);
    puts("PASS: 3 grouped actual-profile C checks; SYNTHETIC/NATIVE ONLY, not physical timing.");
    puts("Fixture: 512 bytes; build=0x56325339 generation=3 nonce=0x0123456789abcdef epoch=7.");
    return 0;
}
