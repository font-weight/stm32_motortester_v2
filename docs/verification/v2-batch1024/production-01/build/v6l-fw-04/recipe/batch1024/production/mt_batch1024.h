#ifndef MT_BATCH1024_H
#define MT_BATCH1024_H
#include <stddef.h>
#include <stdint.h>

/* Shared serializer for V2SE software candidate. Frozen prototype API/body.
 * ADC/DMA/queue ownership, epoch, TIME and lifecycle admission belong to the
 * caller. No USB, callback, dynamic allocation or hidden acquisition pause. */
#define MT_BATCH1024_CAPACITY 1336u
#define MT_BATCH1024_FRAME_MAX 1335u
#define MT_BATCH1024_RAW_SHIFT 7u
#define MT_BATCH1024_QUANTUM_MAX 512u
#define MT_BATCH1024_WRITE_MAX 384u
typedef enum {
    MT_BATCH1024_EMPTY, MT_BATCH1024_COLLECT, MT_BATCH1024_CRC,
    MT_BATCH1024_COBS, MT_BATCH1024_READY, MT_BATCH1024_DONE,
    MT_BATCH1024_ABORTED
} mt_batch1024_phase;

/* Fixed-width pointer-free state:32 bytes on both host and ARM.
 * Input samples use ADC12 scale; prefix_crc rolls over canonical u16le.
 * Byte cursors are local to raw/encoded storage, never source sample indices. */
typedef struct {
    uint32_t prefix_crc, frame_crc;
    uint16_t count, raw_length, read, write, mark, code;
    uint16_t phase, packed_bytes, offset, length;
    uint32_t prefix_seed;
} mt_batch1024_state;
_Static_assert(sizeof(mt_batch1024_state)==32u,"Batch state SRAM contract");

/* This identity reuses existing core tx_* fields in a future integration;
 * it is not another static allocation in the memory proposal. */
typedef struct {
    uint64_t nonce, first_index;
    uint32_t generation, config_id, sequence;
} mt_batch1024_identity;

/* The caller owns exactly capacity bytes and disjoint state/identity/input.
 * Pass fresh/unowned storage. begin alone is not a hardware/queue reset. */
int mt_batch1024_begin(mt_batch1024_state *state,uint8_t *storage,
    const mt_batch1024_identity *identity,uint32_t committed_prefix_crc);

/* Pure prepared-copy seam: use a caller-owned WORK COPY of state.
 * Copies1..512 original ADC12 values after validating ALL codes/indices.
 * Canonical code=(ADC12>>2)<<2; low2 bits are lost explicitly. No queue pop
 * or wire-prefix commit occurs here. First source index must be contiguous.
 * On failure state/storage unchanged. The caller must validate all queue views
 * and epoch/TIME before atomic pop+publication of the prepared work state.
 * Only append into free storage; serialized/accepted bytes are immutable. */
int mt_batch1024_collect(mt_batch1024_state *work,uint8_t *storage,
    uint64_t first_index,const uint16_t *adc12,uint16_t count);

/* Count known only now:1024, or actual retained count after Stop/quiescence.
 * Zero count produces no DATA. No write is exposed before final CRC/COBS.
 * Caller must not invoke seal early during a still-running short batch. */
int mt_batch1024_seal(mt_batch1024_state *work,uint8_t *storage);

/* Bounded CRC or forward in-place COBS: at most budget1..512 INPUT bytes.
 * Transition/CRC/code/delimiter stores add a fixed small amount of work.
 * Does not certify WCET. No full raw/message scratch or memmove.
 * DESTRUCTIVE monotonic stage: COBS overwrites already consumed raw bytes.
 * A copied old state is NOT a rollback of storage. After epoch/TIME/staging
 * invalidation the caller MUST discard/abort this whole in-flight frame;
 * never retry an earlier cursor against partially transformed storage.
 * Returns consumed input bytes,0 if already READY,-1 for invalid call. */
int mt_batch1024_step(mt_batch1024_state *work,uint8_t *storage,uint16_t budget);

/* Immutable fragment of ONE frame, never a standalone sub-DATA.
 * Whole-fit applies to each fragment<=384; no second delimiter is inserted.
 * Neither helper performs I/O. accepted records only known positive/zero;
 * SIZE_MAX/over-acceptance returns0 without changing state. */
int mt_batch1024_piece(const mt_batch1024_state *state,const uint8_t *storage,
    const uint8_t **bytes,size_t *length);
int mt_batch1024_accepted(mt_batch1024_state *state,size_t accepted);

/* Guard seam only, not an implementation of the runtime guards: caller proves
 * current identity/epoch/lifecycle and final TIME after irreversible write.
 * Both global prefix values stay unchanged until all frame bytes are known
 * accepted. seed/end are checked before either mutation. Source endpoint is
 * first_index+actual count, never a rounded1024. No CRC work inside commit. */
int mt_batch1024_commit(mt_batch1024_state *state,uint64_t first_index,
    int final_guards_valid,uint64_t *committed_end,uint32_t *committed_crc);
void mt_batch1024_abort(mt_batch1024_state *state);
#endif
