"""Small independent wire/file contract checks for selectable ADC12/retained10."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from motortester import stream_endpoint as ep
from motortester import stream_recording as journal
from motortester.stream_model import (StreamIdentity, StreamStart, StreamBlock,
                                      StreamTerminal, StreamError, LEGACY_IDENTITY_FIELDS)
from motortester.stream_wire import (Kind, MODE_REVISION, decode_frame, decode_payload,
                                    pack10, unpack10, WireError)
from motortester.v2.stream_files import open_stream, export_stream
from motortester.v2.stream_device import StreamContext, _write_context
from motortester.stream_view import EventDetector
from motortester.v2.stream_device import default_event_config


def literal(kind, payload=b"", *, revision=3, nonce=22, sequence=1, request=0):
    # Independent COBS/CRC envelope oracle, separate from the production encoder.
    raw = struct.pack("<BBBBHHQII", 0, revision, kind, 0, len(payload), 0, nonce, sequence, request) + payload
    raw += struct.pack("<I", zlib.crc32(raw))
    result = bytearray()
    for run in raw.split(b"\0"):
        while len(run) >= 254:
            result.extend(b"\xff" + run[:254])
            run = run[254:]
        result.extend(bytes([len(run) + 1]) + run)
    return bytes(result) + b"\0"


def accepted(endpoint):
    offer, = endpoint.next_write(0)
    endpoint.observe_write(offer.token, len(offer.data), 0)
    return decode_frame(offer.data)


def negotiate(rate=150_000, *, legacy_rate=None):
    endpoint = ep.Endpoint(rate)
    endpoint.hello(11, 0)
    request = accepted(endpoint)
    assert request.revision == "0.2"
    events = endpoint.receive(literal(129, struct.pack("<BBBBHHII", 0, 2, 1, 12, 512, 128,
        0x56325343, 1 if legacy_rate else 3), revision=2, nonce=11, request=1), 0)
    if legacy_rate is None:
        assert isinstance(events[0], ep.ModeRequired)
        assert isinstance(endpoint.plan_start(0)[0], ep.Refused)
        endpoint.select_mode(22, 0)
        request = accepted(endpoint)
        assert request.revision == "0.3"
        mode = {50_000: 1, 100_000: 2, 150_000: 3}[rate]
        assert request.payload == struct.pack("<QHH", 22, mode, 0)
        endpoint.receive(literal(129, struct.pack("<BBBBHHII", 0, 3, 1, 12, 512, 128,
            0x56325343, 1), request=1), 0)
        caps = struct.pack("<IHBBIIHBBI", mode, mode, 0, 12, rate, 1, 128,
                           10 if mode == 3 else 12, 2 if mode == 3 else 1, 1)
    else:
        caps = struct.pack("<IHBBIIHHI", 1, 1, 0, 12, legacy_rate, 1, 128, 0, 1)
    endpoint.get_caps(0)
    accepted(endpoint)
    endpoint.receive(literal(130, caps, revision=2 if legacy_rate else 3,
        nonce=11 if legacy_rate else 22, sequence=2, request=2), 0)
    return endpoint


class StreamModesTests(unittest.TestCase):
    def test_independent_vectors_all_remainders_and_padding(self):
        # q10=(0,1,1023,341), supplied as literal byte oracles, not pack10 outputs.
        vectors = [(b"\x00\x00", (0,)), (b"\x00\x04\x00", (0, 4)),
                   (b"\x00\x04\xf0\x3f", (0, 4, 4092)),
                   (b"\x00\x04\xf0\x7f\x55", (0, 4, 4092, 1364))]
        for packed, codes in vectors:
            self.assertEqual(unpack10(packed, len(codes)), codes)
            self.assertEqual(pack10(codes), packed)
            payload = struct.pack("<IIQHH", 3, 3, 0, len(codes), 0) + packed
            data = decode_payload(decode_frame(literal(152, payload)))
            self.assertEqual(data.samples, codes)
            self.assertEqual(data.raw_samples, struct.pack("<" + "H" * len(codes), *codes))
            if len(codes) % 4:
                corrupt = packed[:-1] + bytes([packed[-1] | 0x80])
                with self.assertRaises(WireError):
                    unpack10(corrupt, len(codes))
        for bad in ((4095,), (-4,), (4096,)):
            with self.assertRaises(WireError):
                pack10(bad)

    def test_discovery_mode_binding_and_legacy_mismatch(self):
        for rate, mode in ((50_000, 1), (100_000, 2), (150_000, 3)):
            endpoint = negotiate(rate)
            plan, = endpoint.plan_start(0)
            endpoint.start(0, plan=plan)
            request = accepted(endpoint)
            self.assertEqual(request.payload, struct.pack("<I", mode))
            self.assertIsInstance(endpoint.select_mode(33, 0)[0], ep.Refused)
            endpoint.receive(literal(136, struct.pack("<IIQ", 3, mode, 0), sequence=3, request=3), 0)
            self.assertEqual(endpoint.state, ep.State.STREAMING)
            # Bounded valid old nonce cannot publish or change accepted mode.
            endpoint.receive(literal(136, struct.pack("<IIQ", 3, 1, 0), revision=2,
                                      nonce=11, sequence=3, request=3), 0)
            self.assertIsNone(endpoint.first_fault)
            endpoint.receive(literal(152, struct.pack("<IIQHHH", 3, 1, 0, 1, 0, 7),
                                      revision=2, sequence=4), 0)
            self.assertEqual(endpoint.first_fault.code, "version")
        for rate in (50_000, 100_000, 200_000):
            endpoint = negotiate(rate, legacy_rate=rate)
            self.assertEqual(endpoint.state, ep.State.STOPPED)
            self.assertIsNone(endpoint.first_fault)
        endpoint = negotiate(150_000, legacy_rate=100_000)
        self.assertEqual(endpoint.first_fault.code, "selected_rate_mismatch_fixed_100000")
        self.assertIsInstance(endpoint.plan_start(0)[0], ep.Refused)
        endpoint = negotiate()
        stale_unknown = literal(152, b"unknown payload", revision=4, nonce=11, sequence=3)
        endpoint.receive(stale_unknown, 0)
        self.assertIsNone(endpoint.first_fault)
        endpoint.receive(literal(152, b"unknown payload", revision=4, sequence=3), 0)
        self.assertEqual(endpoint.first_fault.code, "version")
        endpoint = negotiate()
        endpoint.start(0); accepted(endpoint)
        endpoint.receive(literal(136, struct.pack("<IIQ", 3, 3, 0), sequence=3, request=3), 0)
        corrupted = bytearray(stale_unknown); corrupted[-2] ^= 1
        endpoint.receive(bytes(corrupted), 0)
        self.assertIsNotNone(endpoint.first_fault)  # Foreign nonce never bypasses envelope integrity.
        endpoint = ep.Endpoint(150_000)
        endpoint.hello(11, 0)
        offer, = endpoint.next_write(0)
        endpoint.observe_write(offer.token, len(offer.data) - 1, 0)
        endpoint.receive(literal(129, struct.pack("<BBBBHHII", 0, 2, 1, 12, 512, 128,
            0x56325343, 3), revision=2, nonce=11, request=1), 0)
        self.assertEqual(endpoint.first_fault.code, "request")
        self.assertIsInstance(endpoint.select_mode(22, 0)[0], ep.Refused)

    def test_intrinsic_journal_roundtrip_without_companion_and_csv(self):
        identity = StreamIdentity("wire-0.3:0000000000000016", 3, 3, 150_000, "synthetic",
            MODE_REVISION, "build:56325343", "v2-serial-unknown-accounting:injected-test",
            acquisition_mode=3, retained_bits=10, discarded_lsb=2,
            wire_sample_encoding="u10packed_le", normalization="left_shift_2", quantization="truncate_lsb")
        raw = struct.pack("<5H", 0, 4, 4092, 1364, 2000)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "packed.mtstream"
            start = StreamStart(identity, 128, "test")
            writer = journal.StreamWriter.create(path, start)
            writer.append(StreamBlock(identity, 128, raw))
            writer.finish(StreamTerminal(identity, 133, "stopped", True, None, 133, None,
                                         stop_requested=True, stop_request_id=4))
            writer.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            context, archive = open_stream(path)
            self.assertFalse(context.companion_present)
            self.assertEqual(archive.identity, identity)
            self.assertEqual(b"".join(b.raw_u16le for b in archive.iter_raw()), raw)
            self.assertEqual(path.read_bytes()[:8], journal.MAGIC)
            target = Path(folder) / "export.csv"
            export_stream(target, archive, context)
            lines = target.read_text("utf-8").splitlines()
            self.assertIn("retained10", lines[0])
            self.assertEqual(float(lines[2].split(",")[1]), 1 / 150_000)
            self.assertEqual(json.loads(target.with_suffix(".csv.json").read_text("utf-8"))["identity"], asdict(identity))
            _write_context(path, StreamContext(), identity)
            self.assertTrue(open_stream(path)[0].companion_present)
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
        for code in (1, 4095, 4096):
            with self.assertRaises(StreamError):
                StreamBlock(identity, 0, struct.pack("<H", code))
        with self.assertRaises(StreamError):
            replace(identity, retained_bits=12)
        with self.assertRaises(StreamError):
            journal._construct(StreamIdentity, {k: v for k, v in asdict(identity).items() if k != "discarded_lsb"})
        detector = EventDetector(default_event_config(150_000, 10), 10)
        detector.feed(StreamBlock(identity, 0, struct.pack("<H", 4092)))
        self.assertIn("quantization_edge_bin", detector.status.pending.flags)
        self.assertNotIn("clipping", detector.status.pending.flags)

    def test_old_journal_schemas_and_companion_are_read_without_rewriting(self):
        # Independent tiny legacy header/frame hash chain: historical field set,
        # no new writer masquerading as evidence that old schema still opens.
        with tempfile.TemporaryDirectory() as folder:
            for rate in (50_000, 100_000, 200_000):
                identity = StreamIdentity("old", 3, 1, rate, "synthetic")
                legacy = {k: asdict(identity)[k] for k in LEGACY_IDENTITY_FIELDS}
                start = asdict(StreamStart(identity, 0, "old")); start["identity"] = legacy
                terminal = asdict(StreamTerminal(identity, 2, "stopped", True, 2, 2, 0,
                                                stop_requested=True, stop_request_id=4))
                terminal["identity"] = legacy
                encode = lambda x: json.dumps(x, sort_keys=True, separators=(",", ":")).encode()
                attempt = rate == 100_000
                root = {"preparation": {"identity": legacy, "recording_id": "old", "start_policy": "source_start"}} if attempt else {"start": start}
                metadata = encode({**root, "limits": asdict(journal.StreamLimits())})
                magic = journal.LEGACY_ATTEMPT_MAGIC if attempt else journal.LEGACY_MAGIC
                out = bytearray(struct.pack("<8sI", magic, len(metadata)) + metadata)
                digest = hashlib.sha256(out).digest(); out.extend(digest)
                frames = ((b"S", encode(start)),) if attempt else ()
                for kind, payload in frames + ((b"B", struct.pack("<QIHH", 0, 2, 5, 4095)), (b"T", encode(terminal))):
                    frame = struct.pack("<cI", kind, len(payload)) + payload
                    digest = hashlib.sha256(digest + frame).digest(); out.extend(frame + digest)
                path = Path(folder) / f"legacy{rate}.mtstream"; path.write_bytes(out)
                companion = {"format": "motortester-v2-stream-context", "format_version": 1,
                    "context": asdict(StreamContext()), "time_basis": "nominal_unverified",
                    "journal_sha256": hashlib.sha256(out).hexdigest(), "journal_bytes": len(out),
                    "journal": {"identity": legacy, "recording_id": "old", "first_sample_index": 0, "end_sample_index": 2}}
                path.with_name(path.name + ".v2.json").write_text(json.dumps(companion), "utf-8")
                context, archive = open_stream(path)
                if attempt:
                    archive = archive.recording
                self.assertTrue(context.companion_present)
                self.assertEqual(archive.identity.retained_bits, 12)
                self.assertEqual(archive.identity.nominal_fs_hz, rate)
                self.assertEqual(b"".join(b.raw_u16le for b in archive.iter_raw()), struct.pack("<HH", 5, 4095))
                self.assertEqual(path.read_bytes(), bytes(out))
