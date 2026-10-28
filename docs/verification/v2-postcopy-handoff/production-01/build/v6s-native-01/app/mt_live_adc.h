#ifndef MT_LIVE_ADC_H
#define MT_LIVE_ADC_H
#include "../platform/adc_timer_dma.h"
#include "../platform/mt_timebase.h"
#include "../protocol/mt_live_device.h"

/* One static foreground owner. Driver, TIME, endpoint and guard context outlive
 * this binding. No legacy control, concurrent access, or live reinitialization.
 * stop_scratch avoids adding a full DMA-stop local frame below the live core's
 * own snapshot. It is private mutable scratch, never a published sample view. */
typedef struct {
    mt_adc_dma_t *driver;
    mt_timebase *clock;
    mt_live_device *device;
    mt_adc_dma_start_guard guard;
    mt_adc_dma_stop_snapshot_t stop_scratch;
    unsigned initialized;
} mt_live_adc;
/* Fresh binding storage; driver initialized/stopped/unowned, TIME healthy.
 * Enables stream mode. Does not initialize the endpoint, own USB, enable gates
 * or certify physical off. A real epoch-preserving timed guard is mandatory.
 * The board owner must establish reserved ADC/TIM/DMA clocks before HELLO. */
int mt_live_adc_init(mt_live_adc *binding, mt_adc_dma_t *driver,
                     mt_timebase *clock, mt_live_device *device,
                     const mt_adc_dma_start_guard *guard);
/* Call through board-owner wrappers from matching mt_live_io callbacks. The
 * same binding must back both callbacks; no calls into the live core here. */
int mt_live_adc_start(void *binding, uint32_t generation);
/* Optional V2 entrypoint; no change to the persistent binding/guard layout. */
int mt_live_adc_start_transaction(void *binding, uint32_t generation,
                                 mt_adc_dma_start_transaction_fn transaction);
void mt_live_adc_quiesce(void *binding, mt_live_snapshot *snapshot);
/* At most one driver half512 read and four immediate DATA128 queue offers. Return1
 * accepted,0 no block/inactive,-1 acquisition fault/queue rejection,-2 badarg.
 * A failed offer can synchronously quiesce: never use the old BLOCK view after.
 * Caller owns USB epoch admission and independent TIME/live timer servicing;
 * operation count alone does not prove the <5120us ADC service requirement. */
int mt_live_adc_service(mt_live_adc *binding);

/* One stack-only borrowed private half. No view survives a runtime pass.
 * Queue acceptance is distinct from accepted wire prefix. */
typedef enum {
    MT_LIVE_ADC_SPLIT_BAD_ARGUMENT=-2, MT_LIVE_ADC_SPLIT_FAILED=-1,
    MT_LIVE_ADC_SPLIT_EMPTY=0, MT_LIVE_ADC_SPLIT_OWNED=1,
    MT_LIVE_ADC_SPLIT_PUBLISHED=2, MT_LIVE_ADC_SPLIT_STALE=-3,
    MT_LIVE_ADC_SPLIT_DEADLINE=-4
} mt_live_adc_split_result;
enum { MT_LIVE_ADC_PENDING_NONE, MT_LIVE_ADC_PENDING_OWNED,
       MT_LIVE_ADC_PENDING_PUBLISHED, MT_LIVE_ADC_PENDING_ABORTED };
typedef struct {
    uint64_t nonce;
    mt_adc_dma_block_t block;
    mt_live_adc *owner;
    const mt_acquisition_profile *profile;
    uint32_t generation,epoch,soft_serial,actor;
    uint32_t poll_origin_us,deadline_us;
    uint16_t mode;
    uint8_t revision,entry_state,expected_next_half,phase;
    uint16_t published;
} mt_live_adc_pending;
#if UINTPTR_MAX==UINT32_MAX
_Static_assert(sizeof(mt_live_adc_pending)<=96u,"Pending half uses at most stack96B only");
#endif
/* acquire performs one original read/copy, never an offer. Runtime retains
 * original transport identity and forbids RX/next read until disposition. */
mt_live_adc_split_result mt_live_adc_acquire(mt_live_adc *binding,
    mt_live_adc_pending *pending,uint32_t epoch,uint32_t soft_serial,uint32_t actor);
/* One contiguous128 offer. Runtime supplies fresh pre/post transport admission
 * between <=4 calls; adapter checks source identity and original us deadline.
 * OWNED means one more chunk accepted, not permission to retry that chunk.
 * STALE requires explicit runtime quarantine; it cannot silently mean EMPTY. */
mt_live_adc_split_result mt_live_adc_publish_next(mt_live_adc *binding,
    mt_live_adc_pending *pending);
#endif
