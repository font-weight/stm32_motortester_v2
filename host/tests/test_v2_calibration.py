"""Known synthetic transforms and targeted rejection/persistence checks only."""
from dataclasses import asdict, replace
import json
from math import pi, sin, sqrt
from pathlib import Path
import tempfile
import unittest

from motortester.stream_model import StreamIdentity
from motortester.v2.analog_profile import AnalogSnapshot, RawFormat, nominal_selection, quantize_thresholds
from motortester.v2.calibration import (
    CalibrationPlan, CalibrationRecord, SampleWindow, calibrated_selection,
    fit_dc, fit_ac, validate_control, save_calibration, load_calibration)
from motortester.v2.stream_device import StreamContext, context_from_dict


def format_for(bits=12):
    if bits == 12:
        return RawFormat.from_identity(StreamIdentity("calibration-test", 1, 1, 50_000, "synthetic"))
    return RawFormat(150_000, 5, 12, 10, 2, "u10packed_le", "left_shift_2",
                     "truncate_lsb", "u16le", "adc12", canonical_max=4092, canonical_step=4)


def plan(mode="DC_WIDE", bits=12, origin="synthetic", **changes):
    options = dict(mode_id=mode, raw_format=format_for(bits), hardware_instance_id="fixture-only",
        origin=origin, instrument="Искусственный набор, не измеритель", conditions="software only",
        reference_uncertainty_v=.001, tolerance_v=.1)
    if mode != "DC_WIDE":
        options.update(frequency_hz=1000., polarity_basis="Знак искусственного определения")
    options.update(changes)
    return CalibrationPlan(**options)


def window(p, code, name, *, sine_amplitude=None, noise=0):
    count = 1500 if p.raw_format.retained_bits == 10 else 1000
    step = p.raw_format.canonical_step
    if sine_amplitude is None:
        values = tuple(int(code + noise * (i % 3 - 1)) // step * step for i in range(count))
    else:
        values = tuple(int(round(code + sine_amplitude * sin(2*pi*p.frequency_hz*i/p.raw_format.sample_rate_hz)
                           + noise * (i % 3 - 1))) // step * step for i in range(count))
    return SampleWindow(values, name, p.raw_format, p.mode_id, p.hardware_instance_id, origin=p.origin)


def dc_record(p=None):
    p = p or plan()
    draft = fit_dc(p, window(p, 1500, "first"), -5., window(p, 2500, "second"), 5.)
    return validate_control(draft, window(p, 2000, "control"), 0.)


class CalibrationTests(unittest.TestCase):
    def test_dc_known_affine_and_synthetic_never_applies(self):
        record = dc_record()
        self.assertEqual((record.a, record.b), (.01, -20.))
        self.assertEqual(record.control_error_v, 0.)
        self.assertAlmostEqual(record.control_bound_v, .012)
        self.assertEqual(record.state, "synthetic_verified")
        self.assertFalse(record.can_apply)
        with self.assertRaisesRegex(ValueError, "реальных данных"):
            calibrated_selection(record, record.plan.raw_format, hardware_instance_id="fixture-only")
        packed = dc_record(plan(bits=10))
        self.assertEqual((packed.a, packed.b), (.01, -20.))
        self.assertAlmostEqual(packed.control_bound_v, .042)

    def test_control_includes_fit_uncertainty_and_keeps_failed_result(self):
        p = plan(reference_uncertainty_v=.04, tolerance_v=.05)
        record = dc_record(p)
        self.assertEqual(record.control_error_v, 0)
        self.assertAlmostEqual(record.control_bound_v, .09)
        self.assertEqual(record.state, "control_failed")
        with self.assertRaisesRegex(ValueError, "один раз"):
            validate_control(record, window(p, 2000, "new"), 0)

    def test_device_declared_fixture_roundtrips_snapshot_and_rejects_cross_mode(self):
        # Declared-device objects exercise serialization; this is still an
        # artificial test, not an actual device calibration or validation.
        record = dc_record(plan(origin="device"))
        profile, snapshot = calibrated_selection(record, record.plan.raw_format,
            hardware_instance_id="fixture-only")
        self.assertEqual(profile.state, "calibrated")
        self.assertIsNone(profile.vref_v)
        self.assertIsNone(profile.bandwidth_hz)
        self.assertIsNone(profile.linear_min_v)
        self.assertEqual(profile.voltage(2100), 1.)
        context = StreamContext(input_profile=profile, analog_snapshot=snapshot)
        self.assertEqual(context_from_dict(json.loads(json.dumps(asdict(context)))), context)
        self.assertLess(len(json.dumps(asdict(snapshot))), 6000)
        with self.assertRaises(ValueError):
            replace(snapshot, mode_id="AC_WIDE")
        with self.assertRaises(ValueError):
            snapshot.validate_profile(replace(profile, a=.011))
        with self.assertRaises(ValueError):
            calibrated_selection(record, format_for(10), hardware_instance_id="fixture-only")
        with self.assertRaises(ValueError):
            calibrated_selection(record, record.plan.raw_format, hardware_instance_id="another-board")
        negative = dc_record(plan(origin="device"))
        negative = replace(negative, reference_values=(5., -5., 0.))
        p2, _ = calibrated_selection(negative, negative.plan.raw_format, hardware_instance_id="fixture-only")
        self.assertEqual(quantize_thresholds(p2, 1., .1, "above", 12).code_polarity, "below")
        oldp, olds = nominal_selection("DC_WIDE", record.plan.raw_format)
        old = asdict(olds)
        old.pop("calibration")
        self.assertEqual(AnalogSnapshot.from_dict(old), olds)
        olds.validate_profile(oldp)

    def test_ac_separate_zero_amplitude_definitions_sign_and_control(self):
        for mode in ("AC_WIDE", "AC_SENSITIVE"):
            for kind, reference in (("Vpk", 2.), ("Vpp", 4.), ("Vrms", sqrt(2))):
                p = plan(mode, amplitude_kind=kind, polarity=-1)
                zero = window(p, 2050, "zero")
                # Signal offset intentionally differs: it must not redefine C0.
                draft = fit_ac(p, zero, window(p, 2150, "amplitude", sine_amplitude=400), reference)
                record = validate_control(draft, window(p, 2000, "control", sine_amplitude=200), reference/2)
                self.assertEqual(record.state, "synthetic_verified")
                self.assertAlmostEqual(record.a, -.005, delta=.000005)
                self.assertAlmostEqual(record.b, -record.a*2050)
                self.assertLess(abs(record.control_error_v), .005)
        p = plan("AC_WIDE", bits=10)
        record = validate_control(fit_ac(p, window(p, 2048, "zero"),
            window(p, 2100, "sine", sine_amplitude=400), 4.),
            window(p, 2100, "control", sine_amplitude=200), 2.)
        self.assertAlmostEqual(record.a, .005, delta=.00002)
        self.assertEqual(record.state, "synthetic_verified")

    def test_bad_data_and_reused_control_are_rejected(self):
        p = plan()
        first, second = window(p, 1500, "one"), window(p, 2500, "two")
        for invalid in (replace(first, has_gaps=True), replace(first, settled_confirmed=False),
                        replace(first, origin="device"), replace(first, mode_id="AC_WIDE"),
                        replace(first, codes=(0,)*len(first.codes)),
                        replace(first, codes=tuple(1500+i//5 for i in range(len(first.codes))))):
            with self.assertRaises(ValueError):
                fit_dc(p, invalid, -5., second, 5.)
        with self.assertRaises(ValueError):
            fit_dc(p, first, -5., window(p, 1501, "close"), 5.)
        draft = fit_dc(p, first, -5., second, 5.)
        with self.assertRaisesRegex(ValueError, "перекрывающиеся"):
            validate_control(draft, replace(window(p, 2000, "control"), source_id="one"), 0.)
        with self.assertRaises(ValueError):
            validate_control(draft, window(p, 2000, "control"), 5.)
        ap = plan("AC_WIDE")
        with self.assertRaises(ValueError):
            fit_ac(ap, window(ap, 2050, "zero"), window(ap, 2100, "constant"), 1.)
        with self.assertRaises(ValueError):
            fit_ac(ap, window(ap, 2050, "zero"), window(ap, 2100, "noisy", sine_amplitude=200, noise=100), 1.)
        with self.assertRaises(ValueError):
            fit_ac(ap, window(ap, 2050, "zero"), replace(window(ap, 2100, "short", sine_amplitude=200),
                codes=window(ap, 2100, "short", sine_amplitude=200).codes[:128]), 1.)

    def test_raw_file_preserves_draft_and_control_and_detects_tampering(self):
        record = dc_record()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.mtcal.json"
            save_calibration(path, record)
            self.assertEqual(load_calibration(path), record)
            self.assertEqual(CalibrationRecord.from_dict(record.to_dict()), record)
            with self.assertRaises(FileExistsError):
                save_calibration(path, record)
            data = record.to_dict()
            data["plan"]["origin"] = "device"
            path.write_text(json.dumps(data), encoding="utf8")
            with self.assertRaises(ValueError):
                load_calibration(path)
            data = record.to_dict()
            data["a"] = 123
            path.write_text(json.dumps(data), encoding="utf8")
            with self.assertRaises(ValueError):
                load_calibration(path)
        draft = fit_dc(record.plan, record.windows[0], -5., record.windows[1], 5.)
        self.assertEqual(CalibrationRecord.from_dict(draft.to_dict()).state, "fit_pending_validation")


if __name__ == "__main__":
    unittest.main()
