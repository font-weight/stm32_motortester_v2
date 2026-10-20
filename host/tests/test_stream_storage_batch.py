"""Bounded storage jobs; exact raw/receipts, without Qt or a physical device."""
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from motortester.stream_bridge import StreamBridge
from motortester.stream_model import FailureEvidence, StreamError
from motortester.stream_recording import recover_attempt
from motortester.stream_session import JobCompletion, JobFailure, SessionLimits
from test_stream_bridge import Peer, samples
from test_stream_session import TOKEN, block, completed, ready_preview


class StorageBatchTests(unittest.TestCase):
    def test_pending_prefix_is_bounded_and_new_data_stays_charged(self):
        first = 2**53 + 17
        limits = SessionLimits(max_raw_bytes=32 * 1024, max_raw_items=66)
        session = ready_preview(first, limits)
        # Even with a backlog, selection of R binds exactly the first wire block.
        for n in range(3):
            session.receive(block(first + 128 * n, 128))
        bind = session.next_storage_job()
        self.assertEqual((bind.kind, bind.block.sample_count), ("bind_first_block", 128))
        completed(session, bind)
        for n in range(3, 66):
            session.receive(block(first + 128 * n, 128))
        job = session.next_storage_job()
        self.assertEqual((job.kind, job.block.first_sample_index, job.block.sample_count),
                         ("append", first + 128, 8192))
        self.assertIsNone(session.next_storage_job())
        # The exact reserved job is immutable when another DATA arrives.
        digest = job.sha256
        session.receive(block(first + 66 * 128, 128))
        pending = session.snapshot()
        self.assertEqual((pending.raw_items_held, pending.raw_bytes_held), (66, 66 * 256))
        self.assertEqual(pending.accepted_end_sample_index, first + 128)
        self.assertEqual(job.sha256, digest)
        completed(session, job)
        after = session.snapshot()
        self.assertEqual(after.accepted_end_sample_index, first + 65 * 128)
        self.assertEqual((after.raw_items_held, after.raw_bytes_held), (2, 512))
        tail = session.next_storage_job()
        self.assertEqual((tail.block.first_sample_index, tail.block.sample_count),
                         (first + 65 * 128, 256))
        expected_raw = b"".join(block(first + 128 * n, 128).raw_u16le for n in range(67))
        self.assertEqual(tail.prefix_sha256,
                         hashlib.sha256(expected_raw).hexdigest())
        completed(session, tail)
        self.assertEqual(session.snapshot().raw_items_held, 0)

    def test_failure_or_inexact_receipt_never_advances_or_consumes_raw(self):
        for fault in ("writer", "wrong_end", "wrong_hash", "changed_queue", "duplicate"):
            with self.subTest(fault=fault):
                session = ready_preview()
                session.receive(block(0, 128))
                completed(session)
                session.receive(block(128, 128))
                session.receive(block(256, 128))
                job = session.next_storage_job()
                before = session.snapshot()
                prefix = session._accepted_hash.hexdigest()
                receipt = JobCompletion.for_job(
                    job, token_id=TOKEN, accepted_end=384,
                    checkpointed_end=before.checkpointed_end_sample_index)
                if fault == "writer":
                    session.storage_failed(JobFailure.for_job(
                        job, FailureEvidence("host_io", "controlled writer failure")))
                elif fault == "duplicate":
                    session.storage_completed(receipt)
                    before = session.snapshot()
                    prefix = session._accepted_hash.hexdigest()
                    with self.assertRaises(StreamError):
                        session.storage_completed(receipt)
                else:
                    if fault == "wrong_end":
                        receipt = replace(receipt, accepted_end_sample_index=385)
                    elif fault == "wrong_hash":
                        receipt = replace(receipt, job_sha256="0" * 64)
                    else:
                        # Same indexes/length cannot substitute different raw.
                        original = session._queue[0]
                        changed = bytes([original.raw_u16le[0] ^ 1]) + original.raw_u16le[1:]
                        session._queue[0] = replace(original, raw_u16le=changed)
                    with self.assertRaises(StreamError):
                        session.storage_completed(receipt)
                after = session.snapshot()
                for field in ("accepted_end_sample_index", "checkpointed_end_sample_index",
                              "raw_items_held", "raw_bytes_held"):
                    self.assertEqual(getattr(after, field), getattr(before, field), field)
                self.assertEqual(session._accepted_hash.hexdigest(), prefix)

    def test_real_bridge_roundtrip_keeps_nonzero_r_and_complete_raw(self):
        with tempfile.TemporaryDirectory(prefix="stream-batch-") as folder:
            path = Path(folder) / "raw.mtstream"
            bridge = StreamBridge("batch-attempt")
            peer = Peer(bridge)

            def disk_once():
                operation = bridge.dispatch_storage(peer.now)
                if operation is not None:
                    bridge.storage_tick(peer.now)
                return operation

            def drain():
                for _ in range(16):
                    if disk_once() is None:
                        return
                self.fail("bounded batch drain did not settle")

            try:
                peer.negotiate()
                bridge.preview(peer.now)
                peer.started()
                for n in range(3):
                    peer.data(samples(seed=n * 17))
                first = len(peer.raw) // 2
                bridge.record(path, "batch-recording", peer.now)
                drain()  # Actual prepare; pre-record preview is excluded.
                for n in range(131):
                    peer.data(samples(seed=100 + n * 19))
                disk_once()  # bind_first_block remains exactly 128 samples.
                self.assertEqual(bridge.snapshot().session.accepted_end_sample_index,
                                 first + 128)
                bridge.dispatch_storage(peer.now)
                for n in range(2):
                    peer.data(samples(seed=3000 + n * 31))
                bridge.storage_tick(peer.now)
                self.assertEqual(bridge.snapshot().session.accepted_end_sample_index,
                                 first + 128 + 8192)
                drain()
                peer.stop()
                peer.end()
                peer.ack()
                drain()
                state = bridge.snapshot()
                self.assertTrue(state.session.clean_completion_reported)
                expected = peer.raw[first * 2:]
                self.assertEqual(state.storage.selected_sha256,
                                 hashlib.sha256(expected).hexdigest())
                recovered = recover_attempt(path)
                self.assertIsNone(recovered.recovery_issue)
                recording = recovered.recording
                self.assertTrue(recording.clean_stop_reported)
                self.assertEqual(recording.first_sample_index, first)
                self.assertEqual(recording.end_sample_index, len(peer.raw) // 2)
                self.assertEqual(recording.read_raw(first, len(expected) // 2), expected)
            finally:
                bridge.close(peer.now)
                if bridge.disk_executor is not None:
                    for _ in range(3):
                        bridge.disk_executor.execute_one()
                        bridge.accept_storage_completion(peer.now)
                        if bridge.snapshot().mailbox.close_acknowledged is not None:
                            break


if __name__ == "__main__":
    unittest.main()
