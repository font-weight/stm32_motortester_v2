"""Offline inspection of the failed V2S5 trial; never opens hardware or GUI.

The exported uint16 prefix is wire evidence, not a selected .mtstream recording.
Run with the repository Python; only this directory receives new artifacts.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "host"))
sys.path.insert(0, str(ROOT / "host" / "tools"))
from verify_stream_trial import MAX_TRAFFIC, parse_traffic, require
from motortester.stream_wire import Kind


def sha(data):
    return hashlib.sha256(data).hexdigest()


def preserve(path, raw):
    if path.exists():
        require(path.read_bytes() == raw, "Refusing to replace different existing evidence: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(raw)


def main():
    traffic_path = HERE / "run" / "traffic.bin"
    receipt_path = HERE / "run" / "result.json"
    require(traffic_path.stat().st_size <= MAX_TRAFFIC, "Traffic exceeds offline bound")
    traffic = traffic_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    require(sha(traffic) == receipt["traffic"]["sha256"], "Traffic receipt hash mismatch")
    wire = {}
    frames = parse_traffic(traffic, wire)
    require(not wire["decode_errors"] and wire["trailing_partial_bytes"] == [0, 0]
            and wire["trailing_oversized_frame"] == [False, False], "Invalid/incomplete wire framing")
    for field in ("chunks", "host_bytes", "device_bytes"):
        require(wire[field] == receipt["traffic"][field], "Traffic count differs from receipt")

    # Exact order is evidence about this failed trial, not a generic protocol rule.
    expected = [(0, Kind.HELLO), (1, Kind.HELLO_ACK), (0, Kind.GET_CAPS), (1, Kind.CAPS),
                (0, Kind.START), (1, Kind.START_ACK)]
    expected += [(1, Kind.DATA)] * 9
    expected += [(1, Kind.END), (0, Kind.STOP), (1, Kind.STOP_ACK)]
    require([(direction, frame.kind) for direction, _, frame, _ in frames] == expected,
            "Unexpected frame order; inspect rather than generalize this trial")
    nonce = frames[0][3].nonce
    start = frames[5][3]
    caps = frames[3][3]
    require(tuple(asdict(caps).values()) == (1, 1, 0, 12, 200000, 1, 128, 1), "Unexpected CAPS")
    require(frames[1][3].firmware_build == receipt["expected_build"] == 0x56325335,
            "Unexpected declared build")
    require(start.generation == frames[4][2].request_id and start.first_index == 0
            and start.config_id == caps.config_id, "START identity mismatch")
    sequences = [0, 0]
    requests = {}
    raw = bytearray()
    next_index = 0
    last_data_sequence = 0
    timeline = []
    first_stamp = frames[0][1]
    for direction, stamp, frame, decoded in frames:
        effective_nonce = decoded.nonce if frame.kind == Kind.HELLO else frame.nonce
        require(effective_nonce == nonce, "Mixed nonce")
        require(frame.sequence == sequences[direction] + 1, "Sequence gap/duplicate/out-of-order")
        sequences[direction] = frame.sequence
        if direction == 0:
            require(frame.request_id not in requests, "Duplicate request identifier")
            requests[frame.request_id] = frame.kind
        elif frame.kind not in (Kind.DATA, Kind.END):
            expected_request = {Kind.HELLO_ACK: Kind.HELLO, Kind.CAPS: Kind.GET_CAPS,
                                Kind.START_ACK: Kind.START, Kind.STOP_ACK: Kind.STOP}[frame.kind]
            require(requests.get(frame.request_id) == expected_request, "Reply correlation mismatch")
        else:
            require(frame.request_id == 0, "Nonzero asynchronous request identifier")
        item = {"direction": "device" if direction else "host", "kind": frame.kind.name,
                "sequence": frame.sequence, "request_id": frame.request_id,
                "host_relative_seconds": stamp - first_stamp}
        if frame.kind == Kind.DATA:
            require(decoded.generation == start.generation and decoded.config_id == start.config_id,
                    "DATA identity mismatch")
            require(decoded.first_index == next_index and len(decoded.samples) == 128,
                    "DATA gap, overlap or unexpected block size")
            raw.extend(decoded.raw_samples)
            next_index = decoded.end_index
            last_data_sequence = frame.sequence
            item.update(first_sample_index=decoded.first_index, sample_count=len(decoded.samples))
        elif frame.kind not in (Kind.GET_CAPS, Kind.START, Kind.STOP):
            item["payload"] = asdict(decoded)
        elif frame.kind in (Kind.START, Kind.STOP):
            item["payload"] = decoded
        timeline.append(item)
    end_frame, end = frames[-3][2:]
    stop_frame, stop_generation = frames[-2][2:]
    ack_frame, ack = frames[-1][2:]
    raw = bytes(raw)
    require(end.generation == start.generation and end.config_id == start.config_id,
            "END identity mismatch")
    require(end.prefix_end == next_index == 1152 and len(raw) == 2304,
            "Unexpected received prefix")
    require(end.prefix_crc32 == zlib.crc32(raw) and end.last_data_sequence == last_data_sequence,
            "END prefix CRC or last DATA mismatch")
    require(end.reason == 1 and end.flags == 3 and end.produced_end is None and end.stop_request_id == 0,
            "Unexpected source failure terminal")
    require(frames[-3][1] < frames[-2][1], "STOP did not follow source END")
    require(stop_generation == start.generation and ack.generation == start.generation
            and ack_frame.request_id == stop_frame.request_id and ack.prefix_end == end.prefix_end
            and ack.terminal_sequence == end_frame.sequence and ack.flags == 3,
            "STOP_ACK does not acknowledge the prior terminal")
    final = receipt["final_state"]
    require(receipt["status"] == "FAIL" and final["received"] == next_index
            and final["R"] is None and final["accepted"] is None and final["checkpoint"] is None
            and final["failure"]["source_code"] == end.reason, "Receipt contradicts wire analysis")

    source = ROOT / "build" / "v6-fw-07" / "patched" / "v2" / "protocol" / "mt_live_device.c"
    source_bytes = source.read_bytes()
    mapping = "terminate(d,q==MT_SAMPLE_QUEUE_FULL?1u:2u,n)"
    source_lines = source_bytes.decode("utf-8").splitlines()
    mapping_lines = [i + 1 for i, line in enumerate(source_lines) if mapping in line]
    require(len(mapping_lines) == 1, "Selected source no longer has the reviewed reason mapping")
    report = {
        "schema": "motortester-v2-failed-wire-prefix-analysis-1",
        "offline_validation_status": "PASS",
        "physical_trial_status": "FAIL",
        "scope": "Offline verification and extraction of a received wire prefix; no new hardware operation",
        "tool_sha256": sha(Path(__file__).read_bytes()),
        "parser_sha256": sha((ROOT / "host/tools/verify_stream_trial.py").read_bytes()),
        "traffic_sha256": sha(traffic), "trial_receipt_sha256": sha(receipt_bytes),
        "nonce_hex": f"{nonce:016x}", "observed_build_id": frames[1][3].firmware_build,
        "observed_caps": asdict(caps), "wire": wire,
        "host_sequence_range": [1, sequences[0]], "device_sequence_range": [1, sequences[1]],
        "sequence_gaps_or_duplicates": 0, "reply_correlation_verified": True,
        "timeline": timeline, "timeline_units": "host I/O monotonic seconds, not ADC timestamps",
        "received_prefix": {
            "file": "received-prefix.u16le", "sha256": sha(raw), "crc32": zlib.crc32(raw),
            "crc32_matches_END": True, "format": "unsigned uint16 little endian, raw 12-bit ADC codes",
            "first_sample_index": 0, "end_sample_index_exclusive": next_index,
            "samples": next_index, "bytes": len(raw), "DATA_blocks": 9,
            "nominal_index_interval_seconds": next_index / caps.fs_num,
            "nominal_last_sample_seconds": (next_index - 1) / caps.fs_num,
            "nominal_sample_period_seconds": 1 / caps.fs_num,
            "selected_mtstream_recording": False,
        },
        "terminal": dict(asdict(end), sequence=end_frame.sequence),
        "stop": {"sent_after_source_END": True, "request_id": stop_frame.request_id,
                 "acknowledgement": dict(asdict(ack), sequence=ack_frame.sequence)},
        "recording_selection": {"R": final["R"], "accepted": final["accepted"],
                                "checkpoint": final["checkpoint"], "state": "failed_unbound"},
        "cause": {
            "wire_fact": "Device reported END reason 1 before any host STOP, after a valid 1152-sample prefix",
            "selected_source_interpretation": "reason 1 maps to a full firmware sample queue; it is not a normal requested Stop",
            "source_path": source.relative_to(ROOT).as_posix(), "source_sha256": sha(source_bytes),
            "source_mapping_line": mapping_lines[0], "source_mapping": mapping,
            "root_cause_below_queue_full": "TBD: wire does not measure producer scheduling, USB service, or exact queue occupancy",
        },
        "limits": {
            "actual_produced_samples": None, "lost_samples": None,
            "continuous_200ksps_verified": False, "actual_ADC_frequency_measured": False,
            "voltage_calibration_verified": False, "image_authenticated_by_wire": False,
            "selected_journal_raw_equality_claimed": False,
            "input_condition": receipt["input_condition"],
            "note": "Valid transmitted prefix does not establish lossless acquisition. CAPS is a nominal rate declaration. The trial failed before recording selection R.",
        },
    }
    preserve(HERE / "received-prefix.u16le", raw)
    preserve(HERE / "wire-failure-analysis.json",
             (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"offline_validation_status": report["offline_validation_status"],
                      "physical_trial_status": "FAIL", "samples": next_index,
                      "raw_sha256": sha(raw), "END_reason": end.reason,
                      "END_before_STOP": True, "recording_R": final["R"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
