"""Focused R5 nominal conversion / file migration checks; no COM or hardware."""
from dataclasses import asdict, replace
import csv
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace as NS
import unittest

from motortester.stream_model import StreamIdentity, StreamStart, StreamBlock, StreamTerminal
from motortester.stream_recording import StreamWriter, recover
from motortester.stream_view import EventConfig, EventEntry
from motortester.stream_wire import BATCH1024_REVISION
from motortester.v2.analog_profile import (
    AnalogSnapshot, MODE_IDS, RawFormat, nominal_selection, quantize_thresholds)
from motortester.v2.input import InputProfile, UNKNOWN_PROFILE, V2Error
from motortester.v2.stream_capture import StreamCapture, HEADER, load_capture, save_capture
from motortester.v2.stream_device import (
    StreamContext, StreamConnection, SerialStreamSelection, StreamDeviceBridge,
    _write_context, open_verified_context, companion_path, context_from_dict)
from motortester.v2.stream_files import export_stream
from motortester.v2.stream_search import SearchSnapshot
from motortester.v2.stream_device import default_event_config


STAMP = "2026-11-02T10:00:00+00:00"


def identity(bits=12):
    if bits == 12:
        return StreamIdentity("analog-test", 1, 1, 50_000, "synthetic")
    return StreamIdentity("analog-test", 1, 5, 150_000, "synthetic",
        protocol_revision=BATCH1024_REVISION, acquisition_mode=5, retained_bits=10,
        discarded_lsb=2, wire_sample_encoding="u10packed_le", normalization="left_shift_2",
        quantization="truncate_lsb")


def context(mode="DC_WIDE", bits=12):
    p, s = nominal_selection(mode, identity(bits), confirmed_at_utc=STAMP)
    return StreamContext(input_profile=p, analog_snapshot=s)


class AnalogProfileTests(unittest.TestCase):
    def test_prestart_format_comes_from_accepted_caps_without_session_identity(self):
        for rate, mode, bits, maximum, encoding in ((50_000, 1, 12, 128, 1),
                (100_000, 2, 12, 128, 1), (150_000, 5, 10, 1024, 2)):
            connection = StreamConnection(SerialStreamSelection("test", requested_sample_rate_hz=rate),
                "injected-test", 0x5632534e, (mode, mode, 0, 12, rate, 1, maximum, 1, bits, encoding),
                protocol_revision="0.3")
            observed = RawFormat.from_connection(connection)
            self.assertEqual((observed.sample_rate_hz, observed.retained_bits), (rate, bits))
            p, s = nominal_selection("DC_WIDE", observed, confirmed_at_utc=STAMP)
            # This reproduces actual READY: CAPS exist but START has not yet
            # created any StreamIdentity. A small passive owner runs no COM.
            status = NS(ready=True, can_preview=True, command_pending=False, stop_pending=False,
                        close_requested=False, bridge=NS(identity=None))
            owner = NS(is_device=True, state=status, connection=connection, _closing=False,
                       _disconnecting=False, metadata_pending=False, context=StreamContext())
            owner.input_format = StreamDeviceBridge.input_format.fget(owner)
            self.assertTrue(StreamDeviceBridge.set_input_profile(owner, p, s))
            self.assertEqual(owner.context.analog_snapshot.raw_format, observed)
            owner.state = NS(ready=False)
            self.assertIsNone(StreamDeviceBridge.input_format.fget(owner))
        fixed = StreamConnection(SerialStreamSelection("test", requested_sample_rate_hz=50_000),
            "injected-test", 0x56325334, (1, 1, 0, 12, 50_000, 1, 128, 1))
        self.assertEqual(RawFormat.from_connection(fixed), RawFormat.from_identity(identity()))
        with self.assertRaises(ValueError):
            nominal_selection("DC_WIDE", None)

    def test_three_modes_match_independent_voltage_model_without_double_scaling(self):
        values = ((.036983582897348, 1.6598232004329785),
                  (.03663767425235315, 1.7235668789808918),
                  (.18628619087334683, 1.7235668789808918))
        for mode, (gain, offset) in zip(MODE_IDS, values):
            for bits in (12, 10):
                p, s = nominal_selection(mode, identity(bits), confirmed_at_utc=STAMP)
                for code in (0, 2048, 4092):
                    self.assertAlmostEqual(p.voltage(code), (code * 3.3 / 4096 - offset) / gain)
                self.assertEqual(p.state, "nominal")
                self.assertEqual(s.dc_component_measured, mode == "DC_WIDE")
                self.assertIsNone(p.linear_min_v)
                self.assertIsNone(s.measured_vref_v)
                self.assertIsNone(s.verified_operating_range_v)
        with self.assertRaises(V2Error):
            nominal_selection("DC_SENSITIVE", identity())
        with self.assertRaises(V2Error):
            nominal_selection("DC_WIDE", replace(identity(), nominal_fs_hz=200_000))

    def test_snapshot_rejects_unknown_format_and_calibration_claims(self):
        c = context()
        self.assertEqual(context_from_dict(asdict(c)), c)
        for changes in ({"signed": True}, {"canonical_step": 4}, {"retained_bits": 10},
                        {"stored_code_domain": "adc10"}, {"source_adc_bits": 16}):
            with self.assertRaises(ValueError):
                replace(c.analog_snapshot.raw_format, **changes)
        for changes in ({"calibration_progress": "verified"}, {"measured_vref_v": 3.29},
                        {"source_archive_sha256": "0" * 64}, {"schema_version": True}):
            with self.assertRaises(ValueError):
                replace(c.analog_snapshot, **changes)
        with self.assertRaises(ValueError):
            replace(c, input_profile=replace(c.input_profile, a=.1))
        with self.assertRaises(ValueError):
            c.validate_identity(identity(10))
        with self.assertRaises(ValueError):
            replace(c, analog_snapshot=None)

    def test_voltage_threshold_quantization_edges_negative_gain_and_collapse(self):
        p = InputProfile(a=1., b=-2000., state="nominal", coefficient_source="test")
        self.assertEqual(p.code(-1998., 4), 4)
        self.assertEqual(p.code(-1999.5), 1)
        result = quantize_thresholds(p, 102., 9., "above", 10)
        self.assertEqual((result.trigger_code, result.release_code, result.code_polarity), (2104, 2092, "above"))
        self.assertEqual((result.accepted_threshold_v, result.accepted_hysteresis_v), (104, 12))
        negative = replace(p, a=-1., b=2000.)
        result = quantize_thresholds(negative, -102., 9., "above", 10)
        self.assertEqual((result.trigger_code, result.release_code, result.code_polarity), (2104, 2112, "below"))
        for value in (-2000.1, 2092.1):
            with self.assertRaises(ValueError):
                p.code(value, 4)
        with self.assertRaises(ValueError):
            quantize_thresholds(p, 100., .1, "above", 10)
        for mode in MODE_IDS:
            profile = context(mode).input_profile
            for code in (0, 1, 2000, 4092, 4095):
                self.assertEqual(profile.code(profile.voltage(code)), code)
            self.assertEqual(profile.code(profile.voltage(4092), 4), 4092)
            for step in (1, 4):
                self.assertEqual(profile.code(profile.voltage(step / 2), step), step)
                self.assertEqual(profile.code(profile.voltage(step / 2 - 1e-7), step), 0)

    def test_companion5_raw_and_volt_csv_roundtrip_and_legacy3_4(self):
        with tempfile.TemporaryDirectory() as folder:
            for bits in (12, 10):
                path = Path(folder) / f"sample{bits}.mtstream"
                ident = identity(bits)
                writer = StreamWriter.create(path, StreamStart(ident, 0, "test"))
                raw = struct.pack("<4H", 0, 2048, 2400, 4092)
                writer.append(StreamBlock(ident, 0, raw))
                writer.finish(StreamTerminal(ident, 4, "stopped", True, None, 4, None,
                    stop_requested=True, stop_request_id=1))
                writer.close()
                original = path.read_bytes()
                c = context("AC_SENSITIVE", bits)
                _write_context(path, c, ident)
                opened = open_verified_context(path)
                self.assertEqual(opened.context, c)
                exported = Path(folder) / f"sample{bits}.csv"
                export_stream(exported, recover(path), opened)
                with exported.open(encoding="utf8", newline="") as handle:
                    rows = list(csv.reader(handle))
                self.assertEqual(rows[0][-1], "CH1_ac_component_V")
                self.assertEqual([int(r[2]) for r in rows[1:]], [0, 2048, 2400, 4092])
                self.assertAlmostEqual(float(rows[2][-1]), c.input_profile.voltage(2048))
                self.assertEqual(path.read_bytes(), original)
                metadata = json.loads(companion_path(path).read_text("utf8"))
                metadata["context"]["analog_snapshot"]["mode_id"] = "DC_WIDE"
                companion_path(path).write_text(json.dumps(metadata), encoding="utf8")
                with self.assertRaises(ValueError):
                    open_verified_context(path)
                # Historical companion3 exact context (before this field existed).
                companion_path(path).unlink()
                _write_context(path, StreamContext(), ident)
                metadata = json.loads(companion_path(path).read_text("utf8"))
                metadata["format_version"] = 3
                del metadata["event_search"]
                del metadata["context"]["analog_snapshot"]
                companion_path(path).write_text(json.dumps(metadata), encoding="utf8")
                self.assertEqual(open_verified_context(path).context.input_profile, UNKNOWN_PROFILE)
                metadata["format_version"] = 4
                search = SearchSnapshot(default_event_config(ident.nominal_fs_hz, bits), 2)
                metadata["event_search"] = asdict(search)
                companion_path(path).write_text(json.dumps(metadata), encoding="utf8")
                migrated = open_verified_context(path)
                self.assertEqual(migrated.context.input_profile, UNKNOWN_PROFILE)
                self.assertEqual(migrated.event_search, search)
                self.assertEqual(path.read_bytes(), original)

    def test_shot2_and_independent_legacy_shot1_metadata_preserve_raw(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context("AC_WIDE", 10)
            cfg = EventConfig(2000, 1800, "above", 1, 1, 1, 0, 4, 0, 4092)
            event = EventEntry(0, 1, 0, 4, 0, 1, 3, ())
            raw = struct.pack("<4H", 1000, 2400, 2400, 1000)
            shot = StreamCapture(identity(10), c, cfg, 0, 1, 0, 1, event, raw,
                                 "event_closed", (), None, "running", STAMP)
            path = Path(folder) / "new.mtshot"
            save_capture(path, shot)
            self.assertEqual(load_capture(path), shot)
            # Encode historical metadata directly, not by invoking the new writer.
            old = asdict(replace(shot, context=StreamContext()))
            del old["raw_u16le"]
            del old["context"]["analog_snapshot"]
            old.update(format_version=1, time_basis="nominal_unverified",
                       arm_basis="latest_published_receiver_end_on_host")
            encoded = json.dumps(old).encode("utf8")
            payload = HEADER.pack(b"MTSHOT1\0", len(encoded), 4) + encoded + raw
            legacy = Path(folder) / "legacy.mtshot"
            historical = payload + hashlib.sha256(payload).digest()
            legacy.write_bytes(historical)
            opened = load_capture(legacy)
            self.assertEqual(opened.raw_u16le, raw)
            self.assertEqual(opened.context.input_profile, UNKNOWN_PROFILE)
            self.assertIsNone(opened.context.analog_snapshot)
            self.assertEqual(legacy.read_bytes(), historical)


if __name__ == "__main__":
    unittest.main()
