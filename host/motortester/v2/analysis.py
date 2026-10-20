"""Transparent measurements from immutable raw recordings, with no Qt."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from statistics import median
from .data import Recording, CaptureSettings
from .input import V2Error, finite

MAX_EVENTS = 20_000
ALGORITHM_VERSION = "voltage-threshold-v1"


@dataclass(frozen=True, slots=True)
class Event:
    ordinal: int
    trigger_index: int
    start_index: int
    end_index: int
    quality_flags: tuple[str, ...]


def find_events(recording: Recording, settings: CaptureSettings | None = None):
    """Software voltage crossings with holdoff, never cylinder identification.

    Context uses explicit time bounds, not an asserted duration of combustion.
    Crossings are not inferred across gaps; truncated context remains flagged.
    """
    settings = settings or recording.capture_settings
    profile = recording.input_profile
    threshold = profile.code(settings.threshold_v)
    edge = profile.code_edge(settings.edge)
    fs = recording.sample_rate_hz
    holdoff = int(round(settings.holdoff_s * fs))
    window = max(2, int(round(settings.window_s * fs)))
    pre = int(round(window * settings.pretrigger_fraction))
    triggers, clipped, previous, last_index = [], [], None, None
    next_allowed = -1
    for block in recording.blocks:
        if block.gap_before or last_index != block.start_index:
            previous = None
        for index, code in enumerate(block.samples, block.start_index):
            if profile.clipping((code,)):
                clipped.append(index)
            crossing = previous is not None and (
                previous < threshold <= code if edge == "rising" else previous > threshold >= code)
            if crossing and index >= next_allowed:
                if len(triggers) >= MAX_EVENTS:
                    raise V2Error("Слишком много кандидатов: увеличьте паузу запуска")
                triggers.append(index)
                next_allowed = index + holdoff
            previous = code
        last_index = block.end_index
    gaps = recording.gaps
    block_starts = [block.start_index for block in recording.blocks]
    block_ends = [block.end_index for block in recording.blocks]
    events = []
    for ordinal, index in enumerate(triggers):
        requested_start, requested_stop = index - pre, index - pre + window
        start, stop = max(recording.start_index, requested_start), min(recording.end_index, requested_stop)
        flags = set(recording.quality_flags)
        if requested_start < recording.start_index:
            flags.add("left_truncated")
        if requested_stop > recording.end_index:
            flags.add("right_truncated")
        if any(gap.start_index < stop and (
                gap.end_index > start or gap.start_index == gap.end_index == start) for gap in gaps):
            flags.add("missing_context")
        for block in recording.blocks[bisect_right(block_ends, start):bisect_left(block_starts, stop)]:
            flags.update(block.quality_flags)
        if bisect_left(clipped, stop) > bisect_left(clipped, start):
            flags.add("clipping")
        events.append(Event(ordinal, index, start, stop, tuple(sorted(flags))))
    return tuple(events)


@dataclass(frozen=True, slots=True)
class Measurements:
    minimum_v: float | None
    maximum_v: float | None
    mean_v: float | None
    peak_to_peak_v: float | None
    period_s: float | None
    frequency_hz: float | None
    clipping: bool
    quality_flags: tuple[str, ...]


def analyze(recording: Recording, settings: CaptureSettings | None = None):
    """Require three consistent intervals; scope period ignores capture holdoff.

    Oscilloscope period uses rising crossings of the midpoint of observed
    extrema, without holdoff. Ignition reports the rate of selected threshold
    events with the actual capture settings, not a fundamental frequency/RPM.
    """
    profile = recording.input_profile
    flags = set(recording.quality_flags)
    if recording.gaps:
        flags.add("missing_samples")
    low, high, total, count = 4095, 0, 0, 0
    clipped = False
    for block in recording.blocks:
        flags.update(block.quality_flags)
        low, high = min(low, min(block.samples)), max(high, max(block.samples))
        total += sum(block.samples)
        count += len(block.samples)
        clipped = clipped or profile.clipping(block.samples)
    if clipped:
        flags.add("clipping")
    if not profile.configured:
        flags.add("unconfigured")
        return Measurements(None, None, None, None, None, None, clipped, tuple(sorted(flags)))
    minimum, maximum = sorted((profile.voltage(low), profile.voltage(high)))
    mean = profile.voltage(total / count)
    period = None
    analysis_settings = settings or recording.capture_settings
    if recording.ui_profile == "oscilloscope":
        analysis_settings = replace(analysis_settings, threshold_v=(minimum + maximum) / 2,
                                    edge="rising", holdoff_s=0)
    try:
        events = find_events(recording, analysis_settings)
    except V2Error:
        events = ()
        flags.add("event_analysis_unavailable")
    # A regular interval across a missing region is not evidence of continuity.
    if len(events) >= 4 and not recording.gaps:
        intervals = [(b.trigger_index - a.trigger_index) / recording.sample_rate_hz
                     for a, b in zip(events, events[1:])]
        candidate = median(intervals)
        if candidate > 0 and max(abs(value - candidate) for value in intervals) <= max(
                2 / recording.sample_rate_hz, candidate * 0.05):
            period = candidate
        else:
            flags.add("irregular_intervals")
    else:
        flags.add("insufficient_period_evidence")
    return Measurements(minimum, maximum, mean, maximum - minimum, period,
                        1 / period if period else None, clipped, tuple(sorted(flags)))


@dataclass(frozen=True, slots=True)
class CursorMeasurement:
    time_a_s: float
    time_b_s: float
    voltage_a_v: float | None
    voltage_b_v: float | None
    delta_t_s: float
    delta_v: float | None
    sample_time_a_s: float | None
    sample_time_b_s: float | None


def cursor_measurement(recording, time_a_s, time_b_s):
    finite(time_a_s, "Курсор A"); finite(time_b_s, "Курсор B")
    a, b = recording.sample_at_time(time_a_s), recording.sample_at_time(time_b_s)
    ua, ub = a[2] if a else None, b[2] if b else None
    return CursorMeasurement(time_a_s, time_b_s, ua, ub, time_b_s - time_a_s,
                             ub - ua if ua is not None and ub is not None else None,
                             a[0] if a else None, b[0] if b else None)


def sample_at_time(recording, time_s):
    return recording.sample_at_time(time_s)
