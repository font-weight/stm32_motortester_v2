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
        from PySide6 import QtCore, QtGui, QtWidgets
        from motortester.v2.core import load, cursor_measurement
        from motortester.v2.gui import MainWindow
        app = QtWidgets.QApplication([])
        app.setStyle("Fusion")
        report["qt_platform"] = app.platformName()
        report["qt"] = QtCore.qVersion()
        report["numpy"] = np.__version__
        assert report["frozen"] and sys.platform == "win32"
        assert report["qt_platform"] == "windows"

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

        def image(name):
            flush()
            path = output / name
            assert window.grab().save(str(path))
            decoded = QtGui.QImage(str(path))
            assert not decoded.isNull() and decoded.width() >= 1024

        def unexpected_message(*args, **kwargs):
            raise RuntimeError("Unexpected GUI error: " + str(args[1:3]))

        with tempfile.TemporaryDirectory(dir=output) as temporary, \
             patch.object(QtWidgets.QMessageBox, "critical", side_effect=unexpected_message), \
             patch.object(QtWidgets.QMessageBox, "warning", side_effect=unexpected_message):
            window = MainWindow(settings_path=Path(temporary) / "settings.ini")
            window.timer.stop()
            window.show()
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
            report["checks"].append("single capture; pause-independent recording with a real data gap")

            sample = output / "sample.mtv2"
            with patch.object(window, "_choose_path", return_value=(sample, False)):
                window.save_dialog()
            wait_idle()
            assert load(sample) == captured
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(sample), "")):
                window.open_dialog()
            wait_idle()
            assert window.completed == captured
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
            window.close()
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
