"""Targeted raw statistics/repeatability checks, never physical accuracy tests."""
from dataclasses import FrozenInstanceError, replace
import math
import struct
from types import SimpleNamespace as NS
import unittest

import numpy as np

from motortester.stream_model import StreamIdentity, StreamBlock
from motortester.stream_wire import BATCH1024_REVISION
from motortester.v2.segment_measurements import (
    MAX_MEASUREMENT_SAMPLES, analyze_samples, read_segment)


def sine(count=800, period=100, *, center=2000, amplitude=900, step=1):
    return tuple(round((center + amplitude * math.sin(2*math.pi*i/period)) / step) * step
                 for i in range(count))


class Reader:
    def __init__(self, samples, *, bits=12):
        options = {} if bits == 12 else dict(protocol_revision=BATCH1024_REVISION,
            acquisition_mode=5, retained_bits=10, discarded_lsb=2,
            wire_sample_encoding='u10packed_le', normalization='left_shift_2',
            quantization='truncate_lsb')
        self.identity = StreamIdentity('measurement-fixture', 1, 1 if bits == 12 else 5,
                                      50_000 if bits == 12 else 150_000, 'synthetic', **options)
        self.first_sample_index = 2**54
        self.end_sample_index = self.first_sample_index + len(samples)
        self.samples = samples
        self.mode = None

    def iter_raw(self, start, stop, chunk_samples=8192):
        middle = start + (stop-start)//2
        for position, end in ((start, middle), (middle, stop)):
            raw = struct.pack(f'<{end-position}H',
                              *self.samples[position-self.first_sample_index:end-self.first_sample_index])
            block = StreamBlock(self.identity, position, raw)
            if position == middle:
                if self.mode == 'hole':
                    block = replace(block, first_sample_index=position+1)
                elif self.mode == 'identity':
                    block = replace(block, identity=replace(self.identity, generation=2))
                elif self.mode == 'short':
                    return
            if self.mode in ('gap', 'outside-gap'):
                block = NS(identity=block.identity, first_sample_index=block.first_sample_index,
                    end_sample_index=block.end_sample_index, sample_count=block.sample_count,
                    raw_u16le=block.raw_u16le,
                    gap_before=position == (middle if self.mode == 'gap' else start))
            yield block


class SegmentMeasurementTests(unittest.TestCase):
    def test_sine_offset_inversion_and_nonintegral_fs(self):
        original = np.asarray(sine(), dtype=np.uint16)
        saved = original.copy()
        result = analyze_samples(original, 50_000.5)
        self.assertIsNone(result.data_reason)
        self.assertIsNone(result.period_reason)
        self.assertEqual((result.count, result.min_code, result.max_code, result.mean_code),
                         (800, 1100, 2900, 2000.))
        self.assertAlmostEqual(result.period_s, 100/50_000.5, places=12)
        self.assertAlmostEqual(result.frequency_hz, 50_000.5/100, places=9)
        self.assertTrue(np.array_equal(original, saved))
        inverted = analyze_samples(tuple(3800-int(c) for c in original), 50_000.5)
        shifted = analyze_samples(tuple(int(c)+250 for c in original), 50_000.5)
        self.assertAlmostEqual(inverted.period_s, result.period_s, places=12)
        self.assertAlmostEqual(shifted.period_s, result.period_s, places=12)
        with self.assertRaises(FrozenInstanceError):
            result.count = 1

    def test_repeated_pulses_and_canonical_ten_bits(self):
        pulse = tuple(1000 + (1600 if 15 <= i % 160 < 23 else 0) for i in range(1280))
        result = analyze_samples(pulse, 50_000)
        self.assertAlmostEqual(result.period_s, 160/50_000, places=12)
        self.assertEqual(result.mean_code, 1080)
        inverse = analyze_samples(tuple(3600-c for c in pulse), 50_000)
        self.assertAlmostEqual(inverse.period_s, result.period_s, places=12)
        samples = sine(count=1500, period=150, step=4)
        result = analyze_samples(samples, 150_000, code_step=4)
        self.assertAlmostEqual(result.frequency_hz, 1000., places=9)
        self.assertEqual(result.mean_code, sum(samples)/len(samples))
        self.assertGreater(result.max_code, 2000)  # No additional /4 or *4 conversion.
        invalid = analyze_samples((1001,)*128, 150_000, code_step=4)
        self.assertIsNotNone(invalid.data_reason)
        self.assertIsNone(invalid.mean_code)

    def test_noise_irregularity_changes_and_insufficient_cycles_are_not_frequency(self):
        rng = np.random.default_rng(246)
        cases = [tuple(rng.integers(1200, 2800, 800)), (2000,)*800,
                 sine(count=290), tuple(1000 + (1500 if 120 <= i < 128 else 0) for i in range(800)),
                 sine(count=800, period=8)]
        # Durations change even though all peaks have identical shape.
        irregular = [1000]*1200
        for start in (20, 120, 290, 390, 580, 780, 1030):
            irregular[start:start+8] = [2600]*8
        cases.append(irregular)
        # Equally spaced crossings alone are not sufficient: shape widens.
        changing = [1000]*1000
        for cycle in range(10):
            start = cycle*100+20
            changing[start:start+5+cycle*5] = [2600]*(5+cycle*5)
        cases.append(changing)
        for samples in cases:
            with self.subTest(kind=len(samples), first=samples[:5]):
                result = analyze_samples(samples, 50_000)
                self.assertIsNone(result.data_reason)
                self.assertIsNone(result.period_s)
                self.assertIsNone(result.frequency_hz)
                self.assertTrue(result.period_reason)
                self.assertIsNotNone(result.mean_code)

    def test_gap_and_limits_invalidate_all_aggregates_but_clipping_keeps_raw_mean(self):
        for result in (analyze_samples(sine(), 50_000, has_gap=True),
                       analyze_samples(iter([2000]*(MAX_MEASUREMENT_SAMPLES+1)), 50_000),
                       analyze_samples([], 50_000), analyze_samples((True,)*128, 50_000),
                       analyze_samples((2000,)*128, float('nan'))):
            self.assertTrue(result.data_reason)
            self.assertIsNone(result.mean_code)
            self.assertIsNone(result.min_code)
            self.assertIsNone(result.max_code)
        clipped = analyze_samples((0, 1000, 4095)*100, 50_000)
        self.assertTrue(clipped.clipped)
        self.assertAlmostEqual(clipped.mean_code, 5095/3)
        self.assertIsNone(clipped.frequency_hz)
        clipped10 = analyze_samples((1000, 4092)*100, 150_000, code_step=4)
        self.assertTrue(clipped10.clipped)

    def test_reader_exact_range_identity_gaps_and_large_indices(self):
        reader = Reader(sine())
        start, stop = reader.first_sample_index, reader.end_sample_index
        result = read_segment(reader, start, stop)
        self.assertAlmostEqual(result.frequency_hz, 500.)
        for mode in ('hole', 'identity', 'short', 'gap'):
            reader.mode = mode
            with self.subTest(mode=mode):
                result = read_segment(reader, start, stop)
                self.assertIsNotNone(result.data_reason)
                self.assertIsNone(result.mean_code)
        reader.mode = 'outside-gap'
        self.assertIsNone(read_segment(reader, start, stop).data_reason)
        self.assertIsNotNone(read_segment(reader, start-1, stop).data_reason)
        packed = Reader(sine(count=1500, period=150, step=4), bits=10)
        self.assertAlmostEqual(read_segment(packed, packed.first_sample_index,
                                           packed.end_sample_index).frequency_hz, 1000.)


if __name__ == '__main__':
    unittest.main()
