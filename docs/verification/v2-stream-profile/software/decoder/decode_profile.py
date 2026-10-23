"""Independent offline decoder for the pinned draft S9 profile ABI1.

Two separately obtained dump files are required by the CLI. This program never
opens COM/SWD, executes firmware, follows stored pointers, or changes a dump.
Structural validity is separate from physical trial success and attribution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
HEADER = "firmware/v2-stream/profile/mt_stream_profile.h"
ABI_DOC = "firmware/v2-stream/profile/ABI.md"
HEADER_SHA256 = "786ccf29551bc2a56f6ccd380f2efa5a7506e812929756adda59aeef49a8c5c3"
ABI_DOC_SHA256 = "6ca5f7df50bacb662836def10dc296d824c463c45c3b8b3357434a469b6e5cf6"
MAGIC, VERSION, SIZE, BUILD = 0x4D545046, 1, 512, 0x56325339
CAP_CYCLES, MASK = 18_000_000, 0xFFFFFFFF
STATES = ("EMPTY", "ARMED", "ACTIVE", "CLOSING", "FROZEN")
CLOSE_KINDS = ("NONE", "FIRST_FAULT", "NORMAL_STOP", "CAPTURE_LIMIT", "TIME_FAULT",
               "TRANSPORT_LOSS", "NO_ACTIVE_START", "RECOVERY", "ADC_FAULT")
PHASES = ("NONE", "TASK", "ADC", "RX", "TX", "FLUSH", "GRANT_CALL")
WRITE_KINDS = ("NONE", "POSITIVE", "ZERO_SPACE", "ZERO_OTHER", "UNKNOWN")
STAT_NAMES = ("TASK", "ADC_EMPTY", "ADC_BLOCK", "RX", "TX_ACCEPT", "TX_ZERO", "TX_OTHER",
              "FLUSH", "GRANT_CALL", "TIME_UPDATE", "USB_ISR", "GRANT_INTERVAL",
              "GRANT_FIRST_IN_DELAY", "STEP")
COUNTER_NAMES = ("adc_samples_offered", "data_samples_committed", "write_zero_space", "write_zero_other",
                 "write_unknown", "write_accepted_bytes", "in_completion_gap_max_cycles", "foreground_DWT_reads",
                 "grant_allowed", "grant_denied", "in_transfers_published", "in_transfer_bytes_published",
                 "in_ZLP_transfers", "in_packets_completed", "in_packet_bytes_completed", "burst_resume",
                 "hold_final", "hold_other", "hold_budget", "hold_time_timer", "hold_lifecycle_error", "ISR_DWT_reads")
PRIVATE_NAMES = ("phase_id", "phase_start", "phase_open", "step_start", "step_open", "time_start", "time_open",
                 "grant_start", "grant_open", "grant_seen_IN", "write_kind", "write_accepted",
                 "initial_phase_partial_cycles", "initial_step_partial_cycles", "read_pair_min_cycles",
                 "read_pair_max_cycles", "device_address", "adc_address", "begin_phase_id", "last_IN_cycle")
FG_FLAGS = {1: "SATURATED", 2: "NESTED", 4: "DWT_INVALID", 8: "INITIAL_STEP",
            16: "INITIAL_PHASE", 32: "PARTIAL_END", 64: "CAP_OVERSHOOT", 128: "METADATA_INVALID"}
IRQ_FLAGS = {1: "SATURATED", 2: "PACKET_INVALID", 4: "HAVE_IN"}
HEADER_NAMES = ("magic", "version", "bytes", "firmware_build", "state", "fg_flags", "irq_flags",
                "generation", "epoch", "nonce_lo", "nonce_hi", "start_before", "start_after", "end_before",
                "end_after", "close_kind_reason")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def delta(end, start):
    """Unsigned modulo32 difference; a missed complete wrap is unrecoverable."""
    return (end - start) & MASK


def named(value, names):
    return names[value] if 0 <= value < len(names) else f"UNKNOWN_{value}"


def indices(words):
    return {name: words[i * 2] | words[i * 2 + 1] << 32
            for i, name in enumerate(("head", "next", "prefix", "adc"))}


def legacy_dwt_evidence(first, second, build, nonce, generation):
    """Only correlate the unchanged ABI1/136 DWT evidence; not a full legacy audit."""
    if first is None or second is None:
        return {"status": "UNAVAILABLE", "validity_verified": False}
    result = {"status": "INVALID", "validity_verified": False,
              "first_sha256": sha(first), "second_sha256": sha(second),
              "byte_equal": first == second, "issues": []}
    issues = result["issues"]
    if len(first) != 136 or len(second) != 136:
        issues.append("legacy_size_mismatch")
        return result
    words = struct.unpack("<34I", first)
    result["raw_words_u32"] = list(words)
    result["flags_raw"] = words[5]
    if first != second:
        issues.append("legacy_frozen_copies_differ")
    for index, value, label in ((0, 0x4D544447, "magic"), (1, 1, "version"), (2, 136, "bytes"),
                                (3, build, "build"), (4, 3, "frozen_phase"), (6, generation, "generation")):
        if words[index] != value:
            issues.append("legacy_" + label + "_mismatch")
    if (words[32] | words[33] << 32) != nonce:
        issues.append("legacy_nonce_mismatch")
    if words[30] != words[31]:
        issues.append("legacy_last_freeze_stamp_mismatch")
    if words[5] & ~31:
        issues.append("legacy_unknown_flags")
    if words[5] & (1 | 16):
        issues.append("legacy_DWT_unusable_or_invalid_cycle_source")
    result.update(status="INVALID" if issues else "CORRELATED_FROZEN_DWT_FLAGS_CLEAR",
                  validity_verified=not issues, full_legacy_diagnostics_audit=False)
    return result


def decode_copies(first, second, *, expected_build, expected_nonce, expected_generation,
                  expected_epoch=None, nominal_clock_hz=72_000_000,
                  no_debug_halt_confirmed=False, single_wrap_bound_confirmed=False,
                  physical_trial_status="NOT_ASSESSED", legacy_first=None, legacy_second=None):
    if not isinstance(first, bytes) or not isinstance(second, bytes) or nominal_clock_hz <= 0:
        raise ValueError("Expected two byte strings and a positive nominal clock")
    issues, warnings = [], []
    report = {
        "schema": "v2-06f-profile-decoder-1", "abi_status": "PINNED_DRAFT_NOT_FINAL_FREEZE",
        "header_sha256": HEADER_SHA256, "abi_document_sha256": ABI_DOC_SHA256,
        "diagnostic_integrity": "INVALID", "physical_trial_status": physical_trial_status,
        "physical_100ksps_qualified": False, "adc_losslessness_verified": False,
        "copies": {"first_bytes": len(first), "second_bytes": len(second),
                   "first_sha256": sha(first), "second_sha256": sha(second), "byte_equal": first == second},
        "expected_identity": {"firmware_build": expected_build, "nonce_hex": f"{expected_nonce:016x}",
                              "generation": expected_generation, "epoch": expected_epoch},
        "issues": issues, "warnings": warnings,
        "interpretation_limits": [
            "Independent dump acquisition is an external procedural fact; equal bytes alone do not prove it.",
            "DWT cycles and derived times use the declared nominal clock, not a calibrated oscillator.",
            "All intervals must be shorter than 2^32 cycles; a complete missed wrap or debugger halt cannot be reconstructed.",
            "TIME_UPDATE, STEP and USB_ISR overlap phase wall times; GRANT_INTERVAL is wall delay, not CPU cost.",
            "Raw-read calibration is a heuristic indicator only; it is not a bound on all observer cost and is never subtracted.",
            "IN publication and completion counts need not balance across the observation boundaries.",
            "A retained wire prefix does not establish actual produced samples, lost samples, or continuous rate.",
        ],
    }
    if len(first) != SIZE or len(second) != SIZE:
        issues.append("record_size_mismatch")
        return report
    if first != second:
        issues.append("frozen_copies_differ_including_possible_late_writer")
    words = struct.unpack("<128I", first)
    report["raw_words_u32"] = list(words)
    header = dict(zip(HEADER_NAMES, words[:16]))
    report["header"] = header
    for name, expected in (("magic", MAGIC), ("version", VERSION), ("bytes", SIZE),
                           ("firmware_build", expected_build), ("generation", expected_generation)):
        if header[name] != expected:
            issues.append(name + "_mismatch")
    nonce = header["nonce_lo"] | header["nonce_hi"] << 32
    if nonce != expected_nonce:
        issues.append("nonce_mismatch")
    if expected_epoch is not None and header["epoch"] != expected_epoch:
        issues.append("epoch_mismatch")
    report["identity"] = {"nonce_hex": f"{nonce:016x}", "generation": header["generation"],
                          "epoch": header["epoch"], "firmware_build": header["firmware_build"]}
    report["state"] = named(header["state"], STATES)
    if header["state"] != 4:
        issues.append("not_frozen")
    if header["fg_flags"] & ~255 or header["irq_flags"] & ~7:
        issues.append("unknown_flag_bits")
    for bank, definitions, invalid in (("foreground", FG_FLAGS, 1 | 2 | 4 | 128),
                                       ("ISR", IRQ_FLAGS, 1 | 2)):
        value = header["fg_flags" if bank == "foreground" else "irq_flags"]
        report[bank + "_flags"] = {"raw": value, "names": [name for bit, name in definitions.items() if value & bit]}
        if value & invalid:
            issues.append(bank + "_validity_flags")
    close_kind, primary = header["close_kind_reason"] >> 16, header["close_kind_reason"] & 0xFFFF
    if close_kind not in range(1, len(CLOSE_KINDS)):
        issues.append("invalid_close_kind")
    no_start = close_kind == 6
    report["close"] = {"kind_raw": close_kind, "kind": named(close_kind, CLOSE_KINDS), "passed_primary_reason": primary}
    report["close"]["passed_reason_domain"] = {
        1: "protocol_source_reason", 2: "none", 3: "none", 4: "protocol_clock_reason",
        5: "none", 6: "none", 7: "core_local_error", 8: "adc_dma_fault",
    }.get(close_kind, "unknown")
    if close_kind in (2, 3, 5, 6) and primary != 0 or close_kind == 4 and primary != 3:
        issues.append("close_kind_primary_mismatch")
    primary_maximum = {1: 6, 7: 7, 8: 8}.get(close_kind)
    if primary_maximum is not None and not 1 <= primary <= primary_maximum:
        issues.append("close_primary_outside_typed_domain")
    private = dict(zip(PRIVATE_NAMES, words[108:128]))
    report["private_raw"] = private
    for name in ("phase_open", "step_open"):
        if private[name] not in (0, 1, 2):
            issues.append(name + "_invalid_ticket")
    for name in ("time_open", "grant_open", "grant_seen_IN"):
        if private[name] not in (0, 1):
            issues.append(name + "_invalid_ticket")
    if no_start and any(private[name] for name in ("phase_open", "step_open", "time_open", "grant_open")):
        issues.append("no_active_start_has_open_tickets")
    if private["phase_id"] >= len(PHASES) or private["begin_phase_id"] >= len(PHASES):
        issues.append("unknown_phase_id")
    if private["write_kind"] >= len(WRITE_KINDS):
        issues.append("unknown_write_kind")
    if private["write_kind"] in (0, 2, 3, 4) and private["write_accepted"] != 0:
        issues.append("nonpositive_write_has_accepted_bytes")
    if private["read_pair_max_cycles"] < private["read_pair_min_cycles"]:
        issues.append("read_pair_calibration_order")

    counters = dict(zip(COUNTER_NAMES, words[58:80]))
    report["counters"] = counters
    report["initial_indices"] = indices(words[80:88])
    event = words[88:108]
    first_event = {"indices": indices(event[:8]), "queue_used": event[8], "last_remaining": event[9],
                   "last_poll_us": event[10], "core_state": event[11] & 0xFFFF,
                   "core_first_reason": event[11] >> 16, "adc_state": event[12] & 0xFFFF,
                   "adc_first_fault": event[12] >> 16, "core_local_error": event[13],
                   "tx_offset": event[14], "tx_length": event[15]}
    report["first_event"] = first_event
    first_event["note"] = "RAM-only first-close snapshot before Stop/drain; passed primary reason is distinct from core.first_reason."
    first_event["last_poll_us_meaning"] = "Absolute saved TIM2-extended driver timestamp, not a poll gap or duration."
    if first_event["queue_used"] > 8 or first_event["tx_offset"] > first_event["tx_length"]:
        issues.append("first_snapshot_queue_or_tx_bounds")
    for name, maximum in (("core_state", 8), ("core_first_reason", 6),
                           ("adc_state", 2), ("adc_first_fault", 8), ("core_local_error", 7)):
        if first_event[name] > maximum:
            issues.append("first_snapshot_" + name + "_outside_enum")

    start_width = delta(header["start_after"], header["start_before"])
    end_width = delta(header["end_after"], header["end_before"])
    elapsed = None if no_start else delta(header["end_before"], header["start_after"])
    boundary = None if no_start else start_width + end_width
    boundary_ratio = boundary / elapsed if elapsed else None
    report["window"] = {
        "nominal_clock_hz": nominal_clock_hz, "elapsed_cycles_mod32": elapsed,
        "elapsed_us_nominal": None if elapsed is None else elapsed * 1e6 / nominal_clock_hz,
        "start_bracket_cycles": start_width, "end_bracket_cycles": end_width,
        "boundary_brackets_sum_cycles": boundary, "boundary_to_window_ratio": boundary_ratio,
        "nominal_cap_cycles": CAP_CYCLES,
        "cap_overshoot_cycles": None if elapsed is None else max(0, elapsed - CAP_CYCLES),
        "cap_overshoot_us_nominal": None if elapsed is None else max(0, elapsed - CAP_CYCLES) * 1e6 / nominal_clock_hz,
        "cap_overshoot_flag": bool(header["fg_flags"] & 64),
        "no_debug_halt_confirmed_externally": no_debug_halt_confirmed,
        "single_wrap_bound_confirmed_externally": single_wrap_bound_confirmed,
        "full_wrap_seconds_nominal": 2**32 / nominal_clock_hz,
        "physical_CEN_timestamp_claimed": False,
    }
    if no_start:
        warnings.append("no_active_start_no_timing_attribution")
    elif elapsed == 0:
        issues.append("zero_active_window")
    stats = {}
    for i, name in enumerate(STAT_NAMES):
        count, total, maximum = words[16 + i * 3:19 + i * 3]
        if (count == 0 and (total or maximum)) or maximum > total or total > count * maximum:
            issues.append("inconsistent_stat_" + name)
        stats[name] = {"count": count, "cycles_sum": total, "cycles_max": maximum,
                       "cycles_mean": total / count if count and not no_start else None,
                       "sum_us_nominal": None if no_start else total * 1e6 / nominal_clock_hz,
                       "max_us_nominal": None if no_start else maximum * 1e6 / nominal_clock_hz,
                       "wall_to_window_ratio": total / elapsed if elapsed else None,
                       "CPU_percentage_claimed": False}
    report["stats"] = stats
    partials = {}
    for i, name in enumerate(("phase", "step", "time", "grant")):
        value, ticket = event[16 + i], private[name + "_open"]
        stamp = private[name + "_start"]
        expected = None if no_start else delta(header["end_before"], stamp) if ticket else 0
        partials[name] = {"open_ticket": ticket, "start_cycle_raw": stamp,
                          "cycles_to_close": value, "expected_mod32_cycles": expected,
                          "active_duration_available": not no_start,
                          "us_nominal": None if no_start else value * 1e6 / nominal_clock_hz,
                          "completed_call": False}
        if not no_start and value != expected:
            issues.append("partial_" + name + "_stamp_mismatch")
    partials["phase"].update(phase=named(private["phase_id"], PHASES),
                             write_kind=named(private["write_kind"], WRITE_KINDS),
                             known_accepted_bytes=private["write_accepted"])
    report["partial_intervals_at_close"] = partials
    report["initial_partial_intervals"] = {
        "phase": named(private["begin_phase_id"], PHASES),
        "phase_cycles_raw": private["initial_phase_partial_cycles"],
        "step_cycles_raw": private["initial_step_partial_cycles"],
        "phase_cycles": None if no_start else private["initial_phase_partial_cycles"],
        "step_cycles": None if no_start else private["initial_step_partial_cycles"],
        "meaning": "Clipped first-call remainders after ACTIVE; excluded from complete-call statistics",
    }
    foreground = sum(stats[name]["cycles_sum"] for name in STAT_NAMES[:9])
    foreground += private["initial_phase_partial_cycles"] + event[16]
    residual = None if elapsed is None else elapsed - foreground
    report["foreground_accounting"] = {
        "disjoint_phase_wall_cycles_with_partials": None if no_start else foreground, "window_minus_phase_wall_cycles": residual,
        "residual_is_unattributed": True,
        "note": "This phase subtotal includes any interrupt overlap; TIME/STEP/ISR/grant intervals are not added. Residual is not automatically TIME or USB.",
    }
    if residual is not None and residual < 0:
        warnings.append("phase_wall_subtotal_exceeds_window_review_boundaries_or_hooks")
    reads = counters["foreground_DWT_reads"] + counters["ISR_DWT_reads"]
    low_indicator = reads * private["read_pair_min_cycles"] / 2
    high_indicator = reads * private["read_pair_max_cycles"] / 2
    heuristic_ratio = low_indicator / elapsed if elapsed else None
    report["observer"] = {
        "raw_DWT_reads": reads, "read_pair_min_cycles": private["read_pair_min_cycles"],
        "read_pair_max_cycles": private["read_pair_max_cycles"],
        "heuristic_cycles_using_pair_min": low_indicator,
        "heuristic_cycles_using_pair_max": high_indicator,
        "heuristic_min_to_window_ratio": heuristic_ratio,
        "covers_all_hooks": False, "lower_or_upper_bound_claimed": False, "subtracted_from_stats": False,
        "note": "Only a heuristic indicator for raw-read probes. Max calibration is not WCET; low indicator does not bound actual observer perturbation.",
    }
    observer_limited = bool((heuristic_ratio is not None and heuristic_ratio > .05)
                            or (boundary_ratio is not None and boundary_ratio > .01))
    if observer_limited:
        warnings.append("observer_limited_by_heuristic_or_boundary_policy")
    if not no_debug_halt_confirmed or not single_wrap_bound_confirmed:
        warnings.append("external_timing_preconditions_not_confirmed")
    if not counters["foreground_DWT_reads"] or not private["read_pair_min_cycles"]:
        warnings.append("observer_calibration_missing_or_zero")
    legacy = legacy_dwt_evidence(legacy_first, legacy_second, expected_build, expected_nonce, expected_generation)
    report["legacy_DWT_evidence"] = legacy
    if not legacy["validity_verified"]:
        warnings.append("legacy_DWT_validity_not_established")
    report["timing_source_validity"] = ("INVALID" if header["fg_flags"] & 4 or legacy["status"] == "INVALID" else
                                        "CORRELATED_FLAGS_CLEAR" if legacy["validity_verified"] else "UNAVAILABLE")
    report["attribution_policy"] = {
        "observer_limited": observer_limited, "heuristic_indicator_limit_ratio": .05,
        "boundary_limit_ratio": .01,
        "eligible_under_stated_assumptions": bool(not issues and not warnings and not no_start),
        "measured_CPU_cost_or_WCET_claimed": False,
    }
    report["diagnostic_integrity"] = "INVALID" if issues else ("VALID_FROZEN_NO_ACTIVE_START" if no_start else "VALID_FROZEN")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--build", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--nonce", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--epoch", type=int)
    parser.add_argument("--trial-result", type=Path)
    parser.add_argument("--legacy-first", type=Path)
    parser.add_argument("--legacy-second", type=Path)
    parser.add_argument("--no-debug-halt-confirmed", action="store_true")
    parser.add_argument("--single-wrap-bound-confirmed", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.first.resolve() == args.second.resolve():
        parser.error("Two distinct dump paths are required")
    if bool(args.legacy_first) != bool(args.legacy_second):
        parser.error("Both legacy diagnostic copies are needed")
    if args.legacy_first and args.legacy_first.resolve() == args.legacy_second.resolve():
        parser.error("Two distinct legacy dump paths are required")
    if args.output.exists():
        parser.error("Output exists; preserve previous evidence")
    for path, expected in ((ROOT / HEADER, HEADER_SHA256), (ROOT / ABI_DOC, ABI_DOC_SHA256)):
        if sha(path.read_bytes()) != expected:
            parser.error("ABI source changed; review and repin decoder before interpretation")
    first, second = args.first.read_bytes(), args.second.read_bytes()
    legacy_first = args.legacy_first.read_bytes() if args.legacy_first else None
    legacy_second = args.legacy_second.read_bytes() if args.legacy_second else None
    trial = args.trial_result.read_bytes() if args.trial_result else None
    trial_status = json.loads(trial)["status"] if trial else "NOT_ASSESSED"
    report = decode_copies(first, second, expected_build=args.build, expected_nonce=args.nonce,
                           expected_generation=args.generation, expected_epoch=args.epoch,
                           no_debug_halt_confirmed=args.no_debug_halt_confirmed,
                           single_wrap_bound_confirmed=args.single_wrap_bound_confirmed,
                           physical_trial_status=trial_status, legacy_first=legacy_first, legacy_second=legacy_second)
    report.update(decoder_sha256=sha(Path(__file__).read_bytes()),
                  first_dump_path=str(args.first.resolve()), second_dump_path=str(args.second.resolve()),
                  trial_result_sha256=sha(trial) if trial else None,
                  ELF_address_verified=False)
    if args.first.read_bytes() != first or args.second.read_bytes() != second:
        raise ValueError("A source dump changed during decoding")
    if args.legacy_first and (args.legacy_first.read_bytes() != legacy_first or args.legacy_second.read_bytes() != legacy_second):
        raise ValueError("A legacy dump changed during decoding")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"diagnostic_integrity": report["diagnostic_integrity"],
                      "physical_trial_status": report["physical_trial_status"],
                      "issues": report["issues"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["diagnostic_integrity"].startswith("VALID_FROZEN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
