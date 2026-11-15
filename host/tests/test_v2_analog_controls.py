"""Only the new manual-selection and voltage-search editor boundaries."""
from dataclasses import replace
import unittest

from PySide6 import QtCore, QtWidgets

from motortester.stream_model import StreamIdentity
from motortester.v2.analog_profile import nominal_selection
from motortester.v2.analog_ui import AnalogInputDialog
from motortester.v2.input import UNKNOWN_PROFILE
from motortester.v2.stream_device import default_event_config
from motortester.v2.stream_search_ui import StreamSearchControls


class SearchOwner(QtCore.QObject):
    search_changed = QtCore.Signal()
    input_changed = QtCore.Signal()

    def __init__(self, profile):
        super().__init__()
        self.active_input_profile = profile
        self.voltage_unit = "В"
        self.archive = None
        self._opening = False
        self.cfg = default_event_config(150000, 10)

    def search_basis(self):
        return 150000, 10

    def search_config(self):
        return self.cfg

    def search_editable(self):
        return True

    def search_origin_note(self):
        return "Синтетическая проверка редактора"

    def apply_search(self, config):
        self.cfg = config
        return True


class AnalogControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.identity = StreamIdentity("analog-editor-test", 0, 7, 50000, "synthetic")

    def test_confirmation_resets_on_mode_change_and_new_dialog(self):
        dialog = AnalogInputDialog(identity=self.identity)
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog.mode.setCurrentIndex(1)
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.accept()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        dialog.confirm.setChecked(True)
        dialog.accept()
        self.assertEqual(dialog.profile.state, "nominal")
        next_dialog = AnalogInputDialog(identity=self.identity,
            current_profile=dialog.profile, current_snapshot=dialog.snapshot)
        self.assertFalse(next_dialog.confirm.isChecked())
        self.assertFalse(next_dialog.apply_button.isEnabled())
        next_dialog.confirm.setChecked(True)
        next_dialog.mode.setCurrentIndex(2)
        self.assertFalse(next_dialog.confirm.isChecked())
        self.assertIn("Постоянная составляющая не измеряется", next_dialog.explanation.text())
        next_dialog.mode.setCurrentIndex(0)
        next_dialog.accept()
        self.assertEqual(next_dialog.profile, UNKNOWN_PROFILE)
        self.assertIsNone(next_dialog.snapshot)
        dialog.close()
        next_dialog.close()

    def test_voltage_draft_units_quantization_and_negative_gain(self):
        profile, _ = nominal_selection("DC_WIDE", self.identity)
        for sign in (1, -1):
            with self.subTest(sign=sign):
                owner = SearchOwner(replace(profile, a=sign * abs(profile.a)))
                controls = StreamSearchControls(owner)
                # Rising voltage means decreasing codes for a negative gain.
                controls.rising.setChecked(True)
                requested = owner.active_input_profile.voltage(2601)
                controls.threshold.set_value(requested, emit=True)
                controls.hysteresis.setValue(abs(profile.a) * 399)
                expected = controls.candidate()
                self.assertEqual(expected.threshold_code % 4, 0)
                self.assertEqual(expected.release_code % 4, 0)
                self.assertEqual(expected.polarity, "above" if sign > 0 else "below")
                owner.voltage_unit = "мВ"
                owner.input_changed.emit()
                self.assertTrue(controls.dirty)
                self.assertAlmostEqual(controls.threshold.value, requested)
                self.assertEqual(controls.candidate(), expected)
                self.assertIn("Запрошено", controls.note.text())
                self.assertIn("После округления", controls.note.text())
                self.assertTrue(controls.apply_pending())
                self.assertEqual(owner.cfg, expected)
                controls.close()

    def test_subcode_hysteresis_rejected_without_changing_raw_search(self):
        profile, _ = nominal_selection("AC_SENSITIVE", self.identity)
        owner = SearchOwner(profile)
        original = owner.cfg
        controls = StreamSearchControls(owner)
        controls.hysteresis.setValue(abs(profile.a) * .1)
        self.assertFalse(controls.apply_button.isEnabled())
        self.assertIn("совпали", controls.note.text())
        self.assertFalse(controls.apply_pending())
        self.assertEqual(owner.cfg, original)
        controls.close()


if __name__ == "__main__":
    unittest.main()
