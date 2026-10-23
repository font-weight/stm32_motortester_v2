"""V2 serial admission and ownership over encoded bytes; no real COM or GUI."""
from dataclasses import replace
import csv
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6 import QtCore

from motortester.stream_controller import StreamController
from motortester.stream_model import StreamIdentity, StreamError
from motortester.stream_provenance import DeviceStreamContext, device_context_identity, profile_for_identity
from motortester.stream_recording import recover_attempt
from motortester.stream_serial import SerialSettings, SerialStreamPeer
from motortester.v2.input import UNKNOWN_PROFILE
from motortester.v2.stream_device import (
    SerialStreamSelection, StreamContext, StreamDeviceBridge, companion_path,
    open_verified_context)
from motortester.v2.stream_files import export_stream
from qt_test_support import pump_events
from test_stream_controller import EncodedPeer, CONFIG, waveform


class SelectedPeer(EncodedPeer):
    """Diagnostic-like unknown END and optional incompatible HELLO/CAPS."""
    def __init__(self, incompatible=None, sample_rate_hz=50_000):
        super().__init__()
        self.incompatible = incompatible
        self.sample_rate_hz = sample_rate_hz

    def _rx(self, kind, payload, request=0):
        if kind == 129 and self.sample_rate_hz == 200_000:
            payload = struct.pack("<BBBBHHII", 0, 2, 1, 12, 512, 128, 0x56325335, 1)
        if kind == 130:
            payload = struct.pack("<IHBBIIHHI", 1, 1, 0, 12, self.sample_rate_hz, 1, 128, 0, 1)
        if kind == 129 and self.incompatible == "version":
            payload = payload[:1] + b"\x01" + payload[2:]
        if kind == 130 and self.incompatible == "caps":
            payload = struct.pack("<IHBBIIHHI", 1, 1, 0, 12, 25000, 1, 128, 0, 1)
        return super()._rx(kind, payload, request)

    def _end(self, **kwargs):
        # The firmware's accepted prefix does not define how many ADC samples
        # were actually produced. Do not replace unknown with prefix length.
        super()._end(reason=0, flags=3, produced=0)


class ClosedBackend:
    def __init__(self, factory, kwargs):
        self.factory, self.kwargs = factory, kwargs
        self.port, self.is_open, self._dtr = None, False, False
        self.peer = SelectedPeer(factory.incompatible, factory.sample_rate_hz)
        self.fail_close = False

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self.factory.calls.append(("dtr", self.is_open, value, threading.get_ident()))
        self._dtr = value

    def open(self):
        self.factory.calls.append(("open", self.port, self._dtr, threading.get_ident()))
        self.is_open = True

    def close(self):
        self.factory.calls.append(("close", self.is_open, self.fail_close, threading.get_ident()))
        if self.fail_close:
            raise OSError("deliberate retained handle")
        self.is_open = False

    def read(self, maximum):
        return self.peer.read(maximum)

    def write(self, data):
        return self.peer.write(data)


class FakeSerialFactory:
    def __init__(self, incompatible=None, sample_rate_hz=50_000):
        self.incompatible = incompatible
        self.sample_rate_hz = sample_rate_hz
        self.backends, self.calls = [], []

    def __call__(self, **kwargs):
        self.calls.append(("factory", kwargs["port"], False, threading.get_ident()))
        backend = ClosedBackend(self, kwargs)
        self.backends.append(backend)
        return backend


class V2StreamSerialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="v2-serial-")
        self.root = Path(self.folder.name)
        self.bridges = []
        self.guard = patch("motortester.transport._serial_factory",
                           side_effect=AssertionError("A real COM port must never be opened"))
        self.guard.start()

    def wait(self, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Bounded serial wait timed out")
            pump_events(5)

    def tearDown(self):
        for bridge, factory in self.bridges:
            for backend in factory.backends:
                backend.fail_close = False
            if bridge.metadata_error:
                bridge.abandon_context(bridge.metadata_error)
            bridge.shutdown()
            bridge.retry_close()
            self.wait(lambda: bridge._closed)
            bridge.deleteLater()
        pump_events(5)
        self.guard.stop()
        self.folder.cleanup()

    def make(self, incompatible=None, sample_rate_hz=50_000):
        factory = FakeSerialFactory(incompatible, sample_rate_hz)
        selection = SerialStreamSelection("EXPLICIT-TEST-PORT", "a" * 40, "b" * 64)
        bridge = StreamDeviceBridge(selection=selection, fake_backend_factory=factory,
                                    context=StreamContext("Сохранённый CH1", "ignition"))
        bridge.errors, bridge.saved, bridge.frames, bridge.finished_events = [], [], [], []
        bridge.error.connect(bridge.errors.append)
        bridge.recording_ready.connect(bridge.saved.append)
        bridge.live_ready.connect(lambda result: bridge.frames.__setitem__(slice(None), [result]))
        bridge.finished.connect(lambda: bridge.finished_events.append(True))
        self.bridges.append((bridge, factory))
        return bridge, factory

    def ready(self, sample_rate_hz=50_000):
        bridge, factory = self.make(sample_rate_hz=sample_rate_hz)
        self.assertTrue(bridge.connect_source())
        self.wait(lambda: bridge.state.ready and bridge.connection is not None)
        return bridge, factory

    def record_prefix(self, bridge, factory):
        self.assertTrue(bridge.start_live())
        self.wait(lambda: bridge.state.phase == "preview")
        backend = factory.backends[0]
        backend.peer.data()
        self.wait(lambda: bridge.state.validated_samples == 128)
        path = self.root / "raw.mtstream"
        revision = bridge.state.revision
        self.assertTrue(bridge.record(path))
        self.wait(lambda: bridge.state.phase == "waiting for boundary")
        backend.peer.data()
        backend.peer.data()
        self.wait(lambda: bridge.state.validated_samples == 384)
        self.assertEqual(bridge.state.revision, revision)
        return path, backend

    def test_connect_is_inert_then_dtr_hello_caps_without_start(self):
        bridge, factory = self.make()
        self.assertEqual(factory.calls, [])
        self.assertFalse(bridge.start_live())
        self.assertFalse(bridge.record(self.root / "forbidden.mtstream"))
        self.assertTrue(bridge.connect_source())
        self.assertFalse(bridge.connect_source())
        self.wait(lambda: bridge.state.ready and bridge.connection is not None)
        self.assertEqual([c[0] for c in factory.calls], ["factory", "dtr", "open"])
        self.assertEqual(factory.calls[1][1:3], (False, True))
        self.assertEqual(len({c[3] for c in factory.calls}), 1)
        self.assertNotEqual(factory.calls[0][3], threading.get_ident())
        peer = factory.backends[0].peer
        self.assertEqual([c[0] for c in peer.commands], [1, 2])
        self.assertIsNone(bridge.state.bridge.session)
        self.assertIsNone(bridge.state.bridge.identity)
        self.assertIsNone(bridge.state.bridge.storage)
        self.assertFalse(bridge.state.can_record)
        self.assertFalse(bridge.record(self.root / "forbidden.mtstream"))
        self.assertEqual(bridge.connection.observed_build_id, 0x1234)
        self.assertEqual(bridge.connection.selection.declared_artifact_sha256, "b" * 64)
        self.assertFalse(bridge.connection.image_verified)
        self.assertTrue(bridge.disconnect_source())
        self.wait(lambda: bridge.state.serial.handle_settled)
        self.assertIsNone(bridge.state.bridge.endpoint_first_fault)
        self.assertIsNone(bridge.state.error)
        self.assertEqual(bridge.errors, [])
        self.assertNotIn(8, [c[0] for c in peer.commands])
        self.assertFalse((self.root / "forbidden.mtstream").exists())
        bridge.shutdown()
        self.wait(lambda: bridge._closed)
        self.assertEqual(bridge.errors, [])

    def test_ready_read_failure_remains_visible_after_shutdown(self):
        bridge, factory = self.ready()
        backend = factory.backends[0]
        with patch.object(backend, "read", side_effect=OSError("injected READY read failure")):
            self.wait(lambda: bridge.state.bridge.endpoint_first_fault is not None)
            bridge._poll()
            first_fault = bridge.state.bridge.endpoint_first_fault
            self.assertEqual(first_fault.code, "transport")
            self.assertTrue(bridge.errors)
            self.assertEqual(bridge.state.validated_samples, 0)
            self.assertNotIn(8, [command[0] for command in backend.peer.commands])
            bridge.shutdown()
            self.wait(lambda: bridge._closed)
        self.assertEqual(bridge.state.bridge.endpoint_first_fault, first_fault)
        self.assertTrue(bridge.errors)
        self.assertFalse(backend.is_open)

    def test_incompatible_hello_or_caps_never_admits_start_or_writer(self):
        for incompatible in ("version", "caps"):
            with self.subTest(incompatible=incompatible):
                bridge, factory = self.make(incompatible)
                self.assertTrue(bridge.connect_source())
                self.wait(lambda: bridge.state.bridge is not None and
                          bridge.state.bridge.endpoint_first_fault is not None)
                bridge._poll()
                self.assertFalse(bridge.state.ready)
                self.assertFalse(bridge.start_live())
                self.assertFalse(bridge.record(self.root / (incompatible + ".mtstream")))
                self.assertIsNone(bridge.state.bridge.session)
                self.assertIsNone(bridge.state.bridge.storage)
                self.assertNotIn(8, [c[0] for c in factory.backends[0].peer.commands])
                self.assertTrue(any(incompatible in error for error in bridge.errors))
                bridge.shutdown()
                self.wait(lambda: bridge._closed)

    def test_nonzero_record_boundary_unknown_tail_and_durable_connection(self):
        bridge, factory = self.ready()
        path, backend = self.record_prefix(bridge, factory)
        bridge.stop()
        self.wait(lambda: bridge.saved)
        fresh = recover_attempt(path).recording
        self.assertEqual((fresh.first_sample_index, fresh.end_sample_index), (128, 384))
        self.assertEqual(fresh.read_raw(128, 256), waveform(2))
        self.assertEqual(fresh.identity.origin, "synthetic")
        self.assertIsNone(profile_for_identity(fresh.identity))
        self.assertIsNone(fresh.terminal.device_generated_end_sample_index)
        self.assertFalse(fresh.clean_stop_reported)
        self.assertEqual(fresh.terminal.reason, "stopped")
        self.assertIsNone(fresh.terminal.failure)
        self.assertIsNone(fresh.terminal.loss_samples)
        self.assertIsNotNone(fresh.terminal.stop_request_id)
        self.assertEqual(bridge.state.phase, "stopped unknown tail")
        self.assertIsNone(bridge.state.bridge.session.first_failure)
        self.assertIsNone(bridge.state.bridge.endpoint_first_fault)
        self.assertEqual(bridge.errors, [])
        self.assertFalse(bridge.start_live())  # Physical attempts need a fresh explicit connection.
        context = open_verified_context(path)
        self.assertEqual(context.context.input_profile, UNKNOWN_PROFILE)
        self.assertEqual(context.context.channel_name, "Сохранённый CH1")
        self.assertEqual(context.connection, bridge.connection)
        self.assertEqual(context.connection.accounting_domain, "unknown")
        self.assertEqual(json.loads(companion_path(path).read_text("utf-8"))["format_version"], 2)
        # A prepared-source revision must remain displayable after explicit START.
        self.wait(lambda: bool(bridge.frames))
        self.assertEqual(bridge.frames[0].source.revision, bridge.state.revision)
        bridge.shutdown()
        self.wait(lambda: bridge._closed)
        self.assertEqual(bridge.errors, [])
        # Preview has no journal to finalize; END/ACK still settles its owner.
        preview, preview_factory = self.ready()
        preview.start_live()
        self.wait(lambda: preview.state.phase == "preview")
        preview_factory.backends[0].peer.data()
        self.wait(lambda: preview.state.validated_samples == 128)
        preview.stop()
        self.wait(lambda: preview.state.phase == "stopped unknown tail")
        preview.shutdown()
        self.wait(lambda: preview._closed)
        self.assertEqual(preview.errors, [])
        self.assertIsNone(preview.state.bridge.endpoint_first_fault)

    def test_close_failure_retains_owner_and_requires_explicit_retry(self):
        bridge, factory = self.ready()
        backend = factory.backends[0]
        backend.fail_close = True
        self.assertTrue(bridge.shutdown())
        self.wait(lambda: bridge.state.can_retry_close)
        self.assertTrue(backend.is_open)
        self.assertFalse(bridge._closed)
        self.assertFalse(bridge.finished_events)
        self.assertFalse(bridge.connect_source())
        self.assertIsNone(bridge.state.bridge.endpoint_first_fault)
        bridge._poll()  # Deliver the receiver's already-published close error to Qt.
        self.assertTrue(any("Serial close unconfirmed:" in error for error in bridge.errors))
        closes = len([c for c in factory.calls if c[0] == "close"])
        bridge._poll()
        self.assertEqual(len([c for c in factory.calls if c[0] == "close"]), closes)
        backend.fail_close = False
        self.assertTrue(bridge.retry_close())
        self.wait(lambda: bridge._closed)
        self.assertFalse(backend.is_open)
        self.assertEqual(bridge.finished_events, [True])
        self.assertIsNone(bridge.state.bridge.endpoint_first_fault)

    def test_200k_record_reopen_export_and_companion_rate_binding(self):
        bridge, factory = self.ready(200_000)
        self.assertEqual(bridge.connection.observed_caps[4], 200_000)
        self.assertEqual(bridge.connection.observed_build_id, 0x56325335)
        self.assertFalse(bridge.connection.image_verified)
        path, _ = self.record_prefix(bridge, factory)
        config = bridge.state.config
        self.assertEqual((config.pre_samples, config.post_samples, config.baseline_samples,
                          config.holdoff_samples, config.max_event_samples), (200, 600, 100, 400, 2000))
        bridge.stop()
        self.wait(lambda: bridge.saved)
        recording = recover_attempt(path).recording
        context = open_verified_context(path)
        self.assertEqual(recording.identity.nominal_fs_hz, 200_000)
        self.assertEqual(recording.identity.origin, "synthetic")
        self.assertEqual(recording.read_raw(128, 256), waveform(2))
        self.assertIsNone(profile_for_identity(recording.identity))
        self.assertIsNone(recording.terminal.loss_samples)
        self.assertEqual(context.connection.observed_caps[4], 200_000)
        exported = self.root / "200k.csv"
        export_stream(exported, recording, context)
        with exported.open(newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 256)
        self.assertEqual(float(rows[0]["time_from_recording_start_s"]), 0)
        self.assertEqual(float(rows[1]["time_from_recording_start_s"]), 0.000005)
        self.assertEqual(float(rows[-1]["time_from_recording_start_s"]), 255 / 200_000)
        receipt = json.loads(exported.with_suffix(".csv.json").read_text("utf-8"))
        self.assertEqual(receipt["identity"]["nominal_fs_hz"], 200_000)
        # Reusing an old 50k connection next to 200k raw must be rejected,
        # even though each rate is independently supported.
        sidecar = companion_path(path)
        value = json.loads(sidecar.read_text("utf-8"))
        value["connection"]["observed_caps"][4] = 50_000
        sidecar.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "не соответствует журналу"):
            open_verified_context(path)

    def test_companion_retry_keeps_exact_connection_and_raw_prefix(self):
        bridge, factory = self.ready()
        path, _ = self.record_prefix(bridge, factory)
        with patch("motortester.v2.stream_device._write_context", side_effect=OSError("companion denied")):
            bridge.shutdown()
            self.wait(lambda: bridge.metadata_error is not None)
            failure = bridge.metadata_error
            self.assertEqual(failure.connection, bridge.connection)
            self.assertFalse(bridge.finished_events)
            raw_before = path.read_bytes()
        self.assertTrue(bridge.retry_context(failure))
        self.wait(lambda: bridge._closed)
        self.assertEqual(path.read_bytes(), raw_before)
        self.assertEqual(open_verified_context(path).connection, failure.connection)

    def test_prepared_stop_cancels_queued_start_and_device_identity_is_not_str1(self):
        now = [0]
        factory = FakeSerialFactory()
        peer = SerialStreamPeer(SerialSettings("MANUAL-TEST"), fake_backend_factory=factory)
        controller = StreamController(peer, event_config=CONFIG, threaded=False,
            clock=lambda: now[0], managed_peer=True, device_context=DeviceStreamContext("injected-test"))
        try:
            self.assertTrue(controller.connect())
            controller.service(0)
            self.assertFalse(controller.preview())
            self.assertTrue(controller.prepare())
            for _ in range(8):
                controller.service(0)
            self.assertTrue(controller.snapshot().ready)
            self.assertTrue(controller.preview())
            controller.stop()
            controller.service(0)
            self.assertNotIn(8, [c[0] for c in factory.backends[0].peer.commands])
            self.assertIsNone(controller.snapshot().bridge.session)
        finally:
            controller.close()
            controller.service(0)
            self.assertTrue(controller.join(0))
            self.assertIsNone(controller.snapshot().bridge.endpoint_first_fault)
            self.assertIsNone(controller.snapshot().error)
        # Pure identity construction is not a physical capture test.
        origin, metadata = device_context_identity(DeviceStreamContext(), 0xabcdef01)
        identity = StreamIdentity("declared-model", 3, 1, 50000, origin, *metadata)
        self.assertEqual(identity.origin, "device")
        self.assertEqual(identity.firmware_version, "build:abcdef01")
        self.assertIsNone(profile_for_identity(identity))
        self.assertNotIn("31b936", repr(identity))
        with self.assertRaises(StreamError):
            replace(identity, origin="synthetic")


if __name__ == "__main__":
    unittest.main()
