"""Bounded one-event raw capture; no acquisition commands or invented STOP."""
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import struct

from ..recording import atomic_write, _object, _invalid_number
from ..stream_model import StreamIdentity, StreamBlock, uint
from ..stream_view import EventConfig, EventEntry, DETECTOR_VERSION
from .input import InputProfile
from .stream_device import StreamContext
from .stream_search import validate_config

MAX_SAMPLES = 65536
MAX_METADATA = 65536
HEADER = struct.Struct('<8sII')
MAGIC = b'MTSHOT1\0'
MAX_FILE = HEADER.size + MAX_METADATA + 2 * MAX_SAMPLES + 32


@dataclass(frozen=True, slots=True)
class StreamCapture:
    identity: StreamIdentity
    context: StreamContext
    config: EventConfig
    config_revision: int
    source_revision: int
    source_first: int
    arm_end_index: int
    event: EventEntry
    raw_u16le: bytes
    completion: str
    source_flags: tuple[str, ...]
    loss_samples: int | None
    tail_state: str
    created_at_utc: str
    algorithm_version: str = DETECTOR_VERSION

    def __post_init__(self):
        for value, cls in ((self.identity, StreamIdentity), (self.context, StreamContext),
                           (self.config, EventConfig), (self.event, EventEntry)):
            if type(value) is not cls:
                raise ValueError('Некорректный тип данных захвата')
        self.identity.__post_init__(); self.context.__post_init__(); self.config.__post_init__()
        validate_config(self.config, self.identity.nominal_fs_hz, self.identity.retained_bits)
        for value in (self.config_revision, self.source_revision, self.source_first, self.arm_end_index,
                      self.event.ordinal, self.event.start_index, self.event.end_index,
                      self.event.trigger_index, self.event.baseline_start, self.event.baseline_end):
            uint(value)
        e = self.event
        if not (self.source_first <= e.start_index <= e.baseline_start <= e.baseline_end == e.trigger_index
                < e.end_index and self.source_first <= self.arm_end_index <= e.trigger_index):
            raise ValueError('Несогласованные исходные границы захвата')
        if e.settled_index is not None:
            uint(e.settled_index)
            if not e.trigger_index < e.settled_index <= e.end_index:
                raise ValueError('Некорректная граница возврата')
        count = e.end_index - e.start_index
        if (not 1 <= count <= min(MAX_SAMPLES, self.config.max_event_samples) or
                type(self.raw_u16le) is not bytes or len(self.raw_u16le) != 2 * count):
            raise ValueError('Raw не соответствует ограниченному контексту события')
        for flag_set in (self.source_flags, e.flags):
            if (type(flag_set) is not tuple or len(flag_set) > 32 or
                    any(type(f) is not str or not 1 <= len(f) <= 128 for f in flag_set)):
                raise ValueError('Некорректные флаги захвата')
        if 'pending' in e.flags or self.completion not in ('event_closed', 'interrupted'):
            raise ValueError('Незавершённый контекст нельзя выдать за готовый захват')
        if self.completion == 'interrupted' and 'right_truncated' not in e.flags:
            raise ValueError('Оборванный захват должен быть помечен неполным')
        if self.tail_state not in ('running', 'unknown', 'reported_stopped'):
            raise ValueError('Неизвестное состояние потока')
        if self.loss_samples is not None:
            uint(self.loss_samples)
        if self.algorithm_version != DETECTOR_VERSION:
            raise ValueError('Неизвестный алгоритм поиска захвата')
        stamp = datetime.fromisoformat(self.created_at_utc)
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError('Нужна дата UTC')
        step = 4 if self.identity.retained_bits == 10 else 1
        if any(code > 4095 or code % step for (code,) in struct.iter_unpack('<H', self.raw_u16le)):
            raise ValueError('Коды не соответствуют ADC12/сохранённой разрядности')
        offset = e.trigger_index - e.start_index
        if offset < 1:
            raise ValueError('В захвате нет отсчёта перед порогом')
        before, current = struct.unpack_from('<HH', self.raw_u16le, 2 * (offset - 1))
        if self.config.high(before) or not self.config.high(current):
            raise ValueError('Raw не подтверждает пересечение порога')

    @property
    def first_sample_index(self):
        return self.event.start_index

    @property
    def raw_available_start(self):
        return self.first_sample_index

    @property
    def end_sample_index(self):
        return self.event.end_index

    def iter_raw(self, start_sample_index, end_sample_index, chunk_samples=8192):
        if not self.first_sample_index <= start_sample_index < end_sample_index <= self.end_sample_index:
            raise ValueError('Диапазон вне захваченных отсчётов')
        uint(chunk_samples, MAX_SAMPLES, minimum=1)
        for at in range(start_sample_index, end_sample_index, chunk_samples):
            stop = min(at + chunk_samples, end_sample_index)
            lo, hi = at - self.first_sample_index, stop - self.first_sample_index
            yield StreamBlock(self.identity, at, self.raw_u16le[2 * lo:2 * hi])


class CaptureAttempt:
    """First indexed event at/after the latest published receiver boundary.

    The status boundary is nominal source time on the host, not a hardware
    timestamp of the click. A pending event that started before arm is skipped.
    Metadata/raw eviction is a failed attempt, never a request for a later event.
    """
    def __init__(self, status, context):
        ds = status.detector_status
        if (status.phase not in ('preview', 'recording') or status.stop_pending or
                status.close_requested or ds is None or ds.outcome != 'running' or
                ds.processed_until is None or status.bridge is None or status.bridge.identity is None):
            raise ValueError('Запустите живой поток и дождитесь исходных отсчётов')
        self.identity, self.revision = status.bridge.identity, status.revision
        self.config, self.config_revision = status.config, status.config_revision
        self.boundary = ds.processed_until
        self.ordinal = ds.next_ordinal + (1 if ds.pending is not None else 0)
        self.context = context
        self.partial = None
        self.message = 'Ожидание следующего события · приём и запись продолжаются'
        self.done = False

    def consume(self, source):
        if self.done:
            return None
        if (source.revision != self.revision or source.identity != self.identity or
                source.config_revision != self.config_revision or source.config != self.config):
            self.done = True
            self.message = 'Ожидание отменено: изменился источник или поиск'
            return None
        ds = source.detector
        if ds.processed_until is None or ds.processed_until <= self.boundary:
            return None  # Delayed display copied before arm.
        if ds.first_retained_ordinal > self.ordinal:
            return self.fail('Первое событие вытеснено из индекса; захват не подменён следующим')
        entries = source.events + ((ds.pending,) if ds.pending else ())
        event = next((e for e in entries if e.ordinal == self.ordinal), None)
        if event is not None:
            if event.trigger_index < self.boundary:
                return self.fail('Граница события не соответствует команде захвата')
            if not source.raw_first <= event.start_index < event.end_index <= source.end:
                return self.fail('Исходные отсчёты первого события вышли из буфера')
            offset = event.trigger_index - source.raw_first
            if offset < 1:
                return self.fail('Нет отсчёта перед порогом; фронт не подтверждён')
            before, current = struct.unpack_from('<HH', source.raw, (offset - 1) * 2)
            if self.config.high(before) or not self.config.high(current):
                return self.fail('Пересечение порога не подтверждено исходными отсчётами')
            pending = 'pending' in event.flags
            flags = tuple(f for f in event.flags if f != 'pending')
            if pending:
                flags = tuple(sorted(set(flags) | {'right_truncated', 'capture_in_progress'}))
            e = replace(event, flags=flags)
            lo, hi = e.start_index - source.raw_first, e.end_index - source.raw_first
            shot = StreamCapture(source.identity, self.context, self.config, self.config_revision,
                source.revision, source.first, self.boundary, e, source.raw[2 * lo:2 * hi],
                'interrupted' if pending else 'event_closed', source.flags, source.loss_samples,
                source.tail_state, datetime.now(timezone.utc).isoformat())
            if pending:
                self.partial = shot
                self.message = 'Событие найдено · накапливается контекст'
            else:
                self.done = True
                return shot
        if ds.outcome != 'running':
            return self.finish('source_ended')
        return None

    def fail(self, message):
        self.done = True
        self.message = message
        if self.partial is None:
            return None
        return self.finish('capture_context_unavailable')

    def finish(self, reason):
        self.done = True
        self.message = 'Захват завершён без события: поток остановлен'
        if self.partial is None:
            return None
        e = self.partial.event
        flags = tuple(sorted((set(e.flags) - {'capture_in_progress'}) | {reason, 'right_truncated'}))
        return replace(self.partial, event=replace(e, flags=flags), completion='interrupted',
                       tail_state='unknown')


def encode_capture(shot):
    shot.__post_init__()
    meta = asdict(shot)
    del meta['raw_u16le']
    meta.update(format_version=1, time_basis='nominal_unverified',
                arm_basis='latest_published_receiver_end_on_host')
    data = json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')
    if len(data) > MAX_METADATA:
        raise ValueError('Метаданные захвата превышают предел')
    payload = HEADER.pack(MAGIC, len(data), len(shot.raw_u16le) // 2) + data + shot.raw_u16le
    return payload + hashlib.sha256(payload).digest()


def save_capture(path, shot):
    atomic_write(path, encode_capture(shot))
    return str(path)


def load_capture(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_FILE + 1)
    if not HEADER.size + 32 <= len(data) <= MAX_FILE:
        raise ValueError('Некорректный размер файла захвата')
    magic, meta_size, count = HEADER.unpack_from(data)
    if (magic != MAGIC or not 1 <= meta_size <= MAX_METADATA or not 1 <= count <= MAX_SAMPLES or
            len(data) != HEADER.size + meta_size + count * 2 + 32):
        raise ValueError('Неизвестный или обрезанный файл захвата')
    if not hmac.compare_digest(hashlib.sha256(data[:-32]).digest(), data[-32:]):
        raise ValueError('Нарушена целостность захвата (SHA-256)')
    meta = json.loads(data[HEADER.size:HEADER.size + meta_size].decode('utf-8'),
                      object_pairs_hook=_object, parse_constant=_invalid_number)
    expected = {f.name for f in fields(StreamCapture)} - {'raw_u16le'}
    if type(meta) is not dict or set(meta) != expected | {'format_version', 'time_basis', 'arm_basis'}:
        raise ValueError('Неизвестные или отсутствующие поля захвата')
    version = meta.pop('format_version')
    if (type(version) is not int or version != 1 or
            meta.pop('time_basis') != 'nominal_unverified' or
            meta.pop('arm_basis') != 'latest_published_receiver_end_on_host'):
        raise ValueError('Неизвестная версия или временная основа захвата')
    for name, cls in (('identity', StreamIdentity), ('context', StreamContext),
                      ('config', EventConfig), ('event', EventEntry)):
        if type(meta[name]) is not dict or set(meta[name]) != {f.name for f in fields(cls)}:
            raise ValueError('Неполные или неизвестные поля: ' + name)
    profile = meta['context']['input_profile']
    if type(profile) is not dict or set(profile) != {f.name for f in fields(InputProfile)}:
        raise ValueError('Некорректные поля профиля входа')
    if type(meta['source_flags']) is not list or type(meta['event']['flags']) is not list:
        raise ValueError('Флаги должны быть массивом')
    meta['identity'] = StreamIdentity(**meta['identity'])
    context = meta['context']
    context['input_profile'] = InputProfile(**context['input_profile'])
    meta['context'] = StreamContext(**context)
    meta['config'] = EventConfig(**meta['config'])
    meta['event']['flags'] = tuple(meta['event']['flags'])
    meta['event'] = EventEntry(**meta['event'])
    meta['source_flags'] = tuple(meta['source_flags'])
    return StreamCapture(raw_u16le=data[HEADER.size + meta_size:-32], **meta)
