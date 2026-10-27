"""Offline SH trial analysis, with separate discovery and selected-mode sessions.

Read only completed <Fs>/run evidence. This script never opens COM/SWD or Qt.
It creates only <Fs>/physical-analysis.json/.md, preserving earlier results.
PASS here concerns saved evidence, not independent physical qualification.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "host"), str(ROOT / "host/tools")]
from verify_stream_trial import MAX_TRAFFIC, parse_traffic, require, verify
from motortester.v2.stream_files import open_stream
from motortester.stream_wire import (Kind, MODE_TABLE, MODE_MAX_BLOCK,
                                    MODE_MAX_PAYLOAD, mode_revision, caps_values)

PLAN = json.loads((HERE / "plan.json").read_text("utf-8"))
BUILD = int(PLAN["firmware_build"], 16)
SOURCE = PLAN["source_commit"]
IMAGE_SHA = PLAN["candidate_sha256"]
CANDIDATE = ROOT / PLAN["candidate_path"]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def preserve(path, raw):
    if path.exists():
        require(path.read_bytes() == raw, "Refusing to replace different evidence: " + str(path))
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def analyze(sample_rate, seconds):
    trial = HERE / str(sample_rate)
    run = trial / "run"
    mode = {50000: 1, 100000: 2, 150000: 5}[sample_rate]
    retained, encoding = MODE_TABLE[mode][1:]
    expected_caps = (mode, mode, 0, 12, sample_rate, 1, MODE_MAX_BLOCK[mode], 1, retained, encoding)
    receipt_path, traffic_path = run / "result.json", run / "traffic.bin"
    require(receipt_path.is_file(), "Completed run/result.json required; no active trial reads")
    receipt = json.loads(receipt_path.read_bytes())
    require(receipt["status"] in ("PASS", "FAIL"), "Unknown completed probe status")
    closed = (receipt.get("owners_closed") is True if receipt["status"] == "PASS" else
              receipt.get("cleanup_finished") is True and receipt.get("final_state", {}).get("phase") == "closed")
    require(closed, "Confirmed owner closure must precede offline analysis")
    paths = [p for p in (receipt_path, traffic_path, run / "physical.mtstream",
                        run / "physical.mtstream.v2.json", HERE / "plan.json", trial / "plan.json") if p.is_file()]
    before_hashes = {p.relative_to(HERE).as_posix(): sha(p.read_bytes()) for p in paths}
    issues = []
    def check(condition, label):
        if not condition:
            issues.append(label)
        return bool(condition)

    require(traffic_path.is_file() and traffic_path.stat().st_size <= MAX_TRAFFIC, "Bounded traffic.bin required")
    traffic = traffic_path.read_bytes()
    check(sha(traffic) == receipt["traffic"]["sha256"], "traffic_receipt_hash")
    wire = {}
    frames = parse_traffic(traffic, wire)
    check(not wire["decode_errors"], "wire_decode_errors")
    wire_complete = not wire["decode_errors"] and wire["trailing_partial_bytes"] == [0, 0] and not any(wire["trailing_oversized_frame"])
    for field in ("chunks", "host_bytes", "device_bytes"):
        check(wire[field] == receipt["traffic"][field], "traffic_count_" + field)
    check(receipt.get("expected_build") == BUILD and receipt.get("expected_sample_rate_hz") == sample_rate,
          "probe_expected_identity")
    check(receipt.get("seconds_requested") == seconds, "probe_target_duration")
    check(sha(CANDIDATE.read_bytes()) == IMAGE_SHA, "local_exact_candidate")
    connection = receipt.get("connection")
    if connection is not None:
        check(connection["selection"]["declared_source_commit"] == SOURCE and
              connection["selection"]["declared_artifact_sha256"] == IMAGE_SHA,
              "connection_declared_source_image")
        check(connection["selection"].get("requested_sample_rate_hz") == sample_rate and
              connection["protocol_revision"] == "0.3" and connection["observed_build_id"] == BUILD and
              tuple(connection["observed_caps"]) == expected_caps, "connection_observed_mode")
        check(connection["execution_kind"] == "physical" and connection["image_verified"] is False,
              "connection_provenance")

    sessions, hellos, controls, kinds = {}, [], [], {}
    full_nonce = discovery_nonce = None
    discovery_ack_order = None
    foreign_frames = 0
    start = caps = None
    start_commands, ends, acks, stops = [], [], [], []
    raw, next_index, last_data = bytearray(), 0, 0
    data_count = 0
    full_data_count, data_sizes, short_data = 0, {}, []
    largest_data_frame, largest_selected_frame = 0, 0
    first_data_samples = None
    short_seen, contiguous = False, True
    origin = frames[0][1] if frames else 0
    for order, (direction, stamp, frame, payload) in enumerate(frames):
        name = ("device/" if direction else "host/") + frame.kind.name
        kinds[name] = kinds.get(name, 0) + 1
        effective_nonce = payload.nonce if frame.kind == Kind.HELLO else frame.nonce
        if frame.kind == Kind.HELLO:
            check(direction == 0 and effective_nonce not in sessions, "HELLO_direction_repeat_or_reused_nonce")
            hellos.append({"order": order, "nonce": f"{effective_nonce:016x}",
                           "revision": frame.revision, "mode": payload.mode})
            sessions[effective_nonce] = {"revision": frame.revision, "sequence": [0, 0],
                                         "requests": {}, "frames": 0, "ACK": False}
            if frame.revision == "0.2":
                check(discovery_nonce is None and full_nonce is None and payload.mode == 0, "discovery_order")
                discovery_nonce = effective_nonce
            else:
                check(frame.revision == "0.3" and payload.mode == mode, "selected_HELLO_mode")
                check(full_nonce is None and discovery_nonce is not None and
                      discovery_ack_order is not None and discovery_ack_order < order and
                      effective_nonce != discovery_nonce, "fresh_mode_HELLO_after_discovery_ACK")
                full_nonce = effective_nonce
        session = sessions.get(effective_nonce)
        if session is None:
            foreign_frames += 1
            continue  # Valid old-session frames do not belong to this source.
        check(frame.revision == session["revision"], "session_revision")
        check(frame.sequence == session["sequence"][direction] + 1, "session_sequence_gap_duplicate_or_order")
        session["sequence"][direction] = frame.sequence
        session["frames"] += 1
        requests = session["requests"]
        if direction == 0:
            check(frame.request_id not in requests, "session_duplicate_request")
            requests[frame.request_id] = frame.kind
        elif frame.kind not in (Kind.DATA, Kind.END):
            wanted = {Kind.HELLO_ACK: Kind.HELLO, Kind.CAPS: Kind.GET_CAPS,
                      Kind.START_ACK: Kind.START, Kind.STOP_ACK: Kind.STOP}.get(frame.kind)
            check(wanted is not None and requests.get(frame.request_id) == wanted, "session_reply_correlation")
        else:
            check(frame.request_id == 0, "async_nonzero_request")
        item = {"order": order, "direction": "device" if direction else "host", "kind": frame.kind.name,
                "revision": frame.revision, "nonce": f"{effective_nonce:016x}",
                "sequence": frame.sequence, "request_id": frame.request_id,
                "host_relative_seconds": stamp - origin}
        if effective_nonce == full_nonce:
            # Frame.encoded is the exact captured COBS frame, including its
            # delimiter. A frame may span several host reads; never count
            # traffic chunks as USB packets or as logical DATA frames.
            largest_selected_frame = max(largest_selected_frame, len(frame.encoded))
        if frame.kind == Kind.HELLO_ACK:
            check(payload.firmware_build == BUILD, "HELLO_build")
            check(payload.max_block == (1024 if frame.revision == "0.2" else MODE_MAX_BLOCK[mode]), "HELLO_max_block")
            expected_marker = 15 if frame.revision == "0.2" else 1
            check(payload.capabilities == expected_marker, "HELLO_capability_marker")
            check(payload.max_payload == (1300 if frame.revision == "0.2" else MODE_MAX_PAYLOAD[mode]), "HELLO_max_payload")
            session["ACK"] = True
            if effective_nonce == discovery_nonce:
                discovery_ack_order = order
        if effective_nonce == discovery_nonce:
            check(frame.kind in (Kind.HELLO, Kind.HELLO_ACK), "discovery_must_not_START_or_acquire")
        elif effective_nonce == full_nonce:
            if frame.kind == Kind.CAPS:
                caps = payload
                check(session["ACK"] and caps_values(caps) == expected_caps, "selected_CAPS_contract")
            elif frame.kind == Kind.START:
                check(caps is not None and payload == mode and not start_commands, "START_selected_config_or_repeat")
                start_commands.append(item)
            elif frame.kind == Kind.START_ACK:
                check(start is None and caps is not None and len(start_commands) == 1, "START_ACK_order")
                start = payload
                check(start.generation == frame.request_id and start.first_index == 0 and
                      start.config_id == mode, "START_ACK_identity")
            elif frame.kind == Kind.DATA:
                check(start is not None and not ends and not short_seen, "DATA_order_or_after_short")
                if start is not None:
                    check(payload.generation == start.generation and payload.config_id == mode, "DATA_identity")
                contiguous &= check(payload.first_index == next_index, "DATA_gap_or_overlap")
                check(all(0 <= code <= (4092 if retained == 10 else 4095) and
                          (retained == 12 or code % 4 == 0) for code in payload.samples), "canonical_raw_domain")
                count = len(payload.samples)
                check(1 <= count <= MODE_MAX_BLOCK[mode], "DATA_count_bound")
                check(len(frame.payload) <= MODE_MAX_PAYLOAD[mode] and
                      len(frame.encoded) <= (1335 if mode == 5 else 544), "DATA_frame_bound")
                if first_data_samples is None:
                    first_data_samples = count
                data_sizes[count] = data_sizes.get(count, 0) + 1
                largest_data_frame = max(largest_data_frame, len(frame.encoded))
                if count == MODE_MAX_BLOCK[mode]:
                    full_data_count += 1
                else:
                    short_data.append({"sequence": frame.sequence, "first_index": payload.first_index,
                        "end_index": payload.end_index, "samples": count,
                        "frame_bytes_including_delimiter": len(frame.encoded)})
                raw.extend(payload.raw_samples)
                next_index, last_data = payload.end_index, frame.sequence
                data_count += 1
                short_seen = count < MODE_MAX_BLOCK[mode]
                continue
        if frame.kind in (Kind.GET_CAPS, Kind.START, Kind.STOP):
            item["payload"] = payload
        else:
            item["payload"] = asdict(payload)
        controls.append(item)
        if effective_nonce != full_nonce:
            continue
        if frame.kind == Kind.END:
            ends.append(item)
            check(start is not None and payload.generation == start.generation and payload.config_id == mode,
                  "END_identity")
            check(contiguous and payload.prefix_end == next_index and payload.prefix_crc32 == zlib.crc32(raw)
                  and payload.last_data_sequence == last_data, "END_canonical_prefix_CRC")
        elif frame.kind == Kind.STOP:
            stops.append(item)
            check(start is not None and payload == start.generation, "STOP_generation")
        elif frame.kind == Kind.STOP_ACK:
            acks.append(item)
            check(bool(ends) and all(asdict(payload)[key] == ends[-1]["payload"][key]
                  for key in ("generation", "prefix_end", "flags")), "ACK_terminal_fields")
            check(bool(ends) and payload.terminal_sequence == ends[-1]["sequence"], "ACK_END_sequence")
        elif frame.kind == Kind.ERROR:
            check(False, "device_ERROR_reply")

    terminal = ends[0] if len(ends) == 1 else None
    stop = stops[0] if len(stops) == 1 else None
    ack = acks[0] if len(acks) == 1 else None
    check(len(ends) <= 1 and len(stops) <= 1 and len(acks) <= 1, "repeated_terminal_or_STOP")
    end_before_stop = bool(terminal and stop and terminal["order"] < stop["order"])
    short_is_final = (not short_data or len(short_data) == 1 and
                      short_data[0]["sequence"] == last_data and short_data[0]["end_index"] == next_index)
    check(short_is_final, "DATA_short_must_be_unique_final")
    normal_stop = bool(terminal and stop and ack and not end_before_stop and
        terminal["payload"]["reason"] == 0 and terminal["payload"]["stop_request_id"] == stop["request_id"] and
        ack["request_id"] == stop["request_id"] and ack["order"] > terminal["order"])
    selected, unbound = None, None
    journal_path = run / "physical.mtstream"
    if journal_path.is_file():
        try:
            context, attempt = open_stream(journal_path)
            identity = attempt.preparation.identity
            check(identity.protocol_revision == mode_revision(mode) and identity.origin == "device" and
                  identity.config_id == mode and identity.acquisition_mode == mode and
                  identity.nominal_fs_hz == sample_rate and identity.source_adc_bits == 12 and
                  identity.retained_bits == retained and identity.discarded_lsb == 12 - retained and
                  identity.stored_code_domain == "adc12" and identity.stored_sample_encoding == "u16le",
                  "journal_intrinsic_mode")
            check(context.companion_present and context.connection is not None, "fresh_companion_missing")
            check(context.connection is not None and json.loads(json.dumps(asdict(context.connection))) == connection,
                  "companion_connection")
            if attempt.recording is None:
                unbound = {"identity": asdict(identity), "recovery_issue": attempt.recovery_issue,
                    "discarded_tail_bytes": attempt.discarded_tail_bytes,
                    "outcome": None if attempt.unbound_outcome is None else asdict(attempt.unbound_outcome)}
            else:
                selected = verify(run)
                check(selected["status"] == "PASS" and selected["selected_range_byte_equal"], "selected_wire_raw_equality")
                check(not selected["protocol_issues"] and not selected["raw_gaps"] and not selected["raw_overlaps"]
                      and not selected["immediate_duplicates"], "selected_wire_protocol")
                # The two discovery frames are intentionally another nonce.
                expected_unrelated = sum(1 for _, _, f, p in frames
                    if (p.nonce if f.kind == Kind.HELLO else f.nonce) != full_nonce)
                check(selected["unrelated_frames"] == expected_unrelated, "discovery_exclusion_count")
                check(selected["decoded_data_sha256"] == sha(raw) and selected["decoded_prefix_end"] == next_index,
                      "full_prefix_crosscheck")
                check(selected["recording_recovery_issue"] is None and not selected["discarded_journal_tail_bytes"],
                      "journal_recovery_issue")
                selected["fresh_open_companion_verified"] = context.companion_present
                state = receipt.get("final_state", receipt.get("after_stop", {}))
                check(state.get("R") == selected["R"] and state.get("accepted") == selected["end"] and
                      state.get("checkpoint") == selected["end"], "journal_final_receipt_range")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            issues.append("journal_verification: " + str(exc))
    before = receipt.get("before_stop", {})
    observations = receipt.get("observations", [])
    elapsed = receipt.get("record_wall_seconds")
    rough_rate = ((before["received"] - observations[0]["received"]) / elapsed
                  if observations and elapsed and "received" in before else None)
    duration_ok = elapsed is not None and elapsed >= seconds
    pacing_ok = rough_rate is not None and sample_rate * .9 <= rough_rate <= sample_rate * 1.1
    if receipt["status"] == "PASS":
        check(len(hellos) == 2 and discovery_ack_order is not None and full_nonce is not None,
              "PASS_requires_discovery_then_fresh_mode_session")
        check(normal_stop and wire_complete and selected is not None, "PASS_requires_journal_and_complete_STOP_exchange")
        check(duration_ok and pacing_ok, "PASS_duration_or_rough_pacing")
        check(not before.get("failure") and not before.get("error") and
              not receipt.get("errors") and not receipt.get("callback_errors"), "PASS_host_source_error")
    after_hashes = {p.relative_to(HERE).as_posix(): sha(p.read_bytes()) for p in paths}
    require(after_hashes == before_hashes, "Original evidence changed during analysis")
    issues = list(dict.fromkeys(issues))
    report = {"schema": "v2-06m-physical-offline-analysis-1", "probe_status": receipt["status"],
        "offline_validation_status": "PASS" if not issues else "FAIL", "issues": issues,
        "physical_qualification_complete": False,
        "scope": "One saved trial; no hardware access, no CPU/ADC-clock qualification or inference from host I/O time",
        "expected_build": BUILD, "declared_source_commit": SOURCE, "local_candidate_sha256": IMAGE_SHA,
        "requested_sample_rate_hz": sample_rate, "mode": mode, "retained_bits": retained,
        "discovery_nonce": None if discovery_nonce is None else f"{discovery_nonce:016x}",
        "nonce_hex": None if full_nonce is None else f"{full_nonce:016x}",
        "generation": None if start is None else start.generation,
        "observed_caps": None if caps is None else asdict(caps), "HELLOs": hellos,
        "session_sequences": {f"{nonce:016x}": {"revision": s["revision"], "host_end": s["sequence"][0],
            "device_end": s["sequence"][1], "frames": s["frames"], "ACK_observed": s["ACK"]} for nonce, s in sessions.items()},
        "other_foreign_nonce_frames": foreign_frames, "owners_closed": closed,
        "wire": wire, "wire_complete": wire_complete, "kind_counts": kinds,
        "batch": {"mode": mode, "negotiated_max_block": MODE_MAX_BLOCK[mode],
            "negotiated_max_payload": MODE_MAX_PAYLOAD[mode],
            "DATA_frames": data_count, "full_negotiated_DATA_frames": full_data_count,
            "full_DATA1024_frames": full_data_count if mode == 5 else 0,
            "first_DATA_samples": first_data_samples,
            "DATA_sample_count_histogram": {str(n): data_sizes[n] for n in sorted(data_sizes)},
            "short_tail_frames": len(short_data),
            "terminal_short_samples": short_data[0]["samples"] if short_data and short_is_final else None,
            "short_frames": short_data, "short_is_unique_final": short_is_final,
            "largest_DATA_frame_bytes": largest_data_frame,
            "largest_selected_session_frame_bytes": largest_selected_frame,
            "length_includes_COBS_delimiter": True,
            "scope": "Only complete CRC-valid decoded selected-session frames; partial or corrupt tails are separate wire fields, not published DATA"},
        "control_timeline": controls, "timeline_units": "host I/O monotonic seconds, not ADC or USB IN/NAK timing",
        "received_prefix": {"samples": len(raw) // 2, "end_index": next_index, "bytes": len(raw),
            "sha256": sha(raw), "crc32": zlib.crc32(raw), "DATA_blocks": data_count, "contiguous": contiguous,
            "nominal_sample_interval_seconds": 1 / sample_rate,
            "sample_interval_microseconds_rational": [20, 3] if mode == 5 else [1_000_000 // sample_rate, 1],
            "canonical_encoding": "u16le_adc12_scale", "original_ADC12_complete": retained == 12,
            "normalization": "left_shift_2" if mode == 5 else "identity",
            "quantization": "truncate_lsb" if mode == 5 else "none"},
        "terminal": terminal, "stop": stop, "ack": ack, "END_before_STOP": end_before_stop,
        "normal_stop_exchange": normal_stop,
        "unknown_produced_tail": terminal is None or terminal["payload"]["produced_end"] is None,
        "selected_journal_analysis": selected, "unbound_journal": unbound,
        "record_observation": {"seconds_requested": seconds, "wall_seconds": elapsed,
            "first_received": observations[0]["received"] if observations else None,
            "before_STOP_received": before.get("received"), "rough_delta_received_per_second": rough_rate,
            "rough_within_90_110_percent": pacing_ok, "target_duration_met": duration_ok,
            "qualified_clock_measurement": False, "FAIL_short_prefix_is_not_sustained_rate": receipt["status"] == "FAIL"},
        "input_condition": receipt.get("input_condition"),
        "original_files_sha256_before": before_hashes, "original_files_sha256_after": after_hashes,
        "original_files_unchanged": True, "analysis_tool_sha256": sha(Path(__file__).read_bytes()),
        "wire_verifier_sha256": sha((ROOT / "host/tools/verify_stream_trial.py").read_bytes()),
        "limits": ["Canonical10 retains all transmitted information, not the discarded ADC12 low2 bits.",
            "Quantization edge bins0/4092 do not prove original ADC saturation0/4095.",
            "Matching retained bytes do not prove zero ADC loss or the unobserved produced tail.",
            "FAIL remains FAIL even if its retained prefix is byte-exact; a short-prefix slope is not sustained rate.",
            "Normal END reason0 and unknown produced end do not establish a complete measured ADC tail.",
            "Diagnostics/registers/readback and independent hardware review remain separate."]}
    selected_text = (f"[{selected['R']}, {selected['end']}), {selected['selected_samples']} отсчётов; "
        f"raw SHA-256 `{selected['journal_selected_sha256']}`" if selected else "подтверждённый выбранный диапазон отсутствует")
    md = f"""# V2-06o: сохранённый опыт {sample_rate} отсчётов/с

Probe: **{receipt['status']}**. Offline-проверка: **{report['offline_validation_status']}**.
Это разбор уже закрытого сеанса, без новых подключений и аппаратной приёмки.

- SH/build `0x{BUILD:08x}`, mode{mode}, ADC12 / сохранено{retained} бит.
- Discovery nonce `{report['discovery_nonce']}`; выбранный nonce `{report['nonce_hex']}`, generation `{report['generation']}`.
- Получено {len(raw)//2} кодов в каноническом масштабе12бит; SHA-256 `{sha(raw)}`.
- Полных DATA по{MODE_MAX_BLOCK[mode]}: {full_data_count}; коротких: {len(short_data)}, последний хвост: `{report['batch']['terminal_short_samples']}` отсчётов.
- Максимальный DATA-кадр с COBS и delimiter: {largest_data_frame}байт; это логический кадр, не USB-пакет или host read.
- Запись: {selected_text}.
- Штатный Stop/END/ACK: `{normal_stop}`; END раньше STOP: `{end_before_stop}`.
- Record по host: `{elapsed}`с при запросе{seconds}с; грубый Δполучено/Δhost `{rough_rate}` отсчётов/с.
- Неизвестный произведённый хвост: `{report['unknown_produced_tail']}`; это не нулевые потери.
- Владелец COM закрыт: `{closed}`; исходные файлы неизменны.
- Замечания: `{issues}`.

В150k два младших бита исходного ADC утрачены; сохранённый code12 кратен4.
Крайние корзины0/4092 не доказывают точное насыщение ADC. Сравнение raw/CRC
не подтверждает полосу/калибровку входа, точность частоты или отсутствие
неизвестного хвоста. Короткий отрицательный опыт не доказывает устойчивый темп.
Последовательности двух nonce, fresh Open/companion, побайтное сравнение и
хеши находятся в `physical-analysis.json`. Диагностика/регистры/readback — отдельно.
"""
    preserve(trial / "physical-analysis.json", (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    preserve(trial / "physical-analysis.md", md.encode("utf-8"))
    print(json.dumps({"probe": receipt["status"], "offline": report["offline_validation_status"],
        "Fs": sample_rate, "nonce": report["nonce_hex"], "generation": report["generation"],
        "received": len(raw) // 2, "normal_stop": normal_stop, "issues": issues}, ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-rate", required=True, type=int, choices=(50_000, 100_000, 150_000))
    parser.add_argument("--seconds", required=True, type=float)
    args = parser.parse_args()
    require(0 < args.seconds <= 30, "Expected finite planned Record duration up to30s")
    raise SystemExit(analyze(args.sample_rate, args.seconds))
