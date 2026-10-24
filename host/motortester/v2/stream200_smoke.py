"""Explicit native Qt witness for 100/200 kS/s; injected bytes, never a real port.

This module is loaded only by the requested source/package smoke. The normal
DEMO remains 50 kS/s. Synthetic throughput does not qualify STM32 ADC or USB.
"""
import argparse
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

from .serial_smoke import _Factory, _StreamBackend
from .stream_demo import PacedStreamPeer


class _RatePeer(PacedStreamPeer):
    def __init__(self, sample_rate_hz):
        self.sample_rate_hz = sample_rate_hz
        super().__init__(unknown_tail=True)
        self.peak_backlog_samples = 0
        self.bytes_read = self.saturated_reads = 0

    def _enqueue(self, kind, payload, request=0):
        from ..stream_wire import Kind
        if kind == Kind.CAPS:
            payload = struct.pack("<IHBBIIHHI", 1, 1, 0, 12, self.sample_rate_hz, 1, 128, 0, 1)
        elif kind == Kind.HELLO_ACK:
            # An injected observation is not authentication of a firmware image.
            build = 0x56325337 if self.sample_rate_hz == 100_000 else 0x56325335
            payload = struct.pack("<BBBBHHII", 0, 2, 1, 12, 512, 128, build, 1)
        super()._enqueue(kind, payload, request)

    def read(self, maximum):
        if self._started_at is not None and self._target is None:
            self.peak_backlog_samples = max(self.peak_backlog_samples, self._due() - self._next)
        data = super().read(maximum)
        self.bytes_read += len(data)
        self.saturated_reads += len(data) == maximum
        return data


class _RateBackend(_StreamBackend):
    def __init__(self, owner, sample_rate_hz, **settings):
        super().__init__(owner, **settings)
        self.peer = _RatePeer(sample_rate_hz)


def exercise(app, output, flush=None, *, sample_rate_hz=200_000):
    """Connect → record 5 s → Stop → fresh Open → CSV, with live main UI."""
    import numpy as np
    from PySide6 import QtGui, QtWidgets
    from .gui import MainWindow
    from .stream_device import SerialStreamSelection, StreamDeviceBridge
    from .stream_picker_smoke import _enter_path
    from .stream_ui import StreamDialog

    output = Path(output).resolve()
    assert output.is_dir()
    assert sample_rate_hz in (100_000, 200_000)
    rate = sample_rate_hz
    rate_k = rate // 1000
    interval_us = 1_000_000 // rate
    step_s = 1 / rate
    prefix = f"stream{rate_k}"
    factory = _Factory(lambda owner, **settings: _RateBackend(owner, rate, **settings))
    callbacks, errors = [], []
    report = {"status": "RUNNING", "source": "injected synthetic wire 0.2",
              "execution_kind": "injected-test", "physical_stream_verified": False,
              "nominal_fs_hz": rate, "interval_us": interval_us,
              "python": platform.python_version(), "platform": platform.platform(),
              "qt_platform": app.platformName(), "callback_errors": callbacks,
              "errors": errors, "screenshots": [], "observations": []}
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

    def wait(predicate, description, timeout=12):
        deadline = time.monotonic() + timeout
        while not predicate():
            pump()
            if time.monotonic() >= deadline:
                state = None if dialog is None else dialog.bridge.state
                raise AssertionError(f"{description}: {state!r}")
            time.sleep(.003)
        pump()

    def screenshot(name):
        pump()
        path = output / name
        assert dialog.grab().save(str(path))
        rendered = QtGui.QImage(str(path))
        assert not rendered.isNull()
        report["screenshots"].append({"path": name, "width": rendered.width(),
                                      "height": rendered.height()})

    class FixtureDialog(StreamDialog):
        def __init__(self, *args, **kwargs):
            kwargs["bridge_factory"] = lambda parent, **options: StreamDeviceBridge(
                parent, fake_backend_factory=factory, **options)
            super().__init__(*args, **kwargs)
            self.setWindowTitle(f"Проверка {rate_k} квыб/с · СИНТЕТИЧЕСКИЙ источник")

    try:
        with patch("motortester.transport._serial_factory",
                   side_effect=AssertionError("Real transport forbidden")), \
             patch("serial.serialwin32.Serial.open",
                   side_effect=AssertionError("Real COM forbidden")) as real_open, \
             patch("motortester.v2.stream_ui.StreamDialog", FixtureDialog):
            window = MainWindow(settings_path=output / f"{rate_k}k-settings.ini")
            window.show()
            assert window.timer.isActive()
            assert window._open_stream_workspace(SerialStreamSelection(
                f"V2_{rate_k}K_SYNTHETIC", requested_sample_rate_hz=rate))
            dialog = window.stream_dialog
            dialog.bridge.error.connect(errors.append)
            dialog.connect_button.click()
            wait(lambda: dialog.bridge.state.ready and dialog.bridge.connection is not None, "READY")
            connection = dialog.bridge.connection
            assert connection.observed_caps == (1, 1, 0, 12, rate, 1, 128, 1)
            assert connection.execution_kind == "injected-test" and not connection.image_verified
            backend, = factory.backends
            assert backend.commands == [1, 2] and dialog.bridge.state.validated_samples == 0
            dialog.raw_view.click()
            dialog.live_button.click()
            wait(lambda: dialog.bridge.state.validated_samples >= 20_000, "live data")
            assert str(rate) in dialog.notice.text() and f"шаг {interval_us} мкс" in dialog.notice.text()
            path = output / f"synthetic{rate_k}.mtstream"
            dialog.record_button.click()
            wait(lambda: dialog._record_picker is not None, "record picker")
            picker = dialog._record_picker
            _enter_path(picker, path, pump)
            box = picker.findChild(QtWidgets.QDialogButtonBox, "buttonBox")
            box.button(QtWidgets.QDialogButtonBox.StandardButton.Save).click()
            wait(lambda: dialog.bridge.state.phase == "recording", "recording")
            begin = time.monotonic()
            initial = dialog.bridge.state.validated_samples
            next_observation = begin
            while time.monotonic() - begin < 5:
                pump()
                if time.monotonic() >= next_observation:
                    state = dialog.bridge.state
                    session = state.bridge.session
                    report["observations"].append({"seconds": time.monotonic() - begin,
                        "received": state.validated_samples,
                        "accepted": session.accepted_end_sample_index,
                        "checkpointed": session.checkpointed_end_sample_index,
                        "queued_bytes": session.raw_bytes_held,
                        "queued_items": session.raw_items_held})
                    next_observation += 1
                assert dialog.bridge.state.phase == "recording", dialog.error_label.text()
                assert not errors
                time.sleep(.003)
            elapsed = time.monotonic() - begin
            processed = dialog.bridge.state.validated_samples - initial
            assert processed / elapsed >= rate * .9, "Synthetic receiver did not sustain the requested rate"
            assert window.timer.isActive()
            report["paced_observation"] = {"seconds": elapsed, "samples_received": processed,
                "mean_samples_per_host_second": processed / elapsed,
                "meaning": "host synthetic scheduling observation, not ADC frequency measurement"}
            screenshot(f"{prefix}-live.png")
            dialog.stop_button.click()
            wait(lambda: dialog.saved_path is not None and not dialog.bridge.metadata_pending,
                 "Stop and writer settlement")
            status = dialog.bridge.state
            assert status.phase == "stopped unknown tail"
            assert status.bridge.session.first_failure is None
            assert status.bridge.endpoint_first_fault is None and status.error is None
            assert not errors and not dialog.error_label.text()
            report["limits"] = {"peak_raw_items": status.peak_raw_items,
                "max_raw_items": status.raw_item_limit, "peak_raw_bytes": status.peak_raw_bytes,
                "max_raw_bytes": status.raw_byte_limit, "max_service_gap_ms": status.max_service_gap_ms,
                "peak_synthetic_backlog_samples": backend.peer.peak_backlog_samples,
                "max_synthetic_backlog_samples": backend.peer.max_backlog_samples,
                "saturated_reads": backend.peer.saturated_reads}
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(path), "")):
                dialog.open_button.click()
            wait(lambda: not dialog.busy and dialog.archive is not None and not dialog.viewer.busy,
                 "fresh open")
            archive = dialog.archive
            assert archive.identity.nominal_fs_hz == rate and archive.identity.origin == "synthetic"
            assert str(rate) in dialog.notice.text() and f"шаг {interval_us} мкс" in dialog.notice.text()
            assert dialog.viewer._config.pre_samples == rate // 1000
            assert dialog.viewer._config.post_samples == rate * 3 // 1000
            assert dialog.verified_context.connection == connection
            assert not archive.clean_stop_reported and archive.terminal.loss_samples is None
            assert archive.terminal.device_generated_end_sample_index is None
            period = np.frombuffer(backend.peer._period_raw, dtype="<u2")
            count, digest = 0, hashlib.sha256()
            for block in archive.iter_raw():
                codes = np.frombuffer(block.raw_u16le, dtype="<u2")
                indices = np.arange(block.first_sample_index, block.end_sample_index)
                assert np.array_equal(codes, period[indices % len(period)])
                count += len(codes)
                digest.update(block.raw_u16le)
            assert count >= rate * 4.5
            assert count == archive.end_sample_index - archive.first_sample_index
            wait(lambda: dialog.viewer.curve.getData()[0] is not None, "reopened plot")
            x, _ = dialog.viewer.curve.getData()
            # A min/max display may omit samples; its coordinates still use
            # negotiated time, independently of the all-sample CSV check below.
            assert 0 <= float(x[-1]) <= count / rate
            screenshot(f"{prefix}-open.png")
            export = output / f"synthetic{rate_k}.csv"
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(export), "")):
                dialog.export_button.click()
            wait(lambda: not dialog.busy and export.exists(), "CSV export")
            with export.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                first, second = next(reader), next(reader)
                csv_count = 2 + sum(1 for _ in reader)
            assert float(first["time_from_recording_start_s"]) == 0
            assert float(second["time_from_recording_start_s"]) == step_s
            assert csv_count == count
            receipt = json.loads(export.with_suffix(".csv.json").read_text("utf-8"))
            assert receipt["complete"] and receipt["identity"]["nominal_fs_hz"] == rate
            assert receipt["identity"]["origin"] == "synthetic"
            assert before == hashlib.sha256(path.read_bytes()).hexdigest()
            report["roundtrip"] = {"samples": count, "raw_sha256": digest.hexdigest(),
                "journal_sha256": before, "raw_matches_synthetic_period": True,
                "csv_rows": csv_count, "csv_dt_seconds": step_s,
                "identity": asdict(archive.identity), "connection": asdict(connection),
                "unknown_tail_preserved": True, "minmax_x_end_seconds": float(x[-1])}
            dialog.close()
            wait(lambda: dialog.closed, "dialog close")
            assert not backend.is_open and window._serial_owner is None
            window.close()
            wait(lambda: not window.isVisible(), "main close")
            assert not errors and not callbacks
            report.update(status="PASS", real_serial_open_calls=real_open.call_count, owners_closed=True)
            assert real_open.call_count == 0
    except BaseException:
        report.update(status="FAIL", exception=traceback.format_exc())
        raise
    finally:
        if dialog is not None and not dialog.closed:
            dialog.close()
            deadline = time.monotonic() + 8
            while not dialog.closed and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
        if window is not None:
            window.close()
            app.processEvents()
        sys.excepthook = previous_hook
        (output / f"{prefix}-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-rate", type=int, choices=(100_000, 200_000), default=200_000)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    exercise(QApplication([]), folder, sample_rate_hz=args.sample_rate)
