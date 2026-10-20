"""One bounded native frozen workflow; never opens a physical device."""
import csv
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch


def run(output_name):
    output = Path(output_name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "FAIL", "platform": sys.platform,
        "windows": platform.platform(), "python": sys.version,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": str(Path(sys.executable).resolve()),
        "cwd": str(Path.cwd()), "checks": [], "callback_errors": [],
    }
    original_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: report["callback_errors"].append(
        "".join(traceback.format_exception(kind, value, tb)))
    window = None
    try:
        # Import inside the receipt boundary so a missing Qt/DLL leaves evidence.
        import numpy as np
        import serial
        from serial import serialwin32
        from serial.tools import list_ports, list_ports_windows
        from PySide6 import QtCore, QtGui, QtWidgets
        from motortester.v2.core import load, save, cursor_measurement, UNKNOWN_PROFILE
        from motortester.v2.device import recording_from_capture
        from motortester.v2.device_ui import DevicePanel
        from motortester.v2.gui import MainWindow
        from motortester.wire_demo import synthetic_window, capture_from_synthetic_stream
        from motortester.window import SampleBlock, WindowCode, WindowResult
        app = QtWidgets.QApplication([])
        app.setStyle("Fusion")
        report["qt_platform"] = app.platformName()
        report["qt"] = QtCore.qVersion()
        report["numpy"] = np.__version__
        assert report["frozen"] and sys.platform == "win32"
        assert report["qt_platform"] == "windows"
        assert serial.Serial is serialwin32.Serial and callable(list_ports_windows.comports)

        def flush():
            app.processEvents()
            if report["callback_errors"]:
                raise RuntimeError(report["callback_errors"][0])

        def wait_idle():
            deadline = time.monotonic() + 10
            while window.busy and time.monotonic() < deadline:
                flush()
                time.sleep(.01)
            flush()
            assert not window.busy, "File worker timed out"

        def image(name, widget=None, minimum_width=1024):
            flush()
            path = output / name
            assert (window if widget is None else widget).grab().save(str(path))
            decoded = QtGui.QImage(str(path))
            assert not decoded.isNull() and decoded.width() >= minimum_width

        def unexpected_message(*args, **kwargs):
            raise RuntimeError("Unexpected GUI error: " + str(args[1:3]))

        with tempfile.TemporaryDirectory(dir=output) as temporary, \
             patch.object(QtWidgets.QMessageBox, "critical", side_effect=unexpected_message), \
             patch.object(QtWidgets.QMessageBox, "warning", side_effect=unexpected_message), \
             patch.object(QtWidgets.QMessageBox, "question", side_effect=unexpected_message), \
             patch.object(serialwin32.Serial, "open",
                          side_effect=RuntimeError("Package verification must not open a COM port")) as port_open, \
             patch.object(list_ports, "comports", return_value=(
                 SimpleNamespace(device="MOCK_STM32", description="Synthetic package check"),)) as enumeration:
            window = MainWindow(settings_path=Path(temporary) / "settings.ini")
            window.timer.stop()
            window.show()
            assert not window.device.bridge.running and not window.device.state.connected
            window.device_info()
            panel = window.device_panel
            assert isinstance(panel, DevicePanel)
            assert enumeration.called and panel.port.count() == 1
            assert panel.port.itemText(0) == "MOCK_STM32" and panel.port.currentText() == ""
            assert not panel.connect_button.isEnabled()
            assert not panel.live.isEnabled() and not panel.single.isEnabled()
            image("device-panel.png", panel, minimum_width=400)
            panel.hide()
            assert not window.device.bridge.running and port_open.call_count == 0
            report["checks"].append("packaged Windows pyserial; device panel with mocked enumeration; no COM open")
            image("scope.png")
            original = window.display_recording
            physical = cursor_measurement(original, .984, .988)
            window.units_combo.setCurrentIndex(1)
            assert window.display_recording is original
            assert cursor_measurement(original, .984, .988) == physical
            window.units_combo.setCurrentIndex(0)
            window.change_profile("ignition")
            window.waveform_combo.setCurrentIndex(2)
            window._tick()
            image("ignition.png")
            report["checks"].append("native GUI; both DEMO profiles; V/mV keeps raw and physical values")

            window.arm_single()
            for _ in range(4):
                window._tick()
                if window.armed_after is None:
                    break
            assert window.single and window.single.sample_count == 250
            assert not window.single.quality_flags
            single = window.single
            single_path = output / "single.mtv2"
            with patch.object(window, "_choose_path", return_value=(single_path, False)):
                window.save_dialog()
            wait_idle()
            assert load(single_path) == single
            assert not window.single_dirty
            window.set_mode(0)
            window.toggle_record()
            window._tick()
            window.toggle_pause()
            frozen_view = window.display_recording
            count = window.record_count
            window._tick()
            assert window.record_count == count + 2500 and window.display_recording is frozen_view
            window.inject_gap()
            window._tick()
            window.stop_recording()
            captured = window.completed
            assert captured.sample_count == 7500 and len(captured.gaps) == 1
            report["checks"].append("single capture saved through GUI; pause-independent recording with a real data gap")

            sample = output / "sample.mtv2"
            with patch.object(window, "_choose_path", return_value=(sample, False)):
                window.save_dialog()
            wait_idle()
            assert load(sample) == captured
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(sample), "")):
                window.open_dialog()
            wait_idle()
            assert window.completed is not captured and window.completed == captured
            window.full_signal()
            exported = output / "export.csv"
            with patch.object(window, "_choose_path", return_value=(exported, False)):
                window.export_dialog()
            wait_idle()
            rows = list(csv.DictReader(exported.read_text(encoding="utf-8").splitlines()))
            metadata = json.loads((output / "export.csv.json").read_text(encoding="utf-8"))
            assert len(rows) == 7500
            assert any(row["gap_before"] for row in rows)
            assert metadata["csv_sha256"] == hashlib.sha256(exported.read_bytes()).hexdigest()
            report["sample_count"] = captured.sample_count
            report["session_id"] = captured.session_id
            report["checks"].append("GUI save/open keeps raw and input snapshot; CSV/JSON keeps gap and checksum")

            # Exercise the packaged byte decoder and V2 bridge without a port.
            # This remains simulator data, even though it uses the device format.
            expected_raw, wire = synthetic_window()
            wire_capture = capture_from_synthetic_stream(wire)
            device_window = recording_from_capture(wire_capture)
            assert device_window.blocks[0].samples == expected_raw
            assert device_window.sample_count == 2048 and device_window.start_index == 0
            assert device_window.input_profile == UNKNOWN_PROFILE
            assert device_window.source == "demo" and "wire_simulator" in device_window.quality_flags
            assert device_window.time_basis == "nominal_unverified"
            assert device_window.capture_settings.threshold_v is None
            assert device_window.capture_settings.hardware_threshold_code == 2048
            device_sample = output / "device-window.mtv2"
            save(device_sample, device_window)
            assert load(device_sample) == device_window
            assert port_open.call_count == 0 and not window.device.bridge.running
            report["device_verification"] = {
                "status": "PASS", "serial_version": serial.__version__,
                "serial_backend": serial.Serial.__module__,
                "enumeration_mocked": True, "panel_created": True,
                "serial_open_calls": port_open.call_count, "worker_running": False,
                "wire_source": device_window.source, "sample_count": device_window.sample_count,
                "session_id": device_window.session_id, "voltage_state": device_window.input_profile.state,
                "time_basis": device_window.time_basis, "physical_device_verified": False,
            }
            report["checks"].append("synthetic wire 0.1 window -> V2 unknown scale -> exact save/reopen")
            # Only the exit dialog is under test here. Inject an explicitly
            # synthetic late result; native serial-worker cases run separately.
            partial = WindowResult(False, WindowCode.DISCONNECT, None,
                (SampleBlock(0, tuple(range(250))),), ((250, 2048),),
                None, None, None, (), False, ())
            window.device._incomplete_ready(partial)
            window.device._finished()
            full_before = sample.read_bytes()
            json_before = {path.name for path in output.glob("*.json")}
            decisions = []

            def answer_close(action):
                dialog = app.activeModalWidget()
                try:
                    assert isinstance(dialog, QtWidgets.QMessageBox)
                    assert dialog.windowTitle() == "Незавершённое окно"
                    assert dialog.defaultButton().text() == "Отмена"
                    assert dialog.escapeButton().text() == "Отмена"
                    assert "250" in dialog.text()
                    if action == "cancel":
                        image("incomplete-close.png", dialog, minimum_width=400)
                        app.sendEvent(dialog, QtGui.QKeyEvent(
                            QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape,
                            QtCore.Qt.KeyboardModifier.NoModifier))
                    else:
                        button = next(b for b in dialog.buttons() if b.text() == "Закрыть без JSON")
                        button.click()
                    decisions.append(action)
                except BaseException:
                    report["callback_errors"].append(traceback.format_exc())
                    if dialog is not None:
                        dialog.reject()

            QtCore.QTimer.singleShot(0, lambda: answer_close("cancel"))
            window.close()
            flush()
            assert decisions == ["cancel"]
            assert window.isVisible() and window.device.pending_incomplete is partial
            QtCore.QTimer.singleShot(0, lambda: answer_close("discard"))
            window.close()
            flush()
            assert decisions == ["cancel", "discard"]
            assert not window.isVisible() and window.device.pending_incomplete is None
            assert sample.read_bytes() == full_before
            assert {path.name for path in output.glob("*.json")} == json_before
            assert port_open.call_count == 0
            report["close_verification"] = {
                "status": "PASS", "source": "synthetic injected partial; no serial worker",
                "fragment_samples": 250, "default_and_escape": "cancel",
                "decisions": decisions, "closed_without_json": True,
                "saved_record_unchanged": True, "serial_open_calls": port_open.call_count,
            }
            report["checks"].append("actual exit dialog: Esc retains partial; explicit discard closes without JSON")
            flush()
            report["status"] = "PASS"
    except BaseException:
        report["status"] = "FAIL"
        report["error"] = traceback.format_exc()
    finally:
        if window is not None:
            window.timer.stop()
            window.single_dirty = window.record_dirty = False
            window.recording = window.busy = False
            # Failure cleanup must not open an unhandled modal and hide evidence.
            with patch.object(window, "_choose_incomplete_exit", return_value="cancel"):
                window.close()
            window.hide()
        sys.excepthook = original_hook
        report["files"] = {
            path.name: {"bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in output.iterdir() if path.is_file()
        }
        if report["callback_errors"]:
            report["status"] = "FAIL"
        (output / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1
