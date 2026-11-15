"""Build a manifest-bound local UI candidate without touching the dirty tree.

Uses the existing locked v18w2 environment and dependency license bundle. This
is a local development candidate, not a public distribution/license approval.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def source_files():
    paths = []
    for directory in (ROOT / "host", ROOT / "tools" / "first_power_guide"):
        paths.extend(p for p in directory.rglob("*") if p.is_file() and
            not any(s in {"__pycache__", ".pytest_cache", ".venv", "build", "dist"} for s in p.relative_to(directory).parts)
            and p.suffix not in {".pyc", ".pyo"})
    paths.extend(ROOT / p for p in ("tools/build_calibration_candidate.py", "README.md", "host/README.md",
        "requirements.md", "task.md", "AGENTS.md", "docs/calibration-wizard.md",
        "docs/unified-ui.md", "docs/verification/unified-ui-20261113/SCOPE_RU.md",
        "docs/verification/calibration-live-20261114/SCOPE_RU.md",
        "docs/segment-measurements.md", "docs/verification/segment-measurements-20261114/SCOPE_RU.md",
        "docs/event-frequency.md", "docs/verification/event-frequency-20261114/SCOPE_RU.md",
        "docs/ringdown.md", "docs/verification/ringdown-20261114/SCOPE_RU.md",
        "docs/guides/r53-first-power-ru.md", "docs/verification/calibration-20261113/SCOPE_RU.md",
        "готовые документы/Первое включение платы_R53.pdf"))
    return sorted(set(paths))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--verification", choices=("calibration", "unified", "calibration-live", "segment-measurements", "event-frequency", "ringdown"), default="calibration")
    args = parser.parse_args()
    out = (ROOT / args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    prior = ROOT / "build/v18w2"
    python = prior / "venv/Scripts/python.exe"
    old_bundle = prior / "dist/MotortesterV2"
    sources = source_files()
    source_map = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}
    with zipfile.ZipFile(out / "source.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in sources: z.write(p, p.relative_to(ROOT).as_posix())
    env = os.environ.copy()
    for k in list(env):
        if k.upper() in {"PATH", "PYTHONPATH", "PYTHONHOME"} or k.upper().startswith(("QT", "QML")):
            env.pop(k)
    base_python = subprocess.check_output([str(python), "-c", "import sys; print(sys.base_prefix)"], text=True).strip()
    env["PATH"] = os.pathsep.join((base_python, str(Path(base_python) / "Scripts"), str(Path(os.environ["SystemRoot"]) / "System32")))
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONHASHSEED="0", PYQTGRAPH_QT_LIB="PySide6")
    with (out / "build.log").open("w", encoding="utf-8") as log:
        command = [str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(out / "dist"),
                   "--workpath", str(out / "pyinstaller"), str(ROOT / "host/packaging/v2/motortester-v2.spec")]
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    if source_map != {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}:
        raise RuntimeError("Source changed during packaging")
    bundle = out / "dist/MotortesterV2"
    shutil.copytree(old_bundle / "licenses", bundle / "licenses")
    for name in ("LICENSE", "LICENSE-REVIEW.md", "requirements-win-x64.lock"):
        shutil.copy2(old_bundle / name, bundle / name)
    shutil.copy2(ROOT / "host/packaging/v2/README_PORTABLE_RU.txt", bundle / "README_RU.txt")
    shutil.copy2(ROOT / "docs/calibration-wizard.md", bundle / "Калибровка_RU.md")
    shutil.copy2(ROOT / "docs/unified-ui.md", bundle / "Главный экран_RU.md")
    shutil.copy2(ROOT / "docs/segment-measurements.md", bundle / "Измерения участка_RU.md")
    shutil.copy2(ROOT / "docs/event-frequency.md", bundle / "Частота событий_RU.md")
    shutil.copy2(ROOT / "docs/ringdown.md", bundle / "Затухающие колебания_RU.md")
    shutil.copy2(ROOT / "готовые документы/Первое включение платы_R53.pdf", bundle / "Первое включение платы_R53.pdf")
    scope = {"unified": "V2-17 unified", "calibration": "V2-16 calibration", "calibration-live": "V2-18 live calibration and PDF",
             "segment-measurements": "V2-19 raw segment mean and periodicity",
             "event-frequency": "V2-20 stable readout and live threshold-event frequency",
             "ringdown": "V2-21 selected damped-response analysis"}[args.verification]
    manifest = dict(scope=scope + " local Windows candidate; synthetic checks only", source_commit_base=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), source_tree="working copy bound by hashes",
        source_files=source_map, source_zip_sha256=digest(out / "source.zip"),
        build_command=command, environment="reused locked v18w2 venv; isolated Python/system PATH; no dependency changes",
        files={p.relative_to(bundle).as_posix(): digest(p) for p in sorted(bundle.rglob("*")) if p.is_file()})
    (bundle / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    portable = Path(shutil.make_archive(str(out / "MotortesterV2-windows-x64"), "zip", bundle.parent, bundle.name))
    relocation = out / "Проверка переноса"
    with zipfile.ZipFile(portable) as z: z.extractall(relocation)
    relocated = relocation / "MotortesterV2"
    for relative, expected in manifest["files"].items():
        if digest(relocated / relative) != expected: raise RuntimeError("Relocated bundle differs")
    foreign = out / "Другая рабочая папка"; foreign.mkdir()
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    executable = relocated / "MotortesterV2.exe"
    witness = out / ("frozen-" + args.verification)
    subprocess.run([str(executable), "--verify-" + args.verification, str(witness)],
        cwd=foreign, env=env, check=True, timeout=90)
    receipt = json.loads((witness / "result.json").read_text(encoding="utf-8"))
    if receipt["status"] != "PASS" or not receipt["frozen"] or receipt["qt_platform"] != "windows" or receipt["real_serial_open_calls"]:
        raise RuntimeError("Frozen witness failed")
    if args.verification in ("unified", "calibration-live", "segment-measurements", "event-frequency", "ringdown"):
        cold_start = out / "normal-entry.png"
        subprocess.run([str(executable), "--screenshot", str(cold_start)],
            cwd=foreign, env=env, check=True, timeout=30)
        if not cold_start.is_file() or cold_start.stat().st_size < 1000:
            raise RuntimeError("Normal entrypoint screenshot missing")
    result = dict(status="PASS", executable=str(bundle / "MotortesterV2.exe"),
        portable_sha256=digest(portable), manifest_sha256=digest(bundle / "build-manifest.json"),
        source_zip_sha256=digest(out / "source.zip"), check_result=receipt,
        physical_measurement=False, public_release=False)
    (out / "build-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
