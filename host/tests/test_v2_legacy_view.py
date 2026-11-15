"""Compatibility view keeps source gaps/profiles and never fabricates streams."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PySide6 import QtWidgets

from motortester.v2.data import Recording, SignalBlock
from motortester.v2.input import InputProfile, UNKNOWN_PROFILE
from motortester.v2.legacy_view import LegacyRecordingView
from motortester.v2.storage import save


class LegacyViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_gaps_raw_cursor_and_original_export(self):
        fs = 1000.5
        recording = Recording((SignalBlock(100, fs, (1, 2, 3)),
                               SignalBlock(106, fs, (4, 5)),
                               SignalBlock(108, fs, (6, 7), gap_before='unknown_duration')),
                              source='device', time_basis='measured', input_profile=UNKNOWN_PROFILE)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'old.mtv2'
            save(source, recording)
            before = source.read_bytes()
            view = LegacyRecordingView()
            self.assertEqual(view.load_path(source), recording)
            self.assertEqual(view.recording, recording)
            self.assertEqual(np.isnan(view._x).sum(), 2)
            self.assertEqual(view._codes[np.isfinite(view._codes)].tolist(), [1, 2, 3, 4, 5, 6, 7])
            self.assertIn('разрывов: 2', view.quality.text())
            self.assertIn('измеренная в файле', view.info.text())
            view.set_raw(False)
            self.assertFalse(view.voltage_display)
            view.cursor_toggle.setChecked(True)
            view.cursor_lines[0].setValue(4/fs)
            view.cursor_lines[1].setValue(6/fs)
            self.assertIn('A: нет исходного отсчёта', view.cursor_readout.text())
            self.assertIn('4 код', view.cursor_readout.text())
            self.assertNotIn('Δt:', view.cursor_readout.text())
            exported, sidecar = view.export_path(Path(folder)/'original.csv')
            with exported.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([int(row['sample_index']) for row in rows], [100, 101, 102, 106, 107, 108, 109])
            metadata = json.loads(sidecar.read_text(encoding='utf-8'))
            self.assertEqual(metadata['time_basis'], 'measured')
            self.assertEqual(len(metadata['gaps']), 2)
            self.assertEqual(source.read_bytes(), before)
            view.close()

    def test_negative_voltage_profile_and_scope_units(self):
        profile = InputProfile(a=-.01, b=2., state='nominal', profile_id='saved',
                               coefficient_source='fixture', coupling='AC')
        recording = Recording((SignalBlock(50, 1000, (100, 200, 300)),), input_profile=profile)
        view = LegacyRecordingView()
        view.load_recording(recording)
        self.assertTrue(view.voltage_display)
        np.testing.assert_allclose(view.curve.yData, [1, 0, -1])
        self.assertIn('постоянная составляющая не измеряется', view.profile_note.text())
        view.set_voltage_unit('мВ')
        np.testing.assert_allclose(view.curve.yData, [1, 0, -1])
        self.assertEqual(view.axis.factor, 1000)
        self.assertTrue(view.apply_scope_view(seconds_per_div=.002, x_start_s=.001, y_center=0, codes_per_div=.5))
        np.testing.assert_allclose(view.plot.getViewBox().viewRange()[0], [.001, .021])
        np.testing.assert_allclose(view.plot.getViewBox().viewRange()[1], [-2, 2])
        view.set_raw(True)
        np.testing.assert_allclose(view.curve.yData, [100, 200, 300])
        np.testing.assert_allclose(view.plot.getViewBox().viewRange()[1], [0, 400])
        self.assertIs(view.recording, recording)
        view.full_signal()
        np.testing.assert_allclose(view.plot.getViewBox().viewRange()[0], [0, .003])
        view.close()


if __name__ == '__main__':
    unittest.main()
