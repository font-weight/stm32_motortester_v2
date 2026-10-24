"""Offline analysis of the single V2SB trial, whether probe PASS or FAIL.

Only physical-analysis.json/.md are created. No device access or GUI instance.
The existing verifier owns selected journal/raw equality; this helper adds exact
image/receipt/sequence and STOP-order checks without requiring a failed trial.
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
sys.path.insert(0, str(ROOT / "host/tools"))
from verify_stream_trial import MAX_TRAFFIC, parse_traffic, require, verify
from motortester.v2.stream_device import open_verified_context
from motortester.stream_wire import Kind

BUILD = 0x56325342
SOURCE = "8243fb3224a1e24980848a8ce02431ec41f5bd9c"
IMAGE_SHA = "e7f6f07fc6a43e6b109af6e5c652db1322a0e5023e328007b2c50d303f12536e"
CAPS = (1, 1, 0, 12, 100000, 1, 128, 1)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def preserve(path, raw):
    if path.exists():
        require(path.read_bytes() == raw, "Refusing to replace different evidence: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def main():
    run = HERE / "run"
    receipt_path, traffic_path = run / "result.json", run / "traffic.bin"
    require(receipt_path.is_file(), "Completed run/result.json required; do not read an active trial")
    receipt = json.loads(receipt_path.read_bytes())
    require(receipt["status"] in ("PASS", "FAIL"), "Unknown probe status")
    closed = (receipt.get("owners_closed") is True if receipt["status"] == "PASS" else
              receipt.get("cleanup_finished") is True and receipt.get("final_state", {}).get("phase") == "closed")
    require(closed, "COM owner closure must precede offline analysis")
    original_paths = [p for p in (receipt_path, traffic_path, run / "physical.mtstream",
                                 run / "physical.mtstream.v2.json", HERE / "plan.json") if p.is_file()]
    original_hashes = {p.relative_to(HERE).as_posix(): sha(p.read_bytes()) for p in original_paths}
    issues = []
    def check(condition, label):
        if not condition:
            issues.append(label)
        return bool(condition)
    require(traffic_path.stat().st_size <= MAX_TRAFFIC, "Traffic exceeds bounded verifier size")
    traffic = traffic_path.read_bytes()
    check(sha(traffic) == receipt["traffic"]["sha256"], "traffic_hash_receipt")
    wire = {}
    frames = parse_traffic(traffic, wire)
    check(not wire["decode_errors"], "wire_decode_errors")
    wire_complete = (not wire["decode_errors"] and wire["trailing_partial_bytes"] == [0, 0]
                     and wire["trailing_oversized_frame"] == [False, False])
    for field in ("chunks", "host_bytes", "device_bytes"):
        check(wire[field] == receipt["traffic"][field], "traffic_count_" + field)
    plan = json.loads((HERE / "plan.json").read_bytes())
    check(plan["base_commit"] == SOURCE, "plan_source")
    check(receipt["expected_build"] == BUILD and receipt["expected_sample_rate_hz"] == 100000,
          "probe_expected_identity")
    check(receipt["seconds_requested"] == 30, "probe_target_not_30_seconds")
    candidate = ROOT / "build/v6h-fw-01/MotortesterV2-stream-candidate.bin"
    check(sha(candidate.read_bytes()) == IMAGE_SHA, "local_candidate_bytes")
    connection = receipt.get("connection")
    if connection is not None:
        check(connection["selection"]["declared_source_commit"] == SOURCE and
              connection["selection"]["declared_artifact_sha256"] == IMAGE_SHA,
              "connection_declared_source_image")
        check(connection["observed_build_id"] == BUILD and tuple(connection["observed_caps"]) == CAPS,
              "connection_observed_identity")
    nonce, start, caps = None, None, None
    sequences, requests, kind_counts = [0, 0], {}, {}
    raw, next_index, last_data_sequence = bytearray(), 0, 0
    ends, acks, stops, controls = [], [], [], []
    data_stamps = []
    origin = frames[0][1] if frames else None
    for order, (direction, stamp, frame, decoded) in enumerate(frames):
        key = ("device/" if direction else "host/") + frame.kind.name
        kind_counts[key] = kind_counts.get(key, 0) + 1
        if frame.kind == Kind.HELLO:
            check(nonce is None, "multiple_HELLO")
            nonce = decoded.nonce
        effective_nonce = decoded.nonce if frame.kind == Kind.HELLO else frame.nonce
        check(nonce is not None and effective_nonce == nonce, "mixed_or_missing_nonce")
        check(frame.sequence == sequences[direction] + 1, "sequence_gap_duplicate_or_order")
        sequences[direction] = frame.sequence
        if direction == 0:
            check(frame.request_id not in requests, "duplicate_request_id")
            requests[frame.request_id] = frame.kind
        elif frame.kind not in (Kind.DATA, Kind.END):
            expected = {Kind.HELLO_ACK: Kind.HELLO, Kind.CAPS: Kind.GET_CAPS,
                        Kind.START_ACK: Kind.START, Kind.STOP_ACK: Kind.STOP}.get(frame.kind)
            check(expected is not None and requests.get(frame.request_id) == expected, "reply_correlation")
        else:
            check(frame.request_id == 0, "async_nonzero_request")
        item = {"order": order, "direction": "device" if direction else "host",
                "kind": frame.kind.name, "sequence": frame.sequence, "request_id": frame.request_id,
                "host_relative_seconds": stamp - origin}
        if frame.kind == Kind.HELLO_ACK:
            check(decoded.firmware_build == BUILD, "HELLO_build")
        elif frame.kind == Kind.CAPS:
            caps = decoded
            check(tuple(asdict(caps).values()) == CAPS, "CAPS_contract")
        elif frame.kind == Kind.START_ACK:
            check(start is None and caps is not None, "START_order_or_repeat")
            start = decoded
            check(start.generation == frame.request_id and start.first_index == 0 and
                  start.config_id == CAPS[0], "START_identity")
        elif frame.kind == Kind.DATA:
            check(start is not None and not ends, "DATA_outside_started_session")
            if start is not None:
                check(decoded.generation == start.generation and decoded.config_id == start.config_id,
                      "DATA_identity")
            check(decoded.first_index == next_index, "DATA_gap_or_overlap")
            check(0 < len(decoded.samples) <= 128, "DATA_size")
            raw.extend(decoded.raw_samples)
            next_index, last_data_sequence = decoded.end_index, frame.sequence
            data_stamps.append(stamp)
            continue
        if frame.kind not in (Kind.GET_CAPS, Kind.START, Kind.STOP):
            item["payload"] = asdict(decoded)
        elif frame.kind in (Kind.START, Kind.STOP):
            item["payload"] = decoded
        controls.append(item)
        if frame.kind == Kind.END:
            ends.append(item)
            check(start is not None and decoded.generation == start.generation and
                  decoded.config_id == start.config_id, "END_identity")
            check(decoded.prefix_end == next_index and decoded.prefix_crc32 == zlib.crc32(raw)
                  and decoded.last_data_sequence == last_data_sequence, "END_prefix_CRC")
        elif frame.kind == Kind.STOP:
            stops.append(item)
            check(start is not None and decoded == start.generation, "STOP_generation")
        elif frame.kind == Kind.STOP_ACK:
            acks.append(item)
            check(bool(ends) and all(asdict(decoded)[a] == ends[-1]["payload"][b] for a, b in
                  (("generation", "generation"), ("prefix_end", "prefix_end"),
                   ("flags", "flags"))), "ACK_terminal")
        elif frame.kind == Kind.ERROR:
            check(False, "device_ERROR_reply")
    # ACK uses END frame sequence; perform this explicitly below as well.
    terminal = ends[0] if len(ends) == 1 else None
    stop = stops[0] if len(stops) == 1 else None
    ack = acks[0] if len(acks) == 1 else None
    end_before_stop = bool(terminal and stop and terminal["order"] < stop["order"])
    normal_stop = bool(terminal and stop and ack and not end_before_stop and
                       terminal["payload"]["reason"] == 0 and
                       terminal["payload"]["stop_request_id"] == stop["request_id"] and
                       ack["request_id"] == stop["request_id"])
    if terminal and ack:
        check(ack["payload"]["terminal_sequence"] == terminal["sequence"], "ACK_END_sequence")
    selected = None
    journal = run / "physical.mtstream"
    if journal.is_file():
        try:
            selected = verify(run)
            check(selected["status"] == "PASS" and selected["selected_range_byte_equal"], "journal_wire_equality")
            check(not selected["protocol_issues"] and not selected["raw_gaps"] and not selected["raw_overlaps"]
                  and not selected["immediate_duplicates"] and not selected["unrelated_frames"], "journal_wire_protocol")
            check(selected["decoded_data_sha256"] == sha(raw) and selected["decoded_prefix_end"] == next_index,
                  "full_prefix_crosscheck")
            check(selected["recording_recovery_issue"] is None and not selected["discarded_journal_tail_bytes"],
                  "journal_recovery_issue")
            context = open_verified_context(journal)
            check(context.companion_present and context.connection is not None, "companion_missing")
            check(json.loads(json.dumps(asdict(context.connection))) == connection, "companion_connection")
            selected["fresh_open_companion_verified"] = True
            state = receipt.get("final_state", receipt.get("after_stop", {}))
            check(state.get("R") == selected["R"] and state.get("accepted") == selected["end"] and
                  state.get("checkpoint") == selected["end"], "journal_final_receipt_range")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            issues.append("journal_verification: " + str(exc))
    before = receipt.get("before_stop", {})
    observations = receipt.get("observations", [])
    elapsed = receipt.get("record_wall_seconds")
    rate = ((before["received"] - observations[0]["received"]) / elapsed
            if observations and elapsed and "received" in before else None)
    rough_rate_ok = rate is not None and 90000 <= rate <= 110000
    record_duration_ok = elapsed is not None and elapsed >= 30
    if receipt["status"] == "PASS":
        check(normal_stop and wire_complete, "PASS_requires_complete_normal_STOP_exchange")
        check(selected is not None, "PASS_missing_journal")
        check(record_duration_ok and rough_rate_ok, "PASS_record_duration_or_rough_pacing")
        check(not before.get("failure") and not before.get("error") and
              not receipt.get("errors") and not receipt.get("callback_errors"), "PASS_host_source_error")
    original_after = {p.relative_to(HERE).as_posix(): sha(p.read_bytes()) for p in original_paths}
    require(original_after == original_hashes, "Original evidence changed during offline analysis")
    issues = list(dict.fromkeys(issues))
    report = {
        "schema": "v2-06h-physical-offline-analysis-1", "probe_status": receipt["status"],
        "offline_validation_status": "PASS" if not issues else "FAIL", "issues": issues,
        "physical_qualification_complete": False,
        "scope": "Saved single trial only; diagnostics/registers/readback and independent physical review remain separate.",
        "expected_build": BUILD, "declared_source_commit": SOURCE, "local_candidate_sha256": IMAGE_SHA,
        "nonce_hex": None if nonce is None else f"{nonce:016x}",
        "generation": None if start is None else start.generation,
        "observed_caps": None if caps is None else asdict(caps), "owners_closed": closed,
        "wire": wire, "wire_complete": wire_complete, "kind_counts": kind_counts,
        "sequence_range": {"host": [1, sequences[0]], "device": [1, sequences[1]]},
        "control_timeline": controls, "timeline_units": "host I/O monotonic seconds, not ADC or USB IN/NAK timing",
        "received_prefix": {"samples": len(raw) // 2, "end_index": next_index,
                            "bytes": len(raw), "sha256": sha(raw), "crc32": zlib.crc32(raw),
                            "DATA_blocks": len(data_stamps), "nominal_step_us": 10},
        "terminal": terminal, "stop": stop, "ack": ack, "END_before_STOP": end_before_stop,
        "normal_stop_exchange": normal_stop,
        "unknown_produced_tail": terminal is None or terminal["payload"]["produced_end"] is None,
        "selected_journal_analysis": selected,
        "record_observation": {"seconds_requested": receipt["seconds_requested"], "wall_seconds": elapsed,
                               "first_received": observations[0]["received"] if observations else None,
                               "before_STOP_received": before.get("received"),
                               "rough_delta_received_per_second": rate, "rough_rate_90k_110k": rough_rate_ok,
                               "record_at_least_30_seconds": record_duration_ok,
                               "qualified_clock_measurement": False},
        "input_condition": receipt.get("input_condition"),
        "original_files_sha256": original_hashes, "original_files_unchanged": True,
        "analysis_tool_sha256": sha(Path(__file__).read_bytes()),
        "wire_verifier_sha256": sha((ROOT / "host/tools/verify_stream_trial.py").read_bytes()),
        "limits": ["Known transmitted/selected prefix does not establish unobserved produced samples or zero ADC loss.",
                   "Normal END reason0 with unknown produced end remains a confirmed requested Stop, not a complete measured ADC tail.",
                   "A FAIL probe remains failed even when the retained prefix is byte-exact.",
                   "Host sample-count slope is a rough pacing observation, not ADC calibration, analog bandwidth or voltage validation.",
                   "Offline decoding does not itself authenticate the flashed image or close the independent hardware review."],
    }
    selected_text = (f"[{selected['R']}, {selected['end']}), {selected['selected_samples']} отсчётов; "
                     f"raw SHA-256 `{selected['journal_selected_sha256']}`" if selected else "не подтверждён")
    md = f"""# V2-06h: сохранённый физический опыт

Статус probe: **{receipt['status']}**. Offline-проверка: **{report['offline_validation_status']}**.
Это разбор уже сохранённого опыта; новых подключений/проб нет. Аппаратное
заключение требует отдельных readback, диагностики/регистров и ревью.

- Build `0x{BUILD:08x}`, nonce `{report['nonce_hex']}`, generation `{report['generation']}`.
- Полученный префикс: {len(raw)//2} отсчётов; SHA-256 `{sha(raw)}`.
- Выбранная запись: {selected_text}.
- Штатный обмен Stop/END/ACK: `{normal_stop}`; END раньше STOP: `{end_before_stop}`.
- Длительность Record по host: `{elapsed}` с; грубый темп Δполучено/Δhost: `{rate}` отсчётов/с.
- Неизвестный произведённый хвост: `{report['unknown_produced_tail']}`. Это не нулевое число потерь.
- Закрытие владельца COM: `{closed}`; исходные файлы неизменны.
- Замечания offline-проверки: `{issues}`.

Полное побайтное сравнение выбранного диапазона, последовательность/CRC,
fresh Open/companion и хеши находятся в `physical-analysis.json`.
Грубый темп по host не измеряет частоту ADC, полосу входа или точность напряжения.
Отрицательный физический результат не становится положительным от совпадения сохранённого префикса.
"""
    preserve(HERE / "physical-analysis.json", (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    preserve(HERE / "physical-analysis.md", md.encode("utf-8"))
    print(json.dumps({"probe": receipt["status"], "offline": report["offline_validation_status"],
                      "nonce": report["nonce_hex"], "generation": report["generation"],
                      "received": len(raw)//2, "normal_stop": normal_stop, "issues": issues}, ensure_ascii=False))


if __name__ == "__main__":
    main()
