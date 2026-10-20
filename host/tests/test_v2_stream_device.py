"""Bounded synthetic V2 stream integration; real serial is forbidden."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore

from motortester.stream_recording import recover_attempt
from motortester.stream_controller import ControllerStatus
from motortester.stream_wire import Kind, decode_frame, decode_payload, encode_frame
from motortester.v2.core import UNKNOWN_PROFILE
from motortester.v2.stream_demo import PacedStreamPeer
from motortester.v2.stream_device import (
    StreamContext, StreamDeviceBridge, companion_path, open_verified_context)
from qt_test_support import pump_events


class V2StreamDeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def setUp(self):
        self.folder = None
        self.bridges = []
        self.guard = patch("motortester.transport._serial_factory",
                           side_effect=AssertionError("Real COM forbidden"))
        self.guard.start()

    @property
    def root(self):
        if self.folder is None:
            self.folder = tempfile.TemporaryDirectory(prefix="v2-stream-")
        return Path(self.folder.name)

    def tearDown(self):
        for bridge in self.bridges:
            if bridge.metadata_error is not None:
                bridge.abandon_context(bridge.metadata_error)
            bridge.shutdown()
            self.wait(lambda: bridge._closed)
            bridge.deleteLater()
        pump_events(5)
        self.guard.stop()
        if self.folder is not None:
            self.folder.cleanup()

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("Bounded stream wait timed out")
            pump_events(5)

    def bridge(self, **options):
        bridge = StreamDeviceBridge(**options)
        bridge.saved, bridge.errors, bridge.frames = [], [], []
        bridge.recording_ready.connect(bridge.saved.append)
        bridge.error.connect(bridge.errors.append)
        # Keep only the newest GUI frame; never accumulate a data stream in Qt.
        bridge.live_ready.connect(lambda frame: bridge.frames.__setitem__(slice(None), [frame]))
        self.bridges.append(bridge)
        return bridge

    def test_peer_pacing_and_overrun_are_explicit(self):
        now = [0.]
        peer = PacedStreamPeer(clock=lambda: now[0])
        def command(kind, request, payload, nonce=123):
            frame = encode_frame(kind, 0 if kind == Kind.HELLO else nonce,
                                 request, request, payload)
            self.assertEqual(peer.write(frame), len(frame))
            return decode_payload(decode_frame(peer.read(544)))
        command(Kind.HELLO, 1, struct.pack("<Q", 123))
        command(Kind.GET_CAPS, 2, b"")
        command(Kind.START, 3, struct.pack("<HH", 1, 0))
        self.assertEqual(peer.read(544), b"")
        now[0] = .00256
        block = decode_payload(decode_frame(peer.read(544)))
        self.assertEqual((block.first_index, len(block.samples)), (0, 128))
        self.assertEqual(block.samples[0], 2048)
        now[0] = .1  # GUI scheduling delay is allowed, without skipping indices.
        block = decode_payload(decode_frame(peer.read(544)))
        self.assertEqual((block.first_index, len(block.samples)), (128, 128))
        self.assertEqual(block.samples, tuple(peer._sample(i) for i in range(128, 256)))
        self.assertEqual(peer.max_backlog_samples, 32768)
        self.assertEqual(len(peer._period_raw), 400)
        now[0] = 1.
        terminal = decode_payload(decode_frame(peer.read(544)))
        self.assertEqual(terminal.prefix_end, 256)
        self.assertEqual(terminal.produced_end, 50000)
        self.assertEqual((terminal.reason, terminal.flags), (1, 2))
        self.assertLessEqual(len(peer._incoming), 2048)

    def test_source_admission_rejects_queued_and_late_old_frames(self):
        # Hold the receiver before _begin: command admission has succeeded but
        # its status still carries the previous source revision.
        for direct_record in (False, True):
            with self.subTest(direct_record=direct_record):
                controller = Mock()
                state = [ControllerStatus(revision=7,
                         bridge=SimpleNamespace(identity=object()))]
                controller.snapshot.side_effect = lambda: state[0]
                def admit(*args):
                    state[0] = replace(state[0], can_open=False,
                                       can_preview=False, can_record=False)
                    return True
                controller.preview.side_effect = admit
                controller.record.side_effect = admit
                with patch("motortester.v2.stream_device.StreamController",
                           return_value=controller):
                    bridge = StreamDeviceBridge()
                bridge._timer.stop()
                frames = []
                bridge.live_ready.connect(frames.append)
                old = SimpleNamespace(source=SimpleNamespace(revision=7))
                current = SimpleNamespace(source=SimpleNamespace(revision=8))
                try:
                    bridge._deliver(old)  # Already queued before admission.
                    self.assertIs(bridge._latest, old)
                    self.assertTrue(bridge.record("unused.mtstream") if direct_record
                                    else bridge.start_live())
                    self.assertIsNone(bridge._latest)
                    bridge._deliver(old)  # A worker finishes after admission.
                    bridge._poll()
                    self.assertEqual(frames, [])
                    controller.bind_display.assert_not_called()
                    bridge.stop()  # No receiver advance; old revision persists.
                    bridge._deliver(old)
                    bridge._poll()
                    self.assertEqual(frames, [])
                    # A genuinely new source is now allowed.
                    state[0] = replace(state[0], revision=8, phase="preview",
                                       can_record=True)
                    bridge._deliver(current)
                    bridge._poll()
                    self.assertEqual(frames, [current])
                    if not direct_record:
                        # Preview -> Record belongs to this same source.
                        bridge._deliver(current)
                        self.assertTrue(bridge.record("same-generation.mtstream"))
                        bridge._poll()
                        self.assertEqual(frames, [current, current])
                finally:
                    # The fake controller owns no workers, transport or files.
                    bridge.deleteLater()

    def test_preview_record_nonzero_r_ring_eviction_and_verified_context(self):
        context = StreamContext(channel_name="Непрерывный CH1", ui_profile="ignition")
        bridge = self.bridge(context=context)
        self.assertTrue(bridge.start_live())
        self.wait(lambda: bridge.state.validated_samples >= 2048)
        path = self.root / "indexed.mtstream"
        self.assertTrue(bridge.record(path))
        self.assertFalse(bridge.record(self.root / "duplicate.mtstream"))
        # Presentation metadata is captured when Record is admitted.
        bridge.context = replace(context, channel_name="Следующая попытка")
        self.wait(lambda: bridge.state.validated_samples >= 70_000)
        self.assertEqual(bridge.state.ring_samples, 65536)
        self.assertGreater(bridge.state.raw_available_start, 0)
        self.assertTrue(bridge.stop())
        self.wait(lambda: bool(bridge.saved))
        recording = recover_attempt(path).recording
        self.assertGreater(recording.first_sample_index, 0)
        self.assertLess(recording.first_sample_index, bridge.state.raw_available_start)
        self.assertEqual(recording.identity.origin, "synthetic")
        self.assertTrue(recording.clean_stop_reported)
        raw = recording.read_samples(recording.first_sample_index, 256)
        expected = PacedStreamPeer("ignition")
        self.assertEqual(raw, tuple(expected._sample(i) for i in
                         range(recording.first_sample_index, recording.first_sample_index + 256)))
        loaded = open_verified_context(path)
        self.assertTrue(loaded.companion_present)
        self.assertEqual(loaded.context, context)
        self.assertEqual(loaded.context.input_profile, UNKNOWN_PROFILE)
        self.assertEqual(bridge.errors, [])
        self.assertFalse((self.root / "duplicate.mtstream").exists())
        self.assertTrue(bridge.start_live())  # Clean Stop permits a new generation.
        self.wait(lambda: bridge.state.phase == "preview")

    def test_direct_record_unknown_tail_preserves_prefix_and_blocks_restart(self):
        bridge = self.bridge(peer=PacedStreamPeer(unknown_tail=True))
        path = self.root / "unknown.mtstream"
        self.assertTrue(bridge.record(path))
        self.wait(lambda: bridge.state.validated_samples >= 2048)
        bridge.stop()
        self.wait(lambda: bool(bridge.saved))
        recording = recover_attempt(path).recording
        self.assertEqual(recording.first_sample_index, 0)
        self.assertGreater(recording.end_sample_index, 0)
        self.assertFalse(recording.clean_stop_reported)
        self.assertIsNone(recording.terminal.loss_samples)
        self.assertIsNone(recording.terminal.device_generated_end_sample_index)
        self.assertTrue(recording.terminal.terminal_observed)
        self.assertFalse(bridge.start_live())
        self.assertEqual(open_verified_context(path).context.input_profile, UNKNOWN_PROFILE)

    def test_companion_failure_and_hash_mismatch_never_claim_success(self):
        bridge = self.bridge()
        path = self.root / "kept.mtstream"
        sidecar = companion_path(path)
        sidecar.write_bytes(b"existing user context")
        self.assertTrue(bridge.record(path))
        self.wait(lambda: bridge.state.validated_samples >= 1024)
        bridge.stop()
        self.wait(lambda: bool(bridge.errors))
        self.assertEqual(bridge.saved, [])
        self.assertEqual(sidecar.read_bytes(), b"existing user context")
        self.assertGreater(recover_attempt(path).recording.end_sample_index, 0)
        legacy = self.root / "without-sidecar.mtstream"
        legacy.write_bytes(path.read_bytes())
        loaded = open_verified_context(legacy)
        self.assertFalse(loaded.companion_present)
        self.assertEqual(loaded.context.input_profile, UNKNOWN_PROFILE)
        from motortester.v2.stream_device import _write_context
        _write_context(legacy, StreamContext(), recover_attempt(legacy).preparation.identity)
        value = json.loads(companion_path(legacy).read_text(encoding="utf-8"))
        value["journal_sha256"] = "0" * 64
        companion_path(legacy).write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "не соответствует"):
            open_verified_context(legacy)
        occupied = self.root / "occupied.mtstream"
        original = path.read_bytes()
        occupied.write_bytes(original)
        another = self.bridge()
        self.assertTrue(another.record(occupied))
        self.wait(lambda: another.metadata_error is not None)
        self.assertEqual(another.saved, [])
        self.assertEqual(occupied.read_bytes(), original)
        self.assertFalse(companion_path(occupied).exists())

    def test_shutdown_context_failure_requires_exact_retry_or_abandon(self):
        bridge = self.bridge(context=StreamContext(channel_name="Сохранить при закрытии"))
        finished = []
        bridge.finished.connect(lambda: finished.append(True))
        path = self.root / "retry.mtstream"
        with patch("motortester.v2.stream_device._write_context",
                   side_effect=OSError("synthetic denied")):
            self.assertTrue(bridge.record(path))
            self.wait(lambda: bridge.state.validated_samples >= 1024)
            self.assertTrue(bridge.shutdown())
            self.wait(lambda: bridge.metadata_error is not None)
            failure = bridge.metadata_error
            pump_events(30)
            self.assertEqual(finished, [])
            self.assertFalse(bridge._closed)
            self.assertTrue(bridge.metadata_pending)
            self.assertFalse(bridge.start_live())
            self.assertFalse(bridge.retry_context(replace(failure)))
            self.assertFalse(bridge.abandon_context(replace(failure)))
            self.assertTrue(bridge.cancel_shutdown())
            self.assertTrue(bridge.shutdown())
            self.assertTrue(bridge.retry_context(failure))
            self.wait(lambda: bridge.metadata_error is not None)
            renewed = bridge.metadata_error
            self.assertIsNot(renewed, failure)
            self.assertFalse(bridge.abandon_context(failure))
        original = path.read_bytes()
        self.assertTrue(bridge.retry_context(renewed))
        self.wait(lambda: bridge._closed)
        self.assertEqual(finished, [True])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(open_verified_context(path).context.channel_name,
                         "Сохранить при закрытии")
        self.assertEqual(bridge.saved, [str(path)])
        self.assertFalse(bridge.abandon_context(renewed))

        other = self.bridge()
        dropped = self.root / "abandon.mtstream"
        sidecar = companion_path(dropped)
        sidecar.write_bytes(b"existing user context")
        self.assertTrue(other.record(dropped))
        self.wait(lambda: other.state.validated_samples >= 1024)
        other.shutdown()
        self.wait(lambda: other.metadata_error is not None)
        original = dropped.read_bytes()
        self.assertTrue(other.abandon_context(other.metadata_error))
        self.wait(lambda: other._closed)
        self.assertEqual(dropped.read_bytes(), original)
        self.assertEqual(sidecar.read_bytes(), b"existing user context")
        self.assertEqual(other.saved, [])


if __name__ == "__main__":
    unittest.main()
