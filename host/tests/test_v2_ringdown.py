"""Synthetic damped-response tests; no physical-coil or bandwidth claim."""
from dataclasses import FrozenInstanceError, replace
import math
import struct
from types import SimpleNamespace as NS
import unittest

import numpy as np

from motortester.stream_model import StreamBlock, StreamIdentity
from motortester.stream_wire import BATCH1024_REVISION
from motortester.v2.ringdown import (
    MAX_RINGDOWN_SAMPLES, analyze_ringdown, read_ringdown, suggest_ringdown)


def damped(fs=50_000, *, frequency=2500., tau=.0012, duration=.008,
           baseline=2000., amplitude=800., noise=0., step=1, inverted=False):
    t = np.arange(round(fs*duration), dtype=float)/fs
    values = baseline + (-1 if inverted else 1)*amplitude*np.exp(-t/tau)*np.sin(2*np.pi*frequency*t)
    if noise:
        values += np.random.default_rng(101).normal(0, noise, len(values))
    return tuple(int(round(v/step))*step for v in values)


class Reader:
    def __init__(self, samples, fs=50_000, bits=12):
        options = {} if bits == 12 else dict(protocol_revision=BATCH1024_REVISION,
            acquisition_mode=5, retained_bits=10, discarded_lsb=2,
            wire_sample_encoding='u10packed_le', normalization='left_shift_2',
            quantization='truncate_lsb')
        self.identity = StreamIdentity('ringdown-fixture', 1, 1 if bits == 12 else 5,
                                      fs, 'synthetic', **options)
        self.samples = samples
        self.first_sample_index = 2**54
        self.end_sample_index = self.first_sample_index+len(samples)
        self.problem = None

    def iter_raw(self, start, stop, chunk_samples=8192):
        middle = start+(stop-start)//2
        boundaries = sorted(set((start, middle, stop, *range(start, stop, chunk_samples))))
        for first, end in zip(boundaries[:-1], boundaries[1:]):
            values = self.samples[first-self.first_sample_index:end-self.first_sample_index]
            block = StreamBlock(self.identity, first, struct.pack(f'<{len(values)}H', *values))
            if first == middle:
                if self.problem == 'gap':
                    block = replace(block, first_sample_index=first+1)
                elif self.problem == 'identity':
                    block = replace(block, identity=replace(self.identity, generation=2))
                elif self.problem == 'short':
                    return
                elif self.problem == 'gap_before':
                    block = NS(identity=block.identity, first_sample_index=first,
                        end_sample_index=end, sample_count=len(values),
                        raw_u16le=block.raw_u16le, gap_before=True)
            yield block


class RingdownTests(unittest.TestCase):
    def test_damped_frequency_tau_full_cycle_ratio_rates_and_quantization(self):
        for fs, step in ((50_000, 1), (100_000, 1), (150_000, 4)):
            with self.subTest(fs=fs):
                codes = damped(fs, step=step)
                result = analyze_ringdown(codes, fs, step)
                self.assertTrue(result.available, result.reason)
                self.assertAlmostEqual(result.frequency_hz, 2500, delta=40)
                self.assertAlmostEqual(result.tau_s, .0012, delta=.00015)
                self.assertAlmostEqual(result.amplitude_ratio_per_cycle,
                    math.exp(-1/(2500*.0012)), delta=.04)
                self.assertEqual(result.cycle_count, len(result.peaks)-1)
                self.assertGreaterEqual(result.cycle_count, 3)
                self.assertLess(result.duration_s, len(codes)/fs)
                self.assertAlmostEqual(result.baseline_code, 2000, delta=8)
                self.assertTrue(all(codes[i] == code for i, code in result.peaks))
                with self.assertRaises(FrozenInstanceError):
                    result.available = False

    def test_offset_inversion_and_moderate_noise_keep_same_decay(self):
        clean = analyze_ringdown(damped(), 50_000)
        for kwargs in (dict(baseline=1500), dict(inverted=True), dict(noise=2.0)):
            with self.subTest(kwargs=kwargs):
                codes = damped(**kwargs)
                before = tuple(codes)
                result = analyze_ringdown(codes, 50_000)
                self.assertTrue(result.available, result.reason)
                self.assertAlmostEqual(result.frequency_hz, clean.frequency_hz, delta=45)
                self.assertAlmostEqual(result.tau_s, clean.tau_s, delta=.0002)
                self.assertEqual(codes, before)

    def test_no_decay_noise_clipping_gap_short_and_mixed_frequencies_refuse(self):
        fs = 50_000
        t = np.arange(500)/fs
        cases = [tuple(np.rint(2000+700*np.sin(2*np.pi*2500*t)).astype(int)),
                 (2000,)*500, damped(duration=.0005),
                 tuple(np.random.default_rng(42).integers(1700, 2300, 500)),
                 (4095,)+damped()[1:], damped(frequency=8000),
                 tuple(np.rint(2000+500*np.exp(-t/.002)*(np.sin(2*np.pi*2000*t)
                                                    +np.sin(2*np.pi*2600*t))).astype(int))]
        for samples in cases:
            result = analyze_ringdown(samples, fs)
            self.assertFalse(result.available, str(result))
            self.assertTrue(result.reason)
            self.assertIsNone(result.tau_s)
        self.assertFalse(analyze_ringdown(damped(), fs, has_gap=True).available)
        self.assertFalse(analyze_ringdown([2000]*(MAX_RINGDOWN_SAMPLES+1), fs).available)

    def test_reader_preserves_exact_indices_format_and_rejects_missing_data(self):
        reader = Reader(damped(150_000, step=4), fs=150_000, bits=10)
        first, end = reader.first_sample_index, reader.end_sample_index
        result = read_ringdown(reader, first, end)
        self.assertTrue(result.available, result.reason)
        self.assertTrue(all(code % 4 == 0 for _, code in result.peaks))
        for problem in ('gap', 'identity', 'short', 'gap_before'):
            reader.problem = problem
            self.assertFalse(read_ringdown(reader, first, end).available)
        reader.problem = None
        self.assertFalse(read_ringdown(reader, first-1, end).available)

    def test_suggests_synthetic_plateau_to_ringdown_for_user_confirmation(self):
        tail = damped(duration=.006, baseline=1000, amplitude=600, frequency=2500, tau=.001)
        codes = (1000,)*50 + (3600, 2900, 2300) + (1600,)*147 + tail
        reader = Reader(codes)
        proposed = suggest_ringdown(reader, reader.first_sample_index, reader.end_sample_index)
        self.assertTrue(proposed.available, proposed.reason)
        self.assertGreaterEqual(proposed.relative_start, 180)
        self.assertLessEqual(proposed.relative_start, 230)
        self.assertEqual(proposed.start_index, reader.first_sample_index+proposed.relative_start)
        self.assertEqual(proposed.stop_index, reader.first_sample_index+proposed.relative_stop)
        exact = read_ringdown(reader, proposed.start_index, proposed.stop_index)
        self.assertTrue(exact.available, exact.reason)
        self.assertEqual(exact, proposed.result)
        self.assertIn('Кандидат', proposed.reason)
        clipped_codes = codes[:50] + (4095,) + codes[51:]
        clipped = Reader(clipped_codes)
        self.assertFalse(suggest_ringdown(clipped, clipped.first_sample_index,
                                          clipped.end_sample_index).available)
        self.assertTrue(read_ringdown(clipped, clipped.first_sample_index+200,
                                      clipped.end_sample_index).available)
        doubled = Reader(codes + (1000,)*50 + codes)
        self.assertFalse(suggest_ringdown(doubled, doubled.first_sample_index,
                                          doubled.end_sample_index).available)
        separated_tails = Reader(tail + (1000,)*100 + tail + (1000,)*100)
        ambiguous = suggest_ringdown(separated_tails, separated_tails.first_sample_index,
                                     separated_tails.end_sample_index)
        self.assertFalse(ambiguous.available)
        self.assertIn('несколько', ambiguous.reason)


if __name__ == '__main__':
    unittest.main()
