"""Native Qt witness for serial admission, using only injected byte peers.

The standalone entry point creates QApplication; exercise() reuses the package
verifier's application. No test-tree imports, real COM access, or firmware are
needed. The normal main-window DEMO timer remains active during stream capture.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
import threading
import time
import traceback
from unittest.mock import patch


PORT = "V2_SYNTHETIC_SERIAL"
RECORD_SECONDS = 2.0


class _StreamBackend:
    """Closed pyserial-shaped fixture; paced bytes follow the real wire path."""
    def __init__(self, owner, **settings):
        from .stream_demo import PacedStreamPeer
        self.owner, self.settings = owner, settings
        self.peer = PacedStreamPeer(unknown_tail=True)
        self.port, self.is_open, self._dtr = None, False, False
        self.fail_close = False
        self.commands, self._sent = [], bytearray()
        self.open_entered = threading.Event()
        self.close_count = 0

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self.owner.calls.append(("dtr", self.is_open, value))
        self._dtr = value

    def open(self):
        self.open_entered.set()
        if not self.owner.open_gate.wait(5):
            raise TimeoutError("Synthetic open barrier was not released")
        self.owner.calls.append(("open", self.port, self._dtr))
        self.is_open = True

    def read(self, maximum):
        return self.peer.read(maximum)

    def write(self, data):
        from ..stream_wire import decode_frame
        self._sent.extend(data)
        assert len(self._sent) <= 1088
        while 0 in self._sent:
            stop = self._sent.index(0) + 1
            frame = bytes(self._sent[:stop])
            del self._sent[:stop]
            if frame != b"\0":
                assert len(self.commands) < 16
                self.commands.append(int(decode_frame(frame, "host").kind))
        return self.peer.write(data)

    def close(self):
        self.close_count += 1
        if self.fail_close:
            raise OSError("Synthetic close failure: owner must be retained")
        self.is_open = False


class _WindowBackend:
    """Existing wire 0.1 emulator, used only for HELLO/CAPS and lease conflicts."""
    def __init__(self, owner, **settings):
        from ..device_emulator import DeviceEmulator
        from ..wire import StreamDecoder
        self.owner = owner
        self.peer = DeviceEmulator(all_analog_modes=True, pretrigger=True)
        self.decoder = StreamDecoder()
        self.commands = []
        self.port, self.is_open = None, False
        self.open_entered = threading.Event()

    @staticmethod
    def now():
        return time.monotonic_ns() // 1_000_000

    def open(self):
        self.open_entered.set()
        if not self.owner.open_gate.wait(5):
            raise TimeoutError("Synthetic window open barrier was not released")
        self.is_open = True

    def write(self, data):
        self.commands.extend(frame.message_type for frame in
                             self.decoder.feed(data, self.now()).frames)
        assert len(self.commands) <= 16
        return self.peer.write(data, self.now()).accepted_prefix

    def read(self, maximum):
        return self.peer.read(maximum, self.now())

    def close(self):
        self.is_open = False
        self.peer.disconnect(self.now())


class _Factory:
    def __init__(self, backend_type):
        self.backend_type = backend_type
        self.backends, self.calls = [], []
        self.open_gate = threading.Event()
        self.open_gate.set()

    def __call__(self, **settings):
        self.calls.append(("factory", settings["port"], False))
        backend = self.backend_type(self, **settings)
        self.backends.append(backend)
        return backend


def exercise(app, output, flush=None):
    """Run real Qt buttons with closed injected serial backends; return receipt."""
    import numpy as np
    from PySide6 import QtCore, QtGui, QtWidgets
    from ..session import Phase
    from ..transport import SerialTransport
    from .device import DeviceBridge
    from .gui import MainWindow
    from .stream_device import StreamDeviceBridge
    from .stream_ui import StreamDialog
    from .stream_picker_smoke import _enter_path

    output = Path(output).resolve()
    assert output.is_dir()
    stream_factory, window_factory = _Factory(_StreamBackend), _Factory(_WindowBackend)
    callbacks, checkpoints = [], []
    report = {"status": "RUNNING", "source": "injected serial byte fixtures",
              "physical_stream_verified": False, "real_serial_open_calls": 0,
              "qt_platform": app.platformName(), "callback_errors": callbacks,
              "checkpoints": checkpoints}
    window = dialog = None
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: callbacks.append(
        "".join(traceback.format_exception(kind, value, tb)))

    def pump():
        app.processEvents()
        if flush is not None:
            flush()
        if callbacks:
            raise AssertionError(callbacks[0])

    def wait(predicate, description, timeout=8):
        deadline = time.monotonic() + timeout
        while not predicate():
            pump()
            if time.monotonic() >= deadline:
                state = None if dialog is None else dialog.bridge.state
                raise AssertionError(
                    f"{description}: timed out; phase={None if state is None else state.phase}; "
                    f"path={None if state is None else state.path!r}; "
                    f"saved_path={None if dialog is None else dialog.saved_path!r}; "
                    f"metadata_pending={None if dialog is None else dialog.bridge.metadata_pending}; "
                    f"error={None if dialog is None else dialog.error_label.text()!r}")
            time.sleep(.005)
        pump()

    def receipt(step):
        checkpoints.append(step)
        (output / "serial-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def image(name, widget):
        pump()
        path = output / name
        assert widget.grab().save(str(path))
        assert not QtGui.QImage(str(path)).isNull()

    def unexpected_message(*args, **kwargs):
        raise AssertionError("Unexpected modal message: " + str(args[1:3]))

    def make_window_bridge(parent):
        return DeviceBridge(parent, serial_factory=lambda: SerialTransport(
            backend_factory=window_factory), interval_ms=2)

    class FixtureStreamDialog(StreamDialog):
        def __init__(self, *args, **kwargs):
            kwargs["bridge_factory"] = lambda parent, **options: StreamDeviceBridge(
                parent, fake_backend_factory=stream_factory, **options)
            super().__init__(*args, **kwargs)
            self.setWindowTitle("Автоматическая проверка · синтетический COM · окно закроется само")

    try:
        with patch("motortester.transport._serial_factory",
                   side_effect=AssertionError("Real transport forbidden")), \
             patch("serial.serialwin32.Serial.open",
                   side_effect=AssertionError("Real COM forbidden")) as real_open, \
             patch("motortester.v2.device.available_ports", return_value=((PORT, "Synthetic"),)), \
             patch("motortester.v2.device_ui.available_ports", return_value=((PORT, "Synthetic"),)), \
             patch("motortester.v2.stream_ui.StreamDialog", FixtureStreamDialog), \
             patch.object(QtWidgets.QMessageBox, "critical", side_effect=unexpected_message), \
             patch.object(QtWidgets.QMessageBox, "warning", side_effect=unexpected_message), \
             patch.object(QtWidgets.QMessageBox, "question", side_effect=unexpected_message):
            window = MainWindow(settings_path=output / "serial-settings.ini",
                                device_bridge_factory=make_window_bridge)
            window.show()
            assert window.timer.isActive()
            assert not stream_factory.backends and not window_factory.backends

            # Drive the real port chooser inside its nested Qt loop. Any
            # callback failure rejects the chooser immediately instead of hanging.
            def select_port():
                picker = window.findChild(QtWidgets.QInputDialog)
                try:
                    assert picker is not None and picker.isVisible()
                    assert picker.textValue() == ""
                    picker.setTextValue(PORT)
                    assert picker.textValue() == PORT
                    picker.accept()
                except BaseException:
                    callbacks.append(traceback.format_exc())
                    if picker is not None:
                        picker.reject()
            QtCore.QTimer.singleShot(50, select_port)
            window.device_stream_button.click()
            pump()
            dialog = window.stream_dialog
            assert dialog is not None and dialog.selection.port == PORT
            assert not stream_factory.backends, "Opening the panel must not open COM"
            assert not dialog.live_button.isEnabled() and not dialog.record_button.isEnabled()
            assert dialog.viewer.curve.getData()[0] is None

            # Window Connect owns COM before its asynchronous open finishes.
            window.device_info()
            panel = window.device_panel
            panel.port.setCurrentText(PORT)
            window_factory.open_gate.clear()
            panel.connect_button.click()
            wait(lambda: bool(window_factory.backends) and
                 window_factory.backends[0].open_entered.is_set(), "window open queued")
            assert window._serial_owner is window.device
            dialog.connect_button.click()
            assert not stream_factory.backends
            assert "занят" in dialog.error_label.text()
            assert window._serial_owner is window.device
            receipt("window pending Connect blocks stream before serial construction")
            window_factory.open_gate.set()
            wait(lambda: window.device.snapshot is not None and
                 window.device.snapshot.phase is Phase.READY, "window HELLO/CAPS")
            assert window_factory.backends[0].commands == [1, 2]
            panel.disconnect_button.click()
            wait(lambda: not window.device.state.connected and not window.device.state.busy
                 and window._serial_owner is None, "window disconnect releases lease")
            window.waveform_combo.setCurrentIndex(0)
            assert window.timer.isActive()

            # Stream Connect similarly owns COM before its OS-shaped open.
            stream_factory.open_gate.clear()
            dialog.connect_button.click()
            assert window._serial_owner is dialog
            wait(lambda: bool(stream_factory.backends) and
                 stream_factory.backends[0].open_entered.is_set(), "stream open queued")
            assert not panel.connect_button.isEnabled()
            panel.connect_button.click()
            panel.connect_device()  # A previously queued handler must also refuse.
            assert len(window_factory.backends) == 1 and not window.device.state.busy
            assert window.timer.isActive()
            assert window._serial_owner is dialog
            receipt("stream pending Connect blocks window button and stale handler")
            stream_factory.open_gate.set()
            wait(lambda: dialog.bridge.state.ready and dialog.bridge.connection is not None,
                 "stream HELLO/CAPS ready")
            backend = stream_factory.backends[0]
            assert backend.commands == [1, 2], "Connect must never transmit START"
            assert dialog.bridge.state.validated_samples == 0
            assert dialog.bridge.state.bridge.session is None
            assert dialog.viewer.curve.getData()[0] is None, "Ready must not display an old waveform"
            assert not dialog.record_button.isEnabled()
            assert stream_factory.calls[:3] == [
                ("factory", None, False), ("dtr", False, True), ("open", PORT, True)]
            panel.hide()
            dialog.details.click()
            image("serial-ready.png", dialog)
            report["prepared"] = {"commands": list(backend.commands), "samples": 0,
                                  "connection": asdict(dialog.bridge.connection)}
            receipt("DTR before open; HELLO/CAPS ready without START or waveform")

            dialog.raw_view.click()
            dialog.live_button.click()
            wait(lambda: dialog.bridge.state.phase == "preview" and
                 dialog.bridge.state.validated_samples >= 12000 and
                 dialog.viewer.curve.getData()[0] is not None, "preview waveform")
            assert backend.commands == [1, 2, 8]
            assert dialog.bridge.state.bridge.identity.origin == "synthetic"
            assert "synthetic" in dialog.viewer.source_label.text()
            assert window.timer.isActive()
            path = output / "serial-window.mtstream"
            dialog.record_button.click()
            wait(lambda: dialog._record_picker is not None, "record picker")
            picker = dialog._record_picker
            assert picker.testOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog)
            picker.setWindowTitle("Автоматическая проверка · сохранение синтетического потока")
            _enter_path(picker, path, pump)
            buttons = picker.findChild(QtWidgets.QDialogButtonBox, "buttonBox")
            save_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
            assert save_button is not None and save_button.isEnabled()
            save_button.click()
            wait(lambda: dialog.bridge.state.phase == "recording", "recording")
            before = dialog.bridge.state
            sequence_before = dialog.viewer._latest_live_sequence
            started = time.monotonic()
            last_count = before.validated_samples
            while time.monotonic() - started < RECORD_SECONDS:
                pump()
                state = dialog.bridge.state
                assert state.phase == "recording" and state.revision == before.revision
                assert state.validated_samples >= last_count
                assert window.timer.isActive()
                last_count = state.validated_samples
                time.sleep(.005)
            assert last_count > before.validated_samples
            assert dialog.viewer._latest_live_sequence > sequence_before
            image("serial-recording.png", dialog)
            report["recording"] = {"seconds": time.monotonic() - started,
                                   "samples_before": before.validated_samples,
                                   "samples_after": last_count,
                                   "revision": before.revision,
                                   "main_timer_active": window.timer.isActive()}
            dialog.stop_button.click()
            # Qt returns '/' on Windows, while str(Path) uses '\'. The chosen
            # file must match as a path; separator spelling is not a save error.
            wait(lambda: dialog.saved_path is not None and
                 Path(dialog.saved_path) == path and not dialog.bridge.metadata_pending,
                 "Stop and companion settlement")
            report["settlement"] = {"selected_path": str(path),
                                     "saved_path": dialog.saved_path,
                                     "normalized_path_matches": True,
                                     "metadata_pending": dialog.bridge.metadata_pending}
            assert dialog.open_button.isEnabled()
            # Only the chosen Open pathname is injected; the real button,
            # background fresh reader and viewer adoption run normally.
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName",
                              return_value=(str(path), "Потоковая запись (*.mtstream)")):
                dialog.open_button.click()
            wait(lambda: not dialog.busy and dialog.archive is not None and not dialog.viewer.busy,
                 "fresh open")
            archive = dialog.archive
            assert archive.first_sample_index > 0
            assert not archive.clean_stop_reported
            assert archive.terminal.device_generated_end_sample_index is None
            assert archive.terminal.loss_samples is None
            assert archive.identity.origin == "synthetic"
            assert dialog.verified_context.context.input_profile.state == "unconfigured"
            assert dialog.verified_context.connection == dialog.bridge.connection
            assert archive.terminal.reason == "stopped" and archive.terminal.failure is None
            assert "Остановлено по команде · полнота хвоста неизвестна" in dialog.quality.text()
            period = np.frombuffer(backend.peer._period_raw, dtype="<u2")
            compared = 0
            for block in archive.iter_raw():
                codes = np.frombuffer(block.raw_u16le, dtype="<u2")
                indices = np.arange(block.first_sample_index, block.end_sample_index)
                assert np.array_equal(codes, period[indices % len(period)])
                compared += len(codes)
                pump()
            assert compared == archive.end_sample_index - archive.first_sample_index
            image("serial-open-unknown-tail.png", dialog)
            report["roundtrip"] = {"first_sample_index": archive.first_sample_index,
                                    "end_sample_index": archive.end_sample_index,
                                    "raw_samples_compared": compared,
                                    "unknown_tail_preserved": True,
                                    "origin": archive.identity.origin,
                                    "open_path_choice_injected": True}
            receipt("actual Record/Stop/Open buttons; raw and unknown connection roundtrip")

            # Parent close must retain both the dialog and shared lease when the
            # driver-shaped close fails; retry is an actual enabled GUI button.
            backend.fail_close = True
            window.close()
            wait(lambda: dialog.bridge.state.can_retry_close, "retained failed close")
            assert not dialog.closed and window.isVisible()
            assert window._serial_owner is dialog
            assert not panel.connect_button.isEnabled()
            assert dialog.disconnect_button.isEnabled(), "Close failure must leave retry available"
            assert "Повторить" in dialog.disconnect_button.text()
            assert backend.is_open
            image("serial-close-retry.png", dialog)
            attempts = backend.close_count
            pump()
            assert backend.close_count == attempts, "Close must not retry in a background loop"
            backend.fail_close = False
            dialog.disconnect_button.click()
            wait(lambda: dialog.closed and not window.isVisible(), "parent close after explicit retry")
            assert window._serial_owner is None
            assert not backend.is_open and not window.device.bridge.running
            assert backend.close_count == attempts + 1
            assert real_open.call_count == 0
            report["close"] = {"failed_close_retained_lease": True,
                               "explicit_retry_button": True, "parent_closed": True,
                               "close_attempts": backend.close_count}
            receipt("parent close retains ownership; explicit retry settles owners and releases lease")
            report["status"] = "PASS"
    except BaseException:
        report["status"] = "FAIL"
        report["error"] = traceback.format_exc()
        raise
    finally:
        # Test-owned failed attempts are retained as evidence. Release finite
        # fake barriers and settle owners; do not delete files to make a pass.
        stream_factory.open_gate.set()
        window_factory.open_gate.set()
        for backend in stream_factory.backends:
            backend.fail_close = False
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
                deadline = time.monotonic() + 8
                while ((dialog is not None and not dialog.closed) or window.device.bridge.running):
                    app.processEvents()
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Synthetic GUI cleanup did not settle")
                    time.sleep(.005)
        except BaseException:
            report["status"] = "FAIL"
            report["cleanup_error"] = traceback.format_exc()
        if callbacks:
            report["status"] = "FAIL"
        report["files"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in output.glob("serial-*")
                           if path.is_file() and path.name != "serial-result.json"}
        (output / "serial-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.excepthook = previous_hook
    if report["status"] != "PASS":
        raise AssertionError(report.get("cleanup_error", "Serial GUI callback failure"))
    return report


def run(output_name):
    from PySide6 import QtWidgets
    output = Path(output_name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication([])
    app.setStyle("Fusion")
    result = {"status": "FAIL", "windows": platform.platform(), "python": sys.version,
              "frozen": bool(getattr(sys, "frozen", False)), "qt_platform": app.platformName()}
    try:
        assert sys.platform == "win32" and app.platformName() == "windows"
        result.update(exercise(app, output))
    except BaseException:
        result["status"] = "FAIL"
        result["error"] = traceback.format_exc()
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
