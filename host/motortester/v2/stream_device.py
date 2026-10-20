"""V2 synthetic streaming facade over the existing bounded wire/disk owners.

No physical admission or serial factory is exposed. The journal is the existing
MTSTREAM format; its V2 presentation/input snapshot is a hash-bound companion.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
from pathlib import Path
import threading

from PySide6 import QtCore

from ..recording import atomic_write
from ..stream_controller import StreamController
from ..stream_recording import (ATTEMPT_MAGIC, MAX_ATTEMPT_FILE_BYTES, StreamLimits,
                                recover, recover_attempt)
from ..stream_view import EventConfig
from .input import InputProfile, UNKNOWN_PROFILE, text
from .stream_demo import PacedStreamPeer

CONTEXT_FORMAT = "motortester-v2-stream-context"
# Host-only navigation thresholds. They do not configure the ADC or volts.
DEFAULT_EVENT_CONFIG = EventConfig(2600, 2200, "above", 50, 150, 25, 100, 500, 0, 4095)


@dataclass(frozen=True, slots=True)
class StreamContext:
    channel_name: str = "Канал 1"
    ui_profile: str = "oscilloscope"
    input_profile: InputProfile = UNKNOWN_PROFILE
    channel_id: str = "CH1"

    def __post_init__(self):
        text(self.channel_name, "Имя канала", 80)
        if self.ui_profile not in ("oscilloscope", "ignition") or self.channel_id != "CH1":
            raise ValueError("Требуется CH1 и поддерживаемый профиль")
        if type(self.input_profile) is not InputProfile or self.input_profile != UNKNOWN_PROFILE:
            raise ValueError("Поток V2-04 сохраняет только неизвестную шкалу напряжения")


@dataclass(frozen=True, slots=True)
class VerifiedStreamContext:
    context: StreamContext
    companion_present: bool
    journal_sha256: str | None


@dataclass(frozen=True, slots=True)
class ContextFailure:
    """An exact failed attempt; a decision cannot transfer to another journal."""
    path: str
    context: StreamContext
    identity: object
    message: str

    def __str__(self):
        return self.message


def companion_path(path):
    path = Path(path)
    return path.with_name(path.name + ".v2.json")


def _digest(path):
    digest, count = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            count += len(chunk)
            if count > MAX_ATTEMPT_FILE_BYTES:
                raise ValueError("Потоковый файл превышает ограничение формата")
            digest.update(chunk)
    return digest.hexdigest(), count


def _journal_binding(path):
    with Path(path).open("rb") as stream:
        attempt = stream.read(8) == ATTEMPT_MAGIC
    if attempt:
        report = recover_attempt(path)
        recording = report.recording
        identity, recording_id = report.preparation.identity, report.preparation.recording_id
    else:
        recording = recover(path)
        identity, recording_id = recording.identity, recording.start.recording_id
    return {
        "identity": asdict(identity), "recording_id": recording_id,
        "first_sample_index": None if recording is None else recording.first_sample_index,
        "end_sample_index": None if recording is None else recording.end_sample_index,
    }


def _write_context(path, context, expected_identity):
    """File-owner operation after actual writer settlement, never on the GUI."""
    binding = _journal_binding(path)
    if expected_identity is None or binding["identity"] != asdict(expected_identity):
        raise ValueError("Файл не принадлежит текущей потоковой попытке")
    digest, size = _digest(path)
    value = {
        "format": CONTEXT_FORMAT, "format_version": 1,
        "context": asdict(context), "time_basis": "nominal_unverified",
        "journal_sha256": digest, "journal_bytes": size, "journal": binding,
    }
    atomic_write(companion_path(path),
                 json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
    return str(path)


def open_verified_context(path):
    """Worker-only read. Old files get UNKNOWN_PROFILE, never a DEMO scale.

    A present companion is mandatory evidence: corruption or a mismatched file
    is an error, not a reason to fall back silently to an absent context.
    """
    sidecar = companion_path(path)
    try:
        with sidecar.open("rb") as stream:
            raw = stream.read(16_385)
    except FileNotFoundError:
        return VerifiedStreamContext(StreamContext(), False, None)
    if len(raw) > 16_384:
        raise ValueError("Слишком большой файл контекста потока")
    value = json.loads(raw)
    required = {"format", "format_version", "context", "time_basis",
                "journal_sha256", "journal_bytes", "journal"}
    if (type(value) is not dict or set(value) != required
            or value["format"] != CONTEXT_FORMAT or type(value["format_version"]) is not int
            or value["format_version"] != 1 or value["time_basis"] != "nominal_unverified"):
        raise ValueError("Неизвестный формат контекста потока")
    context = value["context"]
    if type(context) is not dict or set(context) != set(StreamContext.__dataclass_fields__):
        raise ValueError("Некорректный снимок контекста потока")
    context = dict(context)
    context["input_profile"] = InputProfile(**context["input_profile"])
    context = StreamContext(**context)
    digest, size = _digest(path)
    if (type(value["journal_sha256"]) is not str
            or not hmac.compare_digest(digest, value["journal_sha256"])
            or type(value["journal_bytes"]) is not int or size != value["journal_bytes"]
            or value["journal"] != _journal_binding(path)):
        raise ValueError("Контекст не соответствует исходному потоковому файлу")
    return VerifiedStreamContext(context, True, digest)


class StreamDeviceBridge(QtCore.QObject):
    """GUI-thread commands; three legacy workers retain raw/disk/display ownership.

    Pause is a viewer operation: this facade never pauses receiver or writer.
    Closing first requests protocol Stop and preserves finalization/sidecar
    errors; finished is emitted only after the actual owners have joined.
    """
    state_changed = QtCore.Signal(object)
    live_ready = QtCore.Signal(object)
    recording_ready = QtCore.Signal(str)
    error = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, parent=None, *, context=StreamContext(), peer=None,
                 event_config=DEFAULT_EVENT_CONFIG, storage_limits=StreamLimits()):
        super().__init__(parent)
        if type(context) is not StreamContext:
            raise ValueError("Требуется неизменяемый контекст V2")
        context.__post_init__()
        self.context = context
        self.controller = StreamController(
            PacedStreamPeer(context.ui_profile) if peer is None else peer,
            event_config=event_config, storage_limits=storage_limits)
        self._display_lock = threading.Lock()
        self._latest = None
        self._revision = None
        self._minimum_display_revision = 0
        self._record_path = self._metadata = self._executor = None
        self._record_context = None
        self._metadata_identity = self._metadata_error = None
        self._metadata_started = self._closing = self._closed = False
        self._last_error = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    @property
    def state(self):
        return self.controller.snapshot()

    @property
    def metadata_pending(self):
        return self._metadata_error is not None or (
            self._record_path is not None and not self._metadata_started) or (
            self._metadata is not None)

    @property
    def metadata_error(self):
        return self._metadata_error

    def retry_context(self, failure):
        if self._closed or failure is None or failure is not self._metadata_error:
            return False
        self._metadata_error = None
        self._last_error = None
        self._metadata = self._executor.submit(
            _write_context, failure.path, failure.context, failure.identity)
        return True

    def abandon_context(self, failure):
        """Explicitly abandon only this companion; never remove the raw journal."""
        if self._closed or failure is None or failure is not self._metadata_error:
            return False
        self._metadata_error = None
        self._record_path = self._record_context = self._metadata_identity = None
        return True

    def cancel_shutdown(self):
        if self._closed or not self._closing or self._metadata_error is None:
            return False
        self._closing = False
        return True

    def start_live(self):
        if self._closing or self.metadata_pending:
            return False
        previous = self.controller.snapshot()
        if not self.controller.preview():
            return False
        self._fence_new_source(previous.revision)
        return True

    def record(self, path):
        if self._closing or self.metadata_pending:
            return False
        if type(self.context) is not StreamContext:
            raise ValueError("Требуется неизменяемый контекст V2")
        self.context.__post_init__()
        path = str(path)
        previous = self.controller.snapshot()
        if not self.controller.record(path):
            return False
        # can_preview marks a restartable source. Recording an already running
        # preview keeps its generation and display; a direct start replaces it.
        if previous.can_preview:
            self._fence_new_source(previous.revision)
        self._record_path = path
        self._record_context = self.context
        self._metadata_started = False
        self._metadata = None
        return True

    def stop(self):
        return not self._closed and self.controller.stop()

    def shutdown(self):
        if self._closed or self._closing:
            return False
        self._closing = True
        self.controller.stop()
        self._poll()
        return True

    def _deliver(self, result):
        # Called by the display worker. No Qt widgets, per-DATA signals or disk.
        with self._display_lock:
            if result.source.revision >= self._minimum_display_revision:
                self._latest = result

    def _fence_new_source(self, previous_revision):
        # Admission precedes the receiver's _begin/revision increment. Late
        # callbacks stay fenced even if immediate Stop cancels that new start.
        with self._display_lock:
            self._minimum_display_revision = max(
                self._minimum_display_revision, previous_revision + 1)
            self._latest = None

    def _report_error(self, message):
        if message != self._last_error:
            self._last_error = message
            self.error.emit(message)

    @QtCore.Slot()
    def _poll(self):
        if self._closed:
            return
        status = self.controller.snapshot()
        bridge = status.bridge
        if (bridge is not None and bridge.identity is not None
                and status.revision >= self._minimum_display_revision
                and status.revision != self._revision and not status.can_open):
            self._revision = status.revision
            self.controller.bind_display(status.revision, self._deliver)
        with self._display_lock:
            latest, self._latest = self._latest, None
        if (latest is not None and latest.source.revision == status.revision
                and latest.source.revision >= self._minimum_display_revision):
            self.live_ready.emit(latest)
        message = status.error or status.display_error
        if message:
            self._report_error(message)
        if self._record_path is not None and not self._metadata_started and status.can_open:
            self._metadata_started = True
            self._metadata_identity = None if bridge is None else bridge.identity
            self._executor = self._executor or ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="v2-stream-context")
            self._metadata = self._executor.submit(
                _write_context, self._record_path, self._record_context,
                self._metadata_identity)
        if self._metadata is not None and self._metadata.done():
            future, self._metadata = self._metadata, None
            try:
                path = future.result()
            except Exception as exc:
                self._metadata_error = ContextFailure(
                    self._record_path, self._record_context, self._metadata_identity,
                    "Контекст потока не сохранён: " + str(exc))
                self._report_error(str(self._metadata_error))
            else:
                self.recording_ready.emit(path)
        self.state_changed.emit(status)
        # can_open means source/storage are settled; no forced abandonment of
        # a live writer merely because the user closed the window.
        if self._closing and status.can_open and not self.metadata_pending:
            self.controller.close()
        if self._closing and not self.metadata_pending and self.controller.join(0):
            self._closed = True
            self._timer.stop()
            if self._executor is not None:
                self._executor.shutdown(wait=False)
            self.finished.emit()
