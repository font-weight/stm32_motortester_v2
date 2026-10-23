"""Small synthetic ABI checks for the offline decoder; no firmware execution."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

from decode_profile import decode_copies

HERE = Path(__file__).resolve().parent
NONCE = 0x12345678ABCDEF01
BUILD = 0x56325339
MASK = 0xFFFFFFFF


def raw(words):
    return struct.pack("<128I", *words)


def fixture():
    # Explicit uint32 offsets independent of the decoder's field-name tables.
    words = [0] * 128
    start = 0xFFFFFF08
    end = (start + 720000) & MASK
    words[:16] = [0x4D545046, 1, 512, BUILD, 4, 8 | 16 | 32, 4, 3, 9,
                  NONCE & MASK, NONCE >> 32, 0xFFFFFF00, start, end, end + 12, 1 << 16 | 1]
    triples = [(3, 60000, 30000), (7, 14000, 3000), (2, 80000, 40000), (10, 20000, 3000),
               (3, 60000, 20000), (2, 12000, 6000), (0, 0, 0), (5, 50000, 15000),
               (5, 25000, 6000), (100, 200000, 3500), (20, 120000, 8000),
               (4, 500000, 200000), (5, 80000, 20000), (12, 600000, 100000)]
    for i, triple in enumerate(triples):
        words[16 + 3 * i:19 + 3 * i] = triple
    words[58:80] = [2048, 1024, 2, 0, 0, 2456, 25000, 600, 5, 0, 5, 2000, 0,
                    20, 1280, 15, 5, 0, 0, 0, 0, 100]
    words[88:108] = [1024, 0, 2048, 0, 1024, 0, 2048, 0, 8, 512, 123456,
                     3, 2, 0, 0, 307, 8000, 10000, 0, 50000]
    words[108:128] = [2, end - 8000, 1, end - 10000, 1, 0, 0, end - 50000, 1, 1,
                      0, 0, 3000, 5000, 12, 20, 0x20001000, 0x20002000, 3, end - 2000]
    return words


def legacy_fixture(flags=4):
    words = [0] * 34
    words[:7] = [0x4D544447, 1, 136, BUILD, 3, flags, 3]
    words[30:34] = [12345, 12345, NONCE & MASK, NONCE >> 32]
    return struct.pack("<34I", *words)


def decode(words, other=None, **changes):
    options = dict(expected_build=BUILD, expected_nonce=NONCE, expected_generation=3, expected_epoch=9,
                   no_debug_halt_confirmed=True, single_wrap_bound_confirmed=True, physical_trial_status="FAIL",
                   legacy_first=legacy_fixture(), legacy_second=legacy_fixture())
    options.update(changes)
    return decode_copies(raw(words), raw(words if other is None else other), **options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    base = fixture()
    valid = decode(base)
    assert valid["diagnostic_integrity"] == "VALID_FROZEN", valid["issues"]
    assert valid["physical_trial_status"] == "FAIL" and not valid["physical_100ksps_qualified"]
    assert valid["window"]["elapsed_cycles_mod32"] == 720000
    assert valid["window"]["elapsed_us_nominal"] == 10000
    assert valid["window"]["boundary_brackets_sum_cycles"] == 20
    assert valid["stats"]["TIME_UPDATE"]["cycles_sum"] == 200000
    assert valid["stats"]["USB_ISR"]["cycles_sum"] == 120000
    assert valid["first_event"]["core_first_reason"] == 0
    assert valid["close"]["passed_primary_reason"] == 1
    assert valid["partial_intervals_at_close"]["phase"]["cycles_to_close"] == 8000
    assert valid["partial_intervals_at_close"]["phase"]["phase"] == "ADC"
    assert valid["initial_partial_intervals"]["phase_cycles"] == 3000
    assert valid["observer"]["heuristic_cycles_using_pair_min"] == 4200
    assert not valid["observer"]["lower_or_upper_bound_claimed"]
    assert not valid["observer"]["subtracted_from_stats"]
    assert valid["foreground_accounting"]["window_minus_phase_wall_cycles"] == 388000
    assert valid["attribution_policy"]["eligible_under_stated_assumptions"]

    negative = []
    for label, index, value, expected_issue in (
        ("version", 1, 2, "version_mismatch"), ("bytes_field", 2, 508, "bytes_mismatch"),
        ("build", 3, 0x56325338, "firmware_build_mismatch"), ("nonfrozen", 4, 3, "not_frozen"),
        ("generation", 7, 4, "generation_mismatch"), ("nonce", 9, 0, "nonce_mismatch"),
        ("epoch", 8, 10, "epoch_mismatch"), ("FG_saturation", 5, 1, "foreground_validity_flags"),
        ("IRQ_saturation", 6, 1, "ISR_validity_flags"),
        ("DWT_invalid", 5, 4, "foreground_validity_flags"),
        ("partial_stamp", 104, 7999, "partial_phase_stamp_mismatch"),
        ("core_state_enum", 99, 9, "first_snapshot_core_state_outside_enum"),
        ("core_reason_enum", 99, 7 << 16 | 3, "first_snapshot_core_first_reason_outside_enum"),
        ("adc_state_enum", 100, 3, "first_snapshot_adc_state_outside_enum"),
        ("adc_fault_enum", 100, 9 << 16 | 2, "first_snapshot_adc_first_fault_outside_enum"),
        ("local_error_enum", 101, 8, "first_snapshot_core_local_error_outside_enum"),
    ):
        changed = base.copy()
        changed[index] = value
        report = decode(changed)
        assert report["diagnostic_integrity"] == "INVALID" and expected_issue in report["issues"], label
        negative.append({"case": label, "expected_issue": expected_issue})
    for kind, maximum in ((1, 6), (7, 7), (8, 8)):
        for primary in (0, maximum + 1, 65535):
            changed = base.copy()
            changed[15] = kind << 16 | primary
            report = decode(changed)
            assert "close_primary_outside_typed_domain" in report["issues"]
            negative.append({"case": f"typed_close_{kind}_primary_{primary}",
                             "expected_issue": "close_primary_outside_typed_domain"})
    late = base.copy()
    late[110] = 0  # A forbidden late epilogue clears the private phase-open ticket.
    assert "frozen_copies_differ_including_possible_late_writer" in decode(base, late)["issues"]
    short = decode_copies(raw(base)[:-1], raw(base), expected_build=BUILD,
                          expected_nonce=NONCE, expected_generation=3)
    assert short["issues"] == ["record_size_mismatch"]

    capped = base.copy()
    end = (capped[12] + 18_072_000) & MASK
    capped[5] |= 64
    capped[13:16] = [end, end + 12, 3 << 16]
    for index, span in ((109, 8000), (111, 10000), (115, 50000)):
        capped[index] = end - span
    cap = decode(capped)
    assert cap["diagnostic_integrity"] == "VALID_FROZEN", cap["issues"]
    assert cap["window"]["elapsed_us_nominal"] == 251000
    assert cap["window"]["cap_overshoot_cycles"] == 72000
    assert cap["window"]["cap_overshoot_us_nominal"] == 1000
    noisy = base.copy()
    noisy[122:124] = [1200, 2000]
    assert decode(noisy)["attribution_policy"]["observer_limited"]
    uncertain = base.copy()
    uncertain[14] += 7200
    assert decode(uncertain)["attribution_policy"]["observer_limited"]
    recovery = base.copy()
    recovery[15] = 7 << 16 | 6
    assert decode(recovery)["close"]["passed_reason_domain"] == "core_local_error"
    assert decode(recovery)["diagnostic_integrity"] == "VALID_FROZEN"
    adc_close = base.copy()
    adc_close[15] = 8 << 16 | 5
    assert decode(adc_close)["close"]["passed_reason_domain"] == "adc_dma_fault"
    assert decode(adc_close)["diagnostic_integrity"] == "VALID_FROZEN"
    unknown = decode(base, no_debug_halt_confirmed=False, single_wrap_bound_confirmed=False)
    assert not unknown["attribution_policy"]["eligible_under_stated_assumptions"]
    invalid_old = decode(base, legacy_first=legacy_fixture(16), legacy_second=legacy_fixture(16))
    assert invalid_old["diagnostic_integrity"] == "VALID_FROZEN"
    assert invalid_old["timing_source_validity"] == "INVALID"
    assert not invalid_old["attribution_policy"]["eligible_under_stated_assumptions"]
    no_old = decode(base, legacy_first=None, legacy_second=None)
    assert not no_old["attribution_policy"]["eligible_under_stated_assumptions"]
    no_start = base.copy()
    no_start[5:7] = [0, 0]
    no_start[11:16] = [0, 0, 900000, 900010, 6 << 16]
    no_start[16:] = [0] * 112
    inactive = decode(no_start)
    assert inactive["diagnostic_integrity"] == "VALID_FROZEN_NO_ACTIVE_START", inactive["issues"]
    assert inactive["window"]["elapsed_cycles_mod32"] is None
    assert inactive["partial_intervals_at_close"]["phase"]["us_nominal"] is None
    assert inactive["partial_intervals_at_close"]["phase"]["expected_mod32_cycles"] is None
    assert inactive["stats"]["STEP"]["sum_us_nominal"] is None
    no_start[110] = 1
    assert "no_active_start_has_open_tickets" in decode(no_start)["issues"]

    # One CLI round trip checks source pinning, file IO and physical FAIL separation.
    first, second = output / "first.bin", output / "second.bin"
    first.write_bytes(raw(base))
    second.write_bytes(raw(base))
    legacy_first, legacy_second = output / "legacy-first.bin", output / "legacy-second.bin"
    legacy_first.write_bytes(legacy_fixture())
    legacy_second.write_bytes(legacy_fixture())
    trial = output / "synthetic-trial-result.json"
    trial.write_text('{"status":"FAIL","source":"synthetic fixture, never a physical run"}\n', encoding="utf-8")
    command = [sys.executable, "-B", str(HERE / "decode_profile.py"), str(first), str(second),
               "--build", hex(BUILD), "--nonce", hex(NONCE), "--generation", "3", "--epoch", "9",
               "--trial-result", str(trial), "--no-debug-halt-confirmed", "--single-wrap-bound-confirmed",
               "--legacy-first", str(legacy_first), "--legacy-second", str(legacy_second),
               "--output", str(output / "decoded-fixture.json")]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    decoded = json.loads((output / "decoded-fixture.json").read_text(encoding="utf-8"))
    assert decoded["physical_trial_status"] == "FAIL" and decoded["diagnostic_integrity"] == "VALID_FROZEN"
    assert first.read_bytes() == second.read_bytes() == raw(base)
    summary = {
        "schema": "v2-06f-offline-decoder-synthetic-check-1", "status": "PASS",
        "scope": "Synthetic ABI/parser checks only; no firmware execution or hardware trial",
        "groups": ["nominal wrap and complete/partial intervals", "identity/size/frozen/flags rejection",
                   "actual cap overshoot and observer heuristic policy", "pinned CLI roundtrip with physical FAIL preserved"],
        "negative_cases": negative,
        "late_private_mutation_rejected": True, "short_record_rejected": True,
        "no_active_start_timing_unavailable": True, "legacy_DWT_invalid_and_missing_block_attribution": True,
        "native_or_host_implementation_tests_run": False, "hardware_access": False,
        "header_sha256": decoded["header_sha256"], "abi_document_sha256": decoded["abi_document_sha256"],
        "decoder_sha256": hashlib.sha256((HERE / "decode_profile.py").read_bytes()).hexdigest(),
        "checks_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(raw(base)).hexdigest(),
        "cli_argv": command, "cli_stdout": result.stdout, "cli_stderr": result.stderr,
        "cap_fixture_window": cap["window"], "valid_fixture_observer": valid["observer"],
    }
    with (output / "result.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status": "PASS", "groups": len(summary["groups"]), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
