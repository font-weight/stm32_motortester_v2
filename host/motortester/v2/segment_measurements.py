"""Bounded descriptive measurements of original ADC12 coordinates, without Qt.

Period is a conservative repeatability estimate, not a hardware accuracy claim.
It requires three complete Schmitt-trigger cycles, >=10 samples per cycle,
duration agreement within 6%, and similar raw waveforms. Voltage conversion,
including whether a DC mean is meaningful, belongs to the caller's input profile.
"""
from dataclasses import dataclass
from itertools import islice
import math
from numbers import Integral, Real
import struct

import numpy as np

from ..stream_view import _block, _reader


MAX_MEASUREMENT_SAMPLES = 262144
MIN_FULL_PERIODS = 3
MIN_PERIOD_SAMPLES = 10
MIN_DYNAMIC_STEPS = 16
MAX_PERIOD_DEVIATION = .06
MAX_SHAPE_RMS = .12
MAX_CYCLE_RANGE_SPREAD = .15
MAX_CYCLE_MEAN_SPREAD = .08
MAX_CYCLE_STD_SPREAD = .10
PHASE_POINTS = 64


@dataclass(frozen=True, slots=True)
class SegmentMeasurements:
    count: int
    min_code: int | None
    max_code: int | None
    mean_code: float | None
    period_s: float | None
    frequency_hz: float | None
    period_reason: str | None
    data_reason: str | None
    clipped: bool


def _unavailable(count, reason):
    return SegmentMeasurements(count, None, None, None, None, None, reason, reason, False)


def _period(values, span, sample_rate_hz):
    """Schmitt crossings plus duration and full-cycle raw-shape checks.

    Thresholds are relative to the raw range. They are unaffected by a constant
    offset or voltage gain; inversion selects the other edge of the same cycle.
    Resampling is solely an internal comparison, never the plotted envelope or
    the input to the raw mean. Extra per-cycle raw statistics retain narrow
    features which the phase grid alone could miss.
    """
    low = float(values.min()) + .35 * span
    high = float(values.min()) + .65 * span
    armed = bool(values[0] <= low)
    crossings = []
    for index in range(1, len(values)):
        value = values[index]
        if value <= low:
            armed = True
        elif armed and value >= high:
            before = values[index - 1]
            crossing = index - 1 + (high - before) / (value - before)
            crossings.append(float(crossing))
            armed = False
    if len(crossings) < MIN_FULL_PERIODS + 1:
        return None, 'Недостаточно повторений: нужны не менее 3 полных периодов.'
    intervals = np.diff(crossings)
    period = float(np.median(intervals))
    if float(intervals.min()) < MIN_PERIOD_SAMPLES:
        return None, 'Слишком мало отсчётов на период: требуется не менее 10.'
    if float(np.max(np.abs(intervals - period))) > MAX_PERIOD_DEVIATION * period:
        return None, 'Длительности циклов различаются; устойчивая периодичность не подтверждена.'
    axis = np.arange(len(values), dtype=float)
    phases = np.arange(PHASE_POINTS, dtype=float) / PHASE_POINTS
    reference = reference_stats = None
    for left, right in zip(crossings[:-1], crossings[1:]):
        # All comparisons cover complete cycles only. At least10 raw samples
        # and the full span remain available even for a narrow single impulse.
        raw = values[math.ceil(left):math.ceil(right)]
        stats = (float(raw.max() - raw.min()), float(raw.mean()), float(raw.std()))
        cycle = np.interp(left + phases * (right-left), axis, values)
        if reference is None:
            reference, reference_stats = cycle, stats
            continue
        mismatch = float(np.sqrt(np.mean(((cycle-reference) / span) ** 2)))
        spreads = (MAX_CYCLE_RANGE_SPREAD, MAX_CYCLE_MEAN_SPREAD, MAX_CYCLE_STD_SPREAD)
        if mismatch > MAX_SHAPE_RMS or any(abs(a-b) > tolerance * span
                for a, b, tolerance in zip(stats, reference_stats, spreads)):
            return None, 'Форма или амплитуда циклов меняется; периодичность не подтверждена.'
    seconds = period / sample_rate_hz
    if not math.isfinite(seconds) or seconds <= 0:
        return None, 'Временная основа не позволяет выразить период числом.'
    return seconds, None


def analyze_samples(codes, sample_rate_hz, *, code_step=1, has_gap=False):
    """Analyze a complete selected interval; never truncate it to fit the limit.

    Codes may be any finite iterable of integer canonical ADC12 values. For
    retained10 input they already have step4; no rescaling takes place here.
    Missing data invalidate the whole interval's mean/min/max, not just period.
    """
    if type(has_gap) is not bool:
        return _unavailable(0, 'Неизвестна целостность выбранного участка.')
    if (isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, Real)
            or not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0):
        return _unavailable(0, 'Частота дискретизации неизвестна или недопустима.')
    if type(code_step) is not int or code_step not in (1, 4):
        return _unavailable(0, 'Неизвестен формат исходных кодов АЦП.')
    try:
        # Even a generator cannot request unbounded memory or work. Retaining
        # MAX+1 explicitly rejects a larger selection instead of measuring a
        # convenient prefix and presenting it as the complete visible range.
        samples = tuple(islice(iter(codes), MAX_MEASUREMENT_SAMPLES + 1))
    except (TypeError, ValueError):
        return _unavailable(0, 'Исходные отсчёты недоступны.')
    count = len(samples)
    if count > MAX_MEASUREMENT_SAMPLES:
        return _unavailable(count, f'Уменьшите участок до {MAX_MEASUREMENT_SAMPLES} исходных отсчётов.')
    if has_gap:
        return _unavailable(count, 'В выбранном участке есть пропуск или неполные данные.')
    if not count:
        return _unavailable(0, 'В выбранном участке нет исходных отсчётов.')
    maximum_code = 4092 if code_step == 4 else 4095
    if any(isinstance(code, (bool, np.bool_)) or not isinstance(code, Integral)
           or not 0 <= code <= maximum_code or code % code_step for code in samples):
        return _unavailable(count, 'Исходные коды не соответствуют формату ADC12 или сохранённому шагу.')
    minimum, maximum = int(min(samples)), int(max(samples))
    # Convert numpy integer scalars to Python integers before summing so a
    # uint16 accumulator cannot wrap. Original samples are never modified.
    mean = sum(map(int, samples)) / count
    clipped = minimum == 0 or maximum == maximum_code
    period = None
    if clipped:
        reason = 'Есть крайние коды АЦП: возможное ограничение мешает оценке периода.'
    elif maximum == minimum:
        reason = 'Постоянный уровень: период не определяется.'
    elif maximum - minimum < MIN_DYNAMIC_STEPS * code_step:
        reason = 'Изменение сигнала мало относительно шага АЦП; период не подтверждён.'
    elif count < MIN_FULL_PERIODS * MIN_PERIOD_SAMPLES + 1:
        reason = 'Слишком короткий участок для 3 полных периодов.'
    else:
        values = np.asarray(samples, dtype=float)
        period, reason = _period(values, maximum-minimum, float(sample_rate_hz))
    return SegmentMeasurements(count, minimum, maximum, mean, period,
        None if period is None else 1 / period, reason, None, clipped)


def read_segment(reader, start, stop):
    """Read one exact half-open raw interval through the existing reader contract.

    An index hole, overlap, changed identity, malformed block, internal explicit
    gap, or incomplete read returns no aggregate values. A gap immediately
    before start is outside this selected interval and does not invalidate it.
    """
    count = stop-start if type(start) is int and type(stop) is int else 0
    if (type(start) is not int or type(stop) is not int or start < 0
            or not 0 < count <= MAX_MEASUREMENT_SAMPLES):
        return _unavailable(max(0, count), f'Выберите от 1 до {MAX_MEASUREMENT_SAMPLES} исходных отсчётов.')
    try:
        key, first, end = _reader(reader)
        if not first <= start < stop <= end:
            return _unavailable(count, 'Часть выбранного участка находится вне доступных исходных данных.')
        expected, samples = start, []
        for block in reader.iter_raw(start, stop, chunk_samples=8192):
            block_key, block_start, block_end, raw = _block(block)
            if block_key != key:
                return _unavailable(count, 'Источник данных изменился во время чтения участка.')
            if block_start != expected or block_end > stop:
                return _unavailable(count, 'В выбранном участке обнаружен пропуск, наложение или неверная граница.')
            explicit_gap = (getattr(block, 'gap_before', False) and block_start > start)
            flags = getattr(block, 'flags', ())
            gap_flags = {'gap', 'loss', 'unknown_loss', 'discontinuity', 'missing',
                         'incomplete', 'truncated', 'source_overrun', 'host_io'}
            if (explicit_gap or getattr(block, 'has_gap', False) or getattr(block, 'has_gaps', False)
                    or getattr(block, 'incomplete', False) or
                    isinstance(flags, (tuple, list, set, frozenset)) and gap_flags.intersection(flags)):
                return _unavailable(count, 'В выбранном участке отмечен пропуск или неполные данные.')
            samples.extend(code for (code,) in struct.iter_unpack('<H', raw))
            expected = block_end
        if expected != stop or len(samples) != count:
            return _unavailable(count, 'Получены не все исходные отсчёты выбранного участка.')
        if _reader(reader) != (key, first, end):
            return _unavailable(count, 'Источник или доступные границы изменились во время чтения участка.')
        step = 4 if key[10] == 10 else 1  # retained_bits in validated StreamIdentity.
        return analyze_samples(samples, key[3], code_step=step)
    except (AttributeError, TypeError, ValueError, OSError, OverflowError) as exc:
        return _unavailable(count, 'Не удалось прочитать целостный исходный участок: ' + str(exc))
