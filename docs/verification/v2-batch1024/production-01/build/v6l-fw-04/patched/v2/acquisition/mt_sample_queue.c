#include "mt_sample_queue.h"
#include <string.h>

_Static_assert(MT_SAMPLE_QUEUE_SLOTS * MT_SAMPLE_QUEUE_BLOCK * sizeof(uint16_t)
               == 2048u, "raw sample storage budget");

static mt_sample_queue_result fail(mt_sample_queue *q,
                                   mt_sample_queue_result reason) {
    if (q->first_fault == MT_SAMPLE_QUEUE_OK) q->first_fault = reason;
    q->sealed = 1u;
    return reason;
}

void mt_sample_queue_init(mt_sample_queue *q, uint64_t first_index) {
    if (!q) return;
    memset(q, 0, sizeof *q);
    q->head_index = first_index;
    q->next_index = first_index;
}

mt_sample_queue_result mt_sample_queue_push_quantized(mt_sample_queue *q,
                                           uint64_t first_index,
                                           const uint16_t *samples,
                                           uint16_t count,
                                           unsigned final_block,unsigned discarded_lsb) {
    size_t i, tail;
    if (!q) return MT_SAMPLE_QUEUE_ARGUMENT;
    if (q->sealed) return MT_SAMPLE_QUEUE_CLOSED;
    if (!samples || (discarded_lsb!=0u && discarded_lsb!=2u)) return fail(q, MT_SAMPLE_QUEUE_ARGUMENT);
    if (final_block > 1u || count == 0u || count > MT_SAMPLE_QUEUE_BLOCK ||
        (count < MT_SAMPLE_QUEUE_BLOCK && final_block == 0u))
        return fail(q, MT_SAMPLE_QUEUE_COUNT);
    if (first_index != q->next_index) return fail(q, MT_SAMPLE_QUEUE_INDEX);
    if (UINT64_MAX - first_index < count)
        return fail(q, MT_SAMPLE_QUEUE_OVERFLOW);
    for (i = 0; i < count; ++i)
        if (samples[i] > 4095u) return fail(q, MT_SAMPLE_QUEUE_CODE);
    if (q->used == MT_SAMPLE_QUEUE_SLOTS) return fail(q, MT_SAMPLE_QUEUE_FULL);

    /* No fallible operation after validation: publish only a complete block. */
    tail = (q->head + q->used) % MT_SAMPLE_QUEUE_SLOTS;
    if(discarded_lsb==2u) {
        for(i=0;i<count;i++)q->samples[tail][i]=(uint16_t)(samples[i]&UINT16_C(0x0ffc));
    } else memcpy(q->samples[tail], samples, (size_t)count * sizeof samples[0]);
    q->counts[tail] = count;
    ++q->used;
    q->next_index += count;
    if (final_block) q->sealed = 1u;
    return MT_SAMPLE_QUEUE_OK;
}

mt_sample_queue_result mt_sample_queue_push(mt_sample_queue *q,uint64_t first_index,
    const uint16_t *samples,uint16_t count,unsigned final_block) {
    return mt_sample_queue_push_quantized(q,first_index,samples,count,final_block,0u);
}

void mt_sample_queue_seal(mt_sample_queue *q) {
    if (q) q->sealed = 1u;
}

mt_sample_queue_result mt_sample_queue_peek(const mt_sample_queue *q,
                                           mt_sample_block *block) {
    if (!q || !block) return MT_SAMPLE_QUEUE_ARGUMENT;
    if (q->used == 0u) return MT_SAMPLE_QUEUE_EMPTY;
    block->samples = q->samples[q->head];
    block->first_index = q->head_index;
    block->count = q->counts[q->head];
    return MT_SAMPLE_QUEUE_OK;
}

mt_sample_queue_result mt_sample_queue_peek_offset(const mt_sample_queue *q,
    unsigned offset,mt_sample_block *block) {
    size_t slot;uint64_t first;
    if(!offset)return mt_sample_queue_peek(q,block);
    if(!q || !block || offset!=1u)return MT_SAMPLE_QUEUE_ARGUMENT;
    if(q->used<2u)return MT_SAMPLE_QUEUE_EMPTY;
    if(UINT64_MAX-q->head_index<q->counts[q->head])return MT_SAMPLE_QUEUE_STALE;
    first=q->head_index+q->counts[q->head];slot=(q->head+1u)%MT_SAMPLE_QUEUE_SLOTS;
    *block=(mt_sample_block){q->samples[slot],first,q->counts[slot]};
    return MT_SAMPLE_QUEUE_OK;
}
mt_sample_queue_result mt_sample_queue_pop_span(mt_sample_queue *q,
    const mt_sample_block *expected,unsigned blocks) {
    uint64_t end;unsigned i;
    if(!q || !expected || !blocks || blocks>2u)return MT_SAMPLE_QUEUE_ARGUMENT;
    if(q->used<blocks)return MT_SAMPLE_QUEUE_EMPTY;
    end=q->head_index;
    for(i=0;i<blocks;i++) {
        size_t slot=(q->head+i)%MT_SAMPLE_QUEUE_SLOTS;
        if(expected[i].samples!=q->samples[slot] || expected[i].first_index!=end ||
           !expected[i].count || expected[i].count>MT_SAMPLE_QUEUE_BLOCK ||
           expected[i].count!=q->counts[slot] || UINT64_MAX-end<expected[i].count)
            return MT_SAMPLE_QUEUE_STALE;
        end+=expected[i].count;
    }
    /* Every expected view has been validated; no fallible operation follows. */
    q->head_index=end;q->head=(q->head+blocks)%MT_SAMPLE_QUEUE_SLOTS;q->used-=blocks;
    return MT_SAMPLE_QUEUE_OK;
}

mt_sample_queue_result mt_sample_queue_peek_many(const mt_sample_queue *q,
    mt_sample_block *views,unsigned blocks) {
    uint64_t end;unsigned i;
    if(!q || !views || !blocks || blocks>4u)return MT_SAMPLE_QUEUE_ARGUMENT;
    if(q->used<blocks)return MT_SAMPLE_QUEUE_EMPTY;
    end=q->head_index;
    for(i=0;i<blocks;i++) {
        uint16_t n=q->counts[(q->head+i)%MT_SAMPLE_QUEUE_SLOTS];
        if(!n || n>MT_SAMPLE_QUEUE_BLOCK || UINT64_MAX-end<n ||
           (n<MT_SAMPLE_QUEUE_BLOCK && (!q->sealed || i+1u<q->used)))return MT_SAMPLE_QUEUE_STALE;
        end+=n;
    }
    end=q->head_index;
    for(i=0;i<blocks;i++) {
        size_t slot=(q->head+i)%MT_SAMPLE_QUEUE_SLOTS;
        views[i]=(mt_sample_block){q->samples[slot],end,q->counts[slot]};
        end+=q->counts[slot];
    }
    return MT_SAMPLE_QUEUE_OK;
}
mt_sample_queue_result mt_sample_queue_pop_many(mt_sample_queue *q,
    const mt_sample_block *expected,unsigned blocks) {
    uint64_t end;unsigned i;
    if(!q || !expected || !blocks || blocks>4u)return MT_SAMPLE_QUEUE_ARGUMENT;
    if(q->used<blocks)return MT_SAMPLE_QUEUE_EMPTY;
    end=q->head_index;
    for(i=0;i<blocks;i++) {
        size_t slot=(q->head+i)%MT_SAMPLE_QUEUE_SLOTS;
        if(expected[i].samples!=q->samples[slot] || expected[i].first_index!=end ||
           !expected[i].count || expected[i].count>MT_SAMPLE_QUEUE_BLOCK ||
           expected[i].count!=q->counts[slot] || UINT64_MAX-end<expected[i].count ||
           (expected[i].count<MT_SAMPLE_QUEUE_BLOCK && (!q->sealed || i+1u<q->used)))
            return MT_SAMPLE_QUEUE_STALE;
        end+=expected[i].count;
    }
    q->head_index=end;q->head=(q->head+blocks)%MT_SAMPLE_QUEUE_SLOTS;q->used-=blocks;
    return MT_SAMPLE_QUEUE_OK;
}

mt_sample_queue_result mt_sample_queue_pop(mt_sample_queue *q,
                                          uint64_t expected_first_index) {
    if (!q) return MT_SAMPLE_QUEUE_ARGUMENT;
    if (q->used == 0u) return MT_SAMPLE_QUEUE_EMPTY;
    if (expected_first_index != q->head_index) return MT_SAMPLE_QUEUE_STALE;
    q->head_index += q->counts[q->head];
    q->head = (q->head + 1u) % MT_SAMPLE_QUEUE_SLOTS;
    --q->used;
    return MT_SAMPLE_QUEUE_OK;
}
