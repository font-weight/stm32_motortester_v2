"""Operator-run recovery check for exact SC on COM6, nominal100k mode2.

HELLO discovery/selected-mode and GET_CAPS only: no START or Record. Do not
run without a separately admitted recovery decision and confirmed USB replug.
This helper opens COM only when explicitly executed; generation of this file
and AST validation are offline. Source/image strings are declared provenance.
"""
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


EXPECTED_BUILD = 0x56325343
DECLARED_SOURCE = "310d53b10c79a48ddc45357ff65d88c686aef883"
DECLARED_IMAGE = "a36f72a772c03c5cbfd85767e5f07f0abc3ad2f2ffd7d1ee1c43143d20ca1c90"


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
            "operation": "V2SC recovery HELLO/GET_CAPS ready check; no START/Record",
            "declared_source": DECLARED_SOURCE,
            "declared_image_sha256": DECLARED_IMAGE,
            "provenance_note": "Declared pins only; independent full-memory readback authenticates the recovery image.",
            "requested_sample_rate_hz": 100000,
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
            "COM6", DECLARED_SOURCE, DECLARED_IMAGE, requested_sample_rate_hz=100000))
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
                and bridge.connection.execution_kind == "physical"
                and bridge.connection.protocol_revision == "0.3"
                and tuple(bridge.connection.observed_caps) == (2,2,0,12,100000,1,128,1,12,1))
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
                and not report["cleanup_errors"]
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
