"""Native/frozen Windows witness of R5 scales, using injected wire bytes only.

The normal main window, connection owner, receiver, file readers and controls
are exercised. No serial port is opened and no analogue measurement is made.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import faulthandler
import json
import math
from pathlib import Path
import platform
import struct
import sys
import time
import traceback
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets


def exercise(app, output):
    from .analog_ui import AnalogInputDialog
    from .gui import MainWindow
    from .input import UNKNOWN_PROFILE
    from .serial_smoke import _Factory
    from .stream_capture import load_capture
    from .stream_device import StreamDeviceBridge, companion_path
    from .stream_files import open_stream
    from .stream_profiles_smoke import ProfilesBackend
    from .stream_ui import StreamDialog
    from ..stream_recording import AttemptReport

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    log = (output / "run.log").open("w", encoding="utf-8")
    faulthandler.dump_traceback_later(15, file=log)

    def stage(name):
        log.write(name + "\n")
        log.flush()
    report = dict(status="RUNNING", execution_kind="injected-test", physical_measurement=False,
        frozen=bool(getattr(sys, "frozen", False)), platform=sys.platform,
        windows_host=platform.platform(), qt_platform=app.platformName(), executable=sys.executable,
        callback_errors=[], errors=[], checks={}, real_serial_open_calls=0, owners_closed=False)
    started = time.monotonic()
    factory = _Factory(ProfilesBackend)
    window = panel = None
    old_hook = sys.excepthook

    def callback_error(kind, value, tb):
        report["callback_errors"].append("".join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = callback_error

    def pump():
        app.processEvents()
        if report["callback_errors"]:
            raise AssertionError(report["callback_errors"][0])

    def wait(predicate, description, timeout=6):
        deadline = time.monotonic() + timeout
        while not predicate():
            pump()
            if time.monotonic() >= deadline:
                raise AssertionError(description)
            time.sleep(.004)
        pump()

    def screenshot(name, widget):
        pump()
        assert widget.grab().save(str(output / name))

    def modal_callback(action):
        def answer():
            try:
                action(app.activeModalWidget())
            except Exception:
                callback_error(*sys.exc_info())
                modal = app.activeModalWidget()
                if modal is not None:
                    modal.reject()
        QtCore.QTimer.singleShot(0, answer)

    class FixtureDialog(StreamDialog):
        def __init__(self, *args, **kwargs):
            kwargs["bridge_factory"] = lambda parent, **options: StreamDeviceBridge(
                parent, fake_backend_factory=factory, **options)
            super().__init__(*args, **kwargs)

    def assert_curve_projection():
        viewer = panel.viewer
        _, plotted = viewer.curve.getData()
        assert viewer.voltage_display and viewer.input_profile == panel.active_input_profile
        assert plotted is not None and len(plotted) == len(viewer._raw_plot_y) > 0
        matched = 0
        for code, value in zip(viewer._raw_plot_y, plotted):
            if math.isfinite(code):
                assert code % 4 == 0
                assert math.isclose(value, viewer.input_profile.voltage(code), rel_tol=1e-12, abs_tol=1e-12)
                matched += 1
        assert matched > 1
        codes = [code for code in viewer._raw_plot_y if math.isfinite(code)]
        if panel.capture.shot is not None and viewer._held_live is panel.capture.shot:
            raw_codes = [code for (code,) in struct.iter_unpack("<H", panel.capture.shot.raw_u16le)]
            assert min(codes) == min(raw_codes) and max(codes) == max(raw_codes)
        else:
            raw_codes = codes
        low, high = sorted((viewer.input_profile.voltage(min(raw_codes)),
                            viewer.input_profile.voltage(max(raw_codes))))
        for prefix, value in (("Min", low), ("Max", high), ("Размах", high - low)):
            expected = prefix + " " + viewer.value_text(value)
            assert expected in panel.measurement_label.text(), (expected, panel.measurement_label.text())
        return matched

    def assert_cursor_projection():
        viewer, tool = panel.viewer, panel.cursors
        wait(lambda: tool.values is not None, "Курсоры не прочитали исходные отсчёты")
        values = tool.values
        reader = tool._reader
        # Independent readback of the exact two original samples; the curve
        # may be decimated, but cursor voltage must never come from its bins.
        for index, code in ((values.a, values.code_a), (values.b, values.code_b)):
            block = next(iter(reader.iter_raw(index, index + 1, chunk_samples=1)))
            assert struct.unpack("<H", block.raw_u16le)[0] == code
            expected = viewer.value_text(viewer.input_profile.voltage(code))
            assert expected in tool.readout.text(), (expected, tool.readout.text())
        delta = viewer.value_text(viewer.input_profile.a * (values.code_b - values.code_a))
        assert delta in tool.readout.text(), (delta, tool.readout.text())
        return asdict(values)

    try:
        with patch("motortester.v2.device.available_ports", return_value=[("R5_SYNTHETIC", "Fixture")]), \
             patch("motortester.transport._serial_factory", side_effect=AssertionError("Real transport forbidden")), \
             patch("serial.serialwin32.Serial.open", side_effect=AssertionError("Real COM forbidden")) as real_open, \
             patch("motortester.v2.stream_ui.StreamDialog", FixtureDialog):
            stage("Create main window")
            window = MainWindow(settings_path=output / "settings.ini")
            window.show()
            window.timer.stop()
            stage("Open connection entry")

            def port_answer(dialog):
                assert isinstance(dialog, QtWidgets.QInputDialog)
                dialog.setTextValue("R5_SYNTHETIC")
                dialog.accept()

            modal_callback(port_answer)
            window.device_stream_button.click()
            stage("Connection page created")
            panel = window.stream_dialog
            assert panel is not None and not panel.isWindow() and window.left_stack.currentWidget() is panel
            assert not factory.backends
            ui_profile = panel.context.ui_profile
            panel.rate_combo.setCurrentIndex(panel.rate_combo.findData(150_000))
            panel.connect_button.click()
            wait(lambda: panel.bridge.state.ready and panel.bridge.connection is not None, "Нет согласованного соединения")
            stage("Connection ready")
            assert panel.active_input_profile == UNKNOWN_PROFILE and panel.active_analog_snapshot is None
            assert factory.backends[-1].commands == [1, 1, 2] and panel.bridge.state.validated_samples == 0
            report["checks"]["unknown_until_manual_selection"] = True
            selected_modes = []

            for mode_id in ("DC_WIDE", "AC_WIDE", "AC_SENSITIVE"):
                stage("Select " + mode_id)
                def choose(dialog, mode_id=mode_id):
                    assert isinstance(dialog, AnalogInputDialog)
                    dialog.mode.setCurrentIndex(dialog.mode.findData(mode_id))
                    assert not dialog.confirm.isChecked() and not dialog.apply_button.isEnabled()
                    dialog.instance.setText("СИНТЕТИЧЕСКИЙ GUI-опыт R5")
                    dialog.confirm.setChecked(True)
                    if mode_id == "AC_SENSITIVE":
                        screenshot("01-input-dialog.png", dialog)
                    dialog.apply_button.click()
                    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted, dialog.error.text()

                modal_callback(choose)
                panel.input_button.click()
                pump()
                profile, snapshot = panel.active_input_profile, panel.active_analog_snapshot
                assert snapshot.mode_id == mode_id and profile.state == "nominal"
                assert profile.measurement_point == "CH1_before_input_divider"
                assert panel.context.ui_profile == ui_profile
                assert "не калибровано" in panel.input_note.text()
                if mode_id.startswith("AC"):
                    assert "постоянная составляющая" in panel.input_note.text()
                selected_modes.append(dict(mode_id=mode_id, a=profile.a, b=profile.b))

            report["modes"] = selected_modes
            report["checks"]["all_three_modes_manual_no_start_ui_profile_unchanged"] = True
            profile, snapshot = panel.active_input_profile, panel.active_analog_snapshot
            editor = window.stream_search_controls
            editor.threshold.set_value(profile.voltage(2603), emit=True)
            editor.hysteresis.setValue(abs(profile.a) * 400)
            editor.apply_button.click()
            cfg = panel.search_config()
            assert cfg.threshold_code == 2604 and cfg.release_code == 2204
            assert cfg.threshold_code % 4 == cfg.release_code % 4 == 0
            assert profile.voltage(cfg.threshold_code) != profile.voltage(2603)
            assert "Применено" in editor.note.text()
            assert panel.bridge.state.validated_samples == 0 and factory.backends[-1].commands == [1, 1, 2]
            report["checks"]["threshold_quantized_once_to_4_codes"] = True
            report["accepted_search"] = asdict(cfg)

            panel.live_button.click()
            stage("Start live")
            wait(lambda: panel.bridge.state.phase == "preview" and panel.viewer.selection is not None
                 and panel.viewer.curve.getData()[1] is not None, "Нет живого графика")
            assert not panel.input_button.isEnabled() and not panel.apply_input_profile(UNKNOWN_PROFILE)
            assert not editor.fields.isEnabled()
            record_path = output / "analog.mtstream"
            assert panel.record_path(record_path)
            stage("Start recording")
            wait(lambda: panel.bridge.state.phase == "recording" and panel.bridge.state.validated_samples > 6000,
                 "Запись не началась")
            wait(panel.capture.arm_button.isEnabled, "Нет готовности одиночного захвата")
            panel.capture.arm_button.click()
            stage("Wait capture")
            wait(lambda: panel.capture.shot is not None and panel.capture.attempt is None, "Событие не захвачено")
            shot = panel.capture.shot
            assert shot.context.input_profile == profile and shot.context.analog_snapshot == snapshot
            wait(lambda: panel.viewer._held_live is shot and panel.viewer._display_origin == shot.first_sample_index
                 and panel.viewer.curve.getData()[1] is not None,
                 "Захват не показан")
            point_count = assert_curve_projection()
            panel.cursors.enabled.setChecked(True)
            cursor_v = assert_cursor_projection()
            assert "Размах" in panel.measurement_label.text() and " В" in panel.measurement_label.text()
            screenshot("02-live-volts.png", window)
            before_codes = (panel.cursors.values.code_a, panel.cursors.values.code_b)
            window.units_combo.setCurrentIndex(window.units_combo.findText("мВ"))
            wait(lambda: panel.voltage_unit == "мВ", "Единицы главного окна не переданы в поток")
            assert panel.viewer.connector_axis.factor == 1000
            assert_curve_projection()  # Plot coordinates remain physical volts; tick labels become mV.
            cursor_mv = assert_cursor_projection()
            assert before_codes == (panel.cursors.values.code_a, panel.cursors.values.code_b)
            assert "мВ" in panel.measurement_label.text()
            assert editor.threshold.suffix == "мВ"
            screenshot("03-live-millivolts.png", window)
            stage("Volts and millivolts checked")
            received = panel.bridge.state.validated_samples
            wait(lambda: panel.bridge.state.validated_samples > received + 2048, "Просмотр остановил запись")
            assert panel.bridge.state.phase == "recording"
            report["checks"].update(config_locked_during_reception=True, volts_curve_matches_raw=True,
                cursors_match_two_original_samples=True, millivolts_preserve_codes=True,
                metrics_share_scale=True, unit_change_keeps_recording=True)
            report["curve_points"] = point_count
            report["cursor_v"] = cursor_v
            report["cursor_mv"] = cursor_mv

            shot_path = output / "analog.mtshot"
            assert panel.capture.save_path(shot_path)
            wait(lambda: not panel.busy and not panel.capture.dirty, "Захват не сохранился")
            assert load_capture(shot_path) == shot
            panel.stop_button.click()
            stage("Stop recording")
            wait(lambda: panel.bridge.state.can_open and not panel.bridge.metadata_pending and record_path.exists(),
                 "Запись не завершилась")
            verified, archive = open_stream(record_path)
            if isinstance(archive, AttemptReport):
                assert archive.recording is not None
                archive = archive.recording
            assert verified.context.input_profile == profile and verified.context.analog_snapshot == snapshot
            assert archive.identity.retained_bits == 10
            saved = (record_path, companion_path(record_path), shot_path)
            hashes_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in saved}

            assert panel.open_path(shot_path)
            stage("Open shot")
            wait(lambda: not panel.busy and panel.archive is not None, "Захват не открылся")
            assert panel.active_input_profile == profile and panel.active_analog_snapshot == snapshot
            assert panel.archive == shot
            assert panel.open_path(record_path)
            stage("Open recording")
            wait(lambda: not panel.busy and panel.viewer._recording is not None, "Запись не открылась")
            assert panel.active_input_profile == profile and panel.active_analog_snapshot == snapshot
            wait(lambda: panel.viewer.curve.getData()[1] is not None, "Нет графика открытой записи")
            assert_curve_projection()
            screenshot("04-reopened-recording.png", window)
            old_bridge = panel.bridge
            panel.connect_button.click()
            stage("Reconnect")
            wait(lambda: panel.bridge is not old_bridge and panel.bridge.state.ready and panel.archive is None,
                 "Переподключение после записи не завершилось")
            assert panel.active_input_profile == UNKNOWN_PROFILE and panel.active_analog_snapshot is None
            assert panel.context.ui_profile == ui_profile and not panel.viewer.voltage_display
            assert panel.bridge.state.validated_samples == 0 and factory.backends[-1].commands == [1, 1, 2]
            assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes_before[p.name] for p in saved)
            screenshot("05-reconnect-unknown.png", window)
            assert real_open.call_count == 0
            report["files"] = hashes_before
            report["checks"].update(recording_and_capture_keep_profile_snapshot=True,
                reopened_files_use_saved_profile=True, reconnect_resets_unknown=True,
                reconnect_does_not_start=True, saved_files_unchanged=True, no_real_com=True)
            report["saved_samples"] = archive.end_sample_index - archive.first_sample_index

    except Exception:
        report["errors"].append(traceback.format_exc())
    finally:
        stage("Cleanup")
        try:
            if panel is not None:
                panel.capture.dirty = False  # Only this fixture's unsaved frame, never user data.
                panel.close_panel_button.click()
                deadline = time.monotonic() + 6
                while not panel.closed and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.004)
                assert panel.closed, "Потоковые ресурсы не закрылись"
                report["owners_closed"] = bool(panel.viewer._closed and panel.cursors._closed
                    and not panel._serial_reserved and all(not b.is_open for b in factory.backends))
            if window is not None:
                window.close()
                app.processEvents()
        except Exception:
            report["errors"].append("Cleanup: " + traceback.format_exc())
        sys.excepthook = old_hook
        report["elapsed_s"] = round(time.monotonic() - started, 3)
        report["status"] = ("PASS" if not report["errors"] and not report["callback_errors"]
                            and report["owners_closed"] else "FAIL")
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        faulthandler.cancel_dump_traceback_later()
        log.close()
    return report


def run(output):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["MotortesterV2-analog-smoke"])
    app.setStyle("Fusion")
    result = exercise(app, output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m motortester.v2.analog_smoke OUTPUT_FOLDER")
    raise SystemExit(run(sys.argv[1]))
