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
FROZEN_TIMEOUT = 45
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

    # Git archives retain the exact committed notice bytes. A Windows checkout
    # may have CRLF conversion, which must never be worked around by repinning.
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
        "scope": "V2 DEMO, .mtv2/.mtcap files and CSV/JSON; no physical device validation",
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
    pngs = {name: png_info(smoke_output / name) for name in ("scope.png", "ignition.png")}
    for name in ("sample.mtv2", "export.csv", "export.csv.json"):
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
        "ordinary_gui_entrypoint": {"status": "PASS", "mode": "live DEMO ignition",
                                   "automatic_screenshot_exit": True, "png": startup},
        "smoke_files": file_tree(smoke_output),
        "windows_host": platform.platform(),
        "public_release_approved": False,
        "physical_device_verified": False,
    }
    write_json(output / "build-report.json", report)
    artifacts = [portable, source_archive, output / "build-report.json",
                 output / "inspect-report.json", startup_png, log]
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
