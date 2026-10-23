#include "mt_stream_profile.h"
#include "mt_live_device.h"
#include "adc_timer_dma.h"
#include <limits.h>

volatile mt_stream_profile_record mt_stream_profile;
#define P mt_stream_profile
#define V(i) P.private_words[(i)]
#if MT_PROFILE_NATIVE
extern uint32_t mt_profile_native_read(uint32_t address);
extern uint32_t mt_profile_native_address(const void *pointer);
extern const void *mt_profile_native_pointer(uint32_t address);
static uint32_t read32(uint32_t address) { return mt_profile_native_read(address); }
static uint32_t address_of(const void *p) { return mt_profile_native_address(p); }
static const void *pointer_at(uint32_t p) { return mt_profile_native_pointer(p); }
#else
static uint32_t read32(uint32_t address) { return *(volatile uint32_t *)(uintptr_t)address; }
static uint32_t address_of(const void *p) { return (uint32_t)(uintptr_t)p; }
static const void *pointer_at(uint32_t p) { return (const void *)(uintptr_t)p; }
#endif
static void barrier(void) {
#if defined(__arm__) || defined(__thumb__)
    __asm__ volatile("dmb sy" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}
static int active(void) { return P.state==MT_P_ACTIVE; }
static void flag(unsigned irq,uint32_t bits) {
    if(irq)P.irq_flags|=bits;else P.fg_flags|=bits;
}
static void add(volatile uint32_t *value,uint32_t amount,unsigned irq) {
    if(UINT32_MAX-*value<amount) { *value=UINT32_MAX;flag(irq,1u); }
    else *value+=amount;
}
static uint32_t raw(unsigned irq) {
    uint32_t cycle=read32(UINT32_C(0xe0001004));
    if(active())add(&P.counters[irq?MT_P_C_IRQ_DWT_READS:MT_P_C_FG_DWT_READS],1,irq);
    return cycle;
}
static int dwt_ok(void) {
    uint32_t control=read32(UINT32_C(0xe0001000));
    return (read32(UINT32_C(0xe000edfc))&(1u<<24)) &&
        (control&1u) && !(control&(1u<<25));
}
static void stat(unsigned which,uint32_t cycles,unsigned irq) {
    volatile mt_profile_stat *s=&P.stats[which];
    add(&s->count,1,irq);add(&s->cycles_sum,cycles,irq);
    if(cycles>s->cycles_max)s->cycles_max=cycles;
}
static void indices(volatile mt_profile_indices *out) {
    const mt_live_device *d=pointer_at(V(MT_P_V_DEVICE_ADDRESS));
    const mt_adc_dma_t *a=pointer_at(V(MT_P_V_ADC_ADDRESS));
    if(!d || !a) { P.fg_flags|=MT_P_FG_METADATA_INVALID;return; }
    out->head_lo=(uint32_t)d->queue.head_index;out->head_hi=(uint32_t)(d->queue.head_index>>32);
    out->next_lo=(uint32_t)d->queue.next_index;out->next_hi=(uint32_t)(d->queue.next_index>>32);
    out->prefix_lo=(uint32_t)d->prefix_end;out->prefix_hi=(uint32_t)(d->prefix_end>>32);
    out->adc_lo=(uint32_t)a->first_sample_index;out->adc_hi=(uint32_t)(a->first_sample_index>>32);
}
void mt_profile_init(uint32_t build,const void *device,const void *adc) {
    uint32_t i,min=UINT32_MAX,max=0;
    if(P.state!=MT_P_EMPTY)return;
    P.magic=MT_PROFILE_MAGIC;P.version=MT_PROFILE_VERSION;P.bytes=sizeof P;
    P.firmware_build=build;
    V(MT_P_V_DEVICE_ADDRESS)=address_of(device);V(MT_P_V_ADC_ADDRESS)=address_of(adc);
    if(!dwt_ok())P.fg_flags|=MT_P_FG_DWT_INVALID;
    for(i=0;i<32u;++i) {
        uint32_t a=raw(0),b=raw(0),delta=b-a;
        if(delta<min)min=delta;
        if(delta>max)max=delta;
    }
    V(MT_P_V_PAIR_MIN)=min;V(MT_P_V_PAIR_MAX)=max;
    if(!max)P.fg_flags|=MT_P_FG_DWT_INVALID;
    barrier();P.state=MT_P_ARMED;
}
void mt_profile_attempt(uint32_t generation,uint64_t nonce,uint32_t epoch) {
    if(P.state!=MT_P_ARMED)return;
    P.generation=generation;P.epoch=epoch;P.nonce_lo=(uint32_t)nonce;P.nonce_hi=(uint32_t)(nonce>>32);
    if(!generation || !nonce || !epoch)P.fg_flags|=MT_P_FG_METADATA_INVALID;
}
void mt_profile_begin(uint32_t generation,uint64_t nonce,uint32_t epoch) {
    uint32_t after;
    if(P.state!=MT_P_ARMED)return;
    mt_profile_attempt(generation,nonce,epoch);
    indices(&P.initial);
    if(!dwt_ok())P.fg_flags|=MT_P_FG_DWT_INVALID;
    P.start_before=raw(0);barrier();P.state=MT_P_ACTIVE;after=raw(0);P.start_after=after;
    if(V(MT_P_V_PHASE_OPEN)) {
        V(MT_P_V_PHASE_START)=after;V(MT_P_V_PHASE_OPEN)=2;
        V(MT_P_V_BEGIN_PHASE_ID)=V(MT_P_V_PHASE_ID);P.fg_flags|=MT_P_FG_INITIAL_PHASE;
    }
    if(V(MT_P_V_STEP_OPEN)) {
        V(MT_P_V_STEP_START)=after;V(MT_P_V_STEP_OPEN)=2;P.fg_flags|=MT_P_FG_INITIAL_STEP;
    }
}
void mt_profile_close(unsigned kind,unsigned primary_reason) {
    uint32_t end,after;unsigned was_active=(unsigned)active();
    const mt_live_device *d;const mt_adc_dma_t *a;
    if(!active() && !(P.state==MT_P_ARMED && kind==MT_P_CLOSE_NO_START))return;
    if(!was_active) {
        V(MT_P_V_PHASE_OPEN)=V(MT_P_V_STEP_OPEN)=V(MT_P_V_TIME_OPEN)=V(MT_P_V_GRANT_OPEN)=0;
    }
    end=raw(0);P.state=MT_P_CLOSING;barrier();after=raw(0);
    P.end_before=end;P.end_after=after;
    if(kind>65535u || primary_reason>65535u)P.fg_flags|=MT_P_FG_METADATA_INVALID;
    P.close_kind_reason=((uint32_t)kind<<16)|(primary_reason&65535u);
    if(!dwt_ok())P.fg_flags|=MT_P_FG_DWT_INVALID;
    if(kind==MT_P_CLOSE_CAP && (uint32_t)(end-P.start_after)>MT_PROFILE_CAP_CYCLES)
        P.fg_flags|=MT_P_FG_CAP_OVERSHOOT;
    indices(&P.first.indices);
    d=pointer_at(V(MT_P_V_DEVICE_ADDRESS));a=pointer_at(V(MT_P_V_ADC_ADDRESS));
    if(d && a) {
        P.first.queue_used=d->queue.used;P.first.last_remaining=a->last_remaining;
        P.first.last_poll_us=a->last_poll_us;
        if((unsigned)d->state>65535u ||
           (unsigned)a->state>65535u || (unsigned)a->first_fault>65535u)
            P.fg_flags|=MT_P_FG_METADATA_INVALID;
        P.first.core_state_reason=(uint32_t)d->state|((uint32_t)d->first_reason<<16);
        P.first.adc_state_fault=(uint32_t)a->state|((uint32_t)a->first_fault<<16);
        P.first.core_local_error=d->local_error;
        P.first.tx_offset=(uint32_t)d->tx_offset;P.first.tx_length=(uint32_t)d->tx_length;
    }
    if(V(MT_P_V_PHASE_OPEN))P.first.open_phase_cycles=end-V(MT_P_V_PHASE_START);
    if(V(MT_P_V_STEP_OPEN))P.first.open_step_cycles=end-V(MT_P_V_STEP_START);
    if(V(MT_P_V_TIME_OPEN))P.first.open_time_cycles=end-V(MT_P_V_TIME_START);
    if(V(MT_P_V_GRANT_OPEN))P.first.open_grant_cycles=end-V(MT_P_V_GRANT_START);
    if(V(MT_P_V_PHASE_OPEN)||V(MT_P_V_STEP_OPEN)||V(MT_P_V_TIME_OPEN)||V(MT_P_V_GRANT_OPEN))
        P.fg_flags|=MT_P_FG_PARTIAL_END;
    barrier();P.state=MT_P_FROZEN;
}
void mt_profile_check_cap(void) {
    if(active() && (uint32_t)(raw(0)-P.start_after)>=MT_PROFILE_CAP_CYCLES)
        mt_profile_close(MT_P_CLOSE_CAP,0);
}
void mt_profile_phase_begin(unsigned phase) {
    if(P.state==MT_P_ARMED) { V(MT_P_V_PHASE_ID)=phase;V(MT_P_V_PHASE_OPEN)=1;return; }
    if(!active())return;
    if(V(MT_P_V_PHASE_OPEN)) { P.fg_flags|=MT_P_FG_NESTED;return; }
    V(MT_P_V_PHASE_ID)=phase;V(MT_P_V_PHASE_OPEN)=1;V(MT_P_V_PHASE_START)=raw(0);
    if(phase==MT_P_PHASE_TX) { V(MT_P_V_WRITE_KIND)=MT_P_WRITE_NONE;V(MT_P_V_WRITE_ACCEPTED)=0; }
}
void mt_profile_phase_end(int result) {
    uint32_t end,cycles,which=MT_P_TX_OTHER,phase;
    if(P.state==MT_P_ARMED) { V(MT_P_V_PHASE_OPEN)=0;V(MT_P_V_PHASE_ID)=0;return; }
    if(!active())return;
    if(!V(MT_P_V_PHASE_OPEN)) { P.fg_flags|=MT_P_FG_NESTED;return; }
    end=raw(0);cycles=end-V(MT_P_V_PHASE_START);phase=V(MT_P_V_PHASE_ID);
    if(V(MT_P_V_PHASE_OPEN)==2)V(MT_P_V_FIRST_PHASE_PARTIAL)=cycles;
    else {
        switch(phase) {
        case MT_P_PHASE_TASK:which=MT_P_TASK;break;
        case MT_P_PHASE_ADC:which=result==1?MT_P_ADC_BLOCK:MT_P_ADC_EMPTY;
            if(result!=0 && result!=1)P.fg_flags|=MT_P_FG_METADATA_INVALID;
            break;
        case MT_P_PHASE_RX:which=MT_P_RX;break;
        case MT_P_PHASE_TX:
            if(V(MT_P_V_WRITE_KIND)==MT_P_WRITE_POSITIVE)which=MT_P_TX_ACCEPT;
            else if(V(MT_P_V_WRITE_KIND)==MT_P_WRITE_ZERO_SPACE || V(MT_P_V_WRITE_KIND)==MT_P_WRITE_ZERO_OTHER)which=MT_P_TX_ZERO;
            break;
        case MT_P_PHASE_FLUSH:which=MT_P_FLUSH;break;
        case MT_P_PHASE_GRANT:which=MT_P_GRANT_CALL;break;
        default:P.fg_flags|=MT_P_FG_METADATA_INVALID;break;
        }
        stat(which,cycles,0);
    }
    V(MT_P_V_PHASE_OPEN)=0;V(MT_P_V_PHASE_ID)=0;
}
void mt_profile_step_begin(void) {
    if(P.state==MT_P_ARMED) { V(MT_P_V_STEP_OPEN)=1;return; }
    if(!active())return;
    if(V(MT_P_V_STEP_OPEN)) { P.fg_flags|=MT_P_FG_NESTED;return; }
    V(MT_P_V_STEP_OPEN)=1;V(MT_P_V_STEP_START)=raw(0);
}
void mt_profile_step_end(void) {
    uint32_t delta;
    if(P.state==MT_P_ARMED) { V(MT_P_V_STEP_OPEN)=0;return; }
    if(!active())return;
    if(!V(MT_P_V_STEP_OPEN)) { P.fg_flags|=MT_P_FG_NESTED;return; }
    delta=raw(0)-V(MT_P_V_STEP_START);
    if(V(MT_P_V_STEP_OPEN)==2)V(MT_P_V_FIRST_STEP_PARTIAL)=delta;
    else stat(MT_P_STEP,delta,0);
    V(MT_P_V_STEP_OPEN)=0;
}
void mt_profile_time_begin(void) {
    if(!active())return;
    if(V(MT_P_V_TIME_OPEN)) { P.fg_flags|=MT_P_FG_NESTED;return; }
    V(MT_P_V_TIME_OPEN)=1;V(MT_P_V_TIME_START)=raw(0);
}
void mt_profile_time_end(void) {
    if(!active())return;
    if(!V(MT_P_V_TIME_OPEN)) { P.fg_flags|=MT_P_FG_NESTED;return; }
    stat(MT_P_TIME_UPDATE,raw(0)-V(MT_P_V_TIME_START),0);V(MT_P_V_TIME_OPEN)=0;
}
void mt_profile_write_result(unsigned kind,size_t accepted) {
    if(!active())return;
    V(MT_P_V_WRITE_KIND)=kind;V(MT_P_V_WRITE_ACCEPTED)=kind==MT_P_WRITE_POSITIVE?(uint32_t)accepted:0;
    if(kind==MT_P_WRITE_POSITIVE)add(&P.counters[MT_P_C_ACCEPTED_BYTES],(uint32_t)accepted,0);
    else if(kind==MT_P_WRITE_ZERO_SPACE)add(&P.counters[MT_P_C_ZERO_SPACE],1,0);
    else if(kind==MT_P_WRITE_ZERO_OTHER)add(&P.counters[MT_P_C_ZERO_OTHER],1,0);
    else if(kind==MT_P_WRITE_UNKNOWN)add(&P.counters[MT_P_C_WRITE_UNKNOWN],1,0);
    else P.fg_flags|=MT_P_FG_METADATA_INVALID;
}
void mt_profile_write_return(size_t accepted,size_t offered) {
    if(!active())return;
    if(accepted==SIZE_MAX || accepted>offered)mt_profile_write_result(MT_P_WRITE_UNKNOWN,0);
    else if(accepted)mt_profile_write_result(MT_P_WRITE_POSITIVE,accepted);
    else if(V(MT_P_V_WRITE_KIND)!=MT_P_WRITE_ZERO_SPACE)mt_profile_write_result(MT_P_WRITE_ZERO_OTHER,0);
}
void mt_profile_adc_offered(unsigned count) { if(active())add(&P.counters[MT_P_C_ADC_OFFERED],count,0); }
void mt_profile_data_committed(unsigned count) { if(active())add(&P.counters[MT_P_C_DATA_COMMITTED],count,0); }
void mt_profile_grant(unsigned ctr) {
    uint32_t cycle;
    if(!active())return;
    cycle=raw(0);
    if(V(MT_P_V_GRANT_OPEN))stat(MT_P_GRANT_INTERVAL,cycle-V(MT_P_V_GRANT_START),0);
    V(MT_P_V_GRANT_START)=cycle;V(MT_P_V_GRANT_OPEN)=1;V(MT_P_V_GRANT_SEEN_IN)=0;
    add(&P.counters[ctr?MT_P_C_GRANT_ALLOWED:MT_P_C_GRANT_DENIED],1,0);
}
void mt_profile_transfer(uint8_t ep,unsigned bytes) {
    if(!active() || ep!=0x82u)return;
    add(&P.counters[MT_P_C_IN_TRANSFERS],1,0);add(&P.counters[MT_P_C_IN_TRANSFER_BYTES],bytes,0);
    if(!bytes)add(&P.counters[MT_P_C_ZLP_TRANSFERS],1,0);
}
mt_profile_irq_ticket mt_profile_irq_begin(void) {
    mt_profile_irq_ticket ticket={0,0};
    if(active()) { ticket.start=raw(1);ticket.active=1; }return ticket;
}
void mt_profile_irq_end(mt_profile_irq_ticket ticket) {
    if(active() && ticket.active)stat(MT_P_USB_ISR,raw(1)-ticket.start,1);
}
void mt_profile_in_packet(unsigned queued,unsigned total,unsigned mps) {
    uint32_t cycle,bytes;
    if(!active())return;
    cycle=raw(1);add(&P.counters[MT_P_C_IN_PACKETS],1,1);
    if((P.irq_flags&MT_P_IRQ_HAVE_IN) && cycle-V(MT_P_V_LAST_IN_CYCLE)>P.counters[MT_P_C_IN_GAP_MAX_CYCLES])
        P.counters[MT_P_C_IN_GAP_MAX_CYCLES]=cycle-V(MT_P_V_LAST_IN_CYCLE);
    V(MT_P_V_LAST_IN_CYCLE)=cycle;P.irq_flags|=MT_P_IRQ_HAVE_IN;
    if(mps!=64u || total>384u || queued>total || (!queued && total) ||
       (queued<total && (queued&63u)))P.irq_flags|=MT_P_IRQ_PACKET_INVALID;
    else {
        bytes=!total?0u:(queued==total && (total&63u)?total&63u:64u);
        add(&P.counters[MT_P_C_IN_PACKET_BYTES],bytes,1);
    }
    if(V(MT_P_V_GRANT_OPEN) && !V(MT_P_V_GRANT_SEEN_IN)) {
        stat(MT_P_GRANT_FIRST_IN_DELAY,cycle-V(MT_P_V_GRANT_START),1);V(MT_P_V_GRANT_SEEN_IN)=1;
    }
}
int mt_profile_guard(unsigned reason,int actual_condition) {
    unsigned counter=MT_P_C_HOLD_OTHER;
    if(active() && !actual_condition) {
        switch(reason) {
        case MT_P_HOLD_FINAL:counter=MT_P_C_HOLD_FINAL;break;
        case MT_P_HOLD_BUDGET:counter=MT_P_C_HOLD_BUDGET;break;
        case MT_P_HOLD_TIME:counter=MT_P_C_HOLD_TIME;break;
        case MT_P_HOLD_LIFECYCLE:counter=MT_P_C_HOLD_LIFECYCLE;break;
        default:break;
        }
        add(&P.counters[counter],1,1);
    }
    return actual_condition;
}
void mt_profile_burst_resume(void) { if(active())add(&P.counters[MT_P_C_BURST_RESUME],1,1); }
