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
from motortester.stream_wire import (Kind, MODE_REVISION, BATCH_REVISION, BATCH1024_REVISION,
                                    decode_frame, decode_payload, pack10, unpack10, WireError)
from motortester.v2.stream_files import open_stream, export_stream
from motortester.v2.stream_device import (StreamContext, _write_context, StreamConnection,
                                         SerialStreamSelection)
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


def negotiate(rate=150_000, *, legacy_rate=None, marker=15):
    endpoint = ep.Endpoint(rate)
    endpoint.hello(11, 0)
    request = accepted(endpoint)
    assert request.revision == "0.2"
    marker = 1 if legacy_rate else marker
    maximum, payload_maximum = {1: (128, 512), 3: (128, 512), 7: (256, 512), 15: (1024, 1300)}[marker]
    events = endpoint.receive(literal(129, struct.pack("<BBBBHHII", 0, 2, 1, 12,
        payload_maximum, maximum, 0xF0102401, marker), revision=2, nonce=11, request=1), 0)
    if legacy_rate is None:
        if rate == 150_000 and marker != 15:
            return endpoint
        assert isinstance(events[0], ep.ModeRequired)
        assert isinstance(endpoint.plan_start(0)[0], ep.Refused)
        endpoint.select_mode(22, 0)
        request = accepted(endpoint)
        assert request.revision == "0.3"
        mode = {50_000: 1, 100_000: 2, 150_000: 5}[rate]
        assert request.payload == struct.pack("<QHH", 22, mode, 0)
        maximum, payload_maximum = (1024, 1300) if mode == 5 else (128, 512)
        endpoint.receive(literal(129, struct.pack("<BBBBHHII", 0, 3, 1, 12, payload_maximum, maximum,
            0xF0102401, 1), request=1), 0)
        caps = struct.pack("<IHBBIIHBBI", mode, mode, 0, 12, rate, 1, maximum,
                           10 if mode == 5 else 12, 2 if mode == 5 else 1, 1)
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
        # Literal five-byte oracle repeated; it is independent of pack10.
        for count, packed in ((129, vectors[3][0] * 32 + vectors[0][0]),
                              (255, vectors[3][0] * 63 + vectors[2][0]),
                              (256, vectors[3][0] * 64)):
            codes = (vectors[3][1] * 64)[:count]
            framed = literal(152, struct.pack("<IIQHH", 3, 4, 0, count, 0) + packed)
            self.assertLessEqual(len(framed), 371)
            self.assertEqual(decode_payload(decode_frame(framed)).samples, codes)
            self.assertEqual(pack10(codes), packed)
            if count % 4:
                with self.assertRaises(WireError):
                    decode_payload(decode_frame(literal(152, struct.pack("<IIQHH", 3, 4, 0, count, 0) +
                        packed[:-1] + bytes([packed[-1] | 0x80]))))
        for mode, count in ((4, 257), (3, 129), (2, 129)):
            with self.assertRaises(WireError):
                decode_payload(decode_frame(literal(152, struct.pack("<IIQHH", 3, mode, 0, count, 0))))
        with self.assertRaises(WireError):
            decode_payload(decode_frame(literal(152, struct.pack("<IIQHH", 3, 4, (1 << 64) - 128, 256, 0) + b"\0" * 320)))
        # The large envelope is exclusively DATA0.3/config5. Old mode4 above
        # remains max256 even though the generic bounded accumulator is larger.
        for count, packed in ((1023, vectors[3][0] * 255 + vectors[2][0]),
                              (1024, vectors[3][0] * 256)):
            codes = (vectors[3][1] * 256)[:count]
            frame = literal(152, struct.pack("<IIQHH", 3, 5, 0, count, 0) + packed)
            self.assertGreater(len(frame), 544)
            self.assertLessEqual(len(frame), 1335)
            self.assertEqual(decode_payload(decode_frame(frame)).samples, codes)
            self.assertEqual(pack10(codes), packed)
            if count % 4:
                with self.assertRaises(WireError):
                    decode_payload(decode_frame(literal(152, struct.pack("<IIQHH", 3, 5, 0, count, 0) +
                        packed[:-1] + bytes([packed[-1] | 0x80]))))
        for revision, kind, mode in ((2, 152, 5), (3, 152, 4), (3, 153, 5), (4, 152, 5)):
            with self.assertRaises(WireError):
                decode_frame(literal(kind, struct.pack("<IIQHH", 3, mode, 0, 1024, 0) + b"\0" * 1280,
                                     revision=revision), allow_unknown_revision=True)
        with self.assertRaises(WireError):
            decode_payload(decode_frame(literal(152, struct.pack("<IIQHH", 3, 5, 0, 1025, 0))))
        with self.assertRaises(WireError):
            decode_payload(decode_frame(literal(152, struct.pack("<IIQHH", 3, 5, (1 << 64) - 1023, 1024, 0) + b"\0" * 1280)))

    def test_discovery_mode_binding_and_legacy_mismatch(self):
        for rate, mode in ((50_000, 1), (100_000, 2), (150_000, 5)):
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
        for marker in (3, 7):
            for rate in (50_000, 100_000):
                self.assertIsNone(negotiate(rate, marker=marker).first_fault)
            unsupported = negotiate(150_000, marker=marker)
            self.assertEqual(unsupported.first_fault.code, "batch1024_firmware_required")
            self.assertIsInstance(unsupported.plan_start(0)[0], ep.Refused)
            self.assertFalse(any(isinstance(x, ep.WriteOffer) and x.request.kind == Kind.START
                                 for x in unsupported.next_write(0)))
        # ACK and CAPS selected sizes must agree; discovery max is only global.
        for marker, maximum, payload_maximum in ((7, 128, 512), (3, 256, 512), (1, 256, 512),
                                                (15, 1024, 512), (7, 1024, 1300), (15, 256, 1300)):
            with self.assertRaises(WireError):
                decode_payload(decode_frame(literal(129, struct.pack("<BBBBHHII", 0, 2, 1, 12, payload_maximum,
                    maximum, 0x56325344, marker), revision=2)))
        wrong = ep.Endpoint(150_000); wrong.hello(11, 0); accepted(wrong)
        wrong.receive(literal(129, struct.pack("<BBBBHHII", 0, 2, 1, 12, 1300, 1024,
            0xF0102401, 15), revision=2, nonce=11, request=1), 0)
        wrong.select_mode(22, 0); accepted(wrong)
        wrong.receive(literal(129, struct.pack("<BBBBHHII", 0, 3, 1, 12, 512, 128,
            0x56325344, 1), request=1), 0)
        self.assertEqual(wrong.first_fault.code, "selected_block_mismatch")
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
        endpoint.receive(literal(136, struct.pack("<IIQ", 3, 5, 0), sequence=3, request=3), 0)
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
        endpoint = negotiate(); endpoint.start(0); accepted(endpoint)
        endpoint.receive(literal(136, struct.pack("<IIQ", 3, 5, 0), sequence=3, request=3), 0)
        self.assertEqual(ep.MAX_INPUT_BYTES, 544)
        for seq, first, count in ((4, 0, 1024), (5, 1024, 129)):
            framed = literal(152, struct.pack("<IIQHH", 3, 5, first, count, 0) +
                             b"\0" * ((count * 10 + 7) // 8), sequence=seq)
            before = endpoint.received_end
            for offset in range(0, len(framed) - 1, 544):
                events = endpoint.receive(framed[offset:min(offset + 544, len(framed) - 1)], 0)
                self.assertEqual(endpoint.received_end, before)
                self.assertFalse(any(isinstance(event, ep.ValidatedData) for event in events))
            events = endpoint.receive(framed[-1:], 0)
            self.assertEqual(sum(isinstance(event, ep.ValidatedData) for event in events), 1)
        self.assertIsNone(endpoint.first_fault)
        self.assertEqual(endpoint.received_end, 1153)
        self.assertEqual(endpoint.received_crc32, zlib.crc32(b"\0" * 2306))
        endpoint.receive(literal(152, struct.pack("<IIQHH", 3, 5, 1153, 1, 0) + b"\0\0", sequence=6), 0)
        self.assertEqual(endpoint.first_fault.code, "data_after_short")
        # A cut large frame cannot publish a fraction or advance END prefix.
        cut = negotiate(); cut.start(0); accepted(cut)
        cut.receive(literal(136, struct.pack("<IIQ", 3, 5, 0), sequence=3, request=3), 0)
        complete = literal(152, struct.pack("<IIQHH", 3, 5, 0, 1024, 0) + b"\0" * 1280, sequence=4)
        for offset in range(0, len(complete), 544):
            cut.receive(complete[offset:offset + 544], 0)
        partial = literal(152, struct.pack("<IIQHH", 3, 5, 1024, 1024, 0) + b"\0" * 1280, sequence=5)
        cut.receive(partial[:544], 0)
        self.assertEqual(cut.received_end, 1024)
        cut.tick(1001)
        self.assertIsNotNone(cut.first_fault)
        self.assertEqual((cut.received_end, cut.received_crc32), (1024, zlib.crc32(b"\0" * 2048)))

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
            # The new enum is intrinsic; old mode3 above remains readable.
            batch = replace(identity, protocol_revision=BATCH_REVISION, acquisition_mode=4,
                            config_id=4, firmware_version="build:56325344")
            canonical = struct.pack("<385H", *((0, 4, 4092, 1364) * 97)[:385])
            batch_path = Path(folder) / "batch.mtstream"
            writer = journal.StreamWriter.create(batch_path, StreamStart(batch, 256, "batch"))
            writer.append(StreamBlock(batch, 256, canonical[:512]))
            writer.append(StreamBlock(batch, 512, canonical[512:]))
            writer.finish(StreamTerminal(batch, 641, "stopped", True, None, 641, None,
                                         stop_requested=True, stop_request_id=4))
            writer.close()
            original = batch_path.read_bytes()
            bare, reopened = open_stream(batch_path)
            self.assertFalse(bare.companion_present)
            self.assertEqual(reopened.identity, batch)
            self.assertEqual(b"".join(b.raw_u16le for b in reopened.iter_raw()), canonical)
            connection = StreamConnection(SerialStreamSelection("fixture", requested_sample_rate_hz=150_000),
                "injected-test", 0x56325344, (4, 4, 0, 12, 150000, 1, 256, 1, 10, 2),
                protocol_revision="0.3")
            _write_context(batch_path, StreamContext(), batch, connection)
            self.assertEqual(open_stream(batch_path)[0].connection, connection)
            batch_csv = Path(folder) / "batch.csv"
            export_stream(batch_csv, reopened, bare)
            self.assertEqual(float(batch_csv.read_text("utf-8").splitlines()[2].split(",")[1]), 1 / 150_000)
            self.assertEqual(json.loads(batch_csv.with_suffix(".csv.json").read_text("utf-8"))["identity"], asdict(batch))
            self.assertEqual(batch_path.read_bytes(), original)
            for broken in (dict(protocol_revision=MODE_REVISION), dict(acquisition_mode=3, config_id=3),
                           dict(retained_bits=12), dict(wire_sample_encoding="u16le")):
                with self.assertRaises(StreamError):
                    replace(batch, **broken)
            for code in (1, 4095, 4096):
                with self.assertRaises(StreamError):
                    StreamBlock(batch, 0, struct.pack("<H", code))
            with self.assertRaises(StreamError):
                journal._construct(StreamIdentity, {k: v for k, v in asdict(batch).items() if k != "discarded_lsb"})
            large = replace(batch, protocol_revision=BATCH1024_REVISION, acquisition_mode=5,
                            config_id=5, firmware_version="build:f0102401")
            large_raw = struct.pack("<1153H", *((0, 4, 4092, 1364) * 289)[:1153])
            large_path = Path(folder) / "batch1024.mtstream"
            writer = journal.StreamWriter.create(large_path, StreamStart(large, 1024, "batch1024"))
            writer.append(StreamBlock(large, 1024, large_raw[:2048]))
            writer.append(StreamBlock(large, 2048, large_raw[2048:]))
            writer.finish(StreamTerminal(large, 2177, "stopped", True, None, 2177, None,
                                         stop_requested=True, stop_request_id=4))
            writer.close()
            original_large = large_path.read_bytes()
            bare_large, reopened_large = open_stream(large_path)
            self.assertFalse(bare_large.companion_present)
            self.assertEqual(reopened_large.identity, large)
            self.assertEqual(b"".join(b.raw_u16le for b in reopened_large.iter_raw()), large_raw)
            large_connection = StreamConnection(SerialStreamSelection("fixture", requested_sample_rate_hz=150_000),
                "injected-test", 0xF0102401, (5, 5, 0, 12, 150000, 1, 1024, 1, 10, 2), protocol_revision="0.3")
            _write_context(large_path, StreamContext(), large, large_connection)
            self.assertEqual(open_stream(large_path)[0].connection, large_connection)
            large_csv = Path(folder) / "batch1024.csv"
            export_stream(large_csv, reopened_large, bare_large)
            self.assertEqual(float(large_csv.read_text("utf-8").splitlines()[2].split(",")[1]), 1 / 150_000)
            self.assertEqual(json.loads(large_csv.with_suffix(".csv.json").read_text("utf-8"))["identity"], asdict(large))
            self.assertEqual(large_path.read_bytes(), original_large)
            for broken in (dict(protocol_revision=BATCH_REVISION), dict(acquisition_mode=4, config_id=4),
                           dict(retained_bits=12), dict(wire_sample_encoding="u16le")):
                with self.assertRaises(StreamError):
                    replace(large, **broken)
            with self.assertRaises(StreamError):
                StreamBlock(large, 0, struct.pack("<H", 4095))
            with self.assertRaises(StreamError):
                journal._construct(StreamIdentity, {k: v for k, v in asdict(large).items() if k != "discarded_lsb"})
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
