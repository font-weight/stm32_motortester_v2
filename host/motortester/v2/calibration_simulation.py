"""Explicit teaching source for the live calibration collector, never a device.

Qt delivers indexed blocks on a bounded timer. This checks the same snapshot
collector as the physical stream; it is not USB throughput or timing evidence.
"""
from dataclasses import asdict
from types import SimpleNamespace as NS
import uuid

import numpy as np
from PySide6 import QtCore

from ..stream_model import StreamIdentity
from ..stream_wire import mode_revision
from .analog_profile import nominal_selection
from .stream_device import StreamContext


class SyntheticCalibrationStream(QtCore.QObject):
    live_ready = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connection = None
        self.is_device = False
        self.controller = NS(snapshot=self.snapshot)
        self.plan = self.context = self.identity = None
        self.end = 0
        self.raw = b""
        self.revision = 1
        self.role, self.reference = "first", 0.
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)

    def current(self):
        return None if self.plan is None else (self, self.context)

    def prepare(self, plan, role, reference):
        if plan.origin != "synthetic":
            raise ValueError("Учебный поток не может иметь происхождение STM32")
        if plan != self.plan:
            self.end, self.raw = 0, b""
            self.revision += 1
            f = plan.raw_format
            fields = {k: v for k, v in asdict(f).items() if k in StreamIdentity.__dataclass_fields__}
            self.identity = StreamIdentity("teaching-" + uuid.uuid4().hex, 1, f.acquisition_mode,
                f.sample_rate_hz, "synthetic", protocol_revision=mode_revision(f.acquisition_mode),
                application_version="V2-18-teaching", **fields)
            profile, snapshot = nominal_selection(plan.mode_id, f,
                hardware_instance_id=plan.hardware_instance_id)
            self.context = StreamContext(input_profile=profile, analog_snapshot=snapshot)
            self.plan = plan
        self.role, self.reference = role, reference
        self.timer.start()

    def snapshot(self):
        detector = NS(outcome="running", discontinuity=None)
        session = NS(source_started=True, first_failure=None, source_end=None,
                     stop_requested=False, admission_fenced=False, writer_fenced=False)
        bridge = NS(identity=self.identity, source_received_end=self.end, closed=False,
                    endpoint_first_fault=None, late_fault=None, source_terminal=None, session=session)
        return NS(phase="preview", revision=self.revision, command_pending=False, stop_pending=False,
                  stop_requested=False, close_requested=False, worker_unresolved=False,
                  can_retry_close=False, error=None, display_error=None, bridge=bridge,
                  raw_available_start=self.end - len(self.raw) // 2, ring_samples=len(self.raw) // 2,
                  detector_status=detector)

    def advance(self):
        if self.plan is None:
            return
        plan = self.plan
        count = round(plan.raw_format.sample_rate_hz * .04)
        indexes = np.arange(self.end, self.end + count)
        if plan.mode_id == "DC_WIDE":
            values = (self.reference + 40) / .02 + .35 * np.sin(indexes * .7)
        elif self.role == "zero":
            values = np.full(count, 2000.)
        else:
            factor = {"Vpp": 2., "Vpk": 1., "Vrms": 1 / np.sqrt(2)}[plan.amplitude_kind]
            peak = self.reference / factor
            values = 2015 + peak / .005 * np.sin(2 * np.pi * plan.frequency_hz *
                                                indexes / plan.raw_format.sample_rate_hz)
        step = plan.raw_format.canonical_step
        # Saturation is deliberately preserved so the common quality gate
        # can reject an excessive teaching amplitude just as it rejects raw.
        raw = np.clip(np.rint(values / step) * step, 0, plan.raw_format.canonical_max).astype('<u2').tobytes()
        self.raw = (self.raw + raw)[-65536 * 2:]
        self.end += count
        source = NS(identity=self.identity, revision=self.revision, end=self.end,
                    raw_first=self.end - len(self.raw) // 2, raw=self.raw,
                    loss_samples=0, tail_state="running", flags=(),
                    detector=NS(outcome="running", discontinuity=None))
        self.live_ready.emit(NS(source=source))

    def close(self):
        self.timer.stop()
