"""Focused V2 checks with a byte-level fake serial device, never a COM port."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from uuid import UUID

from PySide6 import QtCore

from motortester.device_emulator import DeviceEmulator, WAITING
from motortester.model import Capture
from motortester.session import Phase
from motortester.transport import SerialTransport
from motortester.wire import StreamDecoder
from motortester.v2.core import InputProfile, UNKNOWN_PROFILE, load, save
from motortester.v2.device import DeviceBridge, make_device_config, recording_from_capture
from qt_test_support import pump_events


class IncompatibleHelloDevice(DeviceEmulator):
    def _enqueue(self, kind, payload, request=0, completion=""):
        if kind == 129:
            # Correctly framed/CRC-protected reply declares unsupported 0.2.
            payload = b"\x00\x02" + payload[2:]
        return super()._enqueue(kind, payload, request, completion)


class FakeSerial:
    """Real framing/state machine; injected backend is constructed by worker."""
    def __init__(self, controls, calls, **settings):
        self.controls, self.calls = controls, calls
        peer_class = IncompatibleHelloDevice if controls.get("incompatible_hello") else DeviceEmulator
        self.peer = peer_class(all_analog_modes=True, pretrigger=True)
        self.sent_decoder, self.sent_kinds = StreamDecoder(), []
        self.port, self.is_open = None, False
        self.calls.append(("create", threading.get_ident()))
        controls["backend"] = self

    def now(self):
        return time.monotonic_ns() // 1_000_000

    def open(self):
        self.calls.append(("open", threading.get_ident()))
        self.is_open = True

    def write(self, data):
        self.calls.append(("write", threading.get_ident()))
        self.sent_kinds.extend(frame.message_type for frame in self.sent_decoder.feed(data, self.now()).frames)
        return self.peer.write(data, self.now()).accepted_prefix

    def read(self, size):
        self.calls.append(("read", threading.get_ident()))
        if self.controls.get("silent"):
            return b""
        if self.controls.get("read_error"):
            raise OSError("fake disconnected")
        if self.controls.get("trigger") and self.peer.snapshot().state == WAITING:
            self.peer.trigger(self.now())
        if self.controls.get("partial"):
            # BEGIN and first DATA arrive; remaining bytes are lost on next call.
            data = self.peer.read(min(size, 750), self.now())
            if self.peer.snapshot().window_id and len(data) > 500:
                self.controls["read_error"] = True
            return data
        return self.peer.read(size, self.now())

    def close(self):
        self.calls.append(("close", threading.get_ident()))
        self.is_open = False
        self.peer.disconnect(self.now())


class V2DeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def setUp(self):
        self.controls, self.calls, self.bridges = {}, [], []

    def tearDown(self):
        for device in self.bridges:
            finished = []
            device.finished.connect(lambda: finished.append(True))
            device.shutdown()
            self.wait(lambda: bool(finished) and not device.bridge.running)
            device.deleteLater()
        pump_events(5)

    def wait(self, predicate, timeout=3):
        end = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > end:
                self.fail("Bounded fake-device wait timed out")
            pump_events(5)

    def device(self, *, wait_ready=True):
        def factory():
            return SerialTransport(backend_factory=lambda **kw: FakeSerial(self.controls, self.calls, **kw))
        device = DeviceBridge(serial_factory=factory, interval_ms=2)
        device.records, device.incompletes, device.errors = [], [], []
        device.recording_ready.connect(device.records.append)
        device.incomplete_ready.connect(device.incompletes.append)
        device.error.connect(device.errors.append)
        self.bridges.append(device)
        self.assertEqual(self.calls, [])  # Construction cannot open even the fake port.
        self.assertTrue(device.connect_source("FAKE_V2"))
        if wait_ready:
            self.wait(lambda: device.snapshot is not None and device.snapshot.phase is Phase.READY)
        return device

    def test_incompatible_hello_never_sends_config_or_arm(self):
        self.controls["incompatible_hello"] = True
        device = self.device(wait_ready=False)
        self.wait(lambda: device.snapshot is not None
                  and device.snapshot.phase is Phase.RECOVERY and not device.state.connected)
        self.assertEqual(device.snapshot.recovery.reason.value, "CAPABILITIES")
        self.assertIsNone(device.snapshot.capabilities)
        self.assertFalse(device.start(mode=0))
        self.assertFalse(device.start(mode=2))
        self.assertEqual(self.controls["backend"].sent_kinds, [1])
        self.assertEqual(device.records, [])
        self.assertTrue(device.errors)

    def test_conversion_preserves_raw_and_rejects_assumed_hardware_scale(self):
        capture = Capture(tuple(range(2048)), str(UUID(int=1)), 7, 50_000,
                          "2026-10-20T00:00:00Z", origin="device",
                          trigger_index=512, pretrigger_samples=512,
                          firmware_version="123", protocol_version="draft-0.1")
        result = recording_from_capture(capture)
        self.assertIs(result.blocks[0].samples, capture.samples)
        self.assertEqual(result.input_profile, UNKNOWN_PROFILE)
        self.assertEqual(result.source, "device")
        self.assertIsNone(result.capture_settings.threshold_v)
        self.assertEqual(result.capture_settings.hardware_threshold_code, 2048)
        self.assertEqual(result.capture_settings.window_s, .04096)
        self.assertEqual(result.start_index, 0)
        self.assertEqual(result.legacy_sequence, 7)
        negative = InputProfile(a=-.001, b=2, state="nominal", coefficient_source="test_definition")
        converted = recording_from_capture(capture, input_profile=negative)
        self.assertEqual(converted.capture_settings.edge, "falling")
        self.assertAlmostEqual(converted.capture_settings.threshold_v, -.048)
        from motortester.v2.core import DEMO_PROFILE
        with self.assertRaises(ValueError):
            recording_from_capture(capture, input_profile=DEMO_PROFILE)
        with self.assertRaises(ValueError):
            make_device_config(threshold_code=0)

    def test_single_handshake_retention_save_accept_and_stop(self):
        self.controls["trigger"] = True
        device = self.device()
        self.assertTrue(device.start(mode=2, channel_name="Датчик CH1", ui_profile="ignition"))
        self.wait(lambda: len(device.records) == 1)
        result = device.records[0]
        self.assertIs(device.pending_recording, result)
        self.assertEqual(result.ui_profile, "ignition")
        self.assertEqual(result.channel_name, "Датчик CH1")
        self.assertFalse(device.accept(replace(result)))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "window.mtv2"
            save(path, result)
            self.assertEqual(load(path), result)
        self.assertTrue(device.accept(result))
        self.assertFalse(device.accept(result))
        self.wait(lambda: device.snapshot.phase is Phase.READY and not device.state.has_capture)
        self.assertTrue(device.stop())
        self.wait(lambda: not device.state.busy and not device.snapshot.stop_barrier)
        main_id = threading.get_ident()
        self.assertTrue(self.calls)
        self.assertTrue(all(thread_id != main_id for _, thread_id in self.calls))
        self.assertEqual(device.errors, [])

    def test_repeated_auto_windows_have_separate_local_time_and_stop(self):
        device = self.device()
        self.assertTrue(device.start(mode=0, pretrigger_samples=0))
        self.wait(lambda: len(device.records) == 1)
        first = device.records[0]
        self.assertEqual(first.capture_settings.trigger_kind, "auto_timeout")
        self.assertIsNone(first.trigger_index)
        self.assertTrue(device.accept(first))
        self.wait(lambda: len(device.records) == 2)
        second = device.records[1]
        self.assertEqual((first.start_index, second.start_index), (0, 0))
        self.assertEqual(second.legacy_sequence, first.legacy_sequence + 1)
        self.assertIn("interwindow_timing_unknown", second.quality_flags)
        self.assertTrue(device.stop())
        self.wait(lambda: device.snapshot.phase is Phase.READY and not device.snapshot.stop_barrier)
        self.assertTrue(device.accept(second))
        self.wait(lambda: not device.state.has_capture)
        self.assertEqual(device.errors, [])

    def test_disconnect_retains_fragments_and_requires_reset_before_reconnect(self):
        self.controls.update(trigger=True, partial=True)
        device = self.device()
        self.assertTrue(device.start(mode=2))
        self.wait(lambda: bool(device.incompletes) and not device.state.connected)
        partial = device.incompletes[0]
        self.assertFalse(partial.complete)
        self.assertTrue(partial.fragments)
        self.assertTrue(partial.missing_ranges)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "partial.json"
            device.save_incomplete(path, partial)
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(report["complete_recording"])
            self.assertEqual(report["result"]["fragments"][0]["samples"],
                             list(partial.fragments[0].samples))
            self.assertEqual(report["result"]["missing_ranges"],
                             [list(pair) for pair in partial.missing_ranges])
            with self.assertRaises(FileExistsError):
                device.save_incomplete(path, partial)
        self.assertTrue(device.acknowledge_incomplete(partial))
        self.wait(lambda: not device.state.has_incomplete)
        self.assertFalse(device.connect_source("FAKE_V2"))
        self.assertTrue(device.state.reset_required)

    def test_caps_rejection_and_silent_link_timeout(self):
        device = self.device()
        self.assertFalse(device.start(pretrigger_samples=409))
        self.assertFalse(device.start(mode=1))
        self.assertIsNone(device.snapshot.config)
        self.controls["silent"] = True
        self.assertTrue(device.start(mode=2))
        self.wait(lambda: device.snapshot.phase is Phase.RECOVERY and not device.state.connected)
        self.assertEqual(device.snapshot.recovery.reason.value, "TIMEOUT")
        self.assertEqual(device.records, [])
        self.assertTrue(device.errors)


if __name__ == "__main__":
    unittest.main()
