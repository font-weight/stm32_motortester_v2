"""Artificial file fixtures only: no COM, STM32, or measured calibration.

Some fixtures intentionally contain declared-device metadata to test that
format's admission/roundtrip. Their declarations are NOT physical evidence.
"""
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from motortester.stream_model import StreamIdentity, StreamStart, StreamBlock, StreamTerminal, FailureEvidence
from motortester.stream_recording import StreamWriter, recover
from motortester.stream_view import EventConfig, EventEntry
from motortester.stream_wire import mode_revision
from motortester.v2.analog_profile import RawFormat, nominal_selection
from motortester.v2.calibration import calibrated_selection, fit_ac, validate_control
from motortester.v2.calibration_io import import_window
from motortester.v2.stream_capture import StreamCapture, save_capture, load_capture
from motortester.v2.stream_device import (
    StreamContext, StreamConnection, SerialStreamSelection, _write_context,
    companion_path, open_verified_context)
from motortester.v2.stream_files import export_stream

from test_v2_calibration import plan, dc_record, window


BUILD = 0x5632534e
STAMP = "2026-11-13T10:00:00+00:00"


def declared_identity(rate=50_000, *, synthetic=False):
    mode = {50_000: 1, 100_000: 2, 150_000: 5}[rate]
    packed = rate == 150_000
    kind = "injected-test" if synthetic else "physical"
    ident = StreamIdentity("artificial-declared-device-calibration-test", 1, mode, rate,
        "synthetic" if synthetic else "device", mode_revision(mode), f"build:{BUILD:08x}",
        "v2-serial-unknown-accounting:" + kind, acquisition_mode=mode,
        retained_bits=10 if packed else 12, discarded_lsb=2 if packed else 0,
        wire_sample_encoding="u10packed_le" if packed else "u16le",
        normalization="left_shift_2" if packed else "identity",
        quantization="truncate_lsb" if packed else "none")
    caps = (mode, mode, 0, 12, rate, 1, 1024 if packed else 128, 1,
            10 if packed else 12, 2 if packed else 1)
    connection = StreamConnection(SerialStreamSelection("not-a-real-port", requested_sample_rate_hz=rate),
        kind, BUILD, caps, protocol_revision="0.3")
    return ident, connection


def write_fixture(path, ident, connection, context, *, codes=(2000,) * 512,
                  terminal="stopped_unknown_tail", metadata=True):
    start = 100
    end = start + len(codes)
    raw = struct.pack(f"<{len(codes)}H", *codes)
    writer = StreamWriter.create(path, StreamStart(ident, start, "artificial-test-recording"))
    writer.append(StreamBlock(ident, start, raw))
    if terminal == "stopped_unknown_tail":
        writer.finish(StreamTerminal(ident, end, "stopped", True, None, end, None,
            stop_requested=True, stop_request_id=1))
    elif terminal == "full_accounting":
        writer.finish(StreamTerminal(ident, end, "stopped", True, end, end, 0,
            stop_requested=True, stop_request_id=1))
    elif terminal == "failure":
        writer.finish(StreamTerminal(ident, end, "host_failure", False,
            failure=FailureEvidence("host_io", "artificial disconnect")))
    elif terminal != "missing":
        raise ValueError(terminal)
    writer.close()
    if metadata:
        _write_context(path, context, ident, connection)
    return raw


def fixture_context(ident, mode="DC_WIDE"):
    profile, snapshot = nominal_selection(mode, ident, hardware_instance_id="fixture-only")
    return StreamContext(input_profile=profile, analog_snapshot=snapshot)


class CalibrationIOTests(unittest.TestCase):
    def test_completed_prefix_unknown_generated_tail_imports_and_copies_keep_identity(self):
        ident, connection = declared_identity()
        p = replace(plan(origin="device"), raw_format=RawFormat.from_identity(ident))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.mtstream"
            write_fixture(path, ident, connection, fixture_context(ident))
            before = path.read_bytes()
            self.assertFalse(recover(path).clean_stop_reported)  # Actual protocol has unknown production tail.
            excerpt = import_window(path, p, 100, 256)
            self.assertEqual(excerpt.codes, (2000,) * 256)
            self.assertEqual(excerpt.first_sample_index, 200)
            self.assertEqual(excerpt.source_id, hashlib.sha256(before).hexdigest())
            copied = Path(directory) / "renamed.mtstream"
            copied.write_bytes(before)
            companion_path(copied).write_bytes(companion_path(path).read_bytes())
            another = import_window(copied, p, 100, 256)
            self.assertEqual(another.source_id, excerpt.source_id)
            self.assertEqual(another.first_sample_index, excerpt.first_sample_index)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                import_window(path, p, 500, 256)

    def test_import_rejects_wrong_provenance_binding_mode_rate_instance_and_incomplete(self):
        ident, connection = declared_identity()
        p = replace(plan(origin="device"), raw_format=RawFormat.from_identity(ident))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "good.mtstream"
            write_fixture(path, ident, connection, fixture_context(ident), terminal="full_accounting")
            for changed in (replace(p, hardware_instance_id="wrong-board"),
                    replace(p, mode_id="AC_WIDE", frequency_hz=1000., polarity_basis="fixture"),
                    replace(p, raw_format=RawFormat.from_identity(declared_identity(100_000)[0]))):
                with self.subTest(plan=changed):
                    with self.assertRaisesRegex(ValueError, "другому"):
                        import_window(path, changed, 0, 128)
            synthetic_id, injected = declared_identity(synthetic=True)
            synth = folder / "injected.mtstream"
            write_fixture(synth, synthetic_id, injected, fixture_context(synthetic_id), terminal="full_accounting")
            with self.assertRaisesRegex(ValueError, "Происхождение"):
                import_window(synth, p, 0, 128)
            no_connection = folder / "no-connection.mtstream"
            write_fixture(no_connection, ident, None, fixture_context(ident), terminal="full_accounting")
            with self.assertRaisesRegex(ValueError, "физического соединения"):
                import_window(no_connection, p, 0, 128)
            unknown = folder / "unknown.mtstream"
            write_fixture(unknown, ident, connection, fixture_context(ident), terminal="full_accounting", metadata=False)
            with self.assertRaisesRegex(ValueError, "нет подтверждённого"):
                import_window(unknown, p, 0, 128)
            for terminal in ("failure", "missing"):
                broken = folder / (terminal + ".mtstream")
                write_fixture(broken, ident, connection, fixture_context(ident), terminal=terminal)
                with self.assertRaises(ValueError):
                    import_window(broken, p, 0, 128)
            # The sidecar belongs to a different raw journal, despite a valid JSON structure.
            bad_binding = folder / "bad-binding.mtstream"
            write_fixture(bad_binding, ident, connection, fixture_context(ident), codes=(2004,) * 512,
                          terminal="full_accounting")
            companion_path(bad_binding).write_bytes(companion_path(path).read_bytes())
            with self.assertRaises(ValueError):
                import_window(bad_binding, p, 0, 128)

    def test_measured_context_stream_shot_csv_preserve_raw_at_each_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for rate, mode in ((50_000, "DC_WIDE"), (100_000, "AC_WIDE"), (150_000, "AC_SENSITIVE")):
                with self.subTest(rate=rate, mode=mode):
                    ident, connection = declared_identity(rate)
                    p = replace(plan(mode, origin="device"), raw_format=RawFormat.from_identity(ident))
                    if mode == "DC_WIDE":
                        record = dc_record(p)
                    else:
                        record = validate_control(fit_ac(p, window(p, 2048, "zero"),
                            window(p, 2100, "amplitude", sine_amplitude=400), 4.),
                            window(p, 2100, "control", sine_amplitude=200), 2.)
                    profile, snapshot = calibrated_selection(record, ident, hardware_instance_id="fixture-only")
                    context = StreamContext(input_profile=profile, analog_snapshot=snapshot)
                    path = folder / f"measured-{rate}.mtstream"
                    codes = (2000, 2400, 2400, 2000)
                    raw = write_fixture(path, ident, connection, context, codes=codes)
                    before = path.read_bytes()
                    verified = open_verified_context(path)
                    self.assertEqual(verified.context, context)
                    self.assertLess(companion_path(path).stat().st_size, 16384)
                    csv_path = folder / f"measured-{rate}.csv"
                    export_stream(csv_path, recover(path), verified)
                    with csv_path.open(encoding="utf8", newline="") as handle:
                        rows = list(csv.reader(handle))
                    self.assertEqual(rows[0][-1], "CH1_V" if mode == "DC_WIDE" else "CH1_ac_component_V")
                    self.assertEqual([int(row[2]) for row in rows[1:]], list(codes))
                    for row, code in zip(rows[1:], codes):
                        self.assertAlmostEqual(float(row[3]), profile.a * code + profile.b)
                    self.assertEqual(path.read_bytes(), before)
                    cfg = EventConfig(2200, 2000, "above", 1, 1, 1, 0, 4, 0,
                                      4092 if rate == 150_000 else 4095)
                    event = EventEntry(0, 101, 100, 104, 100, 101, 103, ())
                    shot = StreamCapture(ident, context, cfg, 0, 1, 100, 101, event, raw,
                        "event_closed", (), None, "running", STAMP)
                    shot_path = folder / f"measured-{rate}.mtshot"
                    save_capture(shot_path, shot)
                    loaded = load_capture(shot_path)
                    self.assertEqual(loaded, shot)
                    self.assertEqual(loaded.raw_u16le, raw)
                    self.assertEqual(loaded.context.analog_snapshot.calibration.record_sha256,
                                     profile.calibration_id)


if __name__ == "__main__":
    unittest.main()
