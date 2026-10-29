"""V2 streaming facade over the existing bounded wire/disk owners.

Serial selection is explicit and inert until Connect; HELLO/CAPS never starts
acquisition. The journal keeps its MTSTREAM format and a hash-bound companion.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
import json
from pathlib import Path
import threading

from PySide6 import QtCore

from ..recording import atomic_write
from ..stream_controller import StreamController
from ..stream_provenance import DeviceStreamContext
from ..stream_serial import SerialSettings, SerialStreamPeer
from ..stream_session import SessionLimits
from ..stream_recording import (ATTEMPT_MAGICS, MAX_ATTEMPT_FILE_BYTES, StreamLimits,
                                recover, recover_attempt)
from ..stream_model import LEGACY_IDENTITY_FIELDS
from ..stream_view import EventConfig
from ..stream_wire import SUPPORTED_SAMPLE_RATES, supported_caps, supported_mode_caps, mode_revision
from .input import InputProfile, UNKNOWN_PROFILE, text
from .stream_demo import PacedStreamPeer
from .stream_search import SearchSnapshot, validate_config

CONTEXT_FORMAT = "motortester-v2-stream-context"
# Host-only navigation thresholds. They do not configure the ADC or volts.
DEFAULT_EVENT_CONFIG = EventConfig(2600, 2200, "above", 50, 150, 25, 100, 500, 0, 4095)


def default_event_config(sample_rate_hz, retained_bits=12):
    """Keep default navigation durations at 1/3/0.5/2/10 ms for every rate.

    Threshold codes are unchanged. These are host event windows, not an ADC
    trigger or a claim that the whole physical ignition discharge was captured.
    """
    if sample_rate_hz not in SUPPORTED_SAMPLE_RATES:
        raise ValueError("Неподдерживаемая частота навигации")
    scale = sample_rate_hz // 50_000
    return replace(DEFAULT_EVENT_CONFIG, rail_high=4092 if retained_bits == 10 else 4095, **{
        field: getattr(DEFAULT_EVENT_CONFIG, field) * scale for field in
        ("pre_samples", "post_samples", "baseline_samples", "holdoff_samples", "max_event_samples")})


@dataclass(frozen=True, slots=True)
class SerialStreamSelection:
    """Operator declarations are separate from observations of HELLO/CAPS."""
    port: str
    declared_source_commit: str | None = None
    declared_artifact_sha256: str | None = None
    requested_sample_rate_hz: int | None = None

    def __post_init__(self):
        SerialSettings(self.port)
        if self.requested_sample_rate_hz is not None and (
                type(self.requested_sample_rate_hz) is not int or
                self.requested_sample_rate_hz not in SUPPORTED_SAMPLE_RATES):
            raise ValueError("Неподдерживаемая выбранная частота")
        for value, size in ((self.declared_source_commit, 40), (self.declared_artifact_sha256, 64)):
            if value is not None and (type(value) is not str or len(value) != size or
                    any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("Требуется полный lowercase Git SHA / SHA-256 либо неизвестное значение")


@dataclass(frozen=True, slots=True)
class StreamConnection:
    selection: SerialStreamSelection
    execution_kind: str
    observed_build_id: int
    observed_caps: tuple[int, ...]
    dtr_requested: bool = True
    accounting_domain: str = "unknown"
    image_verified: bool = False
    protocol_revision: str = "0.2"

    def __post_init__(self):
        if type(self.selection) is not SerialStreamSelection:
            raise ValueError("Требуется неизменяемый выбор COM")
        self.selection.__post_init__()
        if (self.execution_kind not in ("physical", "injected-test") or
                type(self.observed_build_id) is not int or not 0 <= self.observed_build_id <= 0xffffffff or
                not ((self.protocol_revision == "0.2" and supported_caps(self.observed_caps)) or
                     (self.protocol_revision == "0.3" and supported_mode_caps(self.observed_caps))) or
                self.dtr_requested is not True or self.accounting_domain != "unknown" or
                self.image_verified is not False):
            raise ValueError("Некорректное наблюдение потока; образ и домен учёта не подтверждены")
        if (self.selection.requested_sample_rate_hz is not None and
                self.selection.requested_sample_rate_hz != self.observed_caps[4]):
            raise ValueError("Выбранная частота не соответствует CAPS")


class _DtrBackend:
    """Transport retains this owner before DTR/open can fail.

    Requested DTR=True is a CDC control request, not proof of a hardware level,
    reset, byte isolation, or the firmware image executing on the board.
    """
    def __init__(self, backend):
        self._backend = backend

    def __getattr__(self, name):
        return getattr(self._backend, name)

    @property
    def port(self):
        return self._backend.port

    @port.setter
    def port(self, value):
        self._backend.port = value

    def open(self):
        if self._backend.is_open is not False:
            raise ValueError("DTR must be selected on a closed backend")
        self._backend.dtr = True
        self._backend.open()


def _serial_peer(selection, fake_backend_factory):
    def factory(**kwargs):
        if fake_backend_factory is None:
            from ..transport import _serial_factory
            backend = _serial_factory(**kwargs)
        else:
            backend = fake_backend_factory(**kwargs)
        return _DtrBackend(backend)
    options = {"backend_factory" if fake_backend_factory is None else "fake_backend_factory": factory}
    return SerialStreamPeer(SerialSettings(selection.port), **options)


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
            raise ValueError("Поток сохраняет только неизвестную шкалу напряжения")


@dataclass(frozen=True, slots=True)
class VerifiedStreamContext:
    context: StreamContext
    companion_present: bool
    journal_sha256: str | None
    connection: StreamConnection | None = None
    event_search: SearchSnapshot | None = None


@dataclass(frozen=True, slots=True)
class ContextFailure:
    """An exact failed attempt; a decision cannot transfer to another journal."""
    path: str
    context: StreamContext
    identity: object
    message: str
    connection: StreamConnection | None = None
    event_search: SearchSnapshot | None = None

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


def _journal_binding(path, *, legacy=False):
    with Path(path).open("rb") as stream:
        magic = stream.read(8)
        attempt = magic in ATTEMPT_MAGICS
    if attempt:
        report = recover_attempt(path)
        recording = report.recording
        identity, recording_id = report.preparation.identity, report.preparation.recording_id
    else:
        recording = recover(path)
        identity, recording_id = recording.identity, recording.start.recording_id
    values = asdict(identity)
    if legacy:
        if magic not in (b"MTSTRM\x01\x00", b"MTSTRM\x02\x00"):
            raise ValueError("Старый companion не описывает новую версию журнала")
        values = {name: values[name] for name in LEGACY_IDENTITY_FIELDS}
    return {
        "identity": values, "recording_id": recording_id,
        "first_sample_index": None if recording is None else recording.first_sample_index,
        "end_sample_index": None if recording is None else recording.end_sample_index,
    }


def _write_context(path, context, expected_identity, connection=None, event_search=None):
    """File-owner operation after actual writer settlement, never on the GUI."""
    binding = _journal_binding(path)
    if expected_identity is None or binding["identity"] != asdict(expected_identity):
        raise ValueError("Файл не принадлежит текущей потоковой попытке")
    digest, size = _digest(path)
    value = {
        "format": CONTEXT_FORMAT, "format_version": 3,
        "context": asdict(context), "time_basis": "nominal_unverified",
        "journal_sha256": digest, "journal_bytes": size, "journal": binding,
        "connection": None,
    }
    if connection is not None:
        _verify_connection(connection, binding["identity"])
        value["connection"] = asdict(connection)
    if event_search is not None:
        event_search.__post_init__()
        validate_config(event_search.config, expected_identity.nominal_fs_hz, expected_identity.retained_bits)
        value.update(format_version=4, event_search=asdict(event_search))
    atomic_write(companion_path(path),
                 json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
    return str(path)


def _verify_connection(connection, identity):
    if type(connection) is not StreamConnection:
        raise ValueError("Некорректный контекст соединения")
    connection.__post_init__()
    origin = "device" if connection.execution_kind == "physical" else "synthetic"
    if (identity["origin"] != origin or
            identity["firmware_version"] != f"build:{connection.observed_build_id:08x}" or
            identity["application_version"] != "v2-serial-unknown-accounting:" + connection.execution_kind or
            identity["protocol_revision"] != (mode_revision(connection.observed_caps[0]) if connection.protocol_revision == "0.3" else "0.2-draft-081721") or
            identity["config_id"] != connection.observed_caps[0] or
            identity["nominal_fs_hz"] != connection.observed_caps[4]):
        raise ValueError("Наблюдение соединения не соответствует журналу")
    if connection.protocol_revision == "0.3" and (
            identity["acquisition_mode"] != connection.observed_caps[0] or
            identity["retained_bits"] != connection.observed_caps[8]):
        raise ValueError("Описание квантования не соответствует CAPS")


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
    if type(value) is dict and value.get("format_version") in (2, 3, 4):
        required.add("connection")
    if type(value) is dict and value.get("format_version") == 4:
        required.add("event_search")
    if (type(value) is not dict or set(value) != required
            or value["format"] != CONTEXT_FORMAT or type(value["format_version"]) is not int
            or value["format_version"] not in (1, 2, 3, 4) or value["time_basis"] != "nominal_unverified"):
        raise ValueError("Неизвестный формат контекста потока")
    context = value["context"]
    if type(context) is not dict or set(context) != set(StreamContext.__dataclass_fields__):
        raise ValueError("Некорректный снимок контекста потока")
    context = dict(context)
    context["input_profile"] = InputProfile(**context["input_profile"])
    context = StreamContext(**context)
    connection = None
    if value["format_version"] == 2 and value["connection"] is None:
        raise ValueError("Старый serial companion требует контекст соединения")
    if value["format_version"] in (2, 3, 4) and value["connection"] is not None:
        raw_connection = value["connection"]
        connection_fields = set(StreamConnection.__dataclass_fields__)
        selection_fields = set(SerialStreamSelection.__dataclass_fields__)
        if value["format_version"] == 2:
            connection_fields.remove("protocol_revision")
            selection_fields.remove("requested_sample_rate_hz")
        if (type(raw_connection) is not dict or
                set(raw_connection) != connection_fields or type(raw_connection["selection"]) is not dict or
                set(raw_connection["selection"]) != selection_fields):
            raise ValueError("Некорректный контекст соединения")
        raw_connection = dict(raw_connection)
        raw_connection["selection"] = SerialStreamSelection(**raw_connection["selection"])
        raw_connection["observed_caps"] = tuple(raw_connection["observed_caps"])
        connection = StreamConnection(**raw_connection)
        _verify_connection(connection, value["journal"]["identity"])
    digest, size = _digest(path)
    if (type(value["journal_sha256"]) is not str
            or not hmac.compare_digest(digest, value["journal_sha256"])
            or type(value["journal_bytes"]) is not int or size != value["journal_bytes"]
            or value["journal"] != _journal_binding(path, legacy=value["format_version"] < 3)):
        raise ValueError("Контекст не соответствует исходному потоковому файлу")
    event_search = None
    if value["format_version"] == 4:
        event_search = SearchSnapshot.from_dict(value["event_search"])
        identity = value["journal"]["identity"]
        validate_config(event_search.config, identity["nominal_fs_hz"], identity["retained_bits"])
    return VerifiedStreamContext(context, True, digest, connection, event_search)


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
                 event_config=DEFAULT_EVENT_CONFIG, storage_limits=StreamLimits(),
                 selection=None, fake_backend_factory=None):
        super().__init__(parent)
        if type(context) is not StreamContext:
            raise ValueError("Требуется неизменяемый контекст V2")
        context.__post_init__()
        if selection is not None:
            if type(selection) is not SerialStreamSelection or peer is not None:
                raise ValueError("Выбор COM требует собственного serial receiver")
            selection.__post_init__()
        if fake_backend_factory is not None and (selection is None or not callable(fake_backend_factory)):
            raise ValueError("Тестовый backend требует явного выбора COM")
        self.context = context
        self._default_event_config = event_config == DEFAULT_EVENT_CONFIG
        self._selection = selection
        self.is_device = selection is not None
        self._execution_kind = "physical" if fake_backend_factory is None else "injected-test"
        self.connection = None
        self._connect_pending = self._disconnecting = False
        if self.is_device:
            peer = _serial_peer(selection, fake_backend_factory)
        self.controller = StreamController(
            PacedStreamPeer(context.ui_profile) if peer is None else peer,
            event_config=event_config, storage_limits=storage_limits,
            # 1024 full wire blocks still fit the existing 256 KiB byte cap.
            # At 200k this allows the same 655 ms disk stall budget as 256
            # blocks at 50k. Exhaustion remains an explicit incomplete stop.
            **({"managed_peer": True, "device_context": DeviceStreamContext(
                    self._execution_kind, selection.requested_sample_rate_hz),
                "session_limits": SessionLimits(max_raw_items=1024)}
               if self.is_device else {}))
        self._display_lock = threading.Lock()
        self._latest = None
        self._revision = None
        self._minimum_display_revision = 0
        self._record_path = self._metadata = self._executor = None
        self._record_context = None
        self._record_connection = None
        self._record_search = None
        self.search_config = None
        self._search_basis = None
        self.search_reset_notice = ""
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
    def selection(self):
        return self._selection

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
            _write_context, failure.path, failure.context, failure.identity, failure.connection,
            failure.event_search)
        return True

    def abandon_context(self, failure):
        """Explicitly abandon only this companion; never remove the raw journal."""
        if self._closed or failure is None or failure is not self._metadata_error:
            return False
        self._metadata_error = None
        self._record_path = self._record_context = self._metadata_identity = None
        self._record_connection = None
        return True

    def cancel_shutdown(self):
        if self._closed or not self._closing or self._metadata_error is None:
            return False
        self._closing = False
        return True

    def start_live(self):
        if self._closing or self._disconnecting or self.metadata_pending:
            return False
        previous = self.controller.snapshot()
        if self.is_device and not previous.ready:
            return False
        # Select sample counts only after accepted CAPS, before a new source.
        # Explicit custom sample configurations retain their caller's meaning.
        config = self.search_config or (default_event_config(self.connection.observed_caps[4],
                    self.connection.observed_caps[8] if self.connection.protocol_revision == "0.3" else 12)
                  if self._default_event_config and self.connection is not None else None)
        if not self.controller.preview(**({"event_config": config} if config is not None else {})):
            return False
        if not previous.ready:
            self._fence_new_source(previous.revision)
        return True

    def set_search_config(self, config):
        """Only the next START may use this draft; running owners are immutable."""
        status = self.state
        if (self._closing or self._disconnecting or self.metadata_pending or
                status.command_pending or status.stop_pending or status.close_requested or
                not (status.can_preview or (self.is_device and status.can_open))):
            return False
        if self.is_device:
            if self.connection is None:
                return False
            caps = self.connection.observed_caps
            fs, bits = caps[4], caps[8] if self.connection.protocol_revision == '0.3' else 12
        else:
            fs, bits = 50_000, 12
        validate_config(config, fs, bits)
        self.search_config = config
        self._search_basis = (fs, bits)
        self.search_reset_notice = ""
        return True

    def connect_source(self, selection=None):
        """Queue selected COM open then HELLO/CAPS, with no START fallback."""
        if (not self.is_device or self._closed or self._closing or self._disconnecting or
                self.metadata_pending or self._connect_pending or
                (selection is not None and selection != self.selection)):
            return False
        previous = self.controller.snapshot()
        if not self.controller.connect():
            return False
        self.connection = None
        self._last_error = None
        self._connect_pending = True
        self._fence_new_source(previous.revision)
        return True

    def select_sample_rate(self, rate):
        if not self.is_device or self._connect_pending or self._disconnecting or self._closing:
            return False
        selection = replace(self.selection, requested_sample_rate_hz=rate)
        if not self.controller.select_sample_rate(rate):
            return False
        if rate != self.selection.requested_sample_rate_hz and self.search_config is not None:
            self.search_config = None
            self.search_reset_notice = "Частота изменена: параметры поиска сброшены. Настройте их после подключения."
        self._selection = selection
        return True

    def disconnect_source(self):
        """Graceful Stop first; keep all owners until close is confirmed."""
        if not self.is_device or self._closed or self._disconnecting:
            return False
        self._connect_pending = False
        self._disconnecting = True
        self.controller.stop()
        self._poll()
        return True

    def retry_close(self):
        return self.is_device and self.controller.retry_close()

    def record(self, path):
        if self._closing or self._disconnecting or self.metadata_pending:
            return False
        if type(self.context) is not StreamContext:
            raise ValueError("Требуется неизменяемый контекст V2")
        self.context.__post_init__()
        path = str(path)
        previous = self.controller.snapshot()
        if self.is_device and (previous.phase != "preview" or self.connection is None):
            return False
        if not self.controller.record(path, **({"event_config": self.search_config}
                if previous.can_preview and self.search_config is not None else {})):
            return False
        # can_preview marks a restartable source. Recording an already running
        # preview keeps its generation and display; a direct start replaces it.
        if previous.can_preview:
            self._fence_new_source(previous.revision)
        self._record_path = path
        self._record_context = self.context
        self._record_connection = self.connection
        self._record_search = None
        self._metadata_started = False
        self._metadata = None
        return True

    def stop(self):
        self._connect_pending = False
        return not self._closed and self.controller.stop()

    def shutdown(self):
        if self._closed or self._closing:
            return False
        self._closing = True
        self._connect_pending = False
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
        if self._connect_pending:
            if status.error or (status.serial and status.serial.first_error):
                self._connect_pending = False
            elif status.can_prepare:
                if self.controller.prepare():
                    self._connect_pending = False
                status = self.controller.snapshot()
        bridge = status.bridge
        if status.ready and self.is_device and self.connection is None:
            self.connection = StreamConnection(self.selection, self._execution_kind,
                                               bridge.accepted_build_id, bridge.accepted_caps,
                                               protocol_revision="0.3" if len(bridge.accepted_caps) == 10 else "0.2")
            basis = (self.connection.observed_caps[4], self.connection.observed_caps[8]
                     if self.connection.protocol_revision == '0.3' else 12)
            if self.search_config is not None and self._search_basis != basis:
                self.search_config = None
                self.search_reset_notice = "Режим АЦП изменён: параметры поиска сброшены для новой частоты и разрядности."
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
        if not message and self.is_device and bridge and bridge.endpoint_first_fault:
            code = bridge.endpoint_first_fault.code
            message = (f"Проверка потока отклонена: {code}. START не разрешён."
                       if bridge.session is None else f"Приём остановлен: {code}. Сохранён проверенный префикс.")
            if code.startswith("selected_rate_mismatch_fixed_"):
                rate = code.removeprefix("selected_rate_mismatch_fixed_")
                message = (f"Эта прошивка имеет фиксированную частоту {rate} отсчётов/с. "
                           "Приём не запущен. После завершения соединения "
                           "выберите эту частоту и переподключитесь на той же странице.")
            elif code == "batch1024_firmware_required":
                message = ("Для 150000 отсчётов/с нужна прошивка с пакетами по 1024 отсчёта. "
                           "Подключённая прошивка этот режим не поддерживает; приём не запущен. "
                           "Можно выбрать 50000 или 100000 и переподключиться, "
                           "либо обновить прошивку после проверки совместимости.")
        if message:
            self._report_error(message)
        if self._record_path is not None and not self._metadata_started and status.can_open:
            self._metadata_started = True
            self._metadata_identity = None if bridge is None else bridge.identity
            # Finalization still owns this attempt. Its accepted controller
            # snapshot, not a later editor draft, accompanies the raw journal.
            self._record_search = SearchSnapshot(status.config, status.config_revision)
            self._executor = self._executor or ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="v2-stream-context")
            self._metadata = self._executor.submit(
                _write_context, self._record_path, self._record_context,
                self._metadata_identity, self._record_connection, self._record_search)
        if self._metadata is not None and self._metadata.done():
            future, self._metadata = self._metadata, None
            try:
                path = future.result()
            except Exception as exc:
                self._metadata_error = ContextFailure(
                    self._record_path, self._record_context, self._metadata_identity,
                    "Контекст потока не сохранён: " + str(exc), self._record_connection,
                    self._record_search)
                self._report_error(str(self._metadata_error))
            else:
                self.recording_ready.emit(path)
        self.state_changed.emit(status)
        if self._disconnecting and status.can_open and not self.metadata_pending:
            self.controller.disconnect()
        if (self._disconnecting and status.serial and status.serial.handle_settled and
                not status.serial_unresolved and not status.command_pending and
                status.phase == "disconnected"):
            self._disconnecting = False
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
