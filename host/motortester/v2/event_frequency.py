"""Recent threshold-event cadence from source sample indices, without raw I/O.

This estimates detected event intervals, not waveform frequency, spark burning
time, RPM or a cylinder. The caller owns source/config resets and a wall-clock
stall guard; this pure model also expires old events as source samples advance.
"""
from dataclasses import dataclass
from itertools import islice
import math
from numbers import Real
from statistics import median

from ..stream_view import DetectorStatus, EventEntry


MAX_INTERVALS = 8
MIN_INTERVALS = 2
MAX_INTERVAL_DEVIATION = .20
STALE_MIN_SECONDS = 1.0
STALE_PERIODS = 3
_RAIL_FLAGS = frozenset(('clipping', 'quantization_edge_bin'))
_ALLOWED_FLAGS = _RAIL_FLAGS | {'pending', 'baseline_unsettled'}
_MAX_INDEX = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class EventFrequency:
    frequency_hz: float | None
    period_s: float | None
    reason: str | None
    interval_count: int
    warning: str | None


def _unavailable(reason, count=0, warning=None):
    return EventFrequency(None, None, reason, count, warning)


def _uint(value):
    return type(value) is int and 0 <= value <= _MAX_INDEX


def _valid_event(event, processed_until):
    if type(event) is not EventEntry:
        return False
    fields = (event.ordinal, event.trigger_index, event.start_index, event.end_index,
              event.baseline_start, event.baseline_end)
    return (all(_uint(value) for value in fields)
            and event.start_index <= event.baseline_start <= event.baseline_end == event.trigger_index
            < event.end_index <= processed_until
            and (event.settled_index is None or _uint(event.settled_index)
                 and event.trigger_index < event.settled_index <= event.end_index)
            and type(event.flags) is tuple and len(event.flags) <= 32
            and all(type(flag) is str and 1 <= len(flag) <= 128 for flag in event.flags))


def estimate_event_frequency(events, status, fs_hz):
    """Use the last <=9 consecutive events, including a clean pending trigger.

    events is the detector's closed-event sequence (tuple/list/deque); pending
    is included from status automatically. Only nine entries are inspected,
    so neither long recordings nor growing event indices increase this work.
    Bad entries inside the selected history are never filtered out or bridged.
    """
    if (isinstance(fs_hz, bool) or not isinstance(fs_hz, Real)
            or not math.isfinite(fs_hz) or fs_hz <= 0):
        return _unavailable('Неизвестна частота дискретизации.')
    if type(status) is not DetectorStatus:
        return _unavailable('Ожидание индекса событий.')
    if status.discontinuity is not None:
        return _unavailable('Разрыв данных: частота событий недоступна.')
    if status.outcome != 'running':
        return _unavailable('Приём остановлен.' if status.outcome == 'stopped' else
                            'Индекс событий остановлен с ошибкой или ограничением.')
    if status.processed_until is None:
        return _unavailable('Ожидание исходных отсчётов.')
    if (not _uint(status.processed_until) or not _uint(status.next_ordinal)
            or not _uint(status.suppressed_crossings)):
        return _unavailable('Некорректные границы индекса событий.')
    try:
        recent = list(reversed(tuple(islice(reversed(events), MAX_INTERVALS + 1))))
    except (TypeError, ValueError):
        return _unavailable('Недоступна ограниченная история событий.')
    pending = status.pending
    if pending is not None:
        if recent and recent[-1] == pending:
            pass  # Tolerate a caller already including the exact same entry.
        else:
            recent.append(pending)
        recent = recent[-(MAX_INTERVALS + 1):]
    if not recent:
        return _unavailable('Ожидание событий: нужны не менее 3.')
    if any(not _valid_event(event, status.processed_until) for event in recent):
        return _unavailable('Некорректные границы пороговых событий.')
    expected_last = status.next_ordinal if pending is not None else status.next_ordinal-1
    if recent[-1].ordinal != expected_last:
        return _unavailable('Последняя часть индекса событий недоступна.')
    for before, after in zip(recent[:-1], recent[1:]):
        if after.ordinal != before.ordinal+1 or after.trigger_index <= before.trigger_index:
            return _unavailable('В истории событий есть пропуск или наложение.')
    if any(set(event.flags) - _ALLOWED_FLAGS for event in recent):
        return _unavailable('События объединены или имеют неполный контекст.')
    if any('pending' in event.flags and event is not pending and event != pending for event in recent):
        return _unavailable('Незавершённое событие внутри истории.')
    warnings = []
    if any(_RAIL_FLAGS.intersection(event.flags) for event in recent):
        warnings.append('Есть крайние коды АЦП; оценена только частота пороговых событий.')
    # The baseline qualifier concerns waveform context, not the known trigger
    # index. A gradual sine crosses the hysteresis band before threshold and
    # naturally has this flag even when every threshold interval is regular.
    if any('baseline_unsettled' in event.flags for event in recent):
        warnings.append('Базовый уровень перед частью событий не установился.')
    if status.suppressed_crossings:
        warnings.append('Часть пересечений подавлена паузой запуска.')
    warning = ' '.join(warnings) or None
    count = len(recent)-1
    if count < MIN_INTERVALS:
        return _unavailable('Ожидание событий: нужны не менее 3.', count, warning)
    # Subtract integer sample indices before floating conversion, including
    # indices >2**53. GUI repaint rate and viewport movement never enter here.
    intervals = tuple(after.trigger_index-before.trigger_index
                      for before, after in zip(recent[:-1], recent[1:]))
    typical = median(intervals)
    if max(abs(value-typical) for value in intervals) > MAX_INTERVAL_DEVIATION * typical:
        return _unavailable('Интервалы событий нерегулярны.', count, warning)
    age = status.processed_until-recent[-1].trigger_index
    if age > max(float(fs_hz) * STALE_MIN_SECONDS, STALE_PERIODS * typical):
        return _unavailable('Новых событий давно нет.', count, warning)
    period = typical / float(fs_hz)
    if not math.isfinite(period) or period <= 0 or not math.isfinite(1/period):
        return _unavailable('Недопустимая временная основа.', count, warning)
    return EventFrequency(1/period, period, None, count, warning)


def format_event_frequency(result):
    """Compact Russian label; warnings remain explicit, including clipped data."""
    if result.frequency_hz is None or result.period_s is None:
        text = 'Частота событий: — · ' + (result.reason or 'Ожидание событий.')
    else:
        period = result.period_s
        factor, unit = ((1e6, 'мкс') if period < .001 else
                        (1e3, 'мс') if period < 1 else (1, 'с'))
        frequency = f'{result.frequency_hz:.5g}'.replace('.', ',')
        interval = f'{period*factor:.5g}'.replace('.', ',')
        text = f'Частота событий: ≈{frequency} Гц · интервал ≈{interval} {unit}'
    return text + (' · ' + result.warning if result.warning else '')
