"""One explicitly selected physical stream trial; never flashes or resets a board.

The real serial factory is wrapped only to preserve byte-level traffic. There
is no simulator fallback. Host timestamps are diagnostics, not ADC timestamps.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import traceback
from unittest.mock import patch

from PySide6 import QtCore

from motortester import transport
from motortester.stream_recording import recover_attempt
from motortester.v2.stream_device import SerialStreamSelection, StreamDeviceBridge, open_verified_context


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "FAIL", "port": args.port, "source": "physical",
              "seconds_requested": args.seconds, "expected_build": args.build_id,
              "input_condition": "PA0 unconnected, as reported by user",
              "voltage_calibration_verified": False, "callback_errors": [], "errors": []}
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    original_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: report["callback_errors"].append(
        "".join(traceback.format_exception(kind, value, tb)))
    original_factory = transport._serial_factory
    wire_path = output / "traffic.bin"
    traffic = wire_path.open("xb")
    counts = {"host_bytes": 0, "device_bytes": 0, "chunks": 0}
    bridge = None
    finished = []
    saved = []

    def audit(direction, payload):
        if not payload:
            return
        if traffic.tell() + len(payload) + 13 > 16 * 1024 * 1024:
            raise RuntimeError("Bounded physical traffic log is full")
        # direction=0 host, 1 device; monotonic seconds, payload length.
        traffic.write(struct.pack("<BdI", direction, time.monotonic(), len(payload)))
        traffic.write(payload)
        counts["device_bytes" if direction else "host_bytes"] += len(payload)
        counts["chunks"] += 1

    class AuditedSerial:
        def __init__(self, backend):
            object.__setattr__(self, "_backend", backend)

        def __getattr__(self, name):
            return getattr(self._backend, name)

        def __setattr__(self, name, value):
            setattr(self._backend, name, value)

        def read(self, size):
            payload = self._backend.read(size)
            audit(1, payload)
            return payload

        def write(self, payload):
            accepted = self._backend.write(payload)
            audit(0, payload[:accepted])
            return accepted

    def factory(**kwargs):
        return AuditedSerial(original_factory(**kwargs))

    def flush():
        app.processEvents()
        if report["callback_errors"]:
            raise RuntimeError(report["callback_errors"][0])
        time.sleep(.003)

    def wait(predicate, seconds, label):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            flush()
        if not predicate():
            raise RuntimeError(label + ": " + str(bridge.state))

    def compact():
        state = bridge.state
        session = None if state.bridge is None else state.bridge.session
        return {
            "host_monotonic": time.monotonic(), "phase": state.phase,
            "received": state.validated_samples, "error": state.error,
            "failure": None if session is None or session.first_failure is None else
                asdict(session.first_failure),
            "R": None if session is None else session.selected_start_sample_index,
            "accepted": None if session is None else session.accepted_end_sample_index,
            "checkpoint": None if session is None else session.checkpointed_end_sample_index,
            "max_service_gap_ms": state.max_service_gap_ms,
            "peak_raw_items": state.peak_raw_items,
        }

    try:
        with patch.object(transport, "_serial_factory", factory):
            selection = SerialStreamSelection(args.port, args.source_commit, args.image_sha256)
            bridge = StreamDeviceBridge(selection=selection)
            bridge.finished.connect(lambda: finished.append(True))
            bridge.recording_ready.connect(saved.append)
            bridge.error.connect(report["errors"].append)
            assert bridge.connect_source(), "Connect rejected before opening port"
            wait(lambda: (bridge.state.ready and bridge.connection is not None) or
                 bridge.state.error, 6, "Handshake timeout")
            assert bridge.state.ready, bridge.state.error
            connection = bridge.connection
            report["connection"] = asdict(connection)
            assert connection.execution_kind == "physical"
            assert connection.observed_build_id == args.build_id, "Unexpected build; START not sent"
            assert bridge.state.validated_samples == 0, "Connect unexpectedly started ADC"
            assert bridge.start_live(), "Preview rejected"
            wait(lambda: bridge.state.validated_samples > 1000 or bridge.state.error, 5, "No stream")
            assert not bridge.state.error, bridge.state.error
            record = output / "physical.mtstream"
            assert bridge.record(record), "Record rejected"
            wait(lambda: bridge.state.phase == "recording" or bridge.state.error, 5, "No record")
            assert bridge.state.phase == "recording", bridge.state.error
            print("RECORDING_STARTED", flush=True)
            start = time.monotonic()
            report["observations"] = [compact()]
            next_checkpoint = start + 1
            while time.monotonic() - start < args.seconds:
                flush()
                state = bridge.state
                if state.error or state.phase == "fault":
                    break
                if time.monotonic() >= next_checkpoint:
                    report["observations"].append(compact())
                    next_checkpoint += 1
            report["record_wall_seconds"] = time.monotonic() - start
            report["before_stop"] = compact()
            if not args.expect_disconnect:
                assert bridge.state.phase == "recording", "Physical stream stopped early"
                assert bridge.stop(), "Stop rejected"
            else:
                assert bridge.state.phase == "fault" or bridge.state.error, "Disconnect was not observed"
            wait(lambda: bool(saved) or bridge.metadata_error is not None, 8, "Writer did not settle")
            assert saved and bridge.metadata_error is None
            report["after_stop"] = compact()
            context = open_verified_context(record)
            attempt = recover_attempt(record)
            recording = attempt.recording
            assert recording is not None and recording.end_sample_index > recording.first_sample_index
            assert recording.identity.origin == "device"
            assert context.connection.execution_kind == "physical"
            assert not context.connection.image_verified
            assert recording.identity == bridge.state.bridge.session.identity
            count = sum(block.sample_count for block in recording.iter_raw(
                recording.first_sample_index, recording.end_sample_index))
            assert count == recording.end_sample_index - recording.first_sample_index
            report["roundtrip"] = {
                "R": recording.first_sample_index, "end": recording.end_sample_index,
                "samples": count, "journal_recovery_verified": True,
                "wire_raw_byte_comparison": False, "origin": recording.identity.origin,
                "clean_stop_reported": recording.clean_stop_reported,
                "terminal": None if recording.terminal is None else asdict(recording.terminal),
                "journal_sha256": context.journal_sha256,
            }
            bridge.shutdown()
            wait(lambda: bool(finished), 8, "Owner did not close")
            report["owners_closed"] = True
            report["status"] = "PASS"
    except BaseException:
        report["exception"] = traceback.format_exc()
    finally:
        if bridge is not None and not finished:
            bridge.shutdown()
            deadline = time.monotonic() + 8
            while not finished and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            report["cleanup_finished"] = bool(finished)
            report["final_state"] = compact()
        traffic.close()
        report["traffic"] = {**counts, "format": "<BdI + payload; 0=host,1=device; monotonic seconds",
                             "sha256": hashlib.sha256(wire_path.read_bytes()).hexdigest()}
        sys.excepthook = original_hook
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                       default=str), encoding="utf-8")
        print(json.dumps({"status": report["status"], "output": str(output),
                          "exception": report.get("exception")}, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--build-id", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--expect-disconnect", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("Trial must be between 1 and 60 seconds")
    raise SystemExit(run(args))
