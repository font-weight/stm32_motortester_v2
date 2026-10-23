"""One actual-C to Python ABI cross-check, not a physical or timing trial."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: check_native_fixture.py native-result-directory new-output-directory")
    native, output = (Path(value).resolve() for value in sys.argv[1:])
    output.mkdir(parents=True, exist_ok=False)
    paths = [native / "actual-profile.bin", native / "result.json", native / "model.c",
             native / "platform/mt_stream_profile.c", native / "platform/mt_stream_profile.h"]
    originals = {path: path.read_bytes() for path in paths}
    raw = originals[paths[0]]
    assert len(raw) == 512
    assert json.loads(originals[paths[1]])["status"] == "PASS"
    first, second = output / "native-first.bin", output / "native-second.bin"
    # These are explicit duplicate fixture copies, NOT two hardware/SWD reads.
    first.write_bytes(raw)
    second.write_bytes(raw)
    decoder = Path(__file__).with_name("decode_profile.py")
    report_path = output / "decoded-native-fixture.json"
    command = [sys.executable, "-B", str(decoder), str(first), str(second),
               "--build", "0x56325339", "--nonce", "0x0123456789abcdef",
               "--generation", "3", "--epoch", "7", "--output", str(report_path)]
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["diagnostic_integrity"] == "VALID_FROZEN", report["issues"]
    assert report["close"]["passed_primary_reason"] == 1
    assert report["first_event"]["core_first_reason"] == 0
    assert report["first_event"]["indices"]["head"] == 0x100000020
    assert report["counters"]["write_accepted_bytes"] == 307
    assert report["counters"]["data_samples_committed"] == 128
    assert report["initial_partial_intervals"]["phase"] == "RX"
    assert report["partial_intervals_at_close"]["time"]["cycles_to_close"] > 0
    assert report["legacy_DWT_evidence"]["status"] == "UNAVAILABLE"
    assert not report["attribution_policy"]["eligible_under_stated_assumptions"]
    assert report["physical_trial_status"] == "NOT_ASSESSED"
    assert not report["physical_100ksps_qualified"]
    assert not report["adc_losslessness_verified"]
    for path, before in originals.items():
        assert path.read_bytes() == before, path
    summary = {
        "schema": "v2-06f-native-profile-decoder-check-1", "status": "PASS",
        "scope": "Actual C native frozen record parsed by independent Python decoder; SYNTHETIC ONLY",
        "independent_hardware_reads": False,
        "copy_origin": "Both files deliberately duplicate one actual-C-generated native fixture",
        "physical_trial_performed": False, "hardware_access": False,
        "native_test_repeated": False, "physical_100ksps_qualified": False,
        "input_files": [{"path": str(path), "bytes": len(raw), "sha256": digest(raw)}
                        for path, raw in originals.items()],
        "source_files_unchanged": True, "command": command,
        "stdout": result.stdout, "stderr": result.stderr,
        "decoder_sha256": digest(decoder.read_bytes()),
        "check_sha256": digest(Path(__file__).read_bytes()),
        "decoded_report_sha256": digest(report_path.read_bytes()),
        "fixture_sha256": digest(raw),
    }
    (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(output), "fixture_sha256": digest(raw)}))


if __name__ == "__main__":
    main()
