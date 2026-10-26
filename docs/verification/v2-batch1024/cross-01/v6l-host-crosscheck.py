"""One actual isolated C serializer -> host codec/journal/raw/CSV witness.

No handshake, production runtime, serial transport, GUI or hardware is executed.
The synthetic journal build label is a fixture value, not a HELLO observation.
"""
import csv
from dataclasses import asdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct
import sys
import traceback
import zlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))
from motortester.stream_wire import Kind, BATCH1024_REVISION, decode_frame, decode_payload
from motortester.stream_model import StreamIdentity, StreamStart, StreamBlock, StreamTerminal
from motortester.stream_recording import StreamWriter
from motortester.v2.stream_files import open_stream, export_stream

source_dir = ROOT / "build/v6l-native-01"
output = ROOT / "build/v6l-host-unit-01"
receipt_path = output / "c1153-producer-journal-crosscheck.json"
journal_path = output / "c1153.mtstream"
csv_path = output / "c1153.csv"
assert output.is_dir()
assert not any(p.exists() for p in (receipt_path, journal_path, csv_path, csv_path.with_suffix(".csv.json")))

def pin(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

def relative(path):
    return path.relative_to(ROOT).as_posix()

report = {"schema": "v2-06l-c1153-host-crosscheck-1", "status": "RUNNING",
    "scope": "Actual isolated C serializer plus existing C END encoder -> Python codec, direct journal, bare fresh Open and CSV",
    "production_runtime_executed": False, "physical_device_verified": False,
    "firmware_build_observed": None, "GUI_executed": False, "COM_calls": 0, "SWD_calls": 0,
    "errors": [], "outputs": {}}
writer = None
before = {}
try:
    producer_receipt = source_dir / "result.json"
    assert pin(producer_receipt)["sha256"] == "9715e3edbc09acd6ba4900dbff208089216262c3e01ebfdf5bf82ca8117a75bc"
    producer = json.loads(producer_receipt.read_text("utf-8"))
    assert producer["status"] == "PASS"
    source = source_dir / "batch1153-transcript.bin"
    assert pin(source)["sha256"] == producer["fixture"]["sha256"] == "cf62a2d6153aa7f59e4c886e9f487e950381ac6d6cbafa1ca285d19f22333013"
    # Bind the copied compiled producer sources to the earlier runner receipt.
    inputs_by_name = {Path(p).name: digest for p, digest in producer["inputs"].items()}
    mapping = {"model.c": "batch1024_model.c", "mt_batch1024.c": "mt_batch1024.c",
        "mt_batch1024.h": "mt_batch1024.h", "mt_wire.c": "mt_wire.c",
        "mt_wire.h": "mt_wire.h", "mt_v2_crc32.h": "mt_v2_crc32.h"}
    for copied, original in mapping.items():
        assert pin(source_dir / copied)["sha256"] == inputs_by_name[original]
    inputs = [source, producer_receipt, *(source_dir / name for name in mapping)]
    before = {relative(path): pin(path) for path in inputs}
    draft = ROOT / "build/v6l-host-draft-01.json"
    draft_receipt = json.loads(draft.read_text("utf-8"))
    for name, expected_pin in draft_receipt["source_files"].items():
        assert pin(ROOT / name) == expected_pin
    report["host_draft_manifest"] = {"path": relative(draft), **pin(draft)}
    report["host_source_files"] = draft_receipt["source_files"]

    content = source.read_bytes()
    assert content.endswith(b"\0")
    encoded = [part + b"\0" for part in content.split(b"\0")[:-1]]
    frames = [decode_frame(frame, "device") for frame in encoded]
    assert [frame.kind for frame in frames] == [Kind.DATA, Kind.DATA, Kind.END]
    assert [frame.sequence for frame in frames] == [4, 5, 6]
    assert all(frame.revision == "0.3" and frame.nonce == 503 and frame.request_id == 0 for frame in frames)
    decoded = [decode_payload(frame) for frame in frames]
    assert [len(block.samples) for block in decoded[:2]] == [1024, 129]
    assert [block.first_index for block in decoded[:2]] == [0, 1024]
    assert all(block.generation == 3 and block.config_id == 5 for block in decoded)
    assert all(len(frame) <= 1335 for frame in encoded)
    expected = tuple(((i * 37 + 3) & 4095) & 4092 for i in range(1024))
    expected += tuple((4095 - i) & 4092 for i in range(129))
    raw = b"".join(block.raw_samples for block in decoded[:2])
    assert raw == struct.pack("<1153H", *expected)
    assert hashlib.sha256(raw).hexdigest() == producer["fixture"]["canonical_u16le_sha256"] == "1f5c9f712929bceae1a09adb39de4cec43d31ef4abe2d99cc8b63531af417b7d"
    end = decoded[2]
    assert (end.prefix_end, end.prefix_crc32, end.last_data_sequence, end.reason, end.flags) == (1153, 1967919874, 5, 0, 3)
    assert end.prefix_crc32 == zlib.crc32(raw) == producer["fixture"]["canonical_END_crc32"]
    assert end.produced_end is None and end.stop_request_id == 4

    identity = StreamIdentity("wire-0.3:00000000000001f7", 3, 5, 150000, "synthetic",
        BATCH1024_REVISION, "build:f0102401", "v2-serial-unknown-accounting:injected-test",
        acquisition_mode=5, retained_bits=10, discarded_lsb=2, wire_sample_encoding="u10packed_le",
        normalization="left_shift_2", quantization="truncate_lsb")
    writer = StreamWriter.create(journal_path, StreamStart(identity, 0, "isolated-c1153"))
    for block in decoded[:2]:
        writer.append(StreamBlock(identity, block.first_index, block.raw_samples))
    writer.finish(StreamTerminal(identity, 1153, "stopped", True, None, 1153, None,
        boundary_evidence="synthetic-C-END", stop_requested=True, stop_request_id=end.stop_request_id))
    writer.close()
    journal_before = pin(journal_path)
    context, archive = open_stream(journal_path)
    assert not context.companion_present and archive.identity == identity
    assert archive.recovery_issue is None and archive.discarded_tail_bytes == 0
    assert b"".join(block.raw_u16le for block in archive.iter_raw()) == raw
    assert archive.terminal.device_generated_end_sample_index is None
    assert archive.terminal.loss_samples is None
    export_stream(csv_path, archive, context)
    with csv_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ["sample_index", "time_from_recording_start_s", "adc12_scale_code_retained10_truncate_lsb2"]
        rows = list(reader)
    assert len(rows) == 1153
    assert [int(row["sample_index"]) for row in rows] == list(range(1153))
    assert [int(row["adc12_scale_code_retained10_truncate_lsb2"]) for row in rows] == list(expected)
    assert all(float(row["time_from_recording_start_s"]) == i / 150000 for i, row in enumerate(rows))
    exported = json.loads(csv_path.with_suffix(".csv.json").read_text("utf-8"))
    assert exported["complete"] is True and exported["identity"] == asdict(identity)
    assert exported["source_companion_present"] is False
    assert pin(journal_path) == journal_before
    report.update(status="PASS", source=relative(source), source_fixture=pin(source),
        C_producer_inputs={relative(source_dir / name): pin(source_dir / name) for name in mapping},
        producer_receipt={"path": relative(producer_receipt), **pin(producer_receipt)},
        decoded={"nonce": 503, "generation": 3, "config_id": 5, "revision": "0.3",
            "counts": [1024, 129], "first_indices": [0, 1024], "frame_sequences": [4, 5, 6],
            "frame_bytes": [len(frame) for frame in encoded], "wire_bytes": len(content),
            "canonical_samples": 1153, "canonical_bytes": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(), "prefix_crc32": zlib.crc32(raw),
            "END": asdict(end)},
        journal={"path": relative(journal_path), **journal_before, "identity": asdict(identity),
            "fresh_open_raw_equal": True, "without_companion": True, "unknown_tail_preserved": True,
            "unchanged_after_open_and_export": True},
        time_basis={"nominal_fs_hz": 150000, "sample_interval_seconds": float(Fraction(1, 150000)),
            "sample_interval_microseconds_rational": [20, 3], "all_CSV_indices_codes_times_equal": True,
            "calibrated_clock": False},
        limits=["Producer is the isolated serializer, not production core/runtime or a firmware image.",
            "No HELLO/START/STOP_ACK lifecycle or USB/ADC throughput is exercised here.",
            "Synthetic END and exact retained prefix do not prove physical completeness.",
            "Partial-frame no-early-publish was checked in unit01; it is not a second runtime test here."])
except BaseException:
    report["status"] = "FAIL"
    report["errors"].append(traceback.format_exc())
finally:
    if writer is not None and not writer.closed:
        writer.close()
    after = {name: pin(ROOT / name) for name in before}
    report["input_pins_before"], report["input_pins_after"] = before, after
    report["inputs_unchanged"] = before == after
    if not report["inputs_unchanged"]:
        report["status"] = "FAIL"
        report["errors"].append("Original inputs changed")
    report["script_sha256"] = pin(Path(__file__))["sha256"]
    for path in (journal_path, csv_path, csv_path.with_suffix(".csv.json")):
        if path.exists():
            report["outputs"][relative(path)] = pin(path)
    receipt_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"status": report["status"], "receipt": relative(receipt_path), **pin(receipt_path),
                      "errors": report["errors"]}, ensure_ascii=False))
sys.exit(0 if report["status"] == "PASS" else 1)
