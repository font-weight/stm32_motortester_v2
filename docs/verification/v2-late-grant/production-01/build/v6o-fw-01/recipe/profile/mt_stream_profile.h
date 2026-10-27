#ifndef MT_STREAM_PROFILE_H
#define MT_STREAM_PROFILE_H
#include <stdint.h>
#include <stddef.h>
#define MT_PROFILE_MAGIC UINT32_C(0x4d545046)
#define MT_PROFILE_VERSION 1u
#define MT_PROFILE_CAP_CYCLES UINT32_C(18000000)
enum { MT_P_EMPTY, MT_P_ARMED, MT_P_ACTIVE, MT_P_CLOSING, MT_P_FROZEN };
enum { MT_P_CLOSE_NONE, MT_P_CLOSE_FAULT, MT_P_CLOSE_STOP, MT_P_CLOSE_CAP,
       MT_P_CLOSE_TIME, MT_P_CLOSE_TRANSPORT, MT_P_CLOSE_NO_START,
       MT_P_CLOSE_RECOVERY, MT_P_CLOSE_ADC }; /* RECOVERY/ADC typed primaries. */
/* Each flag bank has exactly one writer; decoder combines validity, not RMW. */
enum { MT_P_FG_SATURATED=1u, MT_P_FG_NESTED=2u, MT_P_FG_DWT_INVALID=4u,
       MT_P_FG_INITIAL_STEP=8u, MT_P_FG_INITIAL_PHASE=16u,
       MT_P_FG_PARTIAL_END=32u, MT_P_FG_CAP_OVERSHOOT=64u,
       MT_P_FG_METADATA_INVALID=128u };
enum { MT_P_IRQ_SATURATED=1u, MT_P_IRQ_PACKET_INVALID=2u,
       MT_P_IRQ_HAVE_IN=4u }; /* HAVE_IN is history, not invalidity. */
enum { MT_P_TASK, MT_P_ADC_EMPTY, MT_P_ADC_BLOCK, MT_P_RX,
       MT_P_TX_ACCEPT, MT_P_TX_ZERO, MT_P_TX_OTHER, MT_P_FLUSH,
       MT_P_GRANT_CALL, MT_P_TIME_UPDATE, MT_P_USB_ISR,
       MT_P_GRANT_INTERVAL, MT_P_GRANT_FIRST_IN_DELAY, MT_P_STEP,
       MT_P_STAT_COUNT };
enum { MT_P_C_ADC_OFFERED, MT_P_C_DATA_COMMITTED, MT_P_C_ZERO_SPACE,
       MT_P_C_ZERO_OTHER, MT_P_C_WRITE_UNKNOWN, MT_P_C_ACCEPTED_BYTES,
       MT_P_C_IN_GAP_MAX_CYCLES, MT_P_C_FG_DWT_READS,
       MT_P_C_GRANT_ALLOWED, MT_P_C_GRANT_DENIED,
       MT_P_C_IN_TRANSFERS, MT_P_C_IN_TRANSFER_BYTES, MT_P_C_ZLP_TRANSFERS,
       MT_P_C_IN_PACKETS, MT_P_C_IN_PACKET_BYTES, MT_P_C_BURST_RESUME,
       MT_P_C_HOLD_FINAL, MT_P_C_HOLD_OTHER, MT_P_C_HOLD_BUDGET,
       MT_P_C_HOLD_TIME, MT_P_C_HOLD_LIFECYCLE, MT_P_C_IRQ_DWT_READS,
       MT_P_COUNTER_COUNT };
/* Generic FG phase identifiers; ADC/TX are classified on the actual return. */
enum { MT_P_PHASE_NONE, MT_P_PHASE_TASK, MT_P_PHASE_ADC, MT_P_PHASE_RX,
       MT_P_PHASE_TX, MT_P_PHASE_FLUSH, MT_P_PHASE_GRANT };
enum { MT_P_WRITE_NONE, MT_P_WRITE_POSITIVE, MT_P_WRITE_ZERO_SPACE,
       MT_P_WRITE_ZERO_OTHER, MT_P_WRITE_UNKNOWN };
enum { MT_P_HOLD_FINAL, MT_P_HOLD_OTHER, MT_P_HOLD_BUDGET,
       MT_P_HOLD_TIME, MT_P_HOLD_LIFECYCLE };
/* Private words are part of the frozen ABI: late epilogues never clear them. */
enum { MT_P_V_PHASE_ID, MT_P_V_PHASE_START, MT_P_V_PHASE_OPEN,
       MT_P_V_STEP_START, MT_P_V_STEP_OPEN, MT_P_V_TIME_START,
       MT_P_V_TIME_OPEN, MT_P_V_GRANT_START, MT_P_V_GRANT_OPEN,
       MT_P_V_GRANT_SEEN_IN, MT_P_V_WRITE_KIND, MT_P_V_WRITE_ACCEPTED,
       MT_P_V_FIRST_PHASE_PARTIAL, MT_P_V_FIRST_STEP_PARTIAL,
       MT_P_V_PAIR_MIN, MT_P_V_PAIR_MAX, MT_P_V_DEVICE_ADDRESS,
       MT_P_V_ADC_ADDRESS, MT_P_V_BEGIN_PHASE_ID, MT_P_V_LAST_IN_CYCLE,
       MT_P_PRIVATE_COUNT };
typedef struct { uint32_t count, cycles_sum, cycles_max; } mt_profile_stat;
typedef struct {
    uint32_t head_lo,head_hi,next_lo,next_hi,prefix_lo,prefix_hi,adc_lo,adc_hi;
} mt_profile_indices;
typedef struct {
    mt_profile_indices indices;
    uint32_t queue_used,last_remaining,last_poll_us;
    /* core_state low16 / core.first_reason high16; ADC state low16/fault high16.
     * The passed close reason lives separately in header.close_kind_reason. */
    uint32_t core_state_reason,adc_state_fault,core_local_error;
    uint32_t tx_offset,tx_length;
    uint32_t open_phase_cycles,open_step_cycles,open_time_cycles,open_grant_cycles;
} mt_profile_first_event;
typedef struct {
    uint32_t magic,version,bytes,firmware_build,state,fg_flags,irq_flags;
    uint32_t generation,epoch,nonce_lo,nonce_hi;
    uint32_t start_before,start_after,end_before,end_after;
    uint32_t close_kind_reason; /* high16 kind, low16 passed primary reason */
    mt_profile_stat stats[MT_P_STAT_COUNT];
    uint32_t counters[MT_P_COUNTER_COUNT];
    mt_profile_indices initial;
    mt_profile_first_event first;
    uint32_t private_words[MT_P_PRIVATE_COUNT];
} mt_stream_profile_record;
_Static_assert(MT_P_STAT_COUNT==14 && MT_P_COUNTER_COUNT==22 && MT_P_PRIVATE_COUNT==20,"profile slots");
_Static_assert(sizeof(mt_stream_profile_record)==512u,"profile ABI1, all static state in one bank");
_Static_assert(offsetof(mt_stream_profile_record,stats)==64u,"stats offset");
_Static_assert(offsetof(mt_stream_profile_record,counters)==232u,"counter offset");
_Static_assert(offsetof(mt_stream_profile_record,initial)==320u,"initial offset");
_Static_assert(offsetof(mt_stream_profile_record,first)==352u,"first-event offset");
_Static_assert(offsetof(mt_stream_profile_record,private_words)==432u,"private offset");
extern volatile mt_stream_profile_record mt_stream_profile;
/* init/begin/close and all FG probes have one foreground owner. Raw pointers
 * bind the exact mt_live_device/mt_adc_dma_t objects, never borrowed snapshots.
 * Native tests use explicit address-ID seams, not truncated native pointers. */
void mt_profile_init(uint32_t build,const void *device,const void *adc);
void mt_profile_attempt(uint32_t generation,uint64_t nonce,uint32_t epoch);
void mt_profile_begin(uint32_t generation,uint64_t nonce,uint32_t epoch);
void mt_profile_close(unsigned kind,unsigned primary_reason);
void mt_profile_check_cap(void);
void mt_profile_phase_begin(unsigned phase);
void mt_profile_phase_end(int result);
void mt_profile_step_begin(void);
void mt_profile_step_end(void);
void mt_profile_time_begin(void);
void mt_profile_time_end(void);
void mt_profile_write_result(unsigned kind,size_t accepted);
void mt_profile_write_return(size_t accepted,size_t offered);
void mt_profile_adc_offered(unsigned count);
void mt_profile_data_committed(unsigned count);
/* Called at actual existing guarded publication; IRQ counter ownership remains
 * separate. Publication bytes and completed packet bytes need not balance at
 * capture boundaries or for transfers already in flight at ACTIVE/close. */
void mt_profile_grant(unsigned ctr);
void mt_profile_transfer(uint8_t ep,unsigned bytes);
typedef struct { uint32_t start,active; } mt_profile_irq_ticket;
mt_profile_irq_ticket mt_profile_irq_begin(void);
void mt_profile_irq_end(mt_profile_irq_ticket ticket);
void mt_profile_in_packet(unsigned queued,unsigned total,unsigned mps);
int mt_profile_guard(unsigned reason,int actual_condition);
void mt_profile_burst_resume(void);
#endif
