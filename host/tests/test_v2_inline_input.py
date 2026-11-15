"""Only inline draft ownership, physical confirmation and file isolation."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6 import QtWidgets

from motortester.v2.analog_profile import RawFormat, nominal_selection
from motortester.v2.inline_input import InlineAnalogControls
from motortester.v2.input import UNKNOWN_PROFILE


FORMAT = RawFormat(50000, 1, 12, 12, 0, "u16le", "identity", "none", "u16le", "adc12")


class FakePanel:
    def __init__(self):
        self.bridge = SimpleNamespace(connection=object(), input_format=FORMAT)
        self.active_input_profile, self.active_analog_snapshot = UNKNOWN_PROFILE, None
        self._opening = False
        self.editable = True
        self.calls = []

    def input_editable(self):
        return self.editable and not self._opening

    def apply_input_profile(self, profile, snapshot):
        if not self.input_editable():
            return False
        self.calls.append((profile, snapshot))
        self.active_input_profile, self.active_analog_snapshot = profile, snapshot
        return True


class InlineInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_offline_draft_refresh_and_manual_confirmation(self):
        controls = InlineAnalogControls()
        self.assertFalse(controls.mode.isEnabled())
        self.assertTrue(controls.calibration_button.isEnabled())
        panel = FakePanel()
        controls.bind_panel(panel)
        controls.mode.setCurrentIndex(1)
        controls.instance.setText("R53 №1")
        self.assertFalse(controls.apply_input())
        self.assertEqual(panel.calls, [])
        controls.confirm.setChecked(True)
        for _ in range(4):
            controls.refresh()
        self.assertEqual(controls.instance.text(), "R53 №1")
        self.assertTrue(controls.confirm.isChecked())
        # A temporary busy/file-picker state only locks editing, not the draft.
        panel.editable = False
        controls.refresh()
        self.assertFalse(controls.mode.isEnabled())
        self.assertEqual(controls.instance.text(), "R53 №1")
        panel.editable = True
        controls.refresh()
        self.assertTrue(controls.confirm.isChecked())
        self.assertTrue(controls.apply_input())
        self.assertEqual(panel.active_analog_snapshot.mode_id, "DC_WIDE")
        self.assertEqual(panel.active_analog_snapshot.hardware_instance_id, "R53 №1")
        controls.mode.setCurrentIndex(2)
        self.assertFalse(controls.confirm.isChecked())
        self.assertIn("Постоянная составляющая", controls.calibration_note.text())
        controls.mode.setCurrentIndex(0)
        self.assertTrue(controls.apply_input())
        self.assertEqual(panel.active_input_profile, UNKNOWN_PROFILE)
        controls.close()

    def test_connection_and_file_changes_invalidate_without_applying(self):
        controls, panel = InlineAnalogControls(), FakePanel()
        controls.bind_panel(panel)
        controls.mode.setCurrentIndex(1)
        controls.confirm.setChecked(True)
        panel.bridge = SimpleNamespace(connection=object(), input_format=FORMAT)
        controls.refresh()
        self.assertFalse(controls.confirm.isChecked())
        self.assertIsNone(controls.mode.currentData())
        panel.active_input_profile, panel.active_analog_snapshot = nominal_selection("AC_SENSITIVE", FORMAT, hardware_instance_id="recorded board")
        panel._opening = True
        controls.refresh()
        self.assertFalse(controls.mode.isEnabled())
        self.assertFalse(controls.apply_input())
        self.assertEqual(controls.mode.currentData(), "AC_SENSITIVE")
        self.assertIn("Шкала открытой записи", controls.note.text())
        self.assertEqual(panel.calls, [])
        # A ready new device does not inherit the file's R5 identity.
        panel._opening = False
        panel.active_input_profile, panel.active_analog_snapshot = UNKNOWN_PROFILE, None
        controls.refresh()
        self.assertEqual(controls.instance.text(), "")
        self.assertIsNone(controls.mode.currentData())
        controls.close()

    def test_calibration_requires_matching_connection_and_reconfirmation(self):
        controls, panel = InlineAnalogControls(), FakePanel()
        controls.bind_panel(panel)
        controls.mode.setCurrentIndex(1)
        controls.instance.setText("board")
        controls.confirm.setChecked(True)
        pair = nominal_selection("DC_WIDE", FORMAT, hardware_instance_id="board")
        record = SimpleNamespace(plan=SimpleNamespace(mode_id="DC_WIDE"))
        # Replace the file reader/selection only: coefficient calculations and
        # physical provenance gates are tested by the calibration model suite.
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=("fixture.json", "")), \
                patch("motortester.v2.calibration.load_calibration", return_value=record), \
                patch("motortester.v2.calibration.calibrated_selection", return_value=pair):
            self.assertTrue(controls.load_calibration())
        self.assertFalse(controls.confirm.isChecked())
        self.assertFalse(controls.apply_input())
        self.assertEqual(controls.measured_pair, pair)
        controls.refresh()
        self.assertEqual(controls.measured_pair, pair)
        controls.instance.setText("other")
        self.assertIsNone(controls.measured_pair)
        self.assertFalse(controls.confirm.isChecked())
        def switch_connection(*args, **kwargs):
            panel.bridge = SimpleNamespace(connection=object(), input_format=FORMAT)
            return "fixture.json", ""
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", side_effect=switch_connection), \
                patch("motortester.v2.calibration.load_calibration") as reader:
            self.assertFalse(controls.load_calibration())
            reader.assert_not_called()
        self.assertIn("изменился", controls.error.text())
        controls.close()


if __name__ == "__main__":
    unittest.main()
