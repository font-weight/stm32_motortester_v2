"""Read-only, bounded calibration windows from an already running stream.

The controller's mutable ring is owned by its receiver. This adapter uses only
its existing immutable raw display copies, never the plotted envelope. It owns
no serial port and issues no acquisition, stop, or profile-change commands.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import struct
import time

from ..stream_controller import RECENT_SAMPLES
from ..stream_model import StreamIdentity
from .analog_profile import RawFormat
from .calibration import CalibrationPlan, MAX_SAMPLES, SampleWindow
from .stream_device import StreamConnection, StreamContext


@dataclass(frozen=True, slots=True)
class LiveCalibrationContext:
    mode_id: str
    hardware_instance_id: str
    raw_format: RawFormat
    origin: str
    source_id: str
    session_id: str
    generation: int
    source_revision: int
    received_end_index: int


@dataclass(frozen=True, slots=True)
class _Current:
    bridge: object
    context: StreamContext
    connection: StreamConnection | None
    identity: StreamIdentity
    metadata: LiveCalibrationContext

    @property
    def key(self):
        m = self.metadata
        return (self.bridge, self.context, self.connection, self.identity,
                m.source_revision, m.mode_id, m.hardware_instance_id, m.raw_format,
                m.origin, m.source_id)


@dataclass(frozen=True, slots=True)
class _Tail:
    identity: StreamIdentity
    revision: int
    first: int
    end: int
    raw: bytes
    loss_samples: int | None
    tail_state: str
    flags: tuple
    continuous: bool


@dataclass(frozen=True, slots=True)
class _Attempt:
    current: _Current
    plan: CalibrationPlan
    first: int
    count: int
    deadline: float


def _running_detector(detector):
    return (detector is not None and detector.outcome == 'running'
            and detector.discontinuity is None)


class LiveCalibrationProvider:
    """GUI-thread adapter; current() returns (current bridge, active context).

    begin records the received source boundary, which can be ahead of the
    screen. poll yields exactly one new interval, or None while waiting, and
    raises ValueError on failure. A returned window still needs the user's
    explicit steady-state confirmation. close only removes our subscriptions.
    """
    def __init__(self, current, *, clock=time.monotonic, timeout_s=5.0):
        if not callable(current) or not callable(clock):
            raise ValueError('Нужен текущий источник и монотонные часы')
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not math.isfinite(timeout_s) or timeout_s <= 0):
            raise ValueError('Нужен положительный срок ожидания участка')
        self._current = current
        self._clock = clock
        self._timeout = float(timeout_s)
        self._bridge = self._slot = None
        self._tail = self._tail_error = self._attempt = None
        self._closed = False

    @property
    def active(self):
        return self._attempt is not None

    def _detach(self):
        if self._bridge is not None and self._slot is not None:
            try:
                self._bridge.live_ready.disconnect(self._slot)
            except (RuntimeError, TypeError):
                pass  # The GUI may already have deleted the settled old owner.
        self._bridge = self._slot = None
        self._tail = self._tail_error = None

    def _attach(self, bridge):
        if bridge is self._bridge:
            return
        self._detach()
        self._bridge = bridge
        self._slot = lambda result, owner=bridge: self._receive(owner, result)
        bridge.live_ready.connect(self._slot)

    def _receive(self, owner, result):
        if self._closed or owner is not self._bridge:
            return
        try:
            source = result.source
            if (type(source.identity) is not StreamIdentity or type(source.raw) is not bytes
                    or type(source.raw_first) is not int or type(source.end) is not int
                    or type(source.revision) is not int or type(source.flags) is not tuple
                    or not 0 <= source.raw_first <= source.end < 2**63
                    or not 0 < source.end - source.raw_first <= RECENT_SAMPLES
                    or len(source.raw) != 2 * (source.end - source.raw_first)):
                raise ValueError('Повреждён исходный буфер калибровки')
            tail = _Tail(source.identity, source.revision, source.raw_first, source.end,
                         source.raw, source.loss_samples, source.tail_state, source.flags,
                         _running_detector(source.detector))
            if (self._tail is not None and tail.identity == self._tail.identity
                    and tail.revision == self._tail.revision and tail.end < self._tail.end):
                return  # A queued, older display copy cannot move the boundary back.
            self._tail = tail
        except (AttributeError, TypeError, ValueError) as exc:
            # Errors crossing a Qt signal are reported by poll, not raised in
            # the event loop where they could leave the wizard waiting forever.
            self._tail_error = str(exc)

    def _read(self):
        if self._closed:
            raise ValueError('Сбор калибровочных данных закрыт')
        selected = self._current()
        if not isinstance(selected, tuple) or len(selected) != 2 or selected[0] is None:
            self._detach()
            raise ValueError('Нет текущего живого источника калибровки')
        bridge, context = selected
        self._attach(bridge)
        if type(context) is not StreamContext:
            raise ValueError('Неизвестен контекст аналогового входа')
        context.__post_init__()
        snapshot = context.analog_snapshot
        if snapshot is None or not snapshot.hardware_instance_id:
            raise ValueError('Подтвердите режим и экземпляр аналогового входа перед калибровкой')
        status = bridge.controller.snapshot()
        source = status.bridge
        session = None if source is None else source.session
        if (status.phase not in ('preview', 'recording') or status.command_pending
                or status.stop_pending or status.stop_requested or status.close_requested
                or status.can_retry_close or status.error or status.display_error
                or getattr(bridge, 'metadata_error', None) is not None
                or source is None or source.closed or source.endpoint_first_fault
                or source.late_fault or source.source_terminal is not None
                or session is None or not session.source_started or session.first_failure
                or session.source_end is not None or session.stop_requested
                or session.admission_fenced or session.writer_fenced
                or not _running_detector(status.detector_status)):
            raise ValueError('Нужен работающий живой поток без остановки, ошибок и пропусков')
        identity = source.identity
        if type(identity) is not StreamIdentity:
            raise ValueError('Неизвестен исходный сеанс АЦП')
        identity.__post_init__()
        raw_format = RawFormat.from_identity(identity)
        context.validate_identity(identity)
        connection = bridge.connection
        origin = identity.origin
        if connection is not None:
            if type(connection) is not StreamConnection:
                raise ValueError('Неизвестны согласованные параметры соединения')
            connection.__post_init__()
            if RawFormat.from_connection(connection) != raw_format:
                raise ValueError('Формат сеанса не соответствует согласованному АЦП')
            if connection.execution_kind == 'injected-test':
                origin = 'synthetic'
        if origin == 'device':
            serial = status.serial
            if (connection is None or connection.execution_kind != 'physical'
                    or not bridge.is_device or serial is None or serial.state != 'open'
                    or serial.handle_settled or serial.first_error or serial.close_error):
                raise ValueError('Физическое соединение STM32 не подтверждено')
        elif connection is not None and connection.execution_kind == 'physical':
            raise ValueError('Искусственные данные не являются физическим измерением')
        indices = (source.source_received_end, status.raw_available_start, status.ring_samples)
        if any(type(value) is not int or not 0 <= value < 2**63 for value in indices):
            raise ValueError('Неизвестна граница полученных исходных отсчётов')
        received = max(indices[0], indices[1] + indices[2])
        if received >= 2**63:
            raise ValueError('Граница исходных отсчётов вне допустимого диапазона')
        # The identity includes the stable session UUID and source generation.
        # Neither the filename, wizard instance nor point number changes it.
        fingerprint = {'identity': asdict(identity),
                       'connection': None if connection is None else asdict(connection)}
        source_id = 'live:' + hashlib.sha256(json.dumps(fingerprint, sort_keys=True,
            ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        metadata = LiveCalibrationContext(snapshot.mode_id, snapshot.hardware_instance_id,
            raw_format, origin, source_id, identity.session_id, identity.generation,
            status.revision, received)
        return _Current(bridge, context, connection, identity, metadata)

    def context(self):
        """Validated running-source metadata, with no acquisition side effects."""
        return self._read().metadata

    def begin(self, plan, count):
        if self.active:
            raise ValueError('Предыдущий участок ещё собирается; дождитесь его или отмените')
        if type(plan) is not CalibrationPlan:
            raise ValueError('Нужен заранее заданный план калибровки')
        plan.__post_init__()
        if type(count) is not int or not 128 <= count <= MAX_SAMPLES:
            raise ValueError('Для калибровки выберите 128…16384 отсчёта')
        first = self._read()
        if any(getattr(plan, name) != getattr(first.metadata, name) for name in
               ('mode_id', 'hardware_instance_id', 'raw_format', 'origin')):
            raise ValueError('План не соответствует живому входу, формату или происхождению')
        second = self._read()
        if first.key != second.key:
            raise ValueError('Источник изменился во время команды сбора')
        boundary = max(first.metadata.received_end_index, second.metadata.received_end_index)
        if (self._tail is not None and self._tail.identity == second.identity
                and self._tail.revision == second.metadata.source_revision):
            boundary = max(boundary, self._tail.end)
        if boundary + count >= 2**63:
            raise ValueError('Участок выходит за допустимый диапазон исходных индексов')
        self._attempt = _Attempt(second, plan, boundary, count, self._clock() + self._timeout)

    def poll(self):
        attempt = self._attempt
        if attempt is None:
            return None
        try:
            current = self._read()
            if current.key != attempt.current.key:
                raise ValueError('Сбор отменён: изменился источник, режим или экземпляр платы')
            if self._clock() >= attempt.deadline:
                raise ValueError('Новые исходные отсчёты не поступили вовремя; повторите сбор')
            if self._tail_error:
                raise ValueError(self._tail_error)
            tail = self._tail
            if tail is None:
                return None
            if tail.identity != current.identity or tail.revision != current.metadata.source_revision:
                raise ValueError('Буфер относится к другому сеансу АЦП')
            if tail.loss_samples not in (None, 0) or tail.tail_state != 'running' or tail.flags or not tail.continuous:
                raise ValueError('Исходный участок содержит пропуск, ошибку или остановку')
            if tail.first > attempt.first:
                raise ValueError('Новые отсчёты вышли из буфера; участок не заменён более поздним')
            end = attempt.first + attempt.count
            if tail.end < end:
                return None
            offset = (attempt.first - tail.first) * 2
            raw = tail.raw[offset:offset + 2 * attempt.count]
            codes = tuple(code for (code,) in struct.iter_unpack('<H', raw))
            after = self._read()
            if after.key != current.key or after.metadata.received_end_index < end:
                raise ValueError('Источник изменился во время чтения участка')
            result = SampleWindow(codes, current.metadata.source_id, current.metadata.raw_format,
                current.metadata.mode_id, current.metadata.hardware_instance_id,
                current.metadata.origin, attempt.first, has_gaps=False, settled_confirmed=False)
            self._attempt = None
            return result
        except Exception:
            self.cancel()
            raise

    def cancel(self):
        self._attempt = None
        self._detach()

    def close(self):
        self.cancel()
        self._closed = True
