"""Requested Stop with an unknown ADC tail: finite encoded bytes, no real COM."""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from motortester import stream_endpoint as endpoint
from motortester.stream_controller import StreamController
from motortester.stream_recording import recover_attempt
from test_stream_controller import CONFIG, EncodedPeer, waveform
from test_stream_endpoint import ready, data, end, ack, send


class HoldUnknownAckPeer(EncodedPeer):
    def _end(self, **kwargs):
        self.end_sequence = self.sequence
        super()._end(reason=0, flags=3, produced=0, acknowledge=False)

    def acknowledge_stop(self, *, wrong_terminal=False):
        self._rx(133, struct.pack(
            "<IQII", self.generation, len(self.raw) // 2,
            self.end_sequence + int(wrong_terminal), 3), self.stop_request)


class UnknownTailStopTests(unittest.TestCase):
    def test_real_terminal_faults_and_first_failures_are_not_softened(self):
        # flags7 includes unknown quiescence; flags2 with known production is a
        # stated loss. Neither is the ordinary Stop/unknown-produced contract.
        for reason, flags, produced in ((0, 7, 0), (0, 2, 256), (1, 3, 0), (3, 3, 0)):
            with self.subTest(reason=reason, flags=flags):
                ep = ready()
                ep.receive(data(ep), 0)
                ep.stop(0)
                send(ep)
                ep.receive(end(ep, reason=reason, flags=flags, produced=produced), 1)
                self.assertEqual(ep.first_fault.code, "device_" + str(reason))
                if flags & 4:
                    self.assertEqual(ep.state, endpoint.State.RECOVERING)
                    self.assertEqual(ep.receive(ack(ep, request=4), 2), ())
                else:
                    ep.receive(ack(ep), 2)
                    self.assertEqual(ep.state, endpoint.State.NEEDS_HELLO)
                    self.assertIsNotNone(ep.first_fault)

        for prior in ("storage", "capacity", "transport"):
            with self.subTest(prior=prior):
                ep = ready()
                ep.receive(data(ep), 0)
                ep.stop(0)
                send(ep)
                if prior != "transport":
                    ep.adapter_fault(prior, 0)
                    original = ep.first_fault
                ep.receive(end(ep, flags=3), 1)
                if prior == "transport":
                    self.assertIsNone(ep.first_fault)
                    ep.transport_fault(2)
                    original = ep.first_fault
                    self.assertIsNotNone(original)
                else:
                    ep.receive(ack(ep), 2)
                self.assertIs(ep.first_fault, original)
                self.assertEqual(ep.received_end, 128)

    def test_record_waits_for_matching_ack_and_preserves_unknown_raw(self):
        for reply in ("matching", "missing", "wrong", "storage", "late"):
            with self.subTest(reply=reply), tempfile.TemporaryDirectory(
                    prefix="v2-stop-") as folder, patch(
                        "motortester.transport._serial_factory",
                        side_effect=AssertionError("Real COM forbidden")):
                now = [0]
                peer = HoldUnknownAckPeer()
                controller = StreamController(
                    peer, event_config=CONFIG, threaded=False, clock=lambda: now[0])
                path = Path(folder) / "selected.mtstream"

                def advance(predicate, *, disk=True):
                    for _ in range(100):
                        if predicate(controller.snapshot()):
                            return controller.snapshot()
                        controller.service(now[0])
                        if disk:
                            controller.execute_disk_once()
                    self.fail("Finite scheduler exhausted: " + repr(controller.snapshot()))

                try:
                    self.assertTrue(controller.preview())
                    advance(lambda s: s.phase == "preview")
                    peer.data()
                    advance(lambda s: s.validated_samples == 128)
                    self.assertTrue(controller.record(str(path)))
                    advance(lambda s: s.phase == "waiting for boundary")
                    peer.data()
                    peer.data()
                    advance(lambda s: s.bridge.session.accepted_end_sample_index == 384)
                    controller.stop()
                    state = advance(lambda s: s.bridge.source_terminal is not None)
                    self.assertIsNone(state.bridge.endpoint_first_fault)
                    self.assertIsNone(state.bridge.session.first_failure)
                    self.assertIsNone(state.bridge.session.stop_acknowledgement)
                    self.assertFalse(state.bridge.session.finalization_started)
                    self.assertFalse(state.can_open)
                    self.assertEqual(state.phase, "draining")
                    self.assertIsNone(state.bridge.source_terminal.terminal.produced_end)

                    if reply == "missing":
                        now[0] = endpoint.REQUEST_MS
                    else:
                        peer.acknowledge_stop(wrong_terminal=reply == "wrong")
                    if reply == "storage":
                        with patch("motortester.stream_recording.StreamWriter.finish",
                                   side_effect=OSError("deliberate finish failure")):
                            state = advance(lambda s: s.can_open)
                        self.assertEqual(state.phase, "fault")
                        self.assertEqual(state.bridge.storage.failure.code, "host_io")
                        self.assertFalse(state.bridge.session.clean_completion_reported)
                        self.assertIsNotNone(state.bridge.session.first_failure)
                        continue
                    if reply == "late":
                        advance(lambda s: s.bridge.session.finalization_started, disk=False)
                        # The immutable finish job is already issued. Unexpected
                        # DATA after END/ACK must remain visible as a late fault.
                        peer.data()
                        controller.service(now[0])
                        self.assertIsNotNone(controller.snapshot().bridge.late_fault)
                    state = advance(lambda s: s.can_open)
                    fresh = recover_attempt(path).recording
                    self.assertEqual((fresh.first_sample_index, fresh.end_sample_index), (128, 384))
                    self.assertEqual(fresh.read_raw(128, 256), waveform(2))
                    self.assertIsNone(fresh.terminal.device_generated_end_sample_index)
                    self.assertIsNone(fresh.terminal.loss_samples)
                    self.assertFalse(fresh.clean_stop_reported)
                    if reply in ("matching", "late"):
                        if reply == "late":
                            self.assertEqual(state.phase, "fault")
                            self.assertIsNotNone(state.bridge.late_fault)
                            # The issued footer is immutable, not rewritten to
                            # erase or invent the separately retained late cause.
                        else:
                            self.assertEqual(state.phase, "stopped unknown tail")
                            self.assertIsNone(state.bridge.endpoint_first_fault)
                        self.assertIsNone(fresh.terminal.failure)
                        self.assertEqual(fresh.terminal.reason, "stopped")
                        self.assertEqual(fresh.terminal.stop_request_id, peer.stop_request)
                    else:
                        self.assertEqual(state.phase, "fault")
                        code = "stop_timeout" if reply == "missing" else "ack_terminal"
                        self.assertEqual(state.bridge.endpoint_first_fault.code, code)
                        self.assertIsNotNone(fresh.terminal.failure)
                        self.assertIsNone(fresh.terminal.stop_request_id)
                finally:
                    controller.close()
                    for _ in range(4):
                        controller.service(now[0])
                        controller.execute_disk_once()
                    self.assertTrue(controller.join(0))


if __name__ == "__main__":
    unittest.main()
