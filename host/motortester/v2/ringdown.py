"""Conservative, bounded damped-response fit in original ADC12 coordinates.

The result describes the recorded response, including sensor/cable/filter
effects. It is neither a coil diagnosis nor a measurement of physical Q.
Baseline removal and phase/envelope fitting are temporary model operations;
the input and every reported peak code remain unchanged.
"""
from dataclasses import dataclass
from itertools import islice
import math
from numbers import Integral, Real
import struct

import numpy as np

from ..stream_view import _block, _reader


MAX_RINGDOWN_SAMPLES = 32768
MAX_SUGGESTION_CANDIDATES = 14
MIN_CYCLES = 3
MIN_SAMPLES_PER_CYCLE = 10
MIN_AMPLITUDE_STEPS = 8
NOISE_MULTIPLIER = 6
MAX_PERIOD_DEVIATION = .12
MAX_FIT_RESIDUAL_RATIO = .15
MIN_ENVELOPE_DROP = .25


@dataclass(frozen=True, slots=True)
class RingdownResult:
    available: bool
    reason: str | None
    frequency_hz: float | None
    tau_s: float | None
    amplitude_ratio_per_cycle: float | None
    cycle_count: int
    duration_s: float
    peaks: tuple[tuple[int, int], ...]
    baseline_code: float | None
    noise_rms_codes: float | None
    fit_residual_ratio: float | None
    warning: str | None


@dataclass(frozen=True, slots=True)
class RingdownSuggestion:
    available: bool
    reason: str | None
    start_index: int | None
    stop_index: int | None
    relative_start: int | None
    relative_stop: int | None
    result: RingdownResult | None


def _fail(reason, *, noise=None, baseline=None, residual=None):
    return RingdownResult(False, reason, None, None, None, 0, 0., (),
                          baseline, noise, residual, None)


def _validate(codes, fs_hz, code_step, has_gap=False, *, reject_rails=True):
    if has_gap:
        raise ValueError('В участке есть пропуск или неполные данные.')
    if (isinstance(fs_hz, bool) or not isinstance(fs_hz, Real)
            or not math.isfinite(fs_hz) or fs_hz <= 0):
        raise ValueError('Неизвестна частота дискретизации.')
    if type(code_step) is not int or code_step not in (1, 4):
        raise ValueError('Неизвестен канонический формат кодов АЦП.')
    samples = tuple(islice(iter(codes), MAX_RINGDOWN_SAMPLES+1))
    if len(samples) > MAX_RINGDOWN_SAMPLES:
        raise ValueError(f'Сузьте участок до {MAX_RINGDOWN_SAMPLES} исходных отсчётов.')
    if len(samples) < MIN_CYCLES*MIN_SAMPLES_PER_CYCLE+1:
        raise ValueError('Слишком короткий участок для 3 полных колебаний.')
    maximum = 4092 if code_step == 4 else 4095
    if any(isinstance(code, (bool, np.bool_)) or not isinstance(code, Integral)
           or not 0 <= code <= maximum or code % code_step for code in samples):
        raise ValueError('Коды участка не соответствуют ADC12 и сохранённому шагу.')
    if reject_rails and (min(samples) == 0 or max(samples) == maximum):
        raise ValueError('Есть крайние коды АЦП: исключите возможное ограничение.')
    return samples, np.asarray(samples, dtype=float)


def _noise(values, step):
    # MAD of the third difference in the last fifth: white-noise gain sqrt20.
    # A remaining oscillatory tail can inflate this estimate, so it is a
    # conservative detection floor, not an instrument-noise specification.
    tail = values[-max(12, len(values)//5):]
    difference = np.diff(tail, n=3)
    mad = float(np.median(np.abs(difference-np.median(difference))))
    return max(step/math.sqrt(12), mad/(.67448975*math.sqrt(20)))


def _lobes(values, baseline, floor):
    # Hysteretic polarity changes reject small reversals near the noise floor.
    # Only lobes completed by the opposite polarity are accepted; the final
    # unfinished lobe cannot increase the count of confirmed cycles.
    smooth = values.copy()
    smooth[1:-1] = (values[:-2]+2*values[1:-1]+values[2:])/4
    centered = smooth-baseline
    sign, beginning, peaks = 0, 0, []
    for index, value in enumerate(centered):
        current = 1 if value >= floor/2 else -1 if value <= -floor/2 else 0
        if not sign:
            if current:
                sign, beginning = current, index
            continue
        if current and current != sign:
            segment = values[beginning:index+1]
            at = beginning + int(np.argmax(segment) if sign > 0 else np.argmin(segment))
            amplitude = sign*(values[at]-baseline)
            if amplitude >= floor:
                position = float(at)
                if 0 < at < len(values)-1:
                    left, middle, right = smooth[at-1:at+2]
                    curvature = left-2*middle+right
                    if curvature:
                        position += float(np.clip(.5*(left-right)/curvature, -.5, .5))
                peaks.append((at, position, sign, float(amplitude)))
            elif peaks:
                break  # Do not bridge a weak/missing half-cycle into a later burst.
            sign, beginning = current, index
    return peaks


def _fit(values, positions, frequency, tau):
    envelope = np.exp(-positions/tau)
    phase = 2*np.pi*frequency*positions
    matrix = np.column_stack((np.ones(len(values)), envelope*np.cos(phase), envelope*np.sin(phase)))
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, values, rcond=None)
    if rank != 3:
        return None
    residual = values-matrix@coefficients
    mse = float(residual@residual / len(values))
    return mse, coefficients


def _refine(values, period, tau):
    positions = np.arange(len(values), dtype=float)
    frequency = 1/period
    best = None
    # Two finite grids, not an unconstrained optimizer. The peak timing already
    # supplies a close frequency estimate; full raw values verify every fit.
    for frequency_scale, tau_scales in ((.03, np.geomspace(.6, 1.6, 7)),
                                       (.008, np.geomspace(.85, 1.18, 5))):
        center_frequency, center_tau = (frequency, tau) if best is None else best[:2]
        for f in center_frequency*np.linspace(1-frequency_scale, 1+frequency_scale, 7):
            for decay in center_tau*tau_scales:
                fitted = _fit(values, positions, float(f), float(decay))
                if fitted is not None and (best is None or fitted[0] < best[2]):
                    best = float(f), float(decay), fitted[0], fitted[1]
    return best


def analyze_ringdown(codes, fs_hz, code_step=1, *, has_gap=False):
    """Fit one exponentially damped sinusoid; raw, offset and polarity are kept.

    tau_s is the time for the fitted amplitude envelope to fall by e.
    amplitude_ratio_per_cycle = exp(-T/tau), for same-polarity peaks one full
    cycle apart. duration_s spans first to last accepted same-polarity peak,
    excluding quiet data beyond those confirmed cycles.
    """
    try:
        samples, values = _validate(codes, fs_hz, code_step, has_gap)
    except (TypeError, ValueError, OverflowError) as exc:
        return _fail(str(exc))
    noise = _noise(values, code_step)
    baseline = float(np.median(values[-max(12, len(values)//5):]))
    floor = max(MIN_AMPLITUDE_STEPS*code_step, NOISE_MULTIPLIER*noise)
    if float(values.max()-values.min()) < 2*floor:
        return _fail('Колебания не различимы над шумом или шагом АЦП.', noise=noise, baseline=baseline)
    peaks = _lobes(values, baseline, floor)
    positive = [p for p in peaks if p[2] == 1]
    negative = [p for p in peaks if p[2] == -1]
    same = max((positive, negative), key=len)
    if len(same) < MIN_CYCLES+1:
        return _fail('Нужно не менее 3 полных различимых колебаний над шумом.', noise=noise, baseline=baseline)
    periods = np.diff([p[1] for p in same])
    period = float(np.median(periods))
    if period < MIN_SAMPLES_PER_CYCLE or float(periods.min()) < MIN_SAMPLES_PER_CYCLE-.5:
        return _fail('Недостаточная дискретизация: требуется не менее 10 отсчётов на колебание.', noise=noise)
    if float(np.max(np.abs(periods-period))) > MAX_PERIOD_DEVIATION*period+.5:
        return _fail('Интервалы колебаний нерегулярны или содержат несколько частот.', noise=noise)
    x = np.asarray([p[1]-peaks[0][1] for p in peaks], dtype=float)
    amplitudes = np.asarray([p[3] for p in peaks], dtype=float)
    slope, intercept = np.polyfit(x/period, np.log(amplitudes), 1)
    if slope >= 0 or math.exp(float(slope)*(same[-1][1]-same[0][1])/period) > 1-MIN_ENVELOPE_DROP:
        return _fail('Устойчивое снижение амплитуды не подтверждено.', noise=noise, baseline=baseline)
    # A genuinely new excitation in the selected interval is not a continuation
    # of this tail. Check the observed signal beyond the last accepted lobe.
    last = peaks[-1][0]
    if np.any(np.abs(values[min(len(values), last+math.ceil(period)):]-baseline) > max(3*floor, peaks[-1][3]*2)):
        return _fail('После предполагаемого хвоста есть новое выраженное изменение сигнала.', noise=noise)
    fit_start = max(0, math.floor(peaks[0][1]-period/4))
    fit_stop = min(len(values), math.ceil(peaks[-1][1]+period/4)+1)
    fitted = _refine(values[fit_start:fit_stop], period, -period/float(slope))
    if fitted is None:
        return _fail('Не удалось согласовать затухающую модель с исходными отсчётами.', noise=noise)
    frequency, tau, mse, coefficients = fitted
    baseline = float(coefficients[0])
    signal_rms = float(np.sqrt(np.mean((values[fit_start:fit_stop]-baseline)**2)))
    residual_ratio = math.sqrt(mse)/max(signal_rms, code_step)
    if residual_ratio > MAX_FIT_RESIDUAL_RATIO:
        return _fail('Записанный отклик не согласуется с одной затухающей синусоидой.',
                     noise=noise, baseline=baseline, residual=residual_ratio)
    if 1/frequency < MIN_SAMPLES_PER_CYCLE:
        return _fail('Недостаточная дискретизация: требуется не менее 10 отсчётов на колебание.', noise=noise)
    refined_floor = max(floor, NOISE_MULTIPLIER*math.sqrt(mse))
    observed = [(p[0], p[1], p[2]*(values[p[0]]-baseline)) for p in same]
    # Count only the contiguous above-noise prefix, never isolated noise peaks.
    accepted = []
    for point in observed:
        if point[2] < refined_floor:
            break
        accepted.append(point)
    if len(accepted) < MIN_CYCLES+1:
        return _fail('После проверки шума осталось меньше 3 полных колебаний.',
                     noise=noise, baseline=baseline, residual=residual_ratio)
    amplitudes = np.asarray([p[2] for p in accepted])
    times = np.asarray([p[1]-accepted[0][1] for p in accepted])
    expected_log = -times/tau
    measured_log = np.log(amplitudes)
    log_error = measured_log-expected_log
    log_error -= float(np.mean(log_error))
    if (float(np.sqrt(np.mean(log_error**2))) > .20 or
            any(b > a+max(3*noise, .12*a) for a, b in zip(amplitudes[:-1], amplitudes[1:]))):
        return _fail('Амплитуды одноимённых вершин не образуют устойчивый экспоненциальный спад.',
                     noise=noise, baseline=baseline, residual=residual_ratio)
    duration_samples = accepted[-1][1]-accepted[0][1]
    if math.exp(-duration_samples/tau) > 1-MIN_ENVELOPE_DROP:
        return _fail('Спад слишком мал для надёжной оценки времени затухания.', noise=noise)
    frequency_hz, tau_s = frequency*float(fs_hz), tau/float(fs_hz)
    duration_s = duration_samples/float(fs_hz)
    ratio = math.exp(-1/(frequency*tau))
    if not all(math.isfinite(v) and v > 0 for v in (frequency_hz, tau_s, duration_s, ratio)):
        return _fail('Недопустимая временная основа.')
    return RingdownResult(True, None, frequency_hz, tau_s, ratio, len(accepted)-1,
        duration_s, tuple((p[0], int(samples[p[0]])) for p in accepted), baseline,
        noise, residual_ratio, 'Оценён записанный отклик датчика и тракта; это не диагноз катушки.')


def _read_raw(reader, start, stop):
    if (type(start) is not int or type(stop) is not int or start < 0
            or not 0 < stop-start <= MAX_RINGDOWN_SAMPLES):
        raise ValueError(f'Выберите от 1 до {MAX_RINGDOWN_SAMPLES} исходных отсчётов.')
    key, first, end = _reader(reader)
    if not first <= start < stop <= end:
        raise ValueError('Часть выбранного участка находится вне доступных исходных данных.')
    samples, expected = [], start
    gap_flags = {'gap', 'loss', 'unknown_loss', 'discontinuity', 'missing',
                 'incomplete', 'truncated', 'source_overrun', 'host_io'}
    for block in reader.iter_raw(start, stop, chunk_samples=8192):
        block_key, beginning, ending, raw = _block(block)
        if block_key != key or beginning != expected or ending > stop:
            raise ValueError('Источник изменился или в участке есть пропуск/наложение данных.')
        flags = getattr(block, 'flags', ())
        if ((getattr(block, 'gap_before', False) and beginning > start)
                or getattr(block, 'has_gap', False) or getattr(block, 'has_gaps', False)
                or getattr(block, 'incomplete', False)
                or isinstance(flags, (tuple, list, set, frozenset)) and gap_flags.intersection(flags)):
            raise ValueError('В выбранном участке отмечен разрыв или неполные данные.')
        samples.extend(code for (code,) in struct.iter_unpack('<H', raw))
        expected = ending
    if expected != stop or len(samples) != stop-start or _reader(reader) != (key, first, end):
        raise ValueError('Не получен целостный неизменный исходный участок.')
    return tuple(samples), key[3], 4 if key[10] == 10 else 1


def read_ringdown(reader, start, stop):
    try:
        codes, fs, step = _read_raw(reader, start, stop)
    except (AttributeError, TypeError, ValueError, OSError, OverflowError) as exc:
        return _fail(str(exc))
    return analyze_ringdown(codes, fs, step)


def suggest_ringdown(reader, start, stop):
    """Propose one tail region for visual confirmation, never an end-of-spark fact."""
    def fail(reason):
        return RingdownSuggestion(False, reason, None, None, None, None, None)
    try:
        codes, fs, step = _read_raw(reader, start, stop)
        # Automatic selection must not silently route around a clipped main
        # impulse. A manually selected clean tail can be assessed separately;
        # this does not establish amplifier recovery after that overload.
        _, values = _validate(codes, fs, step)
    except (AttributeError, TypeError, ValueError, OSError, OverflowError) as exc:
        return fail(str(exc))
    differences = np.abs(np.diff(values))
    baseline = float(np.median(values[-max(12, len(values)//5):]))
    quiet_floor = max(MIN_AMPLITUDE_STEPS*step, NOISE_MULTIPLIER*_noise(values, step))
    large_jumps = np.flatnonzero(differences > max(8*quiet_floor, .25*float(np.ptp(values))))+1
    excitations = [int(at) for at in large_jumps if at >= 16
                   and np.all(np.abs(values[at-16:at]-baseline) <= quiet_floor)]
    if len(excitations) > 1:
        return fail('В области несколько отдельных выраженных импульсов. Выберите один вручную.')
    # Large slope changes are merely candidate boundaries, not spark labels.
    # Keep 0 for a selection already containing only the response tail.
    candidates = [0]
    separation = max(3, len(values)//512)
    for at in np.argsort(differences)[::-1]:
        at = int(at)+1
        if len(values)-at < 4*MIN_SAMPLES_PER_CYCLE:
            continue
        if all(abs(at-previous) >= separation for previous in candidates):
            candidates.append(at)
        if len(candidates) == MAX_SUGGESTION_CANDIDATES:
            break
    successful = []
    for at in sorted(candidates):
        # A whole qualified response already verifies every cycle in this
        # interval. Re-fitting its nested suffixes changes no proposal and
        # would multiply work for long clean tails by fourteen.
        if any(previous[0] <= at <= previous[2] for previous in successful):
            continue
        result = analyze_ringdown(codes[at:], fs, step)
        if result.available:
            first_peak = at+result.peaks[0][0]
            last_peak = at+result.peaks[-1][0]
            successful.append((at, first_peak, last_peak, result))
    if not successful:
        return fail('Однозначный затухающий участок не найден. Выберите область вручную.')
    # Nearby starts of the same observed tail are one proposal. Two disjoint
    # qualified tails are ambiguous; do not pick a convenient one silently.
    selected = max(successful, key=lambda item: (item[3].cycle_count, -item[0]))
    period = fs/selected[3].frequency_hz
    # A suffix fit rejects later re-excitation, so its failure cannot prove
    # there was no earlier response. Partition *all* observed activity at
    # quiet runs longer than two proposed periods and inspect other groups.
    # This is only an ambiguity guard: no automatic end-of-spark label and
    # no need to fit/qualify a convenient second tail to refuse the proposal.
    active = np.flatnonzero(np.abs(values-baseline) > quiet_floor)
    groups = np.split(active, np.flatnonzero(np.diff(active) > math.ceil(2*period))+1)
    for group in groups:
        if not len(group):
            continue
        first, last = int(group[0]), int(group[-1])
        if last >= selected[1] and first <= selected[2]:
            continue
        if last-first < MIN_CYCLES*period:
            continue
        other = _lobes(values[max(0, first-1):min(len(values), last+2)], baseline, quiet_floor)
        if len(other) >= 2*MIN_CYCLES+1:
            return fail('В области несколько отдельных колебательных откликов. Выберите один вручную.')
    for item in successful:
        overlap = min(item[2], selected[2])-max(item[1], selected[1])
        same_response = (overlap >= period and
            abs(item[3].frequency_hz-selected[3].frequency_hz) <= .05*selected[3].frequency_hz and
            abs(item[3].tau_s-selected[3].tau_s) <= .3*selected[3].tau_s)
        if not same_response:
            return fail('Найдено несколько возможных хвостов. Выберите один вручную.')
    relative_start, _, last_peak, result = selected
    relative_stop = min(len(codes), last_peak+math.ceil(fs/result.frequency_hz)+1)
    # Verify exactly the proposed selection, not a different suffix containing
    # more quiet samples or a hidden future part of the signal.
    exact = analyze_ringdown(codes[relative_start:relative_stop], fs, step)
    if not exact.available:
        relative_stop, exact = len(codes), result
    return RingdownSuggestion(True, 'Кандидат хвоста: проверьте границы по исходному графику.',
        start+relative_start, start+relative_stop, relative_start, relative_stop, exact)
