"""Visible legacy measurements use original blocks and their saved time/profile."""
from dataclasses import replace
import math
import threading
import time
import unittest
from unittest.mock import patch

from PySide6 import QtWidgets

from motortester.v2.data import Recording, SignalBlock
from motortester.v2.input import InputProfile, UNKNOWN_PROFILE
from motortester.v2.legacy_view import LegacyRecordingView, measure_legacy_interval


class LegacyMeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition(), 'Фоновый расчёт не завершился')

    def test_fractional_time_negative_gain_visible_raw_and_units(self):
        fs, origin = 1000.5, (1 << 52) + 100
        codes = tuple(round(2000 + 100 * math.sin(2 * math.pi * i / 100)) for i in range(1000))
        profile = InputProfile(a=-.01, b=25., state='nominal', profile_id='saved-negative',
                               coefficient_source='synthetic-fixture', coupling='DC')
        recording = Recording((SignalBlock(origin, fs, codes),), input_profile=profile)
        view = LegacyRecordingView()
        try:
            view.load_recording(recording)
            view.plot.setXRange(10 / fs, 910 / fs, padding=0)
            # Deliberately replace display points: no aggregate may read them.
            view.curve.setData([0, 1], [0, 4095])
            self.wait_for(lambda: view.measurement_result is not None)
            result = view.measurement_result
            self.assertEqual((result.count, result.min_code, result.max_code, result.mean_code),
                             (900, 1900, 2100, 2000))
            self.assertAlmostEqual(result.period_s, 100 / fs, places=10)
            self.assertIn('Min 4 В · Max 6 В · Размах 2 В', view.measurement_label.text())
            self.assertIn('Среднее DC на CH1: 5 В', view.measurement_label.text())
            self.assertIn('Fs 1000.5', view.measurement_label.text())
            view.set_voltage_unit('мВ')
            view.set_raw(True)
            self.assertIn('Min 1900 код', view.measurement_label.text())
            self.assertIn('Среднее DC на CH1: 5000 мВ', view.measurement_label.text())
            self.assertIs(view.recording, recording)
            self.assertEqual(recording.blocks[0].samples, codes)

            ac = replace(recording, input_profile=replace(profile, coupling='AC'))
            view.load_recording(ac)
            self.wait_for(lambda: view.measurement_result is not None)
            self.assertIn('AC не измеряет постоянную составляющую', view.measurement_label.text())
            self.assertNotIn('Среднее DC на CH1:', view.measurement_label.text())
            view.load_recording(replace(recording, input_profile=UNKNOWN_PROFILE))
            self.wait_for(lambda: view.measurement_result is not None)
            self.assertIn('шкала или режим DC входа не настроены', view.measurement_label.text())
        finally:
            view.close()

    def test_unknown_duration_boundary_missing_data_limit_and_new_file(self):
        recording = Recording((SignalBlock(100, 1000.5, (100,) * 40),
                               SignalBlock(140, 1000.5, (200,) * 40, gap_before='unknown_duration'),
                               SignalBlock(190, 1000.5, (300,) * 40)),
                              source='device', time_basis='nominal_unverified', input_profile=UNKNOWN_PROFILE)
        self.assertIn('разрыв', measure_legacy_interval(recording, 100, 180).data_reason)
        self.assertIn('разрыв', measure_legacy_interval(recording, 170, 210).data_reason)
        self.assertIsNone(measure_legacy_interval(recording, 140, 180).data_reason)
        self.assertIn('границы', measure_legacy_interval(recording, 99, 140).data_reason)
        self.assertIn('262 144', measure_legacy_interval(recording, 100, 262245).data_reason)
        self.assertIn('нет исходных', measure_legacy_interval(recording, 100, 100).data_reason)
        view = LegacyRecordingView()
        started, release = threading.Event(), threading.Event()
        original = measure_legacy_interval

        def delayed(source, start, stop):
            if source is recording:
                started.set()
                release.wait(3)
            return original(source, start, stop)

        try:
            with patch('motortester.v2.legacy_view.measure_legacy_interval', side_effect=delayed):
                view.load_recording(recording)
                self.wait_for(started.is_set)
                replacement = Recording((SignalBlock(0, 2000, (700,) * 64),),
                                        input_profile=UNKNOWN_PROFILE)
                view.load_recording(replacement)
                self.assertIsNone(view.measurement_result)
                release.set()
                self.wait_for(lambda: view.measurement_result is not None)
                self.assertEqual(view.measurement_result.mean_code, 700)
                self.assertIs(view.recording, replacement)
                self.assertIn('Fs 2000', view.measurement_label.text())
                self.assertNotIn('разрыв', view.measurement_label.text())
        finally:
            release.set()
            view.close()


if __name__ == '__main__':
    unittest.main()
