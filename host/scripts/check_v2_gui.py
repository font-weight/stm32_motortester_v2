"""Focused real-Qt V2 smoke; no hardware, serial ports or user settings.

From the repository root:
  .venv\\Scripts\\python.exe host\\scripts\\check_v2_gui.py OUTPUT_DIRECTORY
The output directory must be new. Timers are stopped and source ticks explicit,
so screenshots and state checks do not depend on machine scheduling.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from motortester import recording as legacy
from motortester.model import Capture
from motortester.v2.core import (
    CaptureSettings, DemoSource, InputProfile, Recording, SignalBlock, load, save,
)
from motortester.v2.gui import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {
        "scope": "synthetic real-Qt GUI; no device or packaged Windows release",
        "platform": platform.platform(), "python": sys.version,
        "qt": QtCore.qVersion(), "checks": [], "screenshots": {},
        "callback_errors": [], "status": "FAIL",
    }
    original_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: result["callback_errors"].append(
        "".join(traceback.format_exception(kind, value, tb)))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle("Fusion")
    result["qt_platform"] = app.platformName()
    windows = []

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def flush():
        app.processEvents()
        check(not result["callback_errors"], "Unhandled Qt callback exception")

    def wait_idle(window):
        deadline = time.monotonic() + 10
        while window.busy and time.monotonic() < deadline:
            flush()
            time.sleep(.01)
        flush()
        check(not window.busy, "File worker did not finish within 10 s")

    def unexpected_dialog(*args, **kwargs):
        raise AssertionError("Unexpected GUI message: " + str(args[1:3]))

    def snapshot(window, name):
        flush()
        path = args.output / (name + ".png")
        check(window.grab().save(str(path)), "Screenshot could not be saved")
        knobs = {}
        for attr in ("sweep", "yscale", "xposition", "yposition", "threshold", "holdoff"):
            knob = getattr(window, attr)
            spin, editor = knob.spin, knob.spin.lineEdit()
            knobs[attr] = {
                "text": spin.text(), "width": spin.width(),
                "editor_text": editor.text(), "editor_width": editor.width(),
                "editor_contents_width": editor.contentsRect().width(),
                "text_color": editor.palette().color(QtGui.QPalette.ColorRole.Text).name(),
                "visible": spin.isVisible(), "enabled": spin.isEnabled(),
            }
        result["screenshots"][name] = {
            "file": path.name, "size": [window.width(), window.height()],
            "minimum_size_hint": [window.minimumSizeHint().width(), window.minimumSizeHint().height()],
            "device_pixel_ratio": window.devicePixelRatioF(), "knobs": knobs,
        }

    def save_via_gui(window, filename):
        path = args.output / filename
        with patch.object(window, "_choose_path", return_value=(path, False)):
            window.save_dialog()
        wait_idle(window)
        return load(path)

    def open_via_gui(window, path):
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(path), "")):
            window.open_dialog()
        wait_idle(window)

    try:
        with tempfile.TemporaryDirectory(prefix="v2-smoke-", dir=args.output) as temporary, \
             patch.object(QtWidgets.QMessageBox, "warning", side_effect=unexpected_dialog), \
             patch.object(QtWidgets.QMessageBox, "critical", side_effect=unexpected_dialog):
            settings = Path(temporary) / "isolated.ini"
            window = MainWindow(settings_path=settings)
            windows.append(window)
            window.timer.stop()
            window.show()
            flush()
            snapshot(window, "01_scope")

            # Pausing the picture must leave incoming raw data and Record active.
            window.toggle_record()
            window._tick()
            window._tick()
            window.toggle_pause()
            frozen = window.display_recording
            frozen_xy = tuple(np.array(values, copy=True) for values in window.curve.getData())
            before = window.record_count
            for _ in range(3):
                window._tick()
            check(window.recording and window.record_count == before + 7500,
                  "View pause interrupted recording")
            check(window.display_recording is frozen, "Paused display was replaced")
            check(all(np.array_equal(a, b, equal_nan=True) for a, b in
                      zip(frozen_xy, window.curve.getData())), "Paused curve moved")
            window.inject_gap()
            window._tick()
            window.toggle_record()
            recorded = window.completed
            check(len(recorded.gaps) == 1 and
                  recorded.gaps[0].end_index - recorded.gaps[0].start_index == 5000,
                  "Explicit 100 ms gap was lost")
            snapshot(window, "02_recording")
            check(save_via_gui(window, "сеанс.mtv2") == recorded, "GUI Save changed raw/profile")
            check(not window.record_dirty, "Successful Save left record dirty")
            open_via_gui(window, args.output / "сеанс.mtv2")
            check(window.completed == recorded, "GUI Open changed saved recording")
            window.full_signal()
            csv_path = args.output / "участок.csv"
            with patch.object(window, "_choose_path", return_value=(csv_path, False)):
                window.export_dialog()
            wait_idle(window)
            sidecar = csv_path.with_suffix(".csv.json")
            check(sidecar.exists(), "CSV metadata must use .csv.json")
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
            check(len(rows) == recorded.sample_count, "Full-view export dropped samples")
            check(any(row["gap_before"] == "synthetic_missing_samples" for row in rows),
                  "CSV lost the explicit gap")
            check(meta["csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                  "CSV and JSON are not linked")
            result["checks"].append("pause-independent recording, gap, GUI save/open, CSV+JSON")

            # A new display name is persistent but cannot rewrite a stored session.
            window.set_mode(0)
            check(window.rename_channel("Проверка катушки"), "Rename failed")
            check(window.completed.channel_name == recorded.channel_name, "Rename rewrote recording")
            other = MainWindow(settings_path=settings)
            windows.append(other)
            other.timer.stop()
            check(other.channel_name == "Проверка катушки", "Name did not persist in isolated INI")
            other.close()
            result["checks"].append("persistent CH1 name; old snapshot unchanged")

            # A 200 ms capture needs several 50 ms source blocks after its trigger.
            window.sweep.set_value(.02)
            window.arm_single()
            check(window.armed_after is not None, "Single capture was not armed")
            window._tick()
            check(window._pending_trigger is not None and window.armed_after is not None,
                  "Long single capture did not wait for post-trigger samples")
            check(window.single is None, "Long single capture was published too early")
            for _ in range(8):
                window._tick()
                if window.armed_after is None:
                    break
            single = window.single
            check(single is not None and single.sample_count == 10_000, "Incomplete 200 ms capture")
            check(not single.quality_flags and not single.gaps, "Complete synthetic capture flagged incomplete")
            check(single.trigger_index - single.start_index == 2000, "Wrong 20% prehistory")
            expected = DemoSource("sine")
            expected.next_index = single.start_index
            check(tuple(code for block in single.blocks for code in block.samples)
                  == expected.next_block(single.sample_count).samples, "Single raw samples changed")
            snapshot(window, "03_single")

            # Separate dirty bits protect each object, without unrelated prompts.
            window.set_mode(0)
            with patch.object(window, "_confirm_discard", return_value=False) as confirm:
                window.arm_single()
                check(confirm.call_count == 1 and window.armed_after is None,
                      "Unsaved single was replaced without consent")
                confirm.reset_mock()
                window.toggle_record()
                check(window.recording and not confirm.called,
                      "Unsaved single incorrectly blocked independent Record")
            window._tick()
            window.stop_recording()
            check(window.single_dirty and window.record_dirty, "Dirty states are not independent")
            window.set_mode(1)
            check(save_via_gui(window, "импульс.mtv2") == single, "Single Save changed its snapshot")
            check(not window.single_dirty and window.record_dirty, "Single Save cleared Record dirty")
            window.set_mode(0)
            with patch.object(window, "_confirm_discard", return_value=False) as confirm:
                window.arm_single()
                check(window.armed_after is not None and not confirm.called,
                      "Unsaved Record incorrectly blocked independent Single")
                window.arm_single()  # Cancel waiting; no replacement data existed.
                window.set_mode(0)
                window.toggle_record()
                check(confirm.call_count == 1 and not window.recording,
                      "Unsaved recording was replaced without consent")
            window.set_mode(2)
            save_via_gui(window, "вторая-запись.mtv2")
            result["checks"].append("200 ms single waits for posthistory; exact raw; independent dirty guards")

            signed = Recording(
                (SignalBlock(0, 1000, (1000, 2000, 3000)),),
                input_profile=InputProfile(a=-.002, b=4, state="nominal",
                                          coefficient_source="synthetic-smoke"),
                capture_settings=CaptureSettings(threshold_v=-.5),
            )
            signed_path = args.output / "signed.mtv2"
            save(signed_path, signed)
            open_via_gui(window, signed_path)
            check(window.completed == signed and window.threshold.value == -.5,
                  "Opening signed input profile changed threshold or coefficients")
            check(np.array_equal(window.curve.getData()[1], [2., 0., -2.]),
                  "Signed voltage profile is not applied to displayed raw")
            old = Capture(samples=(20, 30, 40), session_id=str(uuid4()), sequence=7,
                          nominal_fs_hz=1000, received_at_utc="2026-10-20T10:00:00Z",
                          trigger_index=1, pretrigger_samples=1, trigger_level_code=25)
            legacy_path = args.output / "старый.mtcap"
            legacy.save(legacy_path, old)
            open_via_gui(window, legacy_path)
            check(window.completed.input_profile.state == "unconfigured" and
                  window.completed.capture_settings.threshold_v is None,
                  "Legacy file acquired fabricated voltage calibration")
            check(window.unconfigured_text.isVisible() and
                  np.isnan(window.curve.getData()[1]).all(), "Unknown scale displayed fabricated volts")
            result["checks"].append("signed saved input/threshold; legacy unknown scale and threshold=None")

            window.set_mode(0)
            window.change_profile("ignition")
            window.waveform_combo.setCurrentIndex(2)
            window._tick()
            snapshot(window, "04_ignition")
            window.resize(1024, 700)
            snapshot(window, "05_compact")
            check(window.plot.height() >= 170, "Main plot collapsed at compact size")
            check(not window.paused and "Пауза" not in window.state_label.text(),
                  "Changing DEMO waveform left a stale paused-state label")
            check(all(knob["editor_contents_width"] >= 24
                      for image in result["screenshots"].values()
                      for knob in image["knobs"].values()),
                  "Numeric input editor collapsed: values exist but are not readable")
            result["checks"].append("real visible Qt screenshots: scope, recording, single, ignition, compact request")
            major_y = window.plot.getAxis("left").tickValues(-2, 4, 400)[0][0]
            major_x = window.plot.getAxis("bottom").tickValues(0, 200, 600)[0][0]
            check(abs(major_y - window.yscale.value) < 1e-9 and
                  abs(major_x - window.sweep.value * 1000) < 1e-9,
                  "Grid divisions disagree with the displayed per-division controls")
            invalid_analysis = replace(recorded, ui_profile="ignition",
                capture_settings=replace(recorded.capture_settings, threshold_v=10))
            window.open_recording(invalid_analysis)
            check(window.completed is invalid_analysis and window.mode == 2 and not window.events,
                  "Unavailable event analysis prevented raw viewing or partially replaced the document")
            check("События не рассчитаны" in window.statusBar().currentMessage(),
                  "Event-analysis failure was not explained")
            result["checks"].append("physical grid spacing; unavailable event analysis leaves a complete view")
            # One bounded maximum-size observation; no 40-second wait or hardware.
            large = Recording((SignalBlock(0, 50_000, (1000, 3000) * 1_000_000),))
            large_path = args.output / "maximum.mtv2"
            beats = []
            heartbeat = QtCore.QTimer()
            heartbeat.setInterval(10)
            heartbeat.timeout.connect(lambda: beats.append(time.perf_counter()))
            heartbeat.start()
            started = time.perf_counter()
            save(large_path, large)
            open_via_gui(window, large_path)
            opened_seconds = time.perf_counter() - started
            deadline = time.monotonic() + 15
            while (window._analysis_job is not None or window._analysis_pending is not None) and time.monotonic() < deadline:
                flush()
                time.sleep(.005)
            heartbeat.stop()
            check(window._analysis_job is None and window._analysis_pending is None,
                  "Maximum-size analysis exceeded its smoke bound")
            check(window.completed.sample_count == 2_000_000 and window.completed == large,
                  "Maximum-size roundtrip changed the recording")
            result["maximum_recording"] = {
                "samples": large.sample_count, "file_bytes": large_path.stat().st_size,
                "save_open_view_seconds": opened_seconds,
                "total_with_analysis_seconds": time.perf_counter() - started,
                "event_loop_heartbeats_during_open_and_analysis": len(beats),
            }
            result["checks"].append("one 2,000,000-sample raw save/open/view resource observation")
            result["compact_requested"] = [1024, 700]
            result["compact_actual"] = [window.width(), window.height()]
            result["status"] = "PASS"
    except Exception:
        result["failure"] = traceback.format_exc()
    finally:
        for window in windows:
            window.timer.stop()
            window.single_dirty = window.record_dirty = False
            window.recording = False
            window.busy = False
            window.close()
        app.processEvents()
        sys.excepthook = original_hook
        if result["callback_errors"]:
            result["status"] = "FAIL"
        (args.output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f'{result["status"]}: {len(result["checks"])} focused scenarios; {args.output.resolve()}')
    if result.get("failure"):
        print(result["failure"], file=sys.stderr)
    for error in result["callback_errors"]:
        print(error, file=sys.stderr)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
