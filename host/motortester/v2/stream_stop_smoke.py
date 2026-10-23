"""Narrow native Qt witness for requested Stop with an unknown ADC tail.

Only injected wire bytes are used. Actual controller, writer, fresh reader and
dialog actions run normally; this does not exercise a physical COM port.
"""
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import struct
import sys
import time
import traceback
from unittest.mock import patch

from .serial_smoke import PORT, _Factory, _StreamBackend
from .stream_demo import PacedStreamPeer


STOP_TEXT = "Остановлено по команде · полнота хвоста неизвестна"


class _ObservedPeer(PacedStreamPeer):
    def __init__(self, *, suppress_ack=False):
        super().__init__(unknown_tail=True)
        self.suppress_ack = suppress_ack
        self.control_frames = []
        self.ack_attempts = 0

    def _enqueue(self, kind, payload, request=0):
        from ..stream_wire import Kind
        before = len(self._incoming)
        super()._enqueue(kind, payload, request)
        if kind in (Kind.END, Kind.STOP_ACK):
            assert len(self.control_frames) < 4
            # Preserve the actual encoded bytes admitted to the synthetic peer.
            self.control_frames.append(bytes(self._incoming[before:]))

    def _ack(self):
        self.ack_attempts += 1
        if not self.suppress_ack:
            super()._ack()


class _Backend(_StreamBackend):
    def __init__(self, owner, **settings):
        super().__init__(owner, **settings)
        self.peer = _ObservedPeer(suppress_ack=owner.suppress_ack)


def exercise(app, output, flush=None):
    """Return a receipt; all dialogs/owners are settled before returning."""
    import numpy as np
    from PySide6 import QtCore, QtGui, QtWidgets
    from ..stream_wire import Kind, decode_frame, decode_payload
    from .gui import MainWindow
    from .stream_device import SerialStreamSelection, StreamDeviceBridge
    from .stream_picker_smoke import _enter_path
    from .stream_ui import StreamDialog

    output = Path(output).resolve()
    assert output.is_dir()
    callbacks, emitted_errors, factories = [], [], []
    report = {"status": "RUNNING", "source": "injected synthetic wire 0.2",
              "physical_stream_verified": False, "real_serial_open_calls": 0,
              "qt_platform": app.platformName(), "callback_errors": callbacks}
    window = dialog = active_factory = None
    old_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: callbacks.append(
        "".join(traceback.format_exception(kind, value, tb)))

    def pump():
        app.processEvents()
        if flush is not None:
            flush()
        if callbacks:
            raise AssertionError(callbacks[0])

    def wait(predicate, description, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate():
            pump()
            if time.monotonic() >= deadline:
                state = None if dialog is None else dialog.bridge.state
                raise AssertionError(f"{description}: {state!r}")
            time.sleep(.005)
        pump()

    def image(name):
        pump()
        path = output / name
        assert dialog.grab().save(str(path))
        loaded = QtGui.QImage(str(path))
        assert not loaded.isNull()
        return {"path": name, "width": loaded.width(), "height": loaded.height(),
                "logical_width": dialog.width(), "logical_height": dialog.height()}

    class FixtureDialog(StreamDialog):
        def __init__(self, *args, **kwargs):
            factory = active_factory
            kwargs["bridge_factory"] = lambda parent, **options: StreamDeviceBridge(
                parent, fake_backend_factory=factory, **options)
            super().__init__(*args, **kwargs)
            self.setWindowTitle("Проверка штатной остановки · синтетический источник")

    def open_ready(*, suppress_ack=False):
        nonlocal active_factory, dialog
        active_factory = _Factory(_Backend)
        active_factory.suppress_ack = suppress_ack
        factories.append(active_factory)
        assert window._open_stream_workspace(SerialStreamSelection(PORT))
        dialog = window.stream_dialog
        dialog.bridge.error.connect(emitted_errors.append)
        assert not active_factory.backends
        dialog.connect_button.click()
        wait(lambda: dialog.bridge.state.ready, "HELLO/CAPS READY")
        backend = active_factory.backends[0]
        assert backend.commands == [int(Kind.HELLO), int(Kind.GET_CAPS)]
        assert dialog.bridge.state.validated_samples == 0
        assert dialog.bridge.state.bridge.session is None
        assert not dialog.error_label.text() and not emitted_errors
        assert window._serial_owner is dialog
        return backend

    def close_dialog():
        dialog.close()
        wait(lambda: dialog.closed, "dialog owner settlement")
        assert window._serial_owner is None

    def control_frames(peer):
        return [(decode_frame(raw, "device"), decode_payload(decode_frame(raw, "device")))
                for raw in peer.control_frames]

    try:
        with patch("motortester.transport._serial_factory",
                   side_effect=AssertionError("Real transport forbidden")), \
             patch("serial.serialwin32.Serial.open",
                   side_effect=AssertionError("Real COM forbidden")) as real_open, \
             patch("motortester.v2.stream_ui.StreamDialog", FixtureDialog):
            window = MainWindow(settings_path=output / "stop-settings.ini")
            window.show()
            assert window.timer.isActive()

            ready = open_ready()
            close_dialog()
            state = dialog.bridge.state
            assert not ready.is_open and ready.close_count == 1
            assert ready.commands == [int(Kind.HELLO), int(Kind.GET_CAPS)]
            assert state.error is None and state.bridge.endpoint_first_fault is None
            assert not emitted_errors and not dialog.error_label.text()
            assert dialog.saved_path is None and state.validated_samples == 0
            report["ready_close"] = {
                "commands": ready.commands, "phase": state.phase,
                "endpoint_first_fault": None, "emitted_errors": [],
                "handle_closed": True, "lease_released": True, "samples": 0}

            backend = open_ready()
            dialog.raw_view.click()
            dialog.live_button.click()
            wait(lambda: dialog.bridge.state.phase == "preview" and
                 dialog.bridge.state.validated_samples >= 5000, "preview")
            path = output / "stop-unknown-tail.mtstream"
            dialog.record_button.click()
            wait(lambda: dialog._record_picker is not None, "Record pathname")
            picker = dialog._record_picker
            _enter_path(picker, path, pump)
            box = picker.findChild(QtWidgets.QDialogButtonBox, "buttonBox")
            save = box.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
            assert save is not None and save.isEnabled()
            save.click()
            wait(lambda: dialog.bridge.state.phase == "recording", "recording")
            first_count = dialog.bridge.state.validated_samples
            wait(lambda: dialog.bridge.state.validated_samples >= first_count + 5000,
                 "new recorded raw")
            assert window.timer.isActive()
            dialog.stop_button.click()
            wait(lambda: dialog.bridge.state.phase == "stopped unknown tail" and
                 dialog.saved_path is not None and not dialog.bridge.metadata_pending,
                 "confirmed Stop and settled file")
            status = dialog.bridge.state
            assert status.bridge.session.first_failure is None
            assert status.bridge.endpoint_first_fault is None and status.error is None
            assert not emitted_errors and not dialog.error_label.text()
            assert STOP_TEXT in dialog.state_label.text()
            assert "НЕПОЛНЫЕ ДАННЫЕ" not in dialog.state_label.text()
            controls = control_frames(backend.peer)
            assert [frame.kind for frame, _ in controls] == [Kind.END, Kind.STOP_ACK]
            end_frame, end = controls[0]
            ack_frame, ack = controls[1]
            assert end.reason == 0 and end.flags == ack.flags == 3
            assert end.stop_request_id == ack_frame.request_id != 0
            assert end_frame.sequence == ack.terminal_sequence
            assert end.prefix_end == ack.prefix_end
            live_text = dialog.state_label.text()
            before_hash = hashlib.sha256(path.read_bytes()).hexdigest()

            with patch.object(QtWidgets.QFileDialog, "getOpenFileName",
                              return_value=(str(path), "Потоковая запись (*.mtstream)")):
                dialog.open_button.click()
            wait(lambda: not dialog.busy and dialog.archive is not None and
                 not dialog.viewer.busy, "fresh Open")
            archive = dialog.archive
            terminal = archive.terminal
            assert terminal.reason == "stopped" and terminal.failure is None
            assert terminal.device_generated_end_sample_index is None
            assert terminal.loss_samples is None and not archive.clean_stop_reported
            assert archive.identity.origin == "synthetic"
            assert STOP_TEXT in dialog.quality.text()
            assert "НЕПОЛНЫЕ ДАННЫЕ" not in dialog.quality.text()
            assert not dialog.error_label.text() and not emitted_errors
            period = np.frombuffer(backend.peer._period_raw, dtype="<u2")
            samples, digest = 0, hashlib.sha256()
            for block in archive.iter_raw():
                codes = np.frombuffer(block.raw_u16le, dtype="<u2")
                indices = np.arange(block.first_sample_index, block.end_sample_index)
                assert np.array_equal(codes, period[indices % len(period)])
                samples += len(codes)
                digest.update(block.raw_u16le)
                pump()
            assert samples == archive.end_sample_index - archive.first_sample_index > 0
            assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash
            dialog.details.setChecked(True)
            dialog.resize(1220, 870)
            expanded = image("stop-open-details.png")
            dialog.resize(850, 650)
            compact = image("stop-open-compact.png")
            scroll = dialog.viewer.scroll_area
            bar = scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            pump()
            compact_bottom = image("stop-open-compact-bottom.png")
            content, viewport = dialog.viewer.content, scroll.viewport()
            plot_rect = QtCore.QRect(
                dialog.viewer.plot.mapTo(content, QtCore.QPoint()), dialog.viewer.plot.size())
            detail_geometry = {}
            for name in ("source_label", "range_label", "storage_label",
                         "index_label", "event_label", "status_label"):
                label = getattr(dialog.viewer, name)
                rect = QtCore.QRect(label.mapTo(content, QtCore.QPoint()), label.size())
                view_rect = QtCore.QRect(label.mapTo(viewport, QtCore.QPoint()), label.size())
                assert label.isVisible() and content.rect().contains(rect)
                assert not plot_rect.intersects(rect), f"Plot overlaps {name}"
                # Content can be reached by scrolling; clipping in this one
                # screenshot is recorded separately from widget visibility.
                assert rect.top() < viewport.height() + bar.maximum()
                detail_geometry[name] = {
                    "content_rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                    "viewport_rect": [
                        view_rect.x(), view_rect.y(), view_rect.width(), view_rect.height()],
                    "intersects_viewport": viewport.rect().intersects(view_rect),
                    "contained_in_viewport": viewport.rect().contains(view_rect),
                    "plot_intersection": False}
            assert bar.value() == bar.maximum()
            assert detail_geometry["status_label"]["intersects_viewport"]
            bottom_geometry = {
                "scope": "Widget rectangles only; visual/glyph assessment requires PNG review.",
                "scroll_value": bar.value(), "scroll_maximum": bar.maximum(),
                "viewport_size": [viewport.width(), viewport.height()],
                "content_size": [content.width(), content.height()],
                "plot_content_rect": [
                    plot_rect.x(), plot_rect.y(), plot_rect.width(), plot_rect.height()],
                "details": detail_geometry}
            csv_path = output / "stop-unknown-tail.csv"
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName",
                              return_value=(str(csv_path), "CSV (*.csv)")):
                dialog.export_button.click()
            wait(lambda: not dialog.busy, "CSV export")
            assert not dialog.error_label.text(), dialog.error_label.text()
            exported = json.loads(csv_path.with_name(csv_path.name + ".json").read_text(
                encoding="utf-8"))
            assert exported["complete"] is True  # Export file, not ADC completeness.
            assert exported["terminal"] == asdict(terminal)
            assert exported["identity"]["origin"] == "synthetic"
            assert exported["context"]["input_profile"]["state"] == "unconfigured"
            assert exported["source_journal_sha256"] == before_hash
            csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
            assert exported["csv_sha256"] == csv_sha
            csv_count, csv_raw = 0, hashlib.sha256()
            with csv_path.open(encoding="utf-8", newline="") as source:
                rows = csv.DictReader(source)
                assert rows.fieldnames == [
                    "sample_index", "time_from_recording_start_s", "adc_code"]
                for block in archive.iter_raw():
                    for offset, (code,) in enumerate(struct.iter_unpack("<H", block.raw_u16le)):
                        row = next(rows, None)
                        assert row is not None and int(row["adc_code"]) == code
                        assert int(row["sample_index"]) == block.first_sample_index + offset
                        if csv_count == 0:
                            assert float(row["time_from_recording_start_s"]) == 0
                        csv_raw.update(struct.pack("<H", int(row["adc_code"])))
                        csv_count += 1
                    pump()
                assert next(rows, None) is None
            assert csv_count == samples and csv_raw.hexdigest() == digest.hexdigest()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash
            report["normal_stop"] = {
                "phase": status.phase, "live_text": live_text,
                "fresh_open_quality": dialog.quality.text(),
                "end": asdict(end), "ack": asdict(ack),
                "end_sequence": end_frame.sequence, "ack_request_id": ack_frame.request_id,
                "terminal": asdict(terminal), "clean_stop_reported": False,
                "range": [archive.first_sample_index, archive.end_sample_index],
                "raw_samples_compared": samples, "raw_sha256": digest.hexdigest(),
                "journal_sha256_unchanged": before_hash,
                "emitted_errors": [], "main_timer_active": window.timer.isActive(),
                "csv": {"rows": csv_count, "csv_sha256": csv_sha,
                        "raw_sha256": csv_raw.hexdigest(), "export_complete": True,
                        "terminal_equal": True, "clean_stop_reported": False,
                        "produced_end": None, "loss_samples": None,
                        "origin": "synthetic", "input_profile_state": "unconfigured"},
                "screenshots": [expanded, compact, compact_bottom],
                "compact_bottom_geometry": bottom_geometry}
            close_dialog()
            assert not emitted_errors

            # Same valid reason/flags, but ACK is intentionally withheld.
            # The real endpoint deadline must keep this a fault, not a normal Stop.
            negative = open_ready(suppress_ack=True)
            dialog.live_button.click()
            wait(lambda: dialog.bridge.state.phase == "preview" and
                 dialog.bridge.state.validated_samples >= 5000, "negative preview")
            dialog.stop_button.click()

            def unconfirmed_fault():
                state = dialog.bridge.state
                assert state.phase != "stopped unknown tail"
                assert STOP_TEXT not in dialog.state_label.text()
                if state.phase != "fault":
                    return False
                assert state.bridge.endpoint_first_fault is not None
                assert state.bridge.endpoint_first_fault.code == "stop_timeout"
                # The receiver publishes the fault independently of the Qt
                # bridge's 20 ms poll. Wait for the same fault to reach both
                # visible UI and error signal, within the existing deadline.
                return bool(dialog.error_label.text() and emitted_errors)

            wait(unconfirmed_fault, "missing ACK fault", timeout=12)
            state = dialog.bridge.state
            controls = control_frames(negative.peer)
            assert [frame.kind for frame, _ in controls] == [Kind.END]
            assert controls[0][1].reason == 0 and controls[0][1].flags == 3
            assert negative.peer.ack_attempts >= 1
            assert state.bridge.endpoint_first_fault is not None
            assert state.bridge.endpoint_first_fault.code == "stop_timeout"
            assert STOP_TEXT not in dialog.state_label.text()
            assert dialog.error_label.text() and emitted_errors
            report["unconfirmed_stop"] = {
                "phase": state.phase,
                "fault": asdict(state.bridge.endpoint_first_fault),
                "end": asdict(controls[0][1]), "ack_frames": 0,
                "ack_attempts_suppressed": negative.peer.ack_attempts,
                "error_text": dialog.error_label.text(),
                "normal_stop_label_absent": True}
            close_dialog()
            window.close()
            wait(lambda: not window.isVisible() and not window.device.bridge.running,
                 "main window settlement")
            assert real_open.call_count == 0
            report["status"] = "PASS"
    except BaseException:
        report["status"] = "FAIL"
        report["error"] = traceback.format_exc()
        raise
    finally:
        for factory in factories:
            factory.open_gate.set()
        try:
            if dialog is not None and not dialog.closed:
                if dialog._record_picker is not None:
                    dialog._record_picker.reject()
                if dialog.bridge.metadata_error is not None:
                    report["cleanup_companion_failure"] = str(dialog.bridge.metadata_error)
                    dialog.bridge.abandon_context(dialog.bridge.metadata_error)
                dialog.close()
                dialog.bridge.retry_close()
            if window is not None:
                window.close()
            # A previously captured Qt exception must not prevent cleanup from
            # processing the owner-settlement callbacks.
            deadline = time.monotonic() + 10
            while ((dialog is not None and not dialog.closed) or
                   (window is not None and window.device.bridge.running)):
                app.processEvents()
                if time.monotonic() >= deadline:
                    raise RuntimeError("Synthetic Stop smoke cleanup did not settle")
                time.sleep(.005)
        except BaseException:
            report["status"] = "FAIL"
            report["cleanup_error"] = traceback.format_exc()
        if callbacks:
            report["status"] = "FAIL"
        report["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in output.glob("stop-*")
                           if p.is_file() and p.name != "stop-result.json"}
        (output / "stop-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.excepthook = old_hook
    if report["status"] != "PASS":
        raise AssertionError(report.get("cleanup_error", "Stop GUI callback failure"))
    return report


def run(output_name):
    from PySide6 import QtWidgets
    output = Path(output_name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication([])
    app.setStyle("Fusion")
    report = {"status": "FAIL", "windows": platform.platform(), "python": sys.version,
              "frozen": bool(getattr(sys, "frozen", False)), "qt_platform": app.platformName()}
    try:
        assert sys.platform == "win32" and app.platformName() == "windows"
        report.update(exercise(app, output))
    except BaseException:
        report["status"] = "FAIL"
        report["error"] = traceback.format_exc()
    (output / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
