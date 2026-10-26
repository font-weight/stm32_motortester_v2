"""Focused frozen Windows witness for the selectable stream profiles.

The package builder seals and relocates the ZIP before calling this helper.
This check does not replace physical ADC/USB qualification or claim that the
unchanged legacy picker and windowed-acquisition paths were tested again.
"""
from pathlib import Path
import csv
import platform

def verify_profiles_package(*, output, gui_exe, relocated, foreign_cwd,
                            frozen_env, run, portable, portable_hash,
                            expected_tree, source_archive, revision,
                            exe_hashes, log, file_tree, png_info, read_json,
                            sha256, write_json):
    smoke_output = output / "frozen-profiles"
    run(gui_exe, "--verify-profiles", smoke_output, cwd=foreign_cwd,
        environment=frozen_env, timeout=90)
    smoke = read_json(smoke_output / "result.json")
    if (smoke.get("status") != "PASS" or smoke.get("frozen") is not True
            or smoke.get("platform") != "win32"
            or smoke.get("qt_platform") != "windows"
            or Path(smoke.get("executable", "")).resolve() != gui_exe.resolve()
            or smoke.get("callback_errors") != [] or smoke.get("errors") != []
            or type(smoke.get("real_serial_open_calls")) is not int
            or smoke.get("real_serial_open_calls") != 0
            or smoke.get("execution_kind") != "injected-test"
            or smoke.get("physical_stream_verified") is not False
            or smoke.get("owners_closed") is not True):
        raise RuntimeError("Frozen stream-profile GUI check failed")
    # The exact changed-flow fields are required below; do not turn a generic
    # status string or a screenshot into evidence of a recording roundtrip.
    checks = smoke.get("checks", {})
    required = ("selector_modes", "selection_locked", "packed_record_roundtrip",
                "intrinsic_quantization", "csv_timebase", "legacy_mismatch_before_start",
                "batch_mode5_negotiated", "batch1024_wire_evidence",
                "sc_sd150_batch_required_before_start")
    if not isinstance(checks, dict) or any(checks.get(key) is not True for key in required):
        raise RuntimeError("Frozen profile-flow evidence is incomplete")
    pngs = {}
    files = smoke.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("Missing profile-flow artifacts")
    for name, receipt in files.items():
        path = smoke_output / name
        if (not isinstance(name, str) or Path(name).name != name
                or not isinstance(receipt, dict) or not path.is_file()
                or receipt.get("bytes") != path.stat().st_size
                or receipt.get("sha256") != sha256(path)):
            raise RuntimeError("Profile-flow artifact differs from its receipt")
        if path.suffix.lower() == ".png":
            pngs[name] = png_info(path)
    if not pngs:
        raise RuntimeError("Profile GUI check omitted screenshots")
    roundtrip = smoke.get("roundtrip", {})
    identity = roundtrip.get("identity", {})
    if (identity.get("origin") != "synthetic"
            or identity.get("protocol_revision") != "0.3-batch1024-20261025"
            or identity.get("acquisition_mode") != 5
            or identity.get("config_id") != 5
            or identity.get("nominal_fs_hz") != 150_000
            or identity.get("source_adc_bits") != 12
            or identity.get("retained_bits") != 10
            or identity.get("discarded_lsb") != 2
            or identity.get("quantization") != "truncate_lsb"
            or identity.get("stored_code_domain") != "adc12"
            or type(roundtrip.get("samples")) is not int or roundtrip["samples"] <= 0
            or roundtrip.get("journal_sha256") != sha256(smoke_output / "packed150.mtstream")):
        raise RuntimeError("Frozen packed recording identity/hash mismatch")
    if roundtrip.get("connection", {}).get("observed_caps") != [
            5, 5, 0, 12, 150_000, 1, 1024, 1, 10, 2]:
        raise RuntimeError("Frozen batch selected CAPS mismatch")
    # These observations come from decoding the synthetic wire bytes, not
    # from inferring packetization from the 150 kS/s selector or journal chunks.
    batch = smoke.get("batch", {})
    expected = {"acquisition_mode": 5, "config_id": 5,
                "negotiated_max_block": 1024, "discovery_capabilities": 15,
                "discovery_max_block": 1024, "discovery_max_payload": 1300,
                "selected_ack_max_block": 1024, "selected_ack_max_payload": 1300,
                "first_full_data_count": 1024}
    if (not isinstance(batch, dict)
            or any(type(batch.get(key)) is not int or batch[key] != value
                   for key, value in expected.items())
            or batch.get("data_count_sequence_validation") is not True
            or batch.get("canonical_crc_validated") is not True
            or type(batch.get("full_DATA1024_frames")) is not int
            or batch["full_DATA1024_frames"] < 1
            or type(batch.get("largest_frame_bytes")) is not int
            or not 1 <= batch["largest_frame_bytes"] <= 1335
            or type(batch.get("short_tail_frames")) is not int
            or batch["short_tail_frames"] not in (0, 1)
            or "terminal_short_samples" not in batch
            or (batch["short_tail_frames"] == 0 and batch["terminal_short_samples"] is not None)
            or (batch["short_tail_frames"] == 1 and batch["terminal_short_samples"] is None)
            or (batch["terminal_short_samples"] is not None and (
                type(batch["terminal_short_samples"]) is not int
                or not 1 <= batch["terminal_short_samples"] < 1024))):
        raise RuntimeError("Frozen DATA1024 wire witness is incomplete")
    exported = read_json(smoke_output / "packed150.csv.json")
    if (exported.get("complete") is not True or exported.get("identity") != identity
            or exported.get("csv_sha256") != sha256(smoke_output / "packed150.csv")
            or exported.get("source_journal_sha256") != roundtrip["journal_sha256"]):
        raise RuntimeError("Frozen CSV receipt does not match the recording")
    # Check the artifact's columns, count and nominal time step independently
    # of the GUI receipt; the smoke already compares every source raw code.
    with (smoke_output / "packed150.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader) != ["sample_index", "time_from_recording_start_s",
                            "adc12_scale_code_retained10_truncate_lsb2"]:
            raise RuntimeError("CSV omitted the retained-bit label")
        first, second = next(reader), next(reader)
        if (int(second[0]) - int(first[0]) != 1
                or abs(float(second[1]) - float(first[1]) - 1 / 150_000) > 1e-12
                or 2 + sum(1 for _ in reader) != roundtrip["samples"]):
            raise RuntimeError("CSV sample count or fractional time step differs")
    if file_tree(relocated) != expected_tree or sha256(portable) != portable_hash:
        raise RuntimeError("Profile check modified the sealed program")
    report = {
        "status": "PASS", "verification_scope": "selectable-profiles-batch1024",
        "scope": "Frozen Windows profile selector and injected wire/file/CSV path; "
                 "no physical COM, clean-machine or unchanged legacy-suite qualification",
        "source_commit": revision, "portable_zip": portable.name,
        "portable_sha256": portable_hash, "source_sha256": sha256(source_archive),
        "executable_sha256": exe_hashes, "extracted_bundle": str(relocated),
        "working_directory": str(foreign_cwd), "isolated_path": frozen_env["PATH"],
        "frozen_smoke": smoke, "png_files": pngs,
        "smoke_files": file_tree(smoke_output), "windows_host": platform.platform(),
        "physical_device_verified": False, "public_release_approved": False,
    }
    write_json(output / "build-report.json", report)
    artifacts = [portable, source_archive, output / "build-report.json", log]
    artifacts.extend(path for path in sorted(smoke_output.iterdir()) if path.is_file())
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in artifacts),
        encoding="utf-8")
    print(f"\nProfile package verified: {portable}\nEvidence: {output / 'build-report.json'}")
    return 0
