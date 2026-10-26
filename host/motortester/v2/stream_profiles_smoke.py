"""Explicit Windows Qt witness, injected serial only; no physical rate claim."""
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
import zlib
from unittest.mock import patch

from .serial_smoke import _Factory, _StreamBackend
from .stream_demo import PacedStreamPeer
from ..stream_wire import (Kind, MODE_TABLE, MODE_MAX_BLOCK, MODE_MAX_PAYLOAD, BATCH1024_REVISION,
                          decode_frame, decode_payload, encode_frame, pack10)


class ProfilesPeer(PacedStreamPeer):
    """Paced test fixture with one selected mode, same bounded backlog as DEMO."""
    def __init__(self, *, discovery_capabilities=15):
        super().__init__(unknown_tail=True)
        # Old SC/SD advertisements remain separate fixtures; their150k modes
        # must never be silently upgraded to the new1024-sample contract.
        self.discovery_capabilities = discovery_capabilities
        self.discovery_max_block, self.discovery_max_payload, self.fixture_build = {
            3: (128, 512, 0x56325343),
            7: (256, 512, 0x56325344),
            15: (1024, 1300, 0xF0102401),
        }[discovery_capabilities]
        self.revision, self.mode = "0.2", 0
        self.original_period = self._period_raw
        self.handshakes = []
        self.peak_backlog_samples = 0
        self.wire_acks = []
        self.wire_full_frames = 0
        self.wire_short_samples = None
        self.wire_first_full = None
        self.wire_max_frame_bytes = 0
        self.wire_next_index = self.wire_crc = self.wire_last_data_sequence = 0
        self.wire_end_validated = False

    def _enqueue(self, kind, payload, request=0):
        if kind == Kind.DATA:
            generation, _, first, count, reserved = struct.unpack_from("<IIQHH", payload)
            raw = payload[20:]
            if self.mode in (3, 4, 5):
                raw = pack10(tuple(code for (code,) in struct.iter_unpack("<H", raw)))
            payload = struct.pack("<IIQHH", generation, self.mode, first, count, reserved) + raw
        elif kind in (Kind.START_ACK, Kind.END):
            payload = payload[:4] + struct.pack("<I", self.mode) + payload[8:]
        frame = encode_frame(kind, self._nonce, self._sequence, request, payload, revision=self.revision)
        # The receipt describes decoded wire bytes, not just fixture settings.
        decoded_frame = decode_frame(frame, "device")
        observed = decode_payload(decoded_frame)
        if kind == Kind.HELLO_ACK:
            self.wire_acks.append((decoded_frame.revision, observed.capabilities,
                                   observed.max_block, observed.max_payload))
        elif kind == Kind.DATA:
            maximum = MODE_MAX_BLOCK[self.mode]
            assert observed.first_index == self.wire_next_index and self.wire_short_samples is None
            assert observed.generation == self._generation and observed.config_id == self.mode
            if self.wire_last_data_sequence:
                assert decoded_frame.sequence == self.wire_last_data_sequence + 1
            if len(observed.samples) == maximum:
                self.wire_full_frames += 1
                if self.wire_first_full is None:
                    self.wire_first_full = len(observed.samples)
            else:
                assert self._target is not None and observed.end_index == self._target
                self.wire_short_samples = len(observed.samples)
            self.wire_next_index = observed.end_index
            self.wire_crc = zlib.crc32(observed.raw_samples, self.wire_crc)
            self.wire_last_data_sequence = decoded_frame.sequence
            self.wire_max_frame_bytes = max(self.wire_max_frame_bytes, len(frame))
        elif kind == Kind.END:
            assert (observed.prefix_end, observed.prefix_crc32, observed.last_data_sequence) == (
                self.wire_next_index, self.wire_crc, self.wire_last_data_sequence)
            assert decoded_frame.sequence == self.wire_last_data_sequence + 1
            self.wire_end_validated = True
        if len(self._incoming) + len(frame) > 2048:
            raise RuntimeError("Synthetic control queue overflow")
        self._sequence += 1
        self._incoming.extend(frame)

    def write(self, data):
        if type(data) is not bytes or len(data) > 544 or len(self._tx) + len(data) > 1088:
            raise ValueError("Bounded wire bytes required")
        self._tx.extend(data)
        while 0 in self._tx:
            end = self._tx.index(0) + 1
            framed = bytes(self._tx[:end]); del self._tx[:end]
            if framed == b"\0":
                continue
            frame = decode_frame(framed, "host")
            payload = decode_payload(frame)
            if frame.kind == Kind.HELLO:
                self._incoming.clear()
                self._nonce, self._sequence = payload.nonce, 1
                self.revision, self.mode = frame.revision, payload.mode
                self.handshakes.append((frame.revision, payload.nonce, payload.mode))
                self._generation = self._next = self._crc = self._last_data = 0
                self._started_at = self._target = self._produced = self._end_sequence = None
                self._reason = self._flags = self._stop_request = 0
                self._period_raw = self.original_period
                if self.revision == "0.3":
                    self.sample_rate_hz = MODE_TABLE[self.mode][0]
                    assert self.mode in ({3: (1, 2, 3), 7: (1, 2, 3, 4), 15: (1, 2, 3, 4, 5)}[
                        self.discovery_capabilities])
                    if self.mode in (3, 4, 5):
                        self._period_raw = struct.pack("<" + "H" * self._period_samples,
                            *(code & 4092 for (code,) in struct.iter_unpack("<H", self.original_period)))
                discovery = self.revision == "0.2"
                self._enqueue(Kind.HELLO_ACK, struct.pack("<BBBBHHII", 0, int(self.revision[-1]),
                    1, 12, self.discovery_max_payload if discovery else MODE_MAX_PAYLOAD[self.mode],
                    self.discovery_max_block if discovery else MODE_MAX_BLOCK[self.mode],
                    self.fixture_build, self.discovery_capabilities if discovery else 1), frame.request_id)
                continue
            assert self.revision == "0.3" and frame.revision == self.revision
            assert frame.nonce == self._nonce
            if frame.kind == Kind.GET_CAPS:
                rate, retained, encoding = MODE_TABLE[self.mode]
                self._enqueue(Kind.CAPS, struct.pack("<IHBBIIHBBI", self.mode, self.mode, 0, 12,
                              rate, 1, MODE_MAX_BLOCK[self.mode], retained, encoding, 1), frame.request_id)
            elif frame.kind == Kind.START:
                assert payload == self.mode
                self._generation, self._started_at = frame.request_id, self.clock()
                self._enqueue(Kind.START_ACK, struct.pack("<IIQ", self._generation, self.mode, 0), frame.request_id)
            elif frame.kind == Kind.STOP:
                assert payload == self._generation
                self._stop_request = frame.request_id
                if self._end_sequence is not None:
                    self._ack()
                elif self._target is None:
                    self._terminate()
        return len(data)

    def _data(self, count):
        # DATA1024 traverses the200-sample synthetic period several times.
        first = (self._next % self._period_samples) * 2
        repeated = self._period_raw * (2 + count // self._period_samples)
        raw = repeated[first:first + 2 * count]
        assert len(raw) == 2 * count
        self._last_data = self._sequence
        self._enqueue(Kind.DATA, struct.pack("<IIQHH", self._generation, self.mode,
                                            self._next, count, 0) + raw)
        self._crc = zlib.crc32(raw, self._crc)
        self._next += count

    def _produce_one(self):
        if self._started_at is None or self._end_sequence is not None:
            return
        maximum = MODE_MAX_BLOCK[self.mode]
        if self._target is None:
            due = self._due() - self._next
            if due > self.max_backlog_samples:
                self._terminate(overrun=True)
            elif due >= maximum:
                self._data(maximum)
                return
            else:
                return
        remaining = self._target - self._next
        if remaining:
            self._data(min(maximum, remaining))
            return
        self._end_sequence = self._sequence
        self._enqueue(Kind.END, struct.pack("<IIQQIIHHI", self._generation, self.mode,
            self._next, 0 if self.unknown_tail else self._produced,
            self._last_data, self._crc, self._reason, self._flags, self._stop_request))
        if self._stop_request:
            self._ack()

    def read(self, maximum):
        if self._started_at is not None and self._target is None:
            self.peak_backlog_samples = max(self.peak_backlog_samples, self._due() - self._next)
        return super().read(maximum)


class ProfilesBackend(_StreamBackend):
    def __init__(self, owner, *, discovery_capabilities=15, **settings):
        super().__init__(owner, **settings)
        self.peer = ProfilesPeer(discovery_capabilities=discovery_capabilities)


def exercise(app, output):
    import numpy as np
    from .gui import MainWindow
    from .stream_device import SerialStreamSelection, StreamDeviceBridge, companion_path
    from .stream_ui import StreamDialog
    from .stream_files import open_stream
    from .stream200_smoke import _RateBackend

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "errors": [], "callback_errors": [],
              "frozen": bool(getattr(sys, "frozen", False)), "platform": sys.platform,
              "windows_host": platform.platform(),
              "qt_platform": app.platformName(), "executable": sys.executable,
              "owners_closed": False, "real_serial_open_calls": 0, "checks": {}, "files": {},
              "execution_kind": "injected-test", "physical_stream_verified": False}
    window = dialog = mismatch = sc_mismatch = sd_mismatch = None
    factory = _Factory(ProfilesBackend)
    legacy_factory = _Factory(lambda owner, **settings: _RateBackend(owner, 100_000, **settings))
    sc_factory = _Factory(lambda owner, **settings: ProfilesBackend(owner, discovery_capabilities=3, **settings))
    sd_factory = _Factory(lambda owner, **settings: ProfilesBackend(owner, discovery_capabilities=7, **settings))
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: report["callback_errors"].append(
        "".join(traceback.format_exception(kind, value, tb)))

    def pump():
        app.processEvents()
        if report["callback_errors"]:
            raise AssertionError(report["callback_errors"][0])

    def wait(predicate, label, timeout=12):
        deadline = time.monotonic() + timeout
        while not predicate():
            pump()
            if time.monotonic() >= deadline:
                raise AssertionError(label + ": " + str(None if dialog is None else dialog.bridge.state))
            time.sleep(.003)
        pump()

    def screenshot(name, widget):
        pump()
        assert widget.grab().save(str(output / name))

    class FixtureDialog(StreamDialog):
        def __init__(self, *args, **kwargs):
            kwargs["bridge_factory"] = lambda parent, **options: StreamDeviceBridge(
                parent, fake_backend_factory=factory, **options)
            super().__init__(*args, **kwargs)
            self.setWindowTitle("Режимы приёма · СИНТЕТИЧЕСКАЯ проверка")

    try:
        with patch("motortester.transport._serial_factory", side_effect=AssertionError("Real transport forbidden")), \
             patch("serial.serialwin32.Serial.open", side_effect=AssertionError("Real COM forbidden")) as real_open, \
             patch("motortester.v2.stream_ui.StreamDialog", FixtureDialog):
            window = MainWindow(settings_path=output / "settings.ini")
            window.show()
            assert window._open_stream_workspace(SerialStreamSelection("V2_PROFILES_SYNTHETIC"))
            dialog = window.stream_dialog
            dialog.bridge.error.connect(report["errors"].append)
            assert [dialog.rate_combo.itemData(i) for i in range(dialog.rate_combo.count())] == [50_000, 100_000, 150_000]
            assert dialog.rate_combo.isEnabled()
            # Exercise each visible choice while disconnected, then commit150.
            for i in range(3):
                dialog.rate_combo.setCurrentIndex(i); pump()
            report["checks"]["selector_modes"] = True
            dialog.connect_button.click()
            wait(lambda: dialog.bridge.state.ready and dialog.bridge.connection is not None, "mode READY")
            connection = dialog.bridge.connection
            assert connection.protocol_revision == "0.3" and connection.observed_caps == (5, 5, 0, 12, 150_000, 1, 1024, 1, 10, 2)
            backend, = factory.backends
            assert backend.commands == [1, 1, 2]
            assert backend.peer.handshakes[0][1] != backend.peer.handshakes[1][1]
            assert backend.peer.wire_acks == [("0.2", 15, 1024, 1300), ("0.3", 1, 1024, 1300)]
            report["checks"]["batch_mode5_negotiated"] = True
            assert not dialog.rate_combo.isEnabled() and not dialog.bridge.select_sample_rate(50_000)
            report["checks"]["selection_locked"] = True
            dialog.raw_view.click(); dialog.live_button.click()
            wait(lambda: dialog.bridge.state.validated_samples >= 10_000, "packed live")
            assert "10 старших бит" in dialog.notice.text() and "150000" in dialog.notice.text()
            path = output / "packed150.mtstream"
            assert dialog.record_path(str(path))
            wait(lambda: dialog.bridge.state.phase == "recording", "record selection")
            started, initial = time.monotonic(), dialog.bridge.state.validated_samples
            while time.monotonic() - started < 2:
                pump()
                assert dialog.bridge.state.phase == "recording" and not report["errors"]
                time.sleep(.003)
            elapsed = time.monotonic() - started
            count = dialog.bridge.state.validated_samples - initial
            assert count / elapsed >= 135_000
            report["paced_observation"] = {"host_seconds": elapsed, "received": count,
                "samples_per_host_second": count / elapsed,
                "meaning": "synthetic host scheduling only; not ADC/USB performance"}
            screenshot("profiles-live.png", dialog)
            dialog.stop_button.click()
            wait(lambda: dialog.saved_path is not None and not dialog.bridge.metadata_pending, "Stop/journal/context")
            assert dialog.bridge.state.phase == "stopped unknown tail" and not report["errors"]
            peer = backend.peer
            assert peer.wire_end_validated and peer.wire_full_frames > 0 and peer.wire_first_full == 1024
            assert peer.wire_max_frame_bytes <= 1335
            report["batch"] = {"acquisition_mode": 5, "config_id": 5, "negotiated_max_block": 1024,
                "discovery_capabilities": peer.wire_acks[0][1],
                "discovery_max_block": peer.wire_acks[0][2], "discovery_max_payload": peer.wire_acks[0][3],
                "selected_ack_max_block": peer.wire_acks[1][2], "selected_ack_max_payload": peer.wire_acks[1][3],
                "full_DATA1024_frames": peer.wire_full_frames, "first_full_data_count": peer.wire_first_full,
                "short_tail_frames": int(peer.wire_short_samples is not None),
                "terminal_short_samples": peer.wire_short_samples,
                "largest_frame_bytes": peer.wire_max_frame_bytes,
                "data_count_sequence_validation": peer.wire_end_validated,
                "canonical_crc_validated": peer.wire_end_validated}
            report["checks"]["batch1024_wire_evidence"] = True
            report["limits"] = {"peak_raw_items": dialog.bridge.state.peak_raw_items,
                "peak_raw_bytes": dialog.bridge.state.peak_raw_bytes,
                "max_service_gap_ms": dialog.bridge.state.max_service_gap_ms,
                "peak_synthetic_backlog_samples": backend.peer.peak_backlog_samples,
                "synthetic_backlog_limit": backend.peer.max_backlog_samples}
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            assert dialog.open_path(str(path))
            wait(lambda: not dialog.busy and dialog.archive is not None and not dialog.viewer.busy, "fresh Open")
            archive = dialog.archive
            assert archive.identity.retained_bits == 10 and archive.identity.discarded_lsb == 2
            assert archive.identity.protocol_revision == BATCH1024_REVISION and archive.identity.acquisition_mode == archive.identity.config_id == 5
            assert dialog.verified_context.companion_present and dialog.verified_context.connection == connection
            assert archive.recovery_issue is None and archive.terminal.loss_samples is None
            assert "10 старших бит" in dialog.notice.text() and dialog.viewer._config.rail_high == 4092
            period = np.frombuffer(backend.peer.original_period, dtype="<u2")
            digest, sample_count = hashlib.sha256(), 0
            for block in archive.iter_raw():
                codes = np.frombuffer(block.raw_u16le, dtype="<u2")
                indices = np.arange(block.first_sample_index, block.end_sample_index)
                assert np.array_equal(codes, period[indices % len(period)] & 4092)
                digest.update(block.raw_u16le); sample_count += len(codes)
            assert sample_count >= 270_000
            report["checks"]["packed_record_roundtrip"] = True
            screenshot("profiles-open.png", dialog)
            # The intrinsic contract must survive a new path with NO companion.
            bare = output / "intrinsic-only.mtstream"; bare.write_bytes(path.read_bytes())
            bare_context, bare_attempt = open_stream(bare)
            assert not bare_context.companion_present
            assert bare_attempt.recording.identity == archive.identity
            assert b"".join(block.raw_u16le for block in bare_attempt.recording.iter_raw()) == b"".join(block.raw_u16le for block in archive.iter_raw())
            report["checks"]["intrinsic_quantization"] = True
            export = output / "packed150.csv"
            assert dialog.export_path(str(export))
            wait(lambda: not dialog.busy and export.exists(), "CSV export", 30)
            with export.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                rows = [next(reader), next(reader)]
                csv_count = 2 + sum(1 for _ in reader)
            assert csv_count == sample_count
            assert "adc12_scale_code_retained10_truncate_lsb2" in rows[0]
            assert float(rows[0]["time_from_recording_start_s"]) == 0
            assert float(rows[1]["time_from_recording_start_s"]) == 1 / 150_000
            exported = json.loads(export.with_suffix(".csv.json").read_text("utf-8"))
            assert exported["complete"] and exported["identity"] == asdict(archive.identity)
            assert before == hashlib.sha256(path.read_bytes()).hexdigest()
            report["checks"]["csv_timebase"] = True
            report["roundtrip"] = {"samples": sample_count, "raw_sha256": digest.hexdigest(),
                "identity": asdict(archive.identity), "connection": asdict(connection),
                "csv_dt_seconds": 1 / 150_000, "journal_sha256": before}
            dialog.close(); wait(lambda: dialog.closed, "main dialog closed")
            assert not backend.is_open and window._serial_owner is None
            mismatch = StreamDialog(selection=SerialStreamSelection("LEGACY_SYNTHETIC", requested_sample_rate_hz=150_000),
                bridge_factory=lambda parent, **options: StreamDeviceBridge(parent, fake_backend_factory=legacy_factory, **options))
            mismatch.show(); mismatch.connect_button.click()
            wait(lambda: mismatch.bridge.state.bridge is not None and
                 mismatch.bridge.state.bridge.endpoint_first_fault is not None and
                 "фиксированную частоту 100000" in mismatch.error_label.text(), "legacy mismatch visible")
            assert legacy_factory.backends[0].commands == [1, 2]
            assert not mismatch.bridge.state.ready and mismatch.bridge.state.validated_samples == 0
            assert not mismatch.live_button.isEnabled()
            screenshot("profiles-legacy-mismatch.png", mismatch)
            report["checks"]["legacy_mismatch_before_start"] = True
            report["expected_legacy_error"] = mismatch.error_label.text()
            mismatch.close(); wait(lambda: mismatch.closed, "legacy owner closed")
            sc_mismatch = StreamDialog(selection=SerialStreamSelection("SC_SYNTHETIC", requested_sample_rate_hz=150_000),
                bridge_factory=lambda parent, **options: StreamDeviceBridge(parent, fake_backend_factory=sc_factory, **options))
            sc_mismatch.show(); sc_mismatch.connect_button.click()
            wait(lambda: sc_mismatch.bridge.state.bridge is not None and
                 sc_mismatch.bridge.state.bridge.endpoint_first_fault is not None and
                 "нужна прошивка с пакетами по 1024" in sc_mismatch.error_label.text(), "SC150 batch-required visible")
            assert sc_factory.backends[0].commands == [1]
            assert not sc_mismatch.bridge.state.ready and sc_mismatch.bridge.state.validated_samples == 0
            assert not sc_mismatch.live_button.isEnabled()
            screenshot("profiles-sc150-mismatch.png", sc_mismatch)
            report["expected_sc150_error"] = sc_mismatch.error_label.text()
            sc_mismatch.close(); wait(lambda: sc_mismatch.closed, "SC owner closed")
            sd_mismatch = StreamDialog(selection=SerialStreamSelection("SD_SYNTHETIC", requested_sample_rate_hz=150_000),
                bridge_factory=lambda parent, **options: StreamDeviceBridge(parent, fake_backend_factory=sd_factory, **options))
            sd_mismatch.show(); sd_mismatch.connect_button.click()
            wait(lambda: sd_mismatch.bridge.state.bridge is not None and
                 sd_mismatch.bridge.state.bridge.endpoint_first_fault is not None and
                 "нужна прошивка с пакетами по 1024" in sd_mismatch.error_label.text(), "SD150 batch-required visible")
            assert sd_factory.backends[0].commands == [1]
            assert not sd_mismatch.bridge.state.ready and sd_mismatch.bridge.state.validated_samples == 0
            assert not sd_mismatch.live_button.isEnabled()
            screenshot("profiles-sd150-mismatch.png", sd_mismatch)
            report["checks"]["sc_sd150_batch_required_before_start"] = True
            report["expected_sd150_error"] = sd_mismatch.error_label.text()
            sd_mismatch.close(); wait(lambda: sd_mismatch.closed, "SD owner closed")
            window.close(); wait(lambda: not window.isVisible(), "main window closed")
            assert not report["errors"] and not report["callback_errors"] and real_open.call_count == 0
            report.update(status="PASS", owners_closed=all(not b.is_open for f in (factory, legacy_factory, sc_factory, sd_factory) for b in f.backends),
                          real_serial_open_calls=real_open.call_count)
    except BaseException:
        report["status"] = "FAIL"
        report["errors"].append(traceback.format_exc())
    finally:
        for active in (dialog, mismatch, sc_mismatch, sd_mismatch):
            if active is not None and not active.closed:
                active.close()
                deadline = time.monotonic() + 8
                while not active.closed and time.monotonic() < deadline:
                    app.processEvents(); time.sleep(.01)
        if window is not None:
            window.close(); app.processEvents()
        sys.excepthook = previous_hook
        for path in output.iterdir():
            if path.is_file() and path.name != "result.json":
                content = path.read_bytes()
                report["files"][path.name] = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return report


def run(output):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return 0 if exercise(app, output)["status"] == "PASS" else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    sys.exit(run(parser.parse_args().output))
