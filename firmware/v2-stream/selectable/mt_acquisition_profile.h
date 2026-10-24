#ifndef MT_ACQUISITION_PROFILE_H
#define MT_ACQUISITION_PROFILE_H
#include <stddef.h>
#include <stdint.h>

/* Nominal hardware modes, independent of the Oscilloscope/Ignition UI profile.
 * ADC is always12 bits. Mode3 irreversibly discards2 LSB after DMA validation. */
typedef struct {
    uint32_t rate_hz, block_deadline_us;
    uint16_t mode, timer_psc, timer_arr;
    uint16_t period_num_us, period_den, start_bracket_max_us;
    uint8_t retained_bits, encoding;
} mt_acquisition_profile;

/* Immutable descriptors in flash; NULL for an unsupported mode. */
const mt_acquisition_profile *mt_acquisition_profile_get(uint16_t mode);
/* Canonical c12 input,0..4095 (mode3 also divisible by4). One bounded block,
 * count1..128; output/input must not overlap. Returns0 without modifying output
 * on invalid argument/domain/capacity. Packed mode is LSB-first q10 bitstream;
 * unused final high bits are0. No buffer or borrowed reference is retained. */
size_t mt_acquisition_pack(const mt_acquisition_profile *profile,
    const uint16_t *canonical, uint16_t count, uint8_t *output, size_t capacity);
#endif
