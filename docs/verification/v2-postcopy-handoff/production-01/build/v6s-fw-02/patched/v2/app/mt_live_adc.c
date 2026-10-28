#include "mt_live_adc.h"
#include <stddef.h>

static int valid(const mt_live_adc *b)
{
    return b && b->initialized && b->driver && b->driver->initialized &&
        b->driver->stream_mode && b->clock && b->device;
}
static int clock_ok(mt_live_adc *b)
{
    if (mt_timebase_update(b->clock)) return 1;
    mt_adc_dma_invalidate_stream_history(b->driver, MT_ADC_DMA_FAULT_CLOCK);
    return 0;
}
static uint16_t reason(mt_adc_dma_fault_t fault)
{
    switch (fault) {
    case MT_ADC_DMA_FAULT_NONE: return 0u;
    case MT_ADC_DMA_FAULT_CLOCK:
    case MT_ADC_DMA_FAULT_TIMEBASE: return 3u;
    case MT_ADC_DMA_FAULT_SEQUENCE_LIMIT: return 4u;
    case MT_ADC_DMA_FAULT_STOP: return 5u;
    default: return 2u;
    }
}
int mt_live_adc_init(mt_live_adc *b, mt_adc_dma_t *d, mt_timebase *clock,
                     mt_live_device *device, const mt_adc_dma_start_guard *guard)
{
    if (!b || !d || !clock || !device || !guard || !guard->enter ||
        !guard->leave || !guard->allowed || !guard->timed_allowed ||
        !mt_timebase_update(clock)) return 0;
    if (mt_adc_dma_enable_stream(d) != MT_ADC_DMA_OK) return 0;
    *b = (mt_live_adc){.driver=d, .clock=clock, .device=device,
                     .guard=*guard, .initialized=1u};
    return 1;
}
static int start_binding(void *context, uint32_t generation,
                          mt_adc_dma_start_transaction_fn transaction)
{
    mt_live_adc *b = context;
    mt_adc_dma_result_t result;
    if (!valid(b) || !generation || b->device->generation != generation ||
        b->device->state != MT_LIVE_STARTING || !clock_ok(b) ||
        !mt_adc_dma_profile_ready(b->driver,b->device->mode)) return 0;
    result = transaction ? mt_adc_dma_start_transaction(b->driver, &b->guard, transaction)
                         : mt_adc_dma_start_guarded(b->driver, &b->guard);
    if (!clock_ok(b)) return 0;
    return result == MT_ADC_DMA_OK;
}
int mt_live_adc_start(void *context, uint32_t generation) {
    return start_binding(context, generation, NULL);
}
int mt_live_adc_start_transaction(void *context, uint32_t generation,
                                 mt_adc_dma_start_transaction_fn transaction) {
    return transaction && start_binding(context, generation, transaction);
}
void mt_live_adc_quiesce(void *context, mt_live_snapshot *out)
{
    mt_live_adc *b = context;
    uint32_t i;
    int healthy;
    if (!out) return;
    *out = (mt_live_snapshot){0};
    if (!valid(b)) { out->acquisition_reason=5u; return; }
    healthy = clock_ok(b);
    (void)mt_adc_dma_stop_snapshot(b->driver, &b->stop_scratch);
    if (!clock_ok(b)) healthy=0;
    out->hardware_off = b->stop_scratch.hardware_off ? 1u : 0u;
    out->acquisition_reason = reason(b->driver->first_fault);
    /* The first adapter intentionally leaves wire produced_end unknown.
     * Completed DMA transfers do not prove the final ADC/request drain. */
    if (!healthy || !out->hardware_off || !b->stop_scratch.dma_end_known) return;
    for (i=0u; i<b->stop_scratch.count; ++i) {
        unsigned block = i / MT_SAMPLE_QUEUE_BLOCK;
        unsigned offset = i % MT_SAMPLE_QUEUE_BLOCK;
        out->tail[block].first_index = b->stop_scratch.first_sample_index +
            (uint64_t)block * MT_SAMPLE_QUEUE_BLOCK;
        out->tail[block].codes[offset] = b->stop_scratch.samples[i];
        out->tail[block].count = (uint16_t)(offset + 1u);
        out->tail_count = block + 1u;
    }
}
int mt_live_adc_service(mt_live_adc *b)
{
    mt_adc_dma_block_t block;
    mt_adc_dma_result_t result;
    uint16_t why;
    if (!valid(b)) return -2;
    if (b->device->state != MT_LIVE_STARTING && b->device->state != MT_LIVE_STREAMING)
        return 0;
    if (!clock_ok(b)) {
        why = reason(b->driver->first_fault);
        mt_live_device_fault(b->device, why ? why : 3u); return -1;
    }
    result = mt_adc_dma_read_block(b->driver, &block);
    if (!clock_ok(b)) {
        why = reason(b->driver->first_fault);
        mt_live_device_fault(b->device, why ? why : 3u); return -1;
    }
    if (result == MT_ADC_DMA_EMPTY) return 0;
    if (result != MT_ADC_DMA_BLOCK) {
        why = reason(b->driver->first_fault);
        mt_live_device_fault(b->device, why ? why : 2u);
        return -1;
    }
    if (!block.samples || block.count != MT_ADC_DMA_BLOCK_SAMPLES ||
        b->driver->profile!=mt_acquisition_profile_get(b->device->mode) ||
        block.nominal_rate_hz != b->driver->profile->rate_hz ||
        block.first_trigger_offset_num_us != b->driver->profile->period_num_us ||
        block.first_trigger_offset_den != b->driver->profile->period_den) {
        mt_live_device_fault(b->device, 2u); return -1;
    }
    /* DMA ownership is checked for the complete 512-sample half first.
     * DATA/queue granularity stays 128; a rejected chunk never bridges a gap. */
    for (uint32_t offset=0; offset<block.count; offset+=MT_SAMPLE_QUEUE_BLOCK) {
        if (!mt_live_device_offer(b->device, block.first_sample_index+offset,
                block.samples+offset, MT_SAMPLE_QUEUE_BLOCK)) return -1;
    }
    return 1;
}

/* S_POSTCOPY: new entrypoints leave the original service/start/Stop untouched. */
static mt_live_adc_split_result split_source_fault(mt_live_adc *b,
        mt_live_adc_pending *p,uint16_t why)
{
    p->phase=MT_LIVE_ADC_PENDING_ABORTED;
    mt_live_device_fault(b->device,why);
    return MT_LIVE_ADC_SPLIT_FAILED;
}
static int split_source_matches(const mt_live_adc *b,const mt_live_adc_pending *p)
{
    const mt_adc_dma_t *d;
    const mt_live_device *core;
    if(!valid(b) || !p || p->owner!=b || p->phase!=MT_LIVE_ADC_PENDING_OWNED ||
       p->published>MT_ADC_DMA_BLOCK_SAMPLES || (p->published%MT_SAMPLE_QUEUE_BLOCK))return 0;
    d=b->driver;core=b->device;
    return p->profile && d->profile==p->profile &&
        p->profile==mt_acquisition_profile_get(p->mode) &&
        core->nonce==p->nonce && core->generation==p->generation &&
        core->mode==p->mode && core->revision==p->revision &&
        core->state==p->entry_state && core->state==MT_LIVE_STREAMING &&
        !core->hardware_off && !core->queue.sealed &&
        d->state==MT_ADC_DMA_RUNNING && d->owns_peripherals && d->stream_mode &&
        d->stream_history_valid && d->first_fault==MT_ADC_DMA_FAULT_NONE &&
        d->next_half==(p->expected_next_half!=0u) &&
        p->block.samples==d->snapshot && p->block.count==MT_ADC_DMA_BLOCK_SAMPLES &&
        p->block.first_sample_index<=UINT64_MAX-MT_ADC_DMA_BLOCK_SAMPLES &&
        d->first_sample_index==p->block.first_sample_index+MT_ADC_DMA_BLOCK_SAMPLES &&
        core->queue.next_index==p->block.first_sample_index+p->published &&
        d->last_poll_us==p->poll_origin_us &&
        p->deadline_us==p->profile->block_deadline_us &&
        p->block.nominal_rate_hz==p->profile->rate_hz &&
        p->block.start_before_us==d->start_before_us &&
        p->block.start_after_us==d->start_after_us &&
        p->block.first_trigger_offset_num_us==p->profile->period_num_us &&
        p->block.first_trigger_offset_den==p->profile->period_den;
}
static mt_live_adc_split_result split_elapsed(mt_live_adc *b,mt_live_adc_pending *p)
{
    uint32_t us,ms;
    if(!mt_timebase_snapshot(b->clock,&us,&ms)) {
        mt_adc_dma_invalidate_stream_history(b->driver,MT_ADC_DMA_FAULT_CLOCK);
        return split_source_fault(b,p,3u);
    }
    if((uint32_t)(us-p->poll_origin_us)>=p->deadline_us) {
        p->phase=MT_LIVE_ADC_PENDING_ABORTED;
        mt_adc_dma_invalidate_stream_history(b->driver,MT_ADC_DMA_FAULT_DEADLINE);
        mt_live_device_fault(b->device,2u);
        return MT_LIVE_ADC_SPLIT_DEADLINE;
    }
    return MT_LIVE_ADC_SPLIT_OWNED;
}
mt_live_adc_split_result mt_live_adc_acquire(mt_live_adc *b,
        mt_live_adc_pending *p,uint32_t epoch,uint32_t soft_serial,uint32_t actor)
{
    mt_adc_dma_block_t block;
    mt_adc_dma_result_t result;
    uint16_t why;
    if(!valid(b) || !p || p->phase!=MT_LIVE_ADC_PENDING_NONE || !epoch || actor!=epoch)
        return MT_LIVE_ADC_SPLIT_BAD_ARGUMENT;
    if(b->device->state!=MT_LIVE_STREAMING || b->device->mode!=5u)
        return MT_LIVE_ADC_SPLIT_EMPTY;
    if(!clock_ok(b)) {
        why=reason(b->driver->first_fault);
        return split_source_fault(b,p,why?why:3u);
    }
    result=mt_adc_dma_read_block(b->driver,&block);
    if(!clock_ok(b)) {
        why=reason(b->driver->first_fault);
        return split_source_fault(b,p,why?why:3u);
    }
    if(result==MT_ADC_DMA_EMPTY)return MT_LIVE_ADC_SPLIT_EMPTY;
    if(result!=MT_ADC_DMA_BLOCK) {
        why=reason(b->driver->first_fault);
        return split_source_fault(b,p,why?why:2u);
    }
    if(!block.samples || block.samples!=b->driver->snapshot ||
       block.count!=MT_ADC_DMA_BLOCK_SAMPLES ||
       b->driver->profile!=mt_acquisition_profile_get(b->device->mode) ||
       block.nominal_rate_hz!=b->driver->profile->rate_hz ||
       block.first_trigger_offset_num_us!=b->driver->profile->period_num_us ||
       block.first_trigger_offset_den!=b->driver->profile->period_den ||
       block.first_sample_index>UINT64_MAX-MT_ADC_DMA_BLOCK_SAMPLES ||
       b->driver->first_sample_index!=block.first_sample_index+MT_ADC_DMA_BLOCK_SAMPLES ||
       b->device->queue.next_index!=block.first_sample_index)
        return split_source_fault(b,p,2u);
    *p=(mt_live_adc_pending){.nonce=b->device->nonce,.block=block,.owner=b,
        .profile=b->driver->profile,.generation=b->device->generation,
        .epoch=epoch,.soft_serial=soft_serial,.actor=actor,
        .poll_origin_us=b->driver->last_poll_us,
        .deadline_us=b->driver->profile->block_deadline_us,.mode=b->device->mode,
        .revision=b->device->revision,.entry_state=(uint8_t)b->device->state,
        .expected_next_half=b->driver->next_half?1u:0u,
        .phase=MT_LIVE_ADC_PENDING_OWNED};
    return MT_LIVE_ADC_SPLIT_OWNED;
}
mt_live_adc_split_result mt_live_adc_publish_next(mt_live_adc *b,mt_live_adc_pending *p)
{
    mt_live_adc_split_result result;
    if(!valid(b) || !p || p->phase!=MT_LIVE_ADC_PENDING_OWNED ||
       p->published>=MT_ADC_DMA_BLOCK_SAMPLES)return MT_LIVE_ADC_SPLIT_BAD_ARGUMENT;
    if(!split_source_matches(b,p))return MT_LIVE_ADC_SPLIT_STALE;
    result=split_elapsed(b,p);
    if(result!=MT_LIVE_ADC_SPLIT_OWNED)return result;
    if(!mt_live_device_offer(b->device,p->block.first_sample_index+p->published,
            p->block.samples+p->published,MT_SAMPLE_QUEUE_BLOCK)) {
        /* Offer may already have quiesced. Do not read the old source view. */
        p->phase=MT_LIVE_ADC_PENDING_ABORTED;
        return MT_LIVE_ADC_SPLIT_FAILED;
    }
    p->published=(uint16_t)(p->published+MT_SAMPLE_QUEUE_BLOCK);
    result=split_elapsed(b,p);
    if(result!=MT_LIVE_ADC_SPLIT_OWNED)return result;
    if(!split_source_matches(b,p))return MT_LIVE_ADC_SPLIT_STALE;
    if(p->published==MT_ADC_DMA_BLOCK_SAMPLES) {
        p->phase=MT_LIVE_ADC_PENDING_PUBLISHED;
        return MT_LIVE_ADC_SPLIT_PUBLISHED;
    }
    return MT_LIVE_ADC_SPLIT_OWNED;
}
