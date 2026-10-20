"""Targeted exit decisions with synthetic serial; never opens a physical COM."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6 import QtWidgets
from motortester.session import Phase
from motortester.transport import SerialTransport
from motortester.v2.core import load, save
from motortester.v2.device import DeviceBridge, recording_from_capture
from motortester.v2.gui import MainWindow
from motortester.wire_demo import synthetic_window, capture_from_synthetic_stream
from test_v2_device import FakeSerial


class CloseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def wait(self, predicate):
        until = time.monotonic() + 5
        while not predicate() and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertEqual(self.errors, [])
        self.assertTrue(predicate(), "Exit decision timed out")

    @contextmanager
    def connected(self, *, late):
        controls = {"trigger": True, "hold_partial": late, "partial": not late}
        calls, self.errors = [], []
        def factory(parent):
            return DeviceBridge(parent, serial_factory=lambda: SerialTransport(
                backend_factory=lambda **kw: FakeSerial(controls, calls, **kw)), interval_ms=2)
        with tempfile.TemporaryDirectory() as folder, patch.object(
                sys, "excepthook", side_effect=lambda kind, value, tb: self.errors.append(str(value))):
            window = MainWindow(settings_path=Path(folder) / "settings.ini", device_bridge_factory=factory)
            window.show()
            try:
                with patch("motortester.v2.device_ui.available_ports", return_value=()):
                    window.device_info()
                window.device_panel.port.setCurrentText("FAKE_V2")
                window.device_panel.connect_device()
                self.wait(lambda: window.device.snapshot and window.device.snapshot.phase is Phase.READY)
                window.start_device(2)
                if late:
                    self.wait(lambda: controls.get("partial_delivered"))
                    self.assertIsNone(window.device.pending_incomplete)
                else:
                    self.wait(lambda: window.device.pending_incomplete is not None
                              and not window.device.state.connected)
                yield window, Path(folder)
            finally:
                with patch.object(window, "_choose_incomplete_exit", return_value="cancel"):
                    window.device.shutdown()
                    self.wait(lambda: not window.device.bridge.running)
                window.hide()

    def test_pending_cancel_then_discard_keeps_saved_record(self):
        with self.connected(late=False) as (window, folder):
            partial = window.device.pending_incomplete
            _, wire = synthetic_window()
            full = recording_from_capture(capture_from_synthetic_stream(wire))
            path = folder / "saved.mtv2"
            save(path, full)
            original = path.read_bytes()
            window.open_recording(load(path))
            with patch.object(window, "_choose_incomplete_exit", return_value="cancel") as choose:
                window.close()
                self.app.processEvents()
                choose.assert_called_once_with(partial)
            self.assertTrue(window.isVisible())
            self.assertTrue(window.device.bridge.running)
            self.assertIs(window.device.pending_incomplete, partial)
            with patch.object(window, "_choose_incomplete_exit", return_value="discard") as choose:
                window.close()
                self.wait(lambda: not window.device.bridge.running and not window.isVisible())
                choose.assert_called_once_with(partial)
            self.assertIsNone(window.device.pending_incomplete)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(load(path), full)
            self.assertEqual(list(folder.glob("*.json")), [])

    def test_late_partial_discard_closes_without_json(self):
        with self.connected(late=True) as (window, folder):
            with patch.object(window, "_choose_incomplete_exit", return_value="discard") as choose:
                window.close()
                self.wait(lambda: not window.device.bridge.running and not window.isVisible())
                self.assertEqual(choose.call_count, 1)
                partial = choose.call_args.args[0]
            self.assertEqual(sum(len(f.samples) for f in partial.fragments), 250)
            self.assertIsNone(window.device.pending_incomplete)
            self.assertEqual(list(folder.glob("*.json")), [])

    def test_save_cancel_error_then_success(self):
        with self.connected(late=True) as (window, folder):
            with patch.object(window, "_choose_incomplete_exit", return_value="cancel"):
                window.close()
                self.wait(lambda: window._device_shutdown and window.device.pending_incomplete is not None)
            partial = window.device.pending_incomplete
            self.assertTrue(window.isVisible())
            with patch.object(window, "_choose_incomplete_exit", return_value="save"), patch.object(
                    QtWidgets.QFileDialog, "getSaveFileName", return_value=("", "")):
                window.close()
            self.assertIs(window.device.pending_incomplete, partial)
            self.assertTrue(window.isVisible())
            with patch.object(window, "_choose_incomplete_exit", return_value="save"), patch.object(
                    QtWidgets.QFileDialog, "getSaveFileName",
                    return_value=(str(folder / "missing" / "partial.json"), "")), patch.object(
                    QtWidgets.QMessageBox, "warning") as warning:
                window.close()
                self.wait(lambda: not window.busy)
                warning.assert_called_once()
            self.assertIs(window.device.pending_incomplete, partial)
            self.assertTrue(window.isVisible())
            path = folder / "partial.json"
            with patch.object(window, "_choose_incomplete_exit", return_value="save") as choose, patch.object(
                    QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                window.close()
                self.wait(lambda: not window.busy and not window.isVisible())
                choose.assert_called_once_with(partial)
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sum(len(f["samples"]) for f in report["result"]["fragments"]), 250)
            self.assertEqual(report["result"]["missing_ranges"], [[250, 2048]])
            self.assertIsNone(window.device.pending_incomplete)


if __name__ == "__main__":
    unittest.main()
