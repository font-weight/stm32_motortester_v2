"""Focused checks for voltage honesty, bounded records and raw reproducibility."""
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from motortester.model import Capture
from motortester import recording as legacy
from motortester.v2.core import (
    InputProfile, DEMO_PROFILE, UNKNOWN_PROFILE, V2Error, CaptureSettings,
    SignalBlock, Recording, DemoSource, analyze, find_events, cursor_measurement,
    encode, decode, save, load, export_csv,
)


class V2CoreTests(unittest.TestCase):
    def test_signed_connector_conversion_threshold_and_clipping(self):
        profile = InputProfile(a=-0.002, b=4.0, state="nominal",
                               coefficient_source="known-test-circuit")
        self.assertAlmostEqual(profile.voltage(1250), 1.5)
        self.assertEqual(profile.code(1.5), 1250)
        self.assertEqual(profile.code_edge("rising"), "falling")
        bounded = replace(profile, linear_min_v=0, linear_max_v=3)
        with self.assertRaises(V2Error):
            bounded.code(3.5)
        with self.assertRaises(V2Error):
            profile.code(4.001)
        with self.assertRaises(V2Error):
            UNKNOWN_PROFILE.voltage(2048)
        raw = (1500, 1400, 1300, 1200, 1100, 0, 4095)
        rec = Recording((SignalBlock(0, 1000, raw),), input_profile=profile,
                        capture_settings=CaptureSettings(threshold_v=1.5, window_s=.01))
        self.assertEqual(find_events(rec)[0].trigger_index, 3)
        result = analyze(rec)
        self.assertAlmostEqual(result.minimum_v, -4.19)
        self.assertAlmostEqual(result.maximum_v, 4.0)
        self.assertAlmostEqual(result.peak_to_peak_v, 8.19)
        self.assertTrue(result.clipping)

    def test_cursor_dc_values_are_independent_of_ui_profile(self):
        rec = Recording((SignalBlock(100, 1000, (1024, 2048, 3072)),))
        expected = cursor_measurement(rec, .100, .102)
        actual = cursor_measurement(replace(rec, ui_profile="ignition"), .100, .102)
        self.assertEqual(actual, expected)
        self.assertAlmostEqual(actual.voltage_a_v, .825)
        self.assertAlmostEqual(actual.voltage_b_v, 2.475)
        self.assertAlmostEqual(actual.delta_v, 1.65)
        self.assertAlmostEqual(actual.delta_t_s, .002)

    def test_roundtrip_raw_profile_gap_and_csv_time(self):
        rec = Recording((SignalBlock(50, 1000, (100, 200)),
                         SignalBlock(60, 1000, (300, 400), gap_before="source_loss")),
                        channel_name="Проверка катушки")
        self.assertEqual(decode(encode(rec)), rec)
        self.assertEqual([(g.start_index, g.end_index) for g in rec.gaps], [(52, 60)])
        self.assertIsNone(rec.sample_at_time(.055))
        self.assertIsNone(rec.sample_at_time(.0598))  # Never round out of a gap into data.
        adjacent = Recording((SignalBlock(0, 1000, (100, 200)),
                              SignalBlock(2, 1000, (300, 400))))
        self.assertEqual(adjacent.sample_at_time(.0012)[1], 200)
        self.assertEqual(adjacent.sample_at_time(.0018)[1], 300)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.mtv2"
            save(path, rec)
            self.assertEqual(load(path), rec)
            with self.assertRaises(FileExistsError):
                save(path, rec)
            exported, sidecar = export_csv(Path(tmp) / "samples.csv", rec)
            rows = list(csv.DictReader(exported.read_text(encoding="utf-8").splitlines()))
            self.assertEqual([int(r["sample_index"]) for r in rows], [50, 51, 60, 61])
            self.assertEqual(float(rows[2]["time_s"]), .06)
            self.assertEqual(rows[2]["gap_before"], "source_loss")
            self.assertAlmostEqual(float(rows[2]["voltage_v"]), DEMO_PROFILE.voltage(300))
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(meta["csv_sha256"], hashlib.sha256(exported.read_bytes()).hexdigest())
            self.assertEqual(meta["channels"][0]["input_profile"]["a"], DEMO_PROFILE.a)

    def test_corruption_is_rejected(self):
        rec = Recording((SignalBlock(0, 1000, (1, 2, 3)),))
        data = bytearray(encode(rec))
        data[-34] ^= 1
        with self.assertRaisesRegex(V2Error, "целостность"):
            decode(bytes(data))

    def test_legacy_is_unknown_scale_with_original_capture_parameters(self):
        old = Capture(samples=(20, 30, 40), session_id=str(uuid4()), sequence=7,
                      nominal_fs_hz=1000, received_at_utc="2026-10-20T10:00:00Z",
                      trigger_index=1, pretrigger_samples=1, trigger_level_code=25,
                      sensor="Исходный датчик")
        converted = decode(legacy.encode(old))
        self.assertEqual(converted.blocks[0].samples, old.samples)
        self.assertEqual(converted.input_profile.state, "unconfigured")
        self.assertIsNone(analyze(converted).maximum_v)
        self.assertIsNone(converted.capture_settings.threshold_v)
        self.assertEqual(converted.capture_settings.hardware_threshold_code, 25)
        self.assertEqual(converted.legacy_sequence, 7)
        self.assertEqual(converted.input_profile.sensor, old.sensor)
        self.assertEqual(decode(encode(converted)), converted)

    def test_demo_is_continuous_across_chunks_and_period_is_measured(self):
        source = DemoSource("sine")
        first, second = source.next_block(1000), source.next_block(1000)
        whole = DemoSource("sine").next_block(2000)
        self.assertEqual(first.samples + second.samples, whole.samples)
        self.assertEqual(second.start_index, 1000)
        for waveform in ("square", "ignition"):
            other = DemoSource(waveform)
            a, b = other.next_block(1000), other.next_block(1000)
            self.assertEqual(a.samples + b.samples, DemoSource(waveform).next_block(2000).samples)
            self.assertTrue(all(0 < code < 4095 for code in a.samples + b.samples))
        ignition = DemoSource("ignition").next_block(8001).samples
        self.assertEqual([ignition[i] for i in (0, 2000, 4000, 6000, 8000)],
                         [DEMO_PROFILE.code(3.1)] * 5)
        rec = Recording((first, second))
        result = analyze(rec)
        self.assertAlmostEqual(result.frequency_hz, 250.0)
        different_trigger = replace(rec.capture_settings, holdoff_s=.010, threshold_v=3.0, edge="falling")
        self.assertAlmostEqual(analyze(replace(rec, capture_settings=different_trigger)).frequency_hz, 250.0)
        self.assertAlmostEqual(result.mean_v, 1.65, places=4)
        inverse = replace(DEMO_PROFILE, a=-DEMO_PROFILE.a, b=3.3)
        self.assertAlmostEqual(analyze(replace(rec, input_profile=inverse)).frequency_hz, 250.0)
        source.skip(100)
        missing = source.next_block(1000)
        self.assertEqual(missing.start_index, 2100)
        self.assertIsNone(analyze(Recording((first, second, missing))).frequency_hz)

    def test_event_gap_truncation_and_holdoff(self):
        profile = InputProfile(a=.001, b=0, state="nominal", coefficient_source="test")
        settings = CaptureSettings(threshold_v=1, window_s=.008, pretrigger_fraction=.5, holdoff_s=.004)
        rec = Recording((SignalBlock(0, 1000, (0, 1500, 0, 1500)),
                         SignalBlock(6, 1000, (0, 1500, 0, 1500), gap_before="loss")),
                        input_profile=profile, capture_settings=settings)
        events = find_events(rec)
        self.assertEqual([e.trigger_index for e in events], [1, 7])
        self.assertIn("left_truncated", events[0].quality_flags)
        self.assertIn("right_truncated", events[1].quality_flags)
        self.assertIn("missing_context", events[1].quality_flags)
        self.assertIsNone(cursor_measurement(rec, .001, .005).delta_v)
        self.assertEqual(rec.slice(2, 8).blocks[1].start_index, 6)

    def test_irregular_intervals_do_not_create_stable_frequency(self):
        raw = [100] * 50
        for index in (2, 10, 21, 38):
            raw[index] = 3000
        result = analyze(Recording((SignalBlock(0, 1000, tuple(raw)),)))
        self.assertIsNone(result.frequency_hz)
        self.assertIn("irregular_intervals", result.quality_flags)


if __name__ == "__main__":
    unittest.main()
