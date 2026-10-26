#ifndef MT_V2_CRC32_H
#define MT_V2_CRC32_H
#include <stdint.h>
/* IEEE reflected CRC32: immutable shared table, one Flash definition in mt_wire.
 * Input/output here is the unfinalized rolling state; callers retain their
 * existing initial/final XOR and little-endian sample serialization. */
extern const uint32_t mt_v2_crc32_table[256];
static inline __attribute__((always_inline)) uint32_t mt_v2_crc32_byte(
    uint32_t state, uint8_t byte) {
    return (state >> 8) ^ mt_v2_crc32_table[(uint8_t)(state ^ byte)];
}
#endif
