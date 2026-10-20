"""V2 adapter for the existing, bounded wire 0.1 acquisition worker.

Each result is one independently timed 2048-sample window. A host receipt
timestamp does not locate it on a continuous ADC timeline. Serial I/O, Stop
barriers, recovery and thread shutdown remain owned by AcquisitionBridge.
"""
from dataclasses import asdict
import json
from uuid import UUID

from PySide6 import QtCore

from ..acquisition import AcquisitionBridge
from ..model import Capture
from ..recording import atomic_write
from ..session import Capabilities, Config, Phase
from ..transport import SerialTransport
from ..window import MAX_WINDOW_SAMPLES, WindowResult
from .data import CaptureSettings, Recording, SignalBlock
from .input import InputProfile, UNKNOWN_PROFILE, V2Error, text


def available_ports():
    """List names/descriptions only; never probe, open or select a port."""
    from serial.tools.list_ports import comports
    return tuple(sorted((port.device, port.description) for port in comports()))


def _presentation(channel_name, ui_profile):
    text(channel_name, "Имя канала", 80)
    if ui_profile not in ("oscilloscope", "ignition"):
        raise V2Error("Неизвестный профиль интерфейса")


def make_device_config(*, mode=0, threshold_code=2048, edge="rising",
                       pretrigger_samples=512, capabilities=None):
    """The V2 UI currently controls raw ADC thresholds, never assumed volts.

    Profile 1 is the firmware's acquisition profile, unrelated to the two
    presentation profiles. There is no hardware holdoff field in wire 0.1.
    """
    if type(mode) is not int or mode not in (0, 2):
        raise V2Error("Доступны повторные Auto-окна и одиночный захват")
    if edge not in ("rising", "falling"):
        raise V2Error("Неизвестное направление фронта")
    if type(pretrigger_samples) is not int or pretrigger_samples not in (0, 512, 1024):
        raise V2Error("Предыстория прибора: 0, 512 или 1024 отсчёта")
    config = Config(mode=mode, edge=0 if edge == "rising" else 1,
                    level_code=threshold_code, pretrigger_samples=pretrigger_samples,
                    auto_timeout_ms=1000 if mode == 0 else 0)
    if capabilities is not None:
        if type(capabilities) is not Capabilities:
            raise V2Error("Возможности прибора ещё не подтверждены")
        if (config.profile != capabilities.profile
                or not capabilities.mode_bits & (1 << config.mode)
                or not capabilities.source_bits & 1
                or not capabilities.edge_bits & (1 << config.edge)
                or config.pretrigger_samples not in capabilities.pretrigger_samples):
            raise V2Error("Выбранный режим, фронт или предыстория не поддерживаются прибором")
    return config


def recording_from_capture(capture, *, channel_name="Канал 1",
                           ui_profile="oscilloscope", input_profile=UNKNOWN_PROFILE):
    """Preserve an admitted complete window; no interwindow time is inferred."""
    if type(capture) is not Capture or type(input_profile) is not InputProfile:
        raise V2Error("Требуются полное окно и снимок профиля входа")
    capture.__post_init__()
    _presentation(channel_name, ui_profile)
    flags = tuple(dict.fromkeys((*capture.quality_flags, "window_local_time",
                                 "interwindow_timing_unknown")))
    if capture.origin == "simulator":
        flags += ("wire_simulator",)
    configured = input_profile.configured
    return Recording(
        blocks=(SignalBlock(0, capture.nominal_fs_hz, capture.samples, flags),),
        channel_name=channel_name, ui_profile=ui_profile, input_profile=input_profile,
        source="device" if capture.origin == "device" else "demo",
        session_id=capture.session_id, created_at_utc=capture.received_at_utc,
        firmware_version=capture.firmware_version, protocol_version=capture.protocol_version,
        time_basis="nominal_unverified", legacy_sequence=capture.sequence,
        trigger_index=capture.trigger_index, quality_flags=flags,
        capture_settings=CaptureSettings(
            threshold_v=input_profile.voltage(capture.trigger_level_code) if configured else None,
            edge=input_profile.code_edge(capture.trigger_edge) if configured else capture.trigger_edge,
            holdoff_s=0, pretrigger_fraction=capture.pretrigger_samples / len(capture.samples),
            window_s=len(capture.samples) / capture.nominal_fs_hz,
            hardware_threshold_code=capture.trigger_level_code, trigger_kind=capture.trigger_kind),
    )


def save_incomplete(path, result, *, snapshot=None, channel_name="Канал 1",
                    ui_profile="oscilloscope"):
    """Save raw fragments as a diagnostic JSON report, never a full recording.

    Offsets and missing ranges retain the receiver's local-window coordinates.
    No missing code is filled and no voltage calibration is invented.
    """
    if type(result) is not WindowResult or result.semantic_checks_complete:
        raise V2Error("Требуется неполный или не прошедший проверку результат")
    _presentation(channel_name, ui_profile)
    if (type(result.fragments) is not tuple or len(result.fragments) > MAX_WINDOW_SAMPLES
            or sum(len(block.samples) for block in result.fragments) > MAX_WINDOW_SAMPLES):
        raise V2Error("Фрагменты превышают размер окна")
    previous = 0
    for block in result.fragments:
        if (type(block.offset) is not int or type(block.samples) is not tuple
                or not block.samples or block.offset < previous
                or block.offset + len(block.samples) > MAX_WINDOW_SAMPLES
                or any(type(code) is not int or not 0 <= code <= 4095 for code in block.samples)):
            raise V2Error("Некорректные исходные фрагменты")
        previous = block.offset + len(block.samples)
    report = {
        "format": "motortester-v2-incomplete-report", "format_version": 1,
        "complete_recording": False, "source": "device", "channel_id": "CH1",
        "channel_name": channel_name, "ui_profile": ui_profile,
        "input_profile": asdict(UNKNOWN_PROFILE), "time_basis": "nominal_unverified",
        "time_origin": "window_sample_index_zero",
        "interwindow_timing": "unknown", "result": asdict(result),
        "session_id": str(UUID(int=snapshot.session)) if snapshot else None,
        "firmware_version": str(snapshot.capabilities.firmware_build)
        if snapshot and snapshot.capabilities else None,
        "protocol_version": f"draft-0.1@{snapshot.source_sha}" if snapshot else None,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    atomic_write(path, payload)


class DeviceBridge(QtCore.QObject):
    """GUI-thread facade. Retain each Recording before accept(recording).

    A true command return means queued, not acknowledged by the MCU. Keep this
    object alive until finished. Physical reconnect/reset requirements and
    close failures are exposed unchanged through state and bridge.
    """
    state_changed = QtCore.Signal(object)
    recording_ready = QtCore.Signal(object)
    incomplete_ready = QtCore.Signal(object)
    error = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, parent=None, *, serial_factory=SerialTransport,
                 clock_ms=None, interval_ms=10):
        super().__init__(parent)
        self.bridge = AcquisitionBridge(self, serial_factory=serial_factory,
                                        clock_ms=clock_ms, interval_ms=interval_ms)
        self._channel_name, self._ui_profile = "Канал 1", "oscilloscope"
        self._recording = self._capture = None
        self._incomplete_item = self._pending_incomplete = self._saved_incomplete = None
        self._incomplete_release_requested = None
        self._worker_finished = False
        self.bridge.state_changed.connect(self._state_changed)
        self.bridge.capture_ready.connect(self._capture_ready)
        self.bridge.incomplete_ready.connect(self._incomplete_ready)
        self.bridge.error.connect(self.error.emit)
        self.bridge.finished.connect(self._finished)

    @property
    def state(self):
        return self.bridge.state

    @property
    def snapshot(self):
        return self.state.snapshot

    @property
    def pending_recording(self):
        return self._recording

    @property
    def pending_incomplete(self):
        return self._pending_incomplete

    def connect_source(self, port, reset_confirmed=False):
        return self.bridge.connect_source("device", port=port, reset_confirmed=reset_confirmed)

    def start(self, mode=0, threshold_code=2048, edge="rising", pretrigger_samples=512,
              channel_name="Канал 1", ui_profile="oscilloscope"):
        try:
            _presentation(channel_name, ui_profile)
            snapshot = self.snapshot
            if snapshot is None or snapshot.phase is not Phase.READY or snapshot.capabilities is None:
                raise V2Error("Сначала дождитесь подтверждения возможностей прибора")
            settings = make_device_config(
                mode=mode, threshold_code=threshold_code, edge=edge,
                pretrigger_samples=pretrigger_samples, capabilities=snapshot.capabilities)
        except ValueError as exc:
            self.error.emit(str(exc))
            return False
        if not self.bridge.start(settings, simulate_edge=False):
            return False
        self._channel_name, self._ui_profile = channel_name, ui_profile
        return True

    def accept(self, recording):
        if recording is None or recording is not self._recording:
            return False
        return self.bridge.acknowledge(self._capture)

    def acknowledge_incomplete(self, result):
        if result is None or result is not self._pending_incomplete:
            return False
        if self._worker_finished:
            # Shutdown can produce fragments while closing the transport. The
            # dead worker cannot consume an ACK; only our exact successful save
            # permits settling that retained result locally.
            if result is not self._saved_incomplete:
                return False
            self._pending_incomplete = None
            return True
        # A queued live ACK can still be cancelled by Shutdown. Retain the local
        # result until a worker state confirms that it actually consumed it.
        accepted = self.bridge.acknowledge_incomplete(result)
        if accepted and result is self._saved_incomplete:
            self._incomplete_release_requested = result
        return accepted

    def discard_incomplete(self, result):
        """Release only this result after the GUI's explicit Discard choice.

        With a live worker, True means its ACK was queued. Keep the exact
        decision until ACK confirmation or finished: shutdown may cancel that
        queued ACK, but it must not apply the decision to another late result.
        This operation never removes or rewrites any saved file.
        """
        if result is None or result is not self._pending_incomplete:
            return False
        if self._worker_finished:
            self._pending_incomplete = None
            return True
        accepted = self.bridge.acknowledge_incomplete(result)
        if accepted:
            self._incomplete_release_requested = result
        return accepted

    def save_incomplete(self, path, result):
        item = self._incomplete_item
        if item is None or result is not item[0]:
            raise V2Error("Неполный результат не принадлежит этому подключению")
        # The immutable tuple binds data and context for the entire file job,
        # even if a later GUI notification installs another result meanwhile.
        _, snapshot, name, profile = item
        save_incomplete(path, result, snapshot=snapshot, channel_name=name, ui_profile=profile)
        if self._incomplete_item is item:
            self._saved_incomplete = result

    def stop(self):
        return self.bridge.stop()

    def disconnect_source(self):
        return self.bridge.disconnect_source()

    def shutdown(self):
        return self.bridge.shutdown()

    @QtCore.Slot(object)
    def _state_changed(self, state):
        if not state.has_capture:
            self._recording = self._capture = None
        if not state.has_incomplete and not self._worker_finished:
            self._pending_incomplete = None
        self.state_changed.emit(state)

    @QtCore.Slot(object)
    def _capture_ready(self, capture):
        try:
            recording = recording_from_capture(capture, channel_name=self._channel_name,
                                               ui_profile=self._ui_profile)
        except ValueError as exc:
            # The legacy worker retains the original if conversion is rejected.
            self.error.emit(str(exc))
            self.bridge.stop()
            return
        self._capture, self._recording = capture, recording
        self.recording_ready.emit(recording)

    @QtCore.Slot(object)
    def _incomplete_ready(self, result):
        if self._incomplete_item is None or self._incomplete_item[0] is not result:
            self._incomplete_item = (result, self.snapshot, self._channel_name, self._ui_profile)
            self._saved_incomplete = None
            self._incomplete_release_requested = None
        self._pending_incomplete = result
        self.incomplete_ready.emit(result)

    @QtCore.Slot()
    def _finished(self):
        # AcquisitionBridge emits finished only after its final drain and
        # nonblocking native join. Late incomplete_ready has already arrived.
        self._worker_finished = True
        if (self._pending_incomplete is not None
                and self._pending_incomplete is self._incomplete_release_requested):
            self._pending_incomplete = None
        self.finished.emit()
