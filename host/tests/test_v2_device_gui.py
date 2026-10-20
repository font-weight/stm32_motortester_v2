"""One native Qt scenario across DEMO/device/file boundaries; no physical COM."""
import csv
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6 import QtWidgets
from motortester.session import Phase
from motortester.model import Capture
from motortester.transport import SerialTransport
from motortester.v2.core import load
from motortester.v2.device import DeviceBridge, recording_from_capture
from motortester.v2.gui import MainWindow
from test_v2_device import FakeSerial


class DeviceGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_source_pause_file_and_shutdown_boundaries(self):
        errors, calls, controls = [], [], {"trigger": True}
        original_hook = sys.excepthook
        sys.excepthook = lambda kind, value, tb: errors.append(str(value))
        def factory(parent):
            return DeviceBridge(parent, serial_factory=lambda: SerialTransport(
                backend_factory=lambda **kw: FakeSerial(controls, calls, **kw)), interval_ms=2)
        def wait(predicate, timeout=5):
            end = time.monotonic() + timeout
            while not predicate() and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(.005)
            self.app.processEvents()
            self.assertEqual(errors, [])
            self.assertTrue(predicate(), "Timed out waiting for GUI state")
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(settings_path=Path(tmp) / "settings.ini", device_bridge_factory=factory)
            window.show()
            try:
                self.assertEqual(calls, [])
                with patch("motortester.v2.device_ui.available_ports", return_value=(("FAKE_V2", "Synthetic"),)):
                    window.device_info()
                self.assertEqual(window.device_panel.port.currentText(), "")
                self.assertFalse(window.device_panel.connect_button.isEnabled())
                window.device_panel.port.setCurrentText("FAKE_V2")
                window.device_panel.connect_device()
                wait(lambda: window.device.snapshot and window.device.snapshot.phase is Phase.READY)
                self.assertTrue(window.device_active)
                self.assertIsNone(window.display_recording)
                self.assertFalse(window.timer.isActive())
                window.raw_view.setChecked(True)
                window.start_device(0)
                wait(lambda: window.device_last is not None)
                self.assertEqual(window.device_last.source, "device")
                self.assertFalse(window.device_last.input_profile.configured)
                self.assertEqual(window.display_recording.sample_count, 2048)
                self.assertEqual(window._axis_kind, "raw")
                window.toggle_pause()
                frozen = window.display_recording
                latest = window.device_last
                wait(lambda: window.device_last is not latest)
                self.assertIs(window.display_recording, frozen)
                window.device.stop()
                wait(lambda: window.device.snapshot.phase is Phase.READY and not window.device.state.busy)
                wait(lambda: not window.device.state.has_capture)
                self.assertIs(window.single, window.device_last)
                self.assertTrue(window.single_dirty)
                self.assertEqual(window.mode, 1)
                self.assertEqual(window.pretrigger.value(), 25)
                self.assertEqual(window.threshold.spin.specialValueText(), "Не настроен")
                self.assertEqual(window.holdoff.spin.specialValueText(), "Недоступна")
                capture = window.single
                self.assertTrue(all(block.start_index == 0 for block in capture.blocks))
                path = Path(tmp) / "window.mtv2"
                with patch.object(window, "_choose_path", return_value=(path, False)):
                    window.save_dialog()
                wait(lambda: not window.busy)
                self.assertEqual(load(path), capture)
                window.open_recording(load(path))
                self.assertEqual(window.mode, 2)
                self.assertEqual(window.origin_badge.text(), "ФАЙЛ · ПРИБОР")
                window.full_signal()
                export = Path(tmp) / "raw.csv"
                with patch.object(window, "_choose_path", return_value=(export, False)):
                    window.export_dialog()
                wait(lambda: not window.busy)
                rows = list(csv.DictReader(export.read_text(encoding="utf-8").splitlines()))
                self.assertEqual(len(rows), 2048)
                self.assertTrue(all(row["voltage_v"] == "" for row in rows))
                window.device.disconnect_source()
                wait(lambda: not window.device.state.connected and not window.device.state.busy)
                window.waveform_combo.setCurrentIndex(0)
                self.assertFalse(window.device_active)
                self.assertTrue(window.timer.isActive())
                self.assertEqual(window.display_recording.source, "demo")
                self.assertTrue(window.display_recording.input_profile.configured)
                self.assertEqual(window._axis_kind, "voltage")
                self.assertFalse(window.raw_view.isVisible())
                # File viewing is independent of which source will be used next.
                window.open_recording(capture)
                self.assertIn("Прибор", window.provenance_label.text())
                self.assertNotIn("ДЕМО", window.provenance_label.text())
                self.assertTrue(window.waveform_combo.isHidden())
                self.assertFalse(window.units_combo.isEnabled())
                window.close()
                wait(lambda: not window.device.bridge.running and not window.isVisible())
            finally:
                window.single_dirty = window.record_dirty = False
                window.device.shutdown()
                wait(lambda: not window.device.bridge.running)
                window.close()
                sys.excepthook = original_hook

    def test_final_callback_and_new_run_do_not_reuse_previous_window(self):
        """READY can precede the final capture callback; no physical transport."""
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(settings_path=Path(tmp) / "settings.ini")
            try:
                with patch("motortester.v2.device_ui.available_ports", return_value=()):
                    window.device_info()
                window.enter_device()
                old = recording_from_capture(Capture(
                    tuple(range(2048)), "00000000-0000-0000-0000-000000000001",
                    1, 50_000, "2026-10-20T00:00:00Z", origin="device",
                    trigger_index=None, pretrigger_samples=512, trigger_kind="auto_timeout"),
                    ui_profile="ignition")
                new = replace(old, legacy_sequence=2)
                window.device_last = old
                window.device_acquiring = True
                window._device_state(window.device.state)
                with patch.object(window.device, "accept") as accept:
                    window._device_window(new)
                    accept.assert_called_once_with(new)
                self.assertIs(window.single, new)
                self.assertIs(window.display_recording, new)
                self.assertTrue(window.single_dirty)
                self.assertIn("одно окно", window.plot_title.text())
                self.assertIn("Auto · без фронта", window.plot_subtitle.text())
                self.assertEqual(window.tabs[1].text(), "Одиночный захват")

                # Starting from a loaded file clears its display only after
                # the new command is admitted. A stop with no data stays empty.
                window.single_dirty = False
                window.open_recording(new)
                self.assertEqual(window.mode, 2)
                with patch.object(window.device, "start", return_value=True):
                    window.start_device(0)
                self.assertIsNone(window.device_last)
                self.assertIsNone(window.display_recording)
                self.assertIsNone(window.completed)
                self.assertIsNone(window.single)
                self.assertFalse(window.export_button.isEnabled())
                self.assertIn("Ожидание", window.plot_subtitle.text())
                window._device_state(window.device.state)
                self.assertIsNone(window.single)
                self.assertFalse(window.single_dirty)
                self.assertFalse(window.save_button.isEnabled())
            finally:
                window.single_dirty = window.record_dirty = False
                window.device_acquiring = False
                window.close()
                self.app.processEvents()

    def test_close_during_partial_window_save_then_close(self):
        """Shutdown-created fragments must be saveable before the final close."""
        controls, calls, errors = {"trigger": True, "hold_partial": True}, [], []
        def factory(parent):
            return DeviceBridge(parent, serial_factory=lambda: SerialTransport(
                backend_factory=lambda **kw: FakeSerial(controls, calls, **kw)), interval_ms=2)
        def wait(predicate):
            end = time.monotonic() + 5
            while not predicate() and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(.005)
            self.app.processEvents()
            self.assertEqual(errors, [])
            self.assertTrue(predicate(), "Late incomplete GUI operation timed out")
        with tempfile.TemporaryDirectory() as tmp, patch.object(
                sys, "excepthook", side_effect=lambda kind, value, tb: errors.append(str(value))):
            window = MainWindow(settings_path=Path(tmp) / "settings.ini", device_bridge_factory=factory)
            window.show()
            try:
                with patch("motortester.v2.device_ui.available_ports", return_value=()):
                    window.device_info()
                window.device_panel.port.setCurrentText("FAKE_V2")
                window.device_panel.connect_device()
                wait(lambda: window.device.snapshot and window.device.snapshot.phase is Phase.READY)
                window.start_device(2)
                wait(lambda: controls.get("partial_delivered"))
                self.assertIsNone(window.device.pending_incomplete)
                window.close()
                wait(lambda: window._device_shutdown and window.device.pending_incomplete is not None)
                self.assertFalse(window.device.bridge.running)
                self.assertTrue(window.isVisible())
                path = Path(tmp) / "late.json"
                with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                    window.save_device_fragments()
                wait(lambda: not window.busy)
                self.assertIsNone(window.device.pending_incomplete)
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(sum(len(f["samples"]) for f in data["result"]["fragments"]), 250)
                self.assertEqual(data["result"]["missing_ranges"], [[250, 2048]])
                window.close()
                wait(lambda: not window.isVisible())
            finally:
                window.device.shutdown()
                wait(lambda: not window.device.bridge.running)
                window.hide()


if __name__ == "__main__":
    unittest.main()
