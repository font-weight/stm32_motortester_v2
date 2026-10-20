"""Short native GUI witness for the streaming integration; no COM allowed."""
import csv
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import traceback
from unittest.mock import patch


def exercise(app, window, output, flush):
    from PySide6 import QtCore, QtGui
    import numpy as np
    from .stream_device import StreamContext, StreamDeviceBridge
    from .stream_demo import PacedStreamPeer
    from .stream_files import open_stream
    from .stream_ui import StreamDialog
    from ..stream_recording import AttemptReport

    def wait(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate():
            flush()
            if time.monotonic() > deadline:
                state = dialog.bridge.state
                raise AssertionError(f"Stream GUI wait timed out: {state.phase}; revision={state.revision}; "
                    f"display={state.displays_built if hasattr(state, 'displays_built') else state.display_built}; "
                    f"error={state.error}/{state.display_error}; "
                    f"viewer={dialog.viewer.status_label.text()}; selection={dialog.viewer.selection}")
            time.sleep(.005)
        flush()

    def image(name, dialog):
        flush()
        assert dialog.grab().save(str(output / name))
        assert not QtGui.QImage(str(output / name)).isNull()

    window.change_profile("oscilloscope")
    window.open_stream_workspace()
    dialog = window.stream_dialog
    try:
        assert not dialog.raw_view.isChecked() and not dialog.viewer.plot.isVisible()
        dialog.raw_view.setChecked(True)
        assert dialog.start_live()
        wait(lambda: dialog.bridge.state.validated_samples >= 12000)
        path = output / "stream-scope.mtstream"
        assert dialog.record_path(path)
        wait(lambda: dialog.bridge.state.phase == "recording")
        wait(lambda: dialog.viewer.curve.getData()[0] is not None)
        dialog.toggle_pause()
        before = dialog.viewer.curve.getData()[1].copy()
        count = dialog.bridge.state.validated_samples
        wait(lambda: dialog.bridge.state.validated_samples >= count + 10000)
        assert np.array_equal(before, dialog.viewer.curve.getData()[1])
        assert dialog.bridge.state.phase == "recording"
        dialog.toggle_pause()
        wait(lambda: dialog.bridge.state.validated_samples >= count + 15000)
        image("stream-scope.png", dialog)
        dialog.stop()
        wait(lambda: dialog.saved_path is not None)
        assert not dialog.error_label.text(), dialog.error_label.text()
        assert dialog.open_path(path)
        wait(lambda: not dialog.busy and dialog.archive is not None and not dialog.viewer.busy)
        archive = dialog.archive
        assert archive.first_sample_index > 0
        assert archive.terminal.clean_stop_reported
        assert dialog.verified_context.context.ui_profile == "oscilloscope"
        assert dialog.verified_context.context.input_profile.state == "unconfigured"
        csv_path = output / "stream-export.csv"
        assert dialog.export_path(csv_path)
        wait(lambda: not dialog.busy)
        assert not dialog.error_label.text(), dialog.error_label.text()
        receipt = json.loads((output / "stream-export.csv.json").read_text(encoding="utf-8"))
        assert receipt["complete"] is True
        assert receipt["csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
        with csv_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        expected = [code for block in archive.iter_raw()
                    for code in np.frombuffer(block.raw_u16le, dtype="<u2")]
        assert [int(row["adc_code"]) for row in rows] == expected
        assert int(rows[0]["sample_index"]) == archive.first_sample_index
        assert float(rows[0]["time_from_recording_start_s"]) == 0
        # A new source must clear a previously opened file before any DATA.
        assert dialog.start_live()
        assert dialog.viewer.curve.getData()[0] is None
        dialog.stop()
        wait(lambda: dialog.bridge.state.can_open)
        app.sendEvent(dialog, QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress,
                      QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier))
        wait(lambda: dialog.closed)

        window.change_profile("ignition")
        window.open_stream_workspace()
        dialog = window.stream_dialog
        dialog.raw_view.setChecked(True)
        ignition_path = output / "stream-ignition.mtstream"
        assert dialog.record_path(ignition_path)
        wait(lambda: dialog.bridge.state.validated_samples >= 10000)
        image("stream-ignition.png", dialog)
        # Closing the parent drains the child writer and persists its context.
        window.single_dirty = window.record_dirty = False
        window.close()
        wait(lambda: dialog.closed and not window.isVisible())
        context, attempt = open_stream(ignition_path)
        recorded = attempt.recording if isinstance(attempt, AttemptReport) else attempt
        assert recorded.first_sample_index == 0 and recorded.terminal.clean_stop_reported
        assert context.context.ui_profile == "ignition"

        # Diagnostic STR1-like unknown END must not become complete/zero-loss.
        dialog = StreamDialog(context=StreamContext(),
            bridge_factory=lambda parent, **kw: StreamDeviceBridge(
                parent, peer=PacedStreamPeer(unknown_tail=True), **kw))
        dialog.show()
        dialog.raw_view.setChecked(True)
        partial_path = output / "stream-unknown-tail.mtstream"
        assert dialog.record_path(partial_path)
        wait(lambda: dialog.bridge.state.validated_samples >= 5000)
        dialog.stop()
        wait(lambda: dialog.saved_path is not None)
        assert "НЕПОЛНЫЕ ДАННЫЕ" in dialog.state_label.text()
        assert dialog.open_path(partial_path)
        wait(lambda: not dialog.busy and dialog.archive is not None and not dialog.viewer.busy)
        assert dialog.archive.terminal.loss_samples is None
        assert not dialog.archive.terminal.clean_stop_reported
        image("stream-unknown-tail.png", dialog)
        # Open a healthy recording after the fault: no old counter/failure.
        assert dialog.open_path(path)
        wait(lambda: not dialog.busy and dialog.archive is not None)
        assert "НЕПОЛНЫЕ ДАННЫЕ" not in dialog.state_label.text()
        assert dialog.archive.terminal.clean_stop_reported
        dialog.close()
        wait(lambda: dialog.closed)
        return {"status": "PASS", "source": "paced synthetic wire 0.2",
                "record_start": archive.first_sample_index, "exported_samples": len(rows),
                "pause_independent": True, "raw_roundtrip": True,
                "unknown_tail_preserved": True, "parent_close_drained": True,
                "physical_stream_verified": False}
    finally:
        if not dialog.closed:
            dialog.close()
            wait(lambda: dialog.closed)


def run(output_name):
    from PySide6 import QtWidgets
    from .gui import MainWindow
    output = Path(output_name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication([])
    app.setStyle("Fusion")
    errors = []
    original = sys.excepthook
    sys.excepthook = lambda kind, value, tb: errors.append("".join(traceback.format_exception(kind, value, tb)))
    report = {"status": "FAIL", "platform": platform.platform(), "qt_platform": app.platformName()}
    window = MainWindow(settings_path=output / "settings.ini")
    window.show()
    window.timer.stop()

    def flush():
        app.processEvents()
        if errors:
            raise AssertionError(errors[0])

    try:
        with patch("serial.serialwin32.Serial.open", side_effect=AssertionError("COM forbidden")) as serial_open:
            report.update(exercise(app, window, output, flush))
            assert serial_open.call_count == 0
            report["serial_open_calls"] = serial_open.call_count
    except BaseException:
        report["status"] = "FAIL"
        report["error"] = traceback.format_exc()
    finally:
        sys.excepthook = original
        report["callback_errors"] = errors
        report["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in output.iterdir() if p.is_file()}
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
