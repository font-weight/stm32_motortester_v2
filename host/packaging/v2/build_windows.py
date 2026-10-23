"""Build and verify a local V2 portable candidate, never a public release."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import sysconfig
import zipfile
import zlib


PACKAGING = Path(__file__).resolve().parent
HOST = PACKAGING.parent.parent
REPOSITORY = HOST.parent
EXPECTED_PYTHON = (3, 14, 7)
# The existing 70 s picker + 12 s writer regression is followed by the short
# injected-serial GUI flow and short 100 kS/s recording/CSV roundtrip.
FROZEN_TIMEOUT = 180
APP_NAME = "MotortesterV2"

# The existing runner records commands, exit codes and bounded-child cleanup.
# Loading the module does not execute its old build entry point.
sys.path.insert(0, str(PACKAGING.parent))
_legacy_spec = importlib.util.spec_from_file_location(
    "_motortester_legacy_build", PACKAGING.parent / "build_windows.py")
_legacy_build = importlib.util.module_from_spec(_legacy_spec)
_legacy_spec.loader.exec_module(_legacy_build)
run_logged = _legacy_build.run_logged


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_tree(directory):
    return {path.relative_to(directory).as_posix(): sha256(path)
            for path in sorted(directory.rglob("*")) if path.is_file()}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def read_json(path, limit=1024 * 1024):
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError(f"Missing or oversized JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def png_info(path):
    """Check the actual PNG header and hash; no claim of pixel/visual review."""
    if not path.is_file() or not 33 <= path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError(f"Missing or oversized PNG: {path}")
    with path.open("rb") as stream:
        header = stream.read(33)
    if (header[:8] != b"\x89PNG\r\n\x1a\n" or header[8:12] != b"\x00\x00\x00\x0d"
            or header[12:16] != b"IHDR"):
        raise ValueError(f"Invalid PNG/IHDR: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if not (1 <= width <= 8192 and 1 <= height <= 8192 and width * height <= 16_000_000):
        raise ValueError(f"Invalid PNG dimensions: {path}")
    if zlib.crc32(header[12:29]) != struct.unpack(">I", header[29:33])[0]:
        raise ValueError(f"Invalid PNG header checksum: {path}")
    return {"sha256": sha256(path), "bytes": path.stat().st_size,
            "width": width, "height": height, "validation": "PNG IHDR/CRC and SHA-256"}


def verify_serial_smoke(directory, receipt):
    """Bind the injected-serial GUI receipt to its raw file, context and PNGs."""
    if (type(receipt) is not dict or receipt.get("status") != "PASS"
            or receipt.get("source") != "injected serial byte fixtures"
            or receipt.get("qt_platform") != "windows"
            or receipt.get("physical_stream_verified") is not False
            or receipt.get("real_serial_open_calls") != 0
            or receipt.get("callback_errors") != []
            or receipt.get("error") or receipt.get("cleanup_error")
            or read_json(directory / "serial-result.json") != receipt):
        raise RuntimeError("Packaged serial-stream GUI verification did not pass")
    prepared, recording = receipt.get("prepared", {}), receipt.get("recording", {})
    connection = prepared.get("connection", {})
    settlement, roundtrip = receipt.get("settlement", {}), receipt.get("roundtrip", {})
    closed = receipt.get("close", {})
    start, end = roundtrip.get("first_sample_index", 0), roundtrip.get("end_sample_index", 0)
    journal_path = directory / "serial-window.mtstream"
    if (prepared.get("commands") != [1, 2] or prepared.get("samples") != 0
            or connection.get("execution_kind") != "injected-test"
            or connection.get("dtr_requested") is not True
            or connection.get("accounting_domain") != "unknown"
            or connection.get("image_verified") is not False
            or recording.get("seconds", 0) < 2 or recording.get("main_timer_active") is not True
            or recording.get("samples_after", 0) <= recording.get("samples_before", 0)
            or settlement.get("normalized_path_matches") is not True
            or settlement.get("metadata_pending") is not False
            or any(Path(settlement.get(key, "")).resolve() != journal_path.resolve()
                   for key in ("selected_path", "saved_path"))
            or type(start) is not int or type(end) is not int or not 0 < start < end
            or roundtrip.get("raw_samples_compared") != end - start
            or roundtrip.get("unknown_tail_preserved") is not True
            or roundtrip.get("origin") != "synthetic"
            or not all(closed.get(key) is True for key in (
                "failed_close_retained_lease", "explicit_retry_button", "parent_closed"))
            or closed.get("close_attempts", 0) < 2
            or not {
                "window pending Connect blocks stream before serial construction",
                "stream pending Connect blocks window button and stale handler",
            }.issubset(receipt.get("checkpoints", []))):
        raise RuntimeError("Packaged serial-stream lifecycle evidence is incomplete")
    companion_path = directory / "serial-window.mtstream.v2.json"
    companion = read_json(companion_path)
    profile = companion.get("context", {}).get("input_profile", {})
    journal = companion.get("journal", {})
    if (companion.get("format") != "motortester-v2-stream-context"
            or companion.get("format_version") != 2
            or companion.get("connection") != connection
            or companion.get("time_basis") != "nominal_unverified"
            or profile.get("state") != "unconfigured"
            or profile.get("a") is not None or profile.get("b") is not None
            or journal.get("identity", {}).get("origin") != "synthetic"
            or journal.get("first_sample_index") != start or journal.get("end_sample_index") != end
            or companion.get("journal_sha256") != sha256(journal_path)
            or companion.get("journal_bytes") != journal_path.stat().st_size):
        raise RuntimeError("Packaged serial-stream raw/context binding differs from its receipt")
    pngs = {name: png_info(directory / name) for name in (
        "serial-ready.png", "serial-recording.png", "serial-open-unknown-tail.png", "serial-close-retry.png")}
    for name in (*pngs, journal_path.name, companion_path.name):
        if receipt.get("files", {}).get(name) != sha256(directory / name):
            raise RuntimeError(f"Packaged serial-stream receipt checksum differs: {name}")
    return pngs


def verify_stop_smoke(directory, receipt):
    """Keep the final EXE's Stop witness tied to its saved files and images."""
    if (not isinstance(receipt, dict) or receipt.get("status") != "PASS"
            or receipt.get("qt_platform") != "windows"
            or receipt.get("physical_stream_verified") is not False
            or receipt.get("real_serial_open_calls") != 0
            or receipt.get("callback_errors") != []
            or receipt != read_json(directory / "stop-result.json")):
        raise RuntimeError("Packaged Stop verification did not pass")
    ready = receipt.get("ready_close", {})
    normal = receipt.get("normal_stop", {})
    negative = receipt.get("unconfirmed_stop", {})
    terminal = normal.get("terminal", {})
    exported = normal.get("csv", {})
    if (ready.get("commands") != [1, 2] or ready.get("samples") != 0
            or ready.get("emitted_errors") != []
            or ready.get("handle_closed") is not True or ready.get("lease_released") is not True
            or normal.get("phase") != "stopped unknown tail"
            or normal.get("emitted_errors") != []
            or terminal.get("reason") != "stopped" or terminal.get("failure") is not None
            or terminal.get("device_generated_end_sample_index") is not None
            or terminal.get("loss_samples") is not None
            or normal.get("clean_stop_reported") is not False
            or normal.get("raw_samples_compared", 0) <= 0
            or normal.get("journal_sha256_unchanged") != sha256(directory / "stop-unknown-tail.mtstream")
            or exported.get("rows") != normal.get("raw_samples_compared")
            or exported.get("terminal_equal") is not True
            or exported.get("csv_sha256") != sha256(directory / "stop-unknown-tail.csv")
            or exported.get("raw_sha256") != normal.get("raw_sha256")
            or negative.get("phase") != "fault" or negative.get("ack_frames") != 0
            or negative.get("normal_stop_label_absent") is not True):
        raise RuntimeError("Packaged Stop/unknown-tail boundary evidence is incomplete")
    for name, digest in receipt.get("files", {}).items():
        if Path(name).name != name or sha256(directory / name) != digest:
            raise RuntimeError(f"Packaged Stop receipt checksum differs: {name}")
    return {name: png_info(directory / name)
            for name in ("stop-open-details.png", "stop-open-compact.png",
                         "stop-open-compact-bottom.png")}


def clean_environment():
    env = os.environ.copy()
    for name in list(env):
        upper = name.upper()
        if upper in ("PATH", "PYTHONPATH", "PYTHONHOME") or upper.startswith(("QT", "QML")):
            env.pop(name)
    # Dependency discovery must not borrow DLLs from unrelated desktop tools.
    # In particular Poppler's ICU has a different ABI from Windows' system ICU.
    env["PATH"] = os.pathsep.join((sys.base_prefix,
                                  str(Path(sys.base_prefix) / "Scripts"),
                                  str(Path(os.environ["SystemRoot"]) / "System32")))
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONHASHSEED="0",
               PYQTGRAPH_QT_LIB="PySide6")
    return env


def restore_pinned_notice_bytes(staging):
    """Recover line endings only when they reproduce the existing exact hash.

    Some inherited Git blobs already contain CRLF although their pinned upstream
    texts use LF. Never repin or accept merely similar text: any other mismatch
    still fails before the unchanged legacy collector runs.
    """
    script = staging / "host" / "packaging" / "collect_licenses.py"
    spec = importlib.util.spec_from_file_location("_v2_pinned_notices", script)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    pinned = [(collector.PYSERIAL_LICENSE, collector.PYSERIAL_LICENSE_SHA256),
              (collector.DEPENDENCY_GUIDE, collector.DEPENDENCY_GUIDE_SHA256),
              (collector.DEPENDENCY_LICENSES / "manifest.json",
               collector.DEPENDENCY_MANIFEST_SHA256)]
    pinned.extend((collector.QT_LICENSES / name, digest)
                  for name, size, digest, blob in collector.QT_NOTICES)
    # Each vendored notice is addressed by its upstream SHA-256.
    pinned.extend((path, path.name) for path in
                  sorted((collector.DEPENDENCY_LICENSES / "notices").iterdir()) if path.is_file())
    restored = []
    for path, expected in pinned:
        original = path.read_bytes()
        original_hash = hashlib.sha256(original).hexdigest()
        if original_hash == expected:
            continue
        lf = original.replace(b"\r\n", b"\n")
        candidates = (("LF", lf), ("CRLF", lf.replace(b"\n", b"\r\n")))
        for ending, data in candidates:
            if hashlib.sha256(data).hexdigest() == expected:
                path.write_bytes(data)
                restored.append({"path": path.relative_to(staging).as_posix(),
                                 "original_sha256": original_hash, "sha256": expected,
                                 "line_endings": ending, "bytes": len(data)})
                break
        else:
            raise RuntimeError(f"Pinned notice differs beyond line endings: {path.name}")
    return restored


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPOSITORY / "build" / "v2w",
                        help="New short output path (Windows path limits); never removes an existing directory")
    args = parser.parse_args(argv)
    if (sys.platform != "win32" or platform.machine().upper() not in ("AMD64", "X86_64")
            or sys.maxsize <= 2**32 or sys.version_info[:3] != EXPECTED_PYTHON
            or sysconfig.get_config_var("Py_GIL_DISABLED")):
        parser.error("Use regular CPython 3.14.7 x64 on Windows")
    git = shutil.which("git")
    if not git:
        parser.error("Git must be installed")
    revision = subprocess.check_output(
        [git, "rev-parse", "HEAD"], cwd=REPOSITORY, text=True).strip()
    dirty = subprocess.check_output(
        [git, "status", "--porcelain", "--untracked-files=all"], cwd=REPOSITORY, text=True)
    if dirty.strip():
        parser.error("Commit the reviewed source first; the candidate needs a clean checkout")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    log = output / "build.log"
    env = clean_environment()

    def run(*command, cwd=HOST, environment=None, timeout=None):
        result = run_logged(command, cwd=cwd, env=environment or env, log=log, timeout=timeout)
        print(result, end="")
        return result

    run(sys.executable, "-m", "venv", output / "venv")
    python = output / "venv" / "Scripts" / "python.exe"
    lock = PACKAGING / "requirements-win-x64.lock"
    wheelhouse = output / "wheelhouse"
    run(python, "-m", "pip", "--isolated", "download", "--index-url", "https://pypi.org/simple",
        "--require-hashes", "--only-binary=:all:", "--dest", wheelhouse, "-r", lock)
    run(python, "-m", "pip", "--isolated", "install", "--no-index", "--find-links", wheelhouse,
        "--require-hashes", "--only-binary=:all:", "-r", lock)
    run(python, "-m", "pip", "check")
    packages = json.loads(run(python, "-m", "pip", "list", "--format=json"))
    run(python, "-m", "PyInstaller", "--clean", "--noconfirm",
        "--distpath", output / "dist", "--workpath", output / "pyinstaller",
        PACKAGING / "motortester-v2.spec")
    bundle = output / "dist" / APP_NAME
    gui_name, inspect_name = "MotortesterV2.exe", "MotortesterV2Inspect.exe"
    for name in (gui_name, inspect_name):
        if not (bundle / name).is_file():
            raise RuntimeError(f"PyInstaller did not produce {name}")

    # Archive the selected commit. Git's Windows EOL conversion can affect the
    # exported bytes; restore existing upstream notice hashes without repinning.
    license_archive = output / "license-input.zip"
    run(git, "-C", REPOSITORY, "archive", "--format=zip", f"--output={license_archive}",
        revision, "host/packaging/collect_licenses.py", "host/packaging/licenses",
        "host/docs/dependency-sources.md")
    license_input = output / "license-input"
    with zipfile.ZipFile(license_archive) as archive:
        archive.extractall(license_input)
    restored_notices = restore_pinned_notice_bytes(license_input)
    write_json(output / "license-input-restoration.json", restored_notices)
    run(python, license_input / "host" / "packaging" / "collect_licenses.py", bundle / "licenses")
    shutil.copy2(HOST / "LICENSE", bundle / "LICENSE")
    shutil.copy2(PACKAGING.parent / "LICENSE-REVIEW.md", bundle / "LICENSE-REVIEW.md")
    shutil.copy2(PACKAGING / "README_PORTABLE_RU.txt", bundle / "README_RU.txt")
    shutil.copy2(lock, bundle / lock.name)

    run(git, "-C", REPOSITORY, "diff", "--exit-code", revision, "--",
        "host", "AGENTS.md", "README.md", "requirements.md", "task.md", "docs")
    source_archive = output / "source.zip"
    run(git, "-C", REPOSITORY, "archive", "--format=zip", f"--output={source_archive}",
        revision, "host", "AGENTS.md", "README.md", "requirements.md", "task.md", "docs")
    manifest = {
        "status": "local-technical-candidate-not-public-release",
        "source_commit": revision,
        "source_archive_sha256": sha256(source_archive),
        "build_time_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "build_environment": {
            "python_executable": sys.executable,
            "regular_gil_build": True,
            "PYTHONNOUSERSITE": env["PYTHONNOUSERSITE"],
            "PYTHONUTF8": env["PYTHONUTF8"],
            "PYTHONHASHSEED": env["PYTHONHASHSEED"],
            "PYQTGRAPH_QT_LIB": env["PYQTGRAPH_QT_LIB"],
            "python_home_path_and_qt_overrides_removed": True,
            "PATH": env["PATH"],
            "git_executable": git,
        },
        "packages": packages,
        "lock_sha256": sha256(lock),
        "wheelhouse": file_tree(wheelhouse),
        "entrypoints": [gui_name, inspect_name],
        "scope": "V2 DEMO/files, explicit wire 0.1 device windows and wire 0.2 serial streams; "
                 "package checks use injected synthetic byte peers and mocked COM enumeration, "
                 "without physical-device or firmware-image acceptance",
        "license_scope": "Existing notices/source guide included; third-party source archives "
                         "are not bundled; public distribution review remains open",
        "license_input_restoration": restored_notices,
        "verification": "See external build-report.json for this immutable ZIP",
        "files": file_tree(bundle),
    }
    write_json(bundle / "build-manifest.json", manifest)
    portable = Path(shutil.make_archive(str(output / "MotortesterV2-windows-x64"),
                                       "zip", root_dir=bundle.parent, base_dir=bundle.name))
    portable_hash = sha256(portable)
    expected_tree = file_tree(bundle)

    # Verify the final immutable ZIP, not merely the build-directory copy.
    relocated_parent = output / "Проверка переноса"
    with zipfile.ZipFile(portable) as archive:
        archive.extractall(relocated_parent)
    relocated = relocated_parent / APP_NAME
    if file_tree(relocated) != expected_tree:
        raise RuntimeError("Extracted portable ZIP differs from the sealed bundle")
    foreign_cwd = output / "Другая рабочая папка"
    foreign_cwd.mkdir()
    smoke_output = output / "frozen-smoke"
    frozen_env = clean_environment()
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    for name in list(frozen_env):
        if name.upper() == "PATH":
            frozen_env.pop(name)
    frozen_env["PATH"] = str(system_root / "System32")
    gui_exe, inspect_exe = relocated / gui_name, relocated / inspect_name
    exe_hashes = {name: expected_tree[name] for name in (gui_name, inspect_name)}
    run(gui_exe, "--verify-package", smoke_output, cwd=foreign_cwd,
        environment=frozen_env, timeout=FROZEN_TIMEOUT)
    smoke = read_json(smoke_output / "result.json")
    if (type(smoke) is not dict or smoke.get("status") != "PASS"
            or smoke.get("frozen") is not True or smoke.get("platform") != "win32"
            or smoke.get("qt_platform") != "windows" or smoke.get("error")
            or smoke.get("callback_errors") != []
            or Path(smoke.get("executable", "")).resolve() != gui_exe.resolve()):
        raise RuntimeError("Native frozen Windows package verification did not pass")
    device_check = smoke.get("device_verification")
    if (type(device_check) is not dict or device_check.get("status") != "PASS"
            or device_check.get("serial_version") != "3.5"
            or device_check.get("serial_backend") != "serial.serialwin32"
            or device_check.get("enumeration_mocked") is not True
            or device_check.get("panel_created") is not True
            or type(device_check.get("serial_open_calls")) is not int
            or device_check["serial_open_calls"] != 0
            or device_check.get("worker_running") is not False
            or device_check.get("wire_source") != "demo"
            or device_check.get("sample_count") != 2048
            or device_check.get("voltage_state") != "unconfigured"
            or device_check.get("time_basis") != "nominal_unverified"
            or device_check.get("physical_device_verified") is not False):
        raise RuntimeError("Packaged serial/device-panel/synthetic-window checks did not pass")
    close_check = smoke.get("close_verification")
    if (type(close_check) is not dict or close_check.get("status") != "PASS"
            or close_check.get("fragment_samples") != 250
            or close_check.get("default_and_escape") != "cancel"
            or close_check.get("decisions") != ["cancel", "discard"]
            or close_check.get("closed_without_json") is not True
            or close_check.get("saved_record_unchanged") is not True
            or close_check.get("serial_open_calls") != 0):
        raise RuntimeError("Packaged incomplete-window exit decisions did not pass")
    stream_check = smoke.get("stream_verification")
    if (type(stream_check) is not dict or stream_check.get("status") != "PASS"
            or stream_check.get("record_start", 0) <= 0
            or stream_check.get("exported_samples", 0) < 1
            or not all(stream_check.get(key) is True for key in (
                "pause_independent", "raw_roundtrip", "unknown_tail_preserved", "parent_close_drained"))
            or stream_check.get("physical_stream_verified") is not False):
        raise RuntimeError("Packaged synthetic streaming integration did not pass")
    picker = stream_check.get("record_picker", {})
    collision = stream_check.get("existing_path_picker", {})
    if (picker.get("status") != "PASS"
            or picker.get("save_picker", {}).get("elapsed_seconds", 0) < 70
            or picker.get("sustained_record", {}).get("elapsed_seconds", 0) < 12
            or picker.get("roundtrip", {}).get("raw_verified") is not True
            or collision.get("status") != "PASS"
            or collision.get("recording_reported_saved") is not False
            or collision.get("before") != collision.get("after")):
        raise RuntimeError("Packaged save-picker/continuous-writer/error checks did not pass")
    pngs = {name: png_info(smoke_output / name)
            for name in ("scope.png", "ignition.png", "device-panel.png", "incomplete-close.png",
                         "stream-scope.png", "stream-ignition.png", "stream-unknown-tail.png",
                         "stream-record-picker.png", "stream-existing-path.png")}
    pngs.update(verify_serial_smoke(smoke_output, smoke.get("serial_stream_verification")))
    pngs.update(verify_stop_smoke(smoke_output, stream_check.get("stop_verification")))
    high_rate = smoke.get("stream100_verification", {})
    high_roundtrip = high_rate.get("roundtrip", {})
    if (high_rate.get("status") != "PASS"
            or high_rate.get("execution_kind") != "injected-test"
            or high_rate.get("physical_stream_verified") is not False
            or high_rate.get("real_serial_open_calls") != 0
            or high_rate.get("owners_closed") is not True
            or high_rate.get("callback_errors") != [] or high_rate.get("errors") != []
            or high_rate.get("qt_platform") != "windows"
            or high_rate.get("nominal_fs_hz") != 100_000 or high_rate.get("interval_us") != 10
            or high_roundtrip.get("samples", 0) < 450_000
            or high_roundtrip.get("csv_rows") != high_roundtrip.get("samples")
            or high_roundtrip.get("csv_dt_seconds") != .000010
            or high_roundtrip.get("raw_matches_synthetic_period") is not True
            or high_roundtrip.get("unknown_tail_preserved") is not True
            or high_roundtrip.get("journal_sha256") != sha256(smoke_output / "synthetic100.mtstream")
            or read_json(smoke_output / "stream100-result.json") != high_rate):
        raise RuntimeError("Packaged 100 kS/s stream/time/raw roundtrip did not pass")
    high_export = read_json(smoke_output / "synthetic100.csv.json")
    if (high_export.get("identity", {}).get("nominal_fs_hz") != 100_000
            or high_export.get("csv_sha256") != sha256(smoke_output / "synthetic100.csv")):
        raise RuntimeError("Packaged 100 kS/s CSV checksum/timebase mismatch")
    pngs.update({name: png_info(smoke_output / name)
                 for name in ("stream100-live.png", "stream100-open.png")})
    for name in ("sample.mtv2", "export.csv", "export.csv.json", "device-window.mtv2"):
        path = smoke_output / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Package verification omitted {name}")
    exported = read_json(smoke_output / "export.csv.json")
    if exported.get("csv_sha256") != sha256(smoke_output / "export.csv"):
        raise RuntimeError("Export CSV/JSON checksum mismatch")
    with (smoke_output / "export.csv").open(encoding="utf-8", newline="") as stream:
        rows = csv.DictReader(stream)
        if rows.fieldnames != ["sample_index", "time_s", "adc_code", "voltage_v", "block_index", "gap_before"]:
            raise RuntimeError("Unexpected V2 CSV columns")
        exported_count = sum(1 for _ in rows)
    if exported_count < 1 or exported_count != exported.get("sample_count"):
        raise RuntimeError("Export CSV/JSON sample count mismatch")
    inspected = json.loads(run(inspect_exe, smoke_output / "sample.mtv2", cwd=foreign_cwd,
                               environment=frozen_env, timeout=FROZEN_TIMEOUT))
    if (type(inspected) is not dict or inspected.get("source") != "demo"
            or inspected.get("sample_count") != exported_count
            or inspected.get("session_id") != smoke.get("session_id")
            or inspected.get("voltage_state") != "nominal"):
        raise RuntimeError("Frozen console inspector did not read the synthetic V2 recording")
    write_json(output / "inspect-report.json", inspected)
    device_inspected = json.loads(run(inspect_exe, smoke_output / "device-window.mtv2",
        cwd=foreign_cwd, environment=frozen_env, timeout=FROZEN_TIMEOUT))
    if (type(device_inspected) is not dict or device_inspected.get("source") != "demo"
            or device_inspected.get("sample_count") != 2048
            or device_inspected.get("session_id") != device_check.get("session_id")
            or device_inspected.get("voltage_state") != "unconfigured"
            or device_inspected.get("time_basis") != "nominal_unverified"
            or device_inspected.get("available_range") != [0, 2048]):
        raise RuntimeError("Frozen inspector did not preserve the unknown-scale synthetic wire window")
    write_json(output / "device-inspect-report.json", device_inspected)
    # Exercise the ordinary GUI entrypoint with its live acquisition timer,
    # separately from --verify-package. The existing screenshot option exits
    # automatically and uses a private INI instead of the user's settings.
    startup_png = output / "normal-startup.png"
    run(gui_exe, "--screenshot", startup_png, "--settings", output / "startup-settings.ini",
        "--profile", "ignition", cwd=foreign_cwd, environment=frozen_env, timeout=FROZEN_TIMEOUT)
    startup = png_info(startup_png)
    if file_tree(relocated) != expected_tree or sha256(portable) != portable_hash:
        raise RuntimeError("Verification modified the final ZIP or extracted program files")

    report = {
        "status": "PASS",
        "scope": "Local portable package verification on the recorded Windows host; "
                 "not a clean-machine, physical-device or public-release acceptance",
        "source_commit": revision,
        "portable_zip": portable.name,
        "portable_sha256": portable_hash,
        "source_sha256": sha256(source_archive),
        "executable_sha256": exe_hashes,
        "extracted_bundle": str(relocated),
        "working_directory": str(foreign_cwd),
        "isolated_path": frozen_env["PATH"],
        "frozen_smoke": smoke,
        "png_files": pngs,
        "console_inspector": {"status": "PASS", "report": "inspect-report.json",
                              "sample_count": inspected["sample_count"]},
        "device_window_inspector": {"status": "PASS", "report": "device-inspect-report.json",
                                    "sample_count": device_inspected["sample_count"],
                                    "source": "demo", "voltage_state": "unconfigured"},
        "ordinary_gui_entrypoint": {"status": "PASS", "mode": "live DEMO ignition",
                                   "automatic_screenshot_exit": True, "png": startup},
        "smoke_files": file_tree(smoke_output),
        "windows_host": platform.platform(),
        "public_release_approved": False,
        "physical_device_verified": False,
    }
    write_json(output / "build-report.json", report)
    artifacts = [portable, source_archive, output / "build-report.json",
                 output / "inspect-report.json", output / "device-inspect-report.json",
                 startup_png, log]
    artifacts.extend(path for path in sorted(smoke_output.rglob("*")) if path.is_file())
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in artifacts),
        encoding="utf-8")
    print(f"\nPortable candidate verified: {portable}\nEvidence: {output / 'build-report.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        print(f"V2 package build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
