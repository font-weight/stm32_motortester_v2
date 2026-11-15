"""Fresh calibration excerpts over bounded immutable raw; no COM or hardware."""
from dataclasses import replace
import struct
from types import SimpleNamespace as NS
import unittest

from motortester.stream_controller import ControllerStatus
from motortester.stream_model import StreamIdentity
from motortester.stream_wire import BATCH1024_REVISION
from motortester.v2.analog_profile import nominal_selection
from motortester.v2.calibration import CalibrationPlan
from motortester.v2.calibration_live import LiveCalibrationProvider
from motortester.v2.stream_device import SerialStreamSelection, StreamConnection, StreamContext


class Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot):
        self.slots.remove(slot)

    def emit(self, value):
        for slot in tuple(self.slots):
            slot(value)


class Source:
    """A source fixture has no acquisition methods for the provider to call."""
    def __init__(self, *, bits=12, origin='synthetic', connection=None):
        options = {} if bits == 12 else dict(protocol_revision=BATCH1024_REVISION,
            acquisition_mode=5, retained_bits=10, discarded_lsb=2,
            wire_sample_encoding='u10packed_le', normalization='left_shift_2',
            quantization='truncate_lsb')
        self.identity = StreamIdentity('fixture-session', 1, 1 if bits == 12 else 5,
                                       50_000 if bits == 12 else 150_000, origin, **options)
        profile, snapshot = nominal_selection('DC_WIDE', self.identity,
                                               hardware_instance_id='fixture-board')
        self.context = StreamContext(input_profile=profile, analog_snapshot=snapshot)
        self.connection = connection
        self.is_device = connection is not None
        self.metadata_pending = False
        self.live_ready = Signal()
        self.detector = NS(outcome='running', discontinuity=None)
        self.source = NS(identity=self.identity, source_received_end=1024, closed=False,
            endpoint_first_fault=None, late_fault=None, source_terminal=None,
            session=NS(source_started=True, first_failure=None, source_end=None,
                       stop_requested=False, admission_fenced=False, writer_fenced=False))
        self.status = ControllerStatus(revision=1, phase='preview', bridge=self.source,
            can_preview=False, can_record=True, can_open=False, ring_samples=1024,
            detector_status=self.detector,
            serial=NS(state='open', handle_settled=False, first_error=None, close_error=None))
        self.controller = NS(snapshot=lambda: self.status)

    @property
    def plan(self):
        snapshot = self.context.analog_snapshot
        return CalibrationPlan(snapshot.mode_id, snapshot.raw_format,
            snapshot.hardware_instance_id, self.identity.origin,
            'Искусственный источник', 'Только программная проверка', .001, .1)

    def code(self, index):
        return (1024 + index % 512) // self.context.analog_snapshot.raw_format.canonical_step * \
            self.context.analog_snapshot.raw_format.canonical_step

    def received(self, end, first=0):
        self.source.source_received_end = end
        self.status = replace(self.status, raw_available_start=first, ring_samples=end-first)

    def tail(self, end, first=0, **changes):
        self.received(end, first)
        values = tuple(self.code(i) for i in range(first, end))
        data = dict(identity=self.identity, revision=1, raw_first=first, end=end,
                    raw=struct.pack(f'<{len(values)}H', *values), loss_samples=None,
                    tail_state='running', flags=(), detector=self.detector)
        data.update(changes)
        self.live_ready.emit(NS(source=NS(**data)))


class LiveCalibrationTests(unittest.TestCase):
    def make(self, **options):
        source = Source(**options)
        selected = [source]
        clock = [0.0]
        provider = LiveCalibrationProvider(lambda: (selected[0], selected[0].context),
                                           clock=lambda: clock[0], timeout_s=1)
        self.addCleanup(provider.close)
        return source, provider, selected, clock

    def test_received_boundary_beats_delayed_display_and_points_do_not_overlap(self):
        source, provider, _, _ = self.make()
        provider.context()
        source.tail(1024)
        source.received(2048)  # Receiver is ahead of the last visible copy.
        provider.begin(source.plan, 256)
        self.assertIsNone(provider.poll())
        source.tail(2200)
        self.assertIsNone(provider.poll())
        source.tail(2400)
        window = provider.poll()
        self.assertEqual(window.first_sample_index, 2048)
        self.assertEqual(window.codes, tuple(source.code(i) for i in range(2048, 2304)))
        self.assertFalse(window.settled_confirmed)
        self.assertIsNone(provider.poll())  # A delivered point cannot be fitted again as a new read.
        provider.begin(source.plan, 128)
        self.assertIsNone(provider.poll())
        source.tail(2600)
        following = provider.poll()
        self.assertEqual(following.first_sample_index, 2400)
        self.assertEqual(following.source_id, window.source_id)
        self.assertGreaterEqual(following.first_sample_index, window.first_sample_index + len(window.codes))
        again = LiveCalibrationProvider(lambda: (source, source.context))
        self.addCleanup(again.close)
        self.assertEqual(again.context().source_id, window.source_id)
        with self.assertRaises(TypeError):
            window.codes[0] = 0

    def test_cancel_close_and_owner_change_fence_late_callbacks(self):
        source, provider, selected, _ = self.make()
        provider.begin(source.plan, 128)
        late_callback = source.live_ready.slots[0]
        provider.cancel()
        self.assertEqual(source.live_ready.slots, [])
        source.tail(1400)
        self.assertIsNone(provider.poll())
        provider.begin(source.plan, 128)
        selected[0] = Source()
        with self.assertRaisesRegex(ValueError, 'изменился'):
            provider.poll()
        self.assertEqual(source.live_ready.slots, [])
        self.assertEqual(selected[0].live_ready.slots, [])
        late_callback(NS(source=None))
        self.assertIsNone(provider.poll())
        provider.close()
        with self.assertRaisesRegex(ValueError, 'закрыт'):
            provider.context()

    def test_fault_gap_eviction_timeout_and_context_change_reject(self):
        for condition in ('stop', 'fault', 'gap', 'evicted', 'timeout', 'context', 'malformed'):
            with self.subTest(condition=condition):
                source, provider, _, clock = self.make()
                provider.begin(source.plan, 128)
                if condition == 'stop':
                    source.status = replace(source.status, stop_pending=True)
                elif condition == 'fault':
                    source.source.endpoint_first_fault = 'host_io'
                elif condition == 'gap':
                    source.tail(1400, loss_samples=1)
                elif condition == 'evicted':
                    source.tail(1600, first=1200)
                elif condition == 'timeout':
                    clock[0] = 1.01
                elif condition == 'context':
                    profile, snapshot = nominal_selection('AC_WIDE', source.identity,
                        hardware_instance_id='fixture-board')
                    source.context = StreamContext(input_profile=profile, analog_snapshot=snapshot)
                else:
                    source.tail(1400, raw=b'broken')
                with self.assertRaises(ValueError):
                    provider.poll()
                self.assertFalse(provider.active)
                self.assertEqual(source.live_ready.slots, [])

    def test_injected_cannot_claim_device_and_normalized_ten_bits_stay_canonical(self):
        connection = StreamConnection(SerialStreamSelection('TEST-ONLY'), 'injected-test',
            0x1234, (1, 1, 0, 12, 50_000, 1, 128, 1))
        source, provider, _, _ = self.make(origin='device', connection=connection)
        self.assertEqual(provider.context().origin, 'synthetic')
        with self.assertRaisesRegex(ValueError, 'происхождению'):
            provider.begin(source.plan, 128)
        provider.begin(replace(source.plan, origin='synthetic'), 128)
        source.tail(1300)
        self.assertEqual(provider.poll().origin, 'synthetic')
        packed, provider10, _, _ = self.make(bits=10)
        provider10.begin(packed.plan, 256)
        packed.tail(1400)
        result = provider10.poll()
        self.assertEqual(result.raw_format.retained_bits, 10)
        self.assertEqual(result.codes, tuple(packed.code(i) for i in range(1024, 1280)))
        self.assertTrue(all(code % 4 == 0 for code in result.codes))
        physical, provider_physical, _, _ = self.make(origin='device')
        with self.assertRaisesRegex(ValueError, 'Физическое соединение'):
            provider_physical.context()

    def test_postcopy_recheck_rejects_changed_owner_and_limits_are_bounded(self):
        source = Source()
        calls = [0]
        def current():
            calls[0] += 1
            if calls[0] == 4:  # begin checks twice; poll checks before and after copy.
                source.source.session.stop_requested = True
            return source, source.context
        provider = LiveCalibrationProvider(current)
        self.addCleanup(provider.close)
        for count in (127, 16385, True):
            with self.assertRaises(ValueError):
                provider.begin(source.plan, count)
        provider.begin(source.plan, 128)
        with self.assertRaises(ValueError):
            provider.begin(source.plan, 128)
        source.tail(1400)
        with self.assertRaisesRegex(ValueError, 'работающий живой поток'):
            provider.poll()
        self.assertFalse(provider.active)


if __name__ == '__main__':
    unittest.main()
