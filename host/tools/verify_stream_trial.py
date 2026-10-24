"""Offline wire/raw comparison for one v2_stream_probe trial. Never opens COM.

PASS means that the recovered selected [R,end) bytes match valid wire DATA.
It does not turn an unknown produced endpoint into complete ADC acquisition.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import zlib

# Direct script execution, including python -I, imports this checkout's codec.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motortester.stream_recording import recover_attempt
from motortester.stream_wire import (Kind, WireError, MAX_ENCODED,
                                     decode_frame, decode_payload)

CHUNK = struct.Struct("<BdI")
MAX_TRAFFIC = 16 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_traffic(raw, report):
    """Keep directions separate; timestamps describe host I/O, never ADC time."""
    partial = [bytearray(), bytearray()]
    discarding = [False, False]
    frames = []
    position, previous_time = 0, -math.inf
    report.update(chunks=0, host_bytes=0, device_bytes=0, empty_delimiters=0,
                  decode_errors=[], trailing_partial_bytes=[0, 0])
    while position < len(raw):
        offset = position
        require(position + CHUNK.size <= len(raw), "Truncated traffic chunk header")
        direction, stamp, count = CHUNK.unpack_from(raw, position)
        position += CHUNK.size
        require(direction in (0, 1), "Unknown traffic direction")
        require(math.isfinite(stamp) and stamp >= previous_time, "Nonmonotonic traffic timestamp")
        require(0 < count <= MAX_TRAFFIC and position + count <= len(raw),
                "Truncated/invalid traffic payload")
        previous_time = stamp
        payload = raw[position:position + count]
        position += count
        report["chunks"] += 1
        report["device_bytes" if direction else "host_bytes"] += count
        for byte in payload:
            if byte:
                if len(partial[direction]) >= MAX_ENCODED:
                    discarding[direction] = True
                if not discarding[direction]:
                    partial[direction].append(byte)
                continue
            encoded = bytes(partial[direction]) + b"\0"
            partial[direction].clear()
            if discarding[direction]:
                report["decode_errors"].append(
                    {"chunk_offset": offset, "direction": direction, "error": "oversized_frame"})
                discarding[direction] = False
            elif len(encoded) == 1:
                report["empty_delimiters"] += 1
            else:
                try:
                    frame = decode_frame(encoded, "device" if direction else "host")
                    decoded = decode_payload(frame)
                    frames.append((direction, stamp, frame, decoded))
                except WireError as exc:
                    report["decode_errors"].append(
                        {"chunk_offset": offset, "direction": direction, "error": exc.code})
    report["trailing_partial_bytes"] = [len(p) for p in partial]
    report["trailing_oversized_frame"] = discarding
    return frames


def verify(folder):
    traffic_path = folder / "traffic.bin"
    journal_path = folder / "physical.mtstream"
    require(traffic_path.is_file() and traffic_path.stat().st_size <= MAX_TRAFFIC,
            "Expected a completed traffic.bin of at most 16 MiB")
    raw = traffic_path.read_bytes()
    require(len(raw) <= MAX_TRAFFIC, "Traffic grew beyond its limit")
    journal_sha = sha(journal_path.read_bytes())
    attempt = recover_attempt(journal_path)
    recording = attempt.recording
    require(recording is not None, "No recovered selected recording")
    identity = recording.identity
    match = re.fullmatch(r"wire-(0\.[23]):([0-9a-f]{16})", identity.session_id)
    require(match is not None and identity.origin == "device", "Expected physical wire identity")
    revision, nonce = match[1], int(match[2], 16)
    first, stop = recording.first_sample_index, recording.end_sample_index
    require(stop > first and (stop - first) * 2 <= MAX_TRAFFIC, "Selected range outside trial bound")
    report = {
        "schema": "motortester-v2-wire-verification-1", "status": "FAIL",
        "scope": "Offline equality of saved selected raw range and captured wire DATA",
        "tool_sha256": sha(Path(__file__).read_bytes()),
        "traffic_sha256": sha(raw), "journal_sha256": journal_sha,
        "identity": asdict(identity), "nonce_hex": f"0x{nonce:016x}",
        "generation": identity.generation, "R": first, "end": stop,
        "recording_recovery_issue": attempt.recovery_issue,
        "discarded_journal_tail_bytes": attempt.discarded_tail_bytes,
        "journal_terminal": None if recording.terminal is None else asdict(recording.terminal),
        "clean_stop_reported": recording.clean_stop_reported,
        "physical_identity_verified": False, "timing_qualified": False,
        "adc_losslessness_verified": False,
    }
    wire = {}
    frames = parse_traffic(raw, wire)
    report["wire"] = wire
    kinds, last_frames, sequence = Counter(), {}, {}
    duplicates, unrelated, issues, gaps, overlaps, ends, acks = 0, 0, [], [], [], [], []
    requests = {}
    started = False
    previous_end = 0
    full_crc = 0
    full_hash = hashlib.sha256()
    full_samples = 0
    full_contiguous = True
    last_data_sequence = 0
    short_seen = False
    selected = bytearray()
    selected_next = first
    selected_gaps, selected_overlaps = [], []
    hello_seen, caps_seen, hello_ack_seen = False, False, False
    for direction, stamp, frame, decoded in frames:
        effective_nonce = decoded.nonce if frame.kind == Kind.HELLO else frame.nonce
        if effective_nonce != nonce:
            unrelated += 1
            continue
        if frame.revision != revision:
            issues.append({"code": "current_nonce_revision", "observed": frame.revision})
            continue
        key = direction
        if last_frames.get(key) == frame.encoded:
            duplicates += 1
            continue
        expected_sequence = sequence.get(key, 0) + 1
        if frame.sequence != expected_sequence:
            issues.append({"code": "sequence", "direction": direction,
                           "expected": expected_sequence, "observed": frame.sequence})
        sequence[key] = frame.sequence
        last_frames[key] = frame.encoded
        kinds[("device/" if direction else "host/") + frame.kind.name] += 1
        if direction == 0:
            requests[frame.request_id] = frame
            if frame.kind == Kind.HELLO:
                hello_seen = True
            elif frame.kind == Kind.START:
                if frame.request_id != identity.generation or (revision == "0.3" and decoded != identity.config_id):
                    issues.append({"code": "host_start_generation"})
            elif frame.kind == Kind.STOP and decoded != identity.generation:
                issues.append({"code": "host_stop_generation"})
            continue
        if frame.kind not in (Kind.DATA, Kind.END):
            expected_kind = {Kind.HELLO_ACK: Kind.HELLO, Kind.CAPS: Kind.GET_CAPS,
                             Kind.START_ACK: Kind.START, Kind.STOP_ACK: Kind.STOP}.get(frame.kind)
            request = requests.get(frame.request_id)
            if expected_kind is not None and (request is None or request.kind != expected_kind):
                issues.append({"code": "reply_request", "kind": frame.kind.name,
                               "request_id": frame.request_id})
        elif frame.request_id != 0:
            issues.append({"code": "asynchronous_request_id", "kind": frame.kind.name})
        if frame.kind == Kind.HELLO_ACK:
            hello_ack_seen = hello_seen
            report["observed_build_id"] = decoded.firmware_build
        elif frame.kind == Kind.CAPS:
            caps_seen = hello_ack_seen
            if (decoded.config_id != identity.config_id or decoded.fs_num != identity.nominal_fs_hz or
                    decoded.fs_den != 1 or decoded.retained_bits != identity.retained_bits or
                    (revision == "0.3" and decoded.profile != identity.acquisition_mode)):
                issues.append({"code": "caps_identity"})
            report["observed_caps"] = asdict(decoded)
        elif frame.kind == Kind.START_ACK:
            started = (caps_seen and decoded.generation == identity.generation
                       and decoded.config_id == identity.config_id and not started)
            if not started:
                issues.append({"code": "start_ack_identity_or_order"})
        elif frame.kind == Kind.DATA:
            if (not started or ends or decoded.generation != identity.generation
                    or decoded.config_id != identity.config_id):
                issues.append({"code": "data_identity_or_order", "sequence": frame.sequence})
                continue
            if short_seen:
                issues.append({"code": "data_after_short", "sequence": frame.sequence})
            short_seen = len(decoded.samples) < report["observed_caps"]["max_block"]
            if decoded.first_index > previous_end:
                gaps.append([previous_end, decoded.first_index])
                full_contiguous = False
            elif decoded.first_index < previous_end:
                overlaps.append([decoded.first_index, previous_end])
                full_contiguous = False
            previous_end = decoded.end_index
            block = decoded.raw_samples
            full_crc = zlib.crc32(block, full_crc)
            full_hash.update(block)
            full_samples += len(decoded.samples)
            last_data_sequence = frame.sequence
            begin, end = max(first, decoded.first_index), min(stop, decoded.end_index)
            if begin < end:
                if begin > selected_next:
                    selected_gaps.append([selected_next, begin])
                elif begin < selected_next:
                    selected_overlaps.append([begin, min(selected_next, end)])
                selected.extend(block[2 * (begin - decoded.first_index):2 * (end - decoded.first_index)])
                selected_next = end
        elif frame.kind == Kind.END:
            terminal = asdict(decoded)
            terminal.update(sequence=frame.sequence, host_monotonic=stamp,
                            prefix_crc_verified=(full_contiguous and
                                decoded.prefix_end == previous_end and
                                decoded.prefix_crc32 == full_crc and
                                decoded.last_data_sequence == last_data_sequence))
            ends.append(terminal)
            if (not started or len(ends) != 1 or decoded.generation != identity.generation
                    or decoded.config_id != identity.config_id or not terminal["prefix_crc_verified"]):
                issues.append({"code": "end_identity_or_prefix"})
            if decoded.stop_request_id:
                request = requests.get(decoded.stop_request_id)
                if request is None or request.kind != Kind.STOP:
                    issues.append({"code": "end_stop_request"})
        elif frame.kind == Kind.STOP_ACK:
            ack = asdict(decoded)
            ack.update(sequence=frame.sequence, host_monotonic=stamp)
            acks.append(ack)
            if not ends or any(ack[name] != ends[-1][other] for name, other in (
                    ("generation", "generation"), ("prefix_end", "prefix_end"),
                    ("terminal_sequence", "sequence"), ("flags", "flags"))):
                issues.append({"code": "stop_ack_terminal"})
        elif frame.kind == Kind.ERROR:
            issues.append({"code": "device_error_reply", "payload": asdict(decoded)})
    if selected_next < stop:
        selected_gaps.append([selected_next, stop])
    saved_hash = hashlib.sha256()
    offset, first_mismatch = 0, None
    for block in recording.iter_raw(first, stop):
        saved_hash.update(block.raw_u16le)
        expected = selected[offset:offset + len(block.raw_u16le)]
        if expected != block.raw_u16le and first_mismatch is None:
            unequal = next((i for i, (a, b) in enumerate(zip(expected, block.raw_u16le))
                            if a != b), min(len(expected), len(block.raw_u16le)))
            first_mismatch = block.first_sample_index + unequal // 2
        offset += len(block.raw_u16le)
    equal = (offset == len(selected) and first_mismatch is None
             and not selected_gaps and not selected_overlaps)
    terminal = recording.terminal
    if terminal is not None and terminal.terminal_observed:
        if (len(ends) != 1 or
                terminal.device_transmitted_end_sample_index != ends[0]["prefix_end"] or
                terminal.device_generated_end_sample_index != ends[0]["produced_end"]):
            issues.append({"code": "journal_wire_terminal_disagreement"})
    report.update(
        selected_samples=stop - first, selected_bytes=offset,
        wire_selected_samples=len(selected) // 2,
        wire_selected_sha256=sha(selected), journal_selected_sha256=saved_hash.hexdigest(),
        selected_range_byte_equal=equal, first_mismatch_sample=first_mismatch,
        selected_gaps=selected_gaps, selected_overlaps=selected_overlaps,
        decoded_data_samples=full_samples, decoded_data_sha256=full_hash.hexdigest(),
        contiguous_prefix_crc32=f"0x{full_crc:08x}" if full_contiguous else None,
        decoded_prefix_end=previous_end, raw_gaps=gaps, raw_overlaps=overlaps,
        kinds=dict(kinds), immediate_duplicates=duplicates, unrelated_frames=unrelated,
        protocol_issues=issues, ends=ends, stop_acks=acks,
        unknown_produced_end=(not ends or any(e["produced_end"] is None for e in ends)),
        limits=[
            "This is a narrow offline observation check, not a full endpoint deadline replay.",
            "Matching bytes verify the selected retained range, not unobserved ADC conversions.",
            "Missing END or produced_end=null retains an unknown tail; no zero-loss inference.",
            "Host monotonic timestamps are I/O observations, not calibrated sample timing.",
            "Source/image provenance and the physical board require separate evidence.",
        ],
    )
    # A disconnect can leave a partial trailing frame outside the retained
    # range. Report it explicitly; it does not erase a verified earlier prefix.
    report["status"] = "PASS" if equal and started and not issues and not wire["decode_errors"] else "FAIL"
    require(traffic_path.read_bytes() == raw and sha(journal_path.read_bytes()) == journal_sha,
            "Input changed during offline verification")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path)
    args = parser.parse_args()
    output = args.trial.resolve() / "wire-verification.json"
    require(not output.exists(), "wire-verification.json already exists; preserve it before rerunning")
    try:
        report = verify(args.trial.resolve())
    except (ValueError, OSError, KeyError, struct.error) as exc:
        report = {"schema": "motortester-v2-wire-verification-1", "status": "FAIL",
                  "error": type(exc).__name__ + ": " + str(exc),
                  "physical_identity_verified": False, "adc_losslessness_verified": False}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "output": str(output),
                      "selected_range_byte_equal": report.get("selected_range_byte_equal"),
                      "selected_samples": report.get("selected_samples")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
