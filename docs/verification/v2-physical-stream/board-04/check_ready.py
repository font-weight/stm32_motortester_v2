"""Operator-run COM6 V2S4 HELLO/CAPS check. Never starts ADC or recording."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from enum import Enum
import json
from pathlib import Path
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))

from PySide6 import QtCore
from motortester.v2.stream_device import SerialStreamSelection, StreamDeviceBridge


EXPECTED_BUILD = 0x56325334
DECLARED_SOURCE = "c10884fa39ad1a10ce0fcfc9d6e17f170e1e0bf0"
DECLARED_IMAGE = "04ba2853b6a964cd812bf555a32da7fb019bcd60ba9fda0bd586d71112b3143d"


def json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).with_name("ready-handshake.json"),
    )
    output = parser.parse_args().output.resolve()
    # Reserve a new receipt before creating any serial owner.
    with output.open("x", encoding="utf-8") as destination:
        report = {
            "status": "FAIL",
            "operation": "V2S4 HELLO/GET_CAPS ready check; no START/Record",
            "port": "COM6",
            "expected_build": EXPECTED_BUILD,
            "handshake_timeout_seconds": 5,
            "cleanup_timeout_seconds": 5,
            "errors": [],
            "cleanup_errors": [],
            "callback_errors": [],
            "owner_closed": False,
        }
        app = QtCore.QCoreApplication([])
        previous_hook = sys.excepthook
        sys.excepthook = lambda kind, value, tb: report["callback_errors"].append(
            "".join(traceback.format_exception(kind, value, tb)))
        bridge = StreamDeviceBridge(selection=SerialStreamSelection(
            "COM6", DECLARED_SOURCE, DECLARED_IMAGE))
        cleanup = False
        finished = False

        def on_error(message):
            report["cleanup_errors" if cleanup else "errors"].append(str(message))

        def on_finished():
            nonlocal finished
            finished = True

        bridge.error.connect(on_error)
        bridge.finished.connect(on_finished)
        started = time.monotonic()
        try:
            report["connect_accepted"] = bridge.connect_source()
            if not report["connect_accepted"]:
                raise RuntimeError("Connect rejected before handshake")
            while time.monotonic() - started < 5:
                app.processEvents()
                state = bridge.state
                if state.ready and bridge.connection is not None:
                    break
                if state.error or report["errors"] or report["callback_errors"]:
                    break
                time.sleep(0.005)
            state = bridge.state
            report["handshake_elapsed_seconds"] = time.monotonic() - started
            report["ready_state"] = asdict(state)
            report["connection"] = (
                None if bridge.connection is None else asdict(bridge.connection))
            report["ready"] = bool(state.ready and bridge.connection is not None)
            report["expected_build_observed"] = bool(
                bridge.connection is not None
                and bridge.connection.observed_build_id == EXPECTED_BUILD
                and bridge.connection.execution_kind == "physical")
            report["no_source_started"] = bool(
                state.validated_samples == 0 and state.path is None
                and state.bridge is not None and state.bridge.session is None
                and state.bridge.pending_start is None
                and state.bridge.identity is None)
        except Exception as exc:
            report["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            cleanup = True
            report["shutdown_accepted"] = bridge.shutdown()
            closing_started = time.monotonic()
            while not finished and time.monotonic() - closing_started < 5:
                app.processEvents()
                time.sleep(0.005)
            final_state = bridge.state
            report["cleanup_elapsed_seconds"] = time.monotonic() - closing_started
            report["final_state"] = asdict(final_state)
            report["owner_closed"] = bool(
                finished and bridge.controller.join(0)
                and not final_state.serial_unresolved
                and final_state.serial is not None
                and final_state.serial.handle_settled
                and not final_state.can_retry_close)
            report["final_validated_samples"] = final_state.validated_samples
            if (
                report.get("ready")
                and report.get("expected_build_observed")
                and report.get("no_source_started")
                and final_state.validated_samples == 0
                and report["owner_closed"]
                and not report["errors"]
                and not report["callback_errors"]
            ):
                report["status"] = "PASS"
            sys.excepthook = previous_hook
            encoded = json.dumps(report, ensure_ascii=False, indent=2, default=json_value)
            destination.write(encoded + "\n")
            destination.flush()
            print(encoded, flush=True)
        return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
