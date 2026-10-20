"""Operator-run COM6 rollback check: HELLO/GET_CAPS only, never CONFIG/ARM."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from enum import Enum
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))

from PySide6 import QtCore
from motortester.acquisition import AcquisitionBridge
from motortester.session import Phase


def enum_value(value):
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).with_name("rollback-handshake.json"),
    )
    output = parser.parse_args().output.resolve()
    # Preserve earlier evidence and fail before opening COM if output is occupied.
    with output.open("x", encoding="utf-8") as destination:
        report = {
            "status": "FAIL",
            "operation": "HELLO/GET_CAPS rollback confirmation; no CONFIG/ARM/START",
            "port": "COM6",
            "handshake_timeout_seconds": 5,
            "cleanup_timeout_seconds": 3,
            "snapshot": None,
            "errors": [],
            "cleanup_errors": [],
            "owner_closed": False,
        }
        app = QtCore.QCoreApplication([])
        bridge = AcquisitionBridge()
        cleanup = False
        finished = False

        def error(message):
            report["cleanup_errors" if cleanup else "errors"].append(str(message))

        def on_finished():
            nonlocal finished
            finished = True

        bridge.error.connect(error)
        bridge.finished.connect(on_finished)
        start = time.monotonic()
        try:
            report["connect_accepted"] = bridge.connect_source("device", port="COM6")
            if not report["connect_accepted"]:
                raise RuntimeError("AcquisitionBridge rejected connect_source")
            while time.monotonic() - start < 5:
                app.processEvents()
                snapshot = bridge.state.snapshot
                if snapshot is not None and snapshot.phase is Phase.READY:
                    report["snapshot"] = asdict(snapshot)
                    break
                if snapshot is not None and snapshot.phase is Phase.RECOVERY:
                    break
                time.sleep(0.005)
            snapshot = bridge.state.snapshot
            if report["snapshot"] is None and snapshot is not None:
                report["snapshot"] = asdict(snapshot)
            report["handshake_elapsed_seconds"] = time.monotonic() - start
            report["ready"] = snapshot is not None and snapshot.phase is Phase.READY
            report["no_capture_configuration"] = bool(
                snapshot is not None
                and snapshot.config is None
                and snapshot.config_id == 0
                and snapshot.generation == 0
                and snapshot.next_tx_sequence == 3
                and snapshot.next_request_id == 3
            )
            report["expected_rollback_build"] = bool(
                snapshot is not None
                and snapshot.capabilities is not None
                and snapshot.capabilities.firmware_build == 20261017
                and snapshot.capabilities.capability_bits == 61
            )
        except Exception as exc:
            report["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            cleanup = True
            report["shutdown_accepted"] = bridge.shutdown()
            cleanup_start = time.monotonic()
            while not finished and time.monotonic() - cleanup_start < 3:
                app.processEvents()
                time.sleep(0.005)
            report["cleanup_elapsed_seconds"] = time.monotonic() - cleanup_start
            report["owner_closed"] = bool(
                finished and not bridge.running and not bridge.state.connected
                and not bridge.state.close_failed
            )
            report["final_state"] = asdict(bridge.state)
            if (
                report.get("ready")
                and report.get("no_capture_configuration")
                and report.get("expected_rollback_build")
                and not report["errors"]
                and report["owner_closed"]
            ):
                report["status"] = "PASS"
            encoded = json.dumps(report, ensure_ascii=False, indent=2, default=enum_value)
            destination.write(encoded + "\n")
            destination.flush()
            print(encoded, flush=True)
        if bridge.running:
            # A failed owner close is recorded; do not destroy a running QThread.
            os._exit(1)
        return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
