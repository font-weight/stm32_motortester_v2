#ifndef MT_STREAM_PROGRESS_H
#define MT_STREAM_PROGRESS_H
#include <stddef.h>
#include <stdint.h>
#include "../protocol/mt_live_device.h"

#ifndef CFG_MT_PROGRESS_TRACE
#define CFG_MT_PROGRESS_TRACE 0
#endif
#if CFG_MT_PROGRESS_TRACE != 0 && CFG_MT_PROGRESS_TRACE != 1
#error "Progress trace must be explicitly 0 or 1"
#endif
#define MT_N_MAGIC UINT32_C(0x4d544e31) /* MTN1: fixed layout/version1,64 bytes. */
#if CFG_MT_PROGRESS_TRACE
#include "mt_firmware_build.h"
#ifndef MT_FIRMWARE_BUILD
#error "Progress trace requires generated target build identity"
#endif
#define MT_N_BUILD MT_FIRMWARE_BUILD /* Same config-derived identity as mt_board. */
#endif
#define MT_N_CAP_CYCLES UINT32_C(18000000) /* Nominal250ms at72MHz, checkpoint only. */
enum { MT_N_EMPTY, MT_N_ARMED, MT_N_ACTIVE, MT_N_CLOSING, MT_N_FROZEN };
enum {
    MT_N_PHASE_MASK=7u, MT_N_HAVE_POSITIVE=1u<<3, MT_N_SATURATED=1u<<4,
    MT_N_DWT_INVALID=1u<<5, MT_N_PARTIAL_WRITE=1u<<6, MT_N_UNKNOWN_WRITE=1u<<7,
    MT_N_PARTIAL_PREPARE=1u<<8, MT_N_CORE_SNAPSHOT=1u<<9,
    MT_N_NO_ACTIVE_START=1u<<10, MT_N_CAP_OVERSHOOT=1u<<11,
    MT_N_METADATA_INVALID=1u<<12, MT_N_WRITE_SPACE_MARK=1u<<13,
    MT_N_PREPARE_OPEN=1u<<14, MT_N_START_ACK_PENDING=1u<<15
};
#define MT_N_PRIMARY_SHIFT 16u
#define MT_N_PRIMARY_MASK UINT32_C(0xffff0000)
enum {
    MT_N_CLOSE_NONE, MT_N_CLOSE_QUEUE, MT_N_CLOSE_SOURCE, MT_N_CLOSE_RECOVERY,
    MT_N_CLOSE_STOP, MT_N_CLOSE_CAP, MT_N_CLOSE_TRANSPORT, MT_N_CLOSE_ADC,
    MT_N_CLOSE_HELLO, MT_N_CLOSE_NO_START, MT_N_CLOSE_UNAVAILABLE, MT_N_CLOSE_TIME
};
enum {
    MT_N_USB_VALID=1u, MT_N_USB_HELD=2u, MT_N_USB_DEFERRED=4u,
    MT_N_USB_TASK_READY=8u
};

/* Exactly ONE64B foreground-owned bank, including all persistent scratch.
 * Not self-authenticating: decode only paired with the unchanged136B record
 * matching nonce/generation/generated target build and an independently pinned image.
 * Cycle values/sums include IRQ time, assume <one DWT wrap, and are NOT CPU%.
 * Counts saturate; partial/unknown writes are explicit flags, not bytes lost.
 */
typedef struct {
    uint32_t magic,flags,generation,nonce_low,nonce_high;
    uint32_t begin_cycle,end_cycle,prepare_cycles,positive_bytes;
    uint32_t last_positive_cycle,max_positive_gap_cycles;
    uint16_t prepare_count,positive_count,zero_space_count,zero_other_count;
    uint16_t tx_offset,tx_length,stage_count,fifo_free;
    uint8_t stage_phase,queue_used,snapshot_bits,close_kind;
} mt_stream_progress_record;
_Static_assert(sizeof(mt_stream_progress_record)==64u,"Progress static bank64B");
_Static_assert(offsetof(mt_stream_progress_record,prepare_count)==44u,"Progress counters ABI");
_Static_assert(offsetof(mt_stream_progress_record,tx_offset)==52u,"Progress TX ABI");
_Static_assert(offsetof(mt_stream_progress_record,stage_phase)==60u,"Progress snapshot ABI");

extern volatile mt_stream_progress_record mt_stream_progress;
void mt_progress_begin(const mt_live_device *device);
uint32_t mt_progress_prepare_begin(void);
void mt_progress_prepare_end(uint32_t begin);
void mt_progress_write_begin(void);
void mt_progress_zero_space(void);
void mt_progress_write_end(size_t offered,size_t accepted);
void mt_progress_close(const mt_live_device *device,unsigned kind,unsigned primary);
void mt_progress_checkpoint(const mt_live_device *device);
#endif
