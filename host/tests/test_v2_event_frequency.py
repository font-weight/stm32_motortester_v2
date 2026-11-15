"""Finite threshold-event cadence checks; no COM, raw reader or clock service."""
from dataclasses import FrozenInstanceError, replace
import struct
import unittest

from motortester.stream_model import StreamBlock, StreamIdentity
from motortester.stream_view import DetectorStatus, Discontinuity, EventDetector, EventEntry
from motortester.v2.event_frequency import estimate_event_frequency, format_event_frequency
from motortester.v2.stream_demo import PacedStreamPeer
from motortester.v2.stream_device import DEFAULT_EVENT_CONFIG


def event(ordinal, trigger, flags=()):
    return EventEntry(ordinal, trigger, trigger-20, trigger+40, trigger-20, trigger,
                      trigger+5 if 'pending' not in flags else None, flags)


def detector_status(events, *, pending=None, processed=None, **changes):
    last = pending or (events[-1] if events else None)
    if processed is None:
        processed = None if last is None else last.end_index
    value = DetectorStatus('running', len(events), processed, pending, None, 0,
        'recent', events[0].ordinal if events else 0,
        pending.ordinal if pending is not None else events[-1].ordinal+1 if events else 0, 0)
    return replace(value, **changes)


class EventFrequencyTests(unittest.TestCase):
    def test_25hz_across_rates_large_indices_and_pending(self):
        for fs in (50_000, 100_000, 150_000):
            with self.subTest(fs=fs):
                base = 2**54
                events = tuple(event(i, base+i*(fs//25)) for i in range(12))
                result = estimate_event_frequency(events, detector_status(events), fs)
                self.assertEqual(result.frequency_hz, 25.)
                self.assertEqual(result.period_s, .04)
                self.assertEqual(result.interval_count, 8)
                self.assertIsNone(result.reason)
                self.assertIn('≈25 Гц', format_event_frequency(result))
                self.assertIn('≈40 мс', format_event_frequency(result))
                with self.assertRaises(FrozenInstanceError):
                    result.frequency_hz = 0
        closed = (event(0, 100), event(1, 2100))
        pending = event(2, 4100, ('pending',))
        result = estimate_event_frequency(closed, detector_status(closed, pending=pending), 50_000)
        self.assertEqual(result.frequency_hz, 25.)
        self.assertEqual(result.interval_count, 2)

    def test_waiting_and_staleness_follow_sample_indices(self):
        for events in ((), (event(0, 100),), (event(0, 100), event(1, 2100))):
            result = estimate_event_frequency(events, detector_status(events), 50_000)
            self.assertIsNone(result.frequency_hz)
            self.assertIn('Ожидание', result.reason)
        events = tuple(event(i, 100+i*2000) for i in range(3))
        boundary = events[-1].trigger_index+50_000
        self.assertEqual(estimate_event_frequency(events,
            detector_status(events, processed=boundary), 50_000).frequency_hz, 25.)
        stale = estimate_event_frequency(events, detector_status(events, processed=boundary+1), 50_000)
        self.assertIsNone(stale.frequency_hz)
        self.assertIn('давно', stale.reason)
        slow = tuple(event(i, 100+i*100_000) for i in range(3))
        self.assertEqual(estimate_event_frequency(slow,
            detector_status(slow, processed=slow[-1].trigger_index+250_000), 50_000).frequency_hz, .5)
        self.assertIsNone(estimate_event_frequency(slow,
            detector_status(slow, processed=slow[-1].trigger_index+300_001), 50_000).frequency_hz)

    def test_irregular_gap_fault_and_bad_event_are_not_skipped(self):
        events = tuple(event(i, trigger) for i, trigger in enumerate((100, 2100, 6100)))
        self.assertIn('нерегулярны', estimate_event_frequency(events, detector_status(events), 50_000).reason)
        regular = tuple(event(i, 100+i*2000) for i in range(12))
        for flag in ('overlapping_activity', 'tail_ambiguous', 'right_truncated', 'left_truncated'):
            bad = regular[:-2] + (replace(regular[-2], flags=(flag,)), regular[-1])
            self.assertIsNone(estimate_event_frequency(bad, detector_status(bad), 50_000).frequency_hz)
        # A bad event outside the selected eight intervals is not inside the estimate.
        old_bad = (replace(regular[0], flags=('overlapping_activity',)),) + regular[1:]
        self.assertEqual(estimate_event_frequency(old_bad, detector_status(old_bad), 50_000).frequency_hz, 25.)
        missing = regular[:-2] + (regular[-1],)
        self.assertIsNone(estimate_event_frequency(missing, detector_status(missing), 50_000).frequency_hz)
        for changes in (dict(discontinuity=Discontinuity(1000, 1200, 'loss')),
                        dict(outcome='source_fault'), dict(outcome='stopped')):
            self.assertIsNone(estimate_event_frequency(regular,
                detector_status(regular, **changes), 50_000).frequency_hz)

    def test_clipped_events_have_warning_but_not_false_waveform_claim(self):
        for rail in ('clipping', 'quantization_edge_bin'):
            events = tuple(event(i, 100+i*2000, (rail,)) for i in range(4))
            result = estimate_event_frequency(events, detector_status(events), 50_000)
            self.assertEqual(result.frequency_hz, 25.)
            self.assertIn('крайние', result.warning)
            self.assertIn('пороговых событий', format_event_frequency(result))
        events = tuple(event(i, 100+i*2000) for i in range(4))
        result = estimate_event_frequency(events, detector_status(events, suppressed_crossings=3), 50_000)
        self.assertIn('паузой запуска', result.warning)

    def test_actual_detector_and_demo_defaults_explain_merged_sine(self):
        def indexed(waveform, config):
            peer = PacedStreamPeer(waveform)
            identity = StreamIdentity('event-frequency-fixture', 1, 1, 50_000, 'synthetic')
            detector = EventDetector(config, 64, retention='recent')
            for start in range(0, 24_000, 1000):
                raw = struct.pack('<1000H', *(peer._sample(i) for i in range(start, start+1000)))
                detector.feed(StreamBlock(identity, start, raw))
            return estimate_event_frequency(detector.retained_events, detector.status, 50_000)
        ignition = indexed('ignition', DEFAULT_EVENT_CONFIG)
        self.assertEqual(ignition.frequency_hz, 25.)
        merged = indexed('oscilloscope', DEFAULT_EVENT_CONFIG)
        self.assertIsNone(merged.frequency_hz)
        self.assertIn('объединены', merged.reason)
        clean = indexed('oscilloscope', replace(DEFAULT_EVENT_CONFIG, post_samples=25))
        self.assertEqual(clean.frequency_hz, 250.)
        self.assertIn('Базовый уровень', clean.warning)


if __name__ == '__main__':
    unittest.main()
