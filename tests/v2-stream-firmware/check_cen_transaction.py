"""Execute narrow CEN regression with exact image C bodies and full TIME/ADC."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("Run python -I -B")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image", "zig", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    image, out, zig = args.image.resolve(), args.output.resolve(), args.zig.resolve(strict=True)
    if out.exists() or not out.is_relative_to(root / "build"):
        raise ValueError("Use a new build/ output")
    out.mkdir()
    inputs = {str(Path(__file__).resolve()): sha(Path(__file__)), str(zig): sha(zig)}

    def read(path):
        inputs[str(path)] = sha(path)
        return path.read_text("utf-8")

    helper_path = Path(__file__).with_name("check_usb_gate.py").resolve()
    read(helper_path)
    spec = importlib.util.spec_from_file_location("extract", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    receipt_path = image / "receipt.json"
    receipt = json.loads(read(receipt_path))
    if receipt["status"] != "BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE":
        raise ValueError("Image must finish its static check first")
    runtime = read(image / "patched/v2/app/mt_live_runtime.c")
    bodies = "\n".join(helper.function(runtime, name) for name in (
        "adc_read", "adc_write", "commit_allowed", "commit_timed", "commit_timer"))
    model = read(Path(__file__).with_name("cen_transaction_model.c").resolve())
    (out / "cen.c").write_text(model.replace("/* BODIES */", bodies), encoding="utf-8", newline="\n")
    for name, source in (
        ("adc_timer_dma.c", "patched/v2/platform/adc_timer_dma.c"),
        ("adc_timer_dma.h", "patched/v2/platform/adc_timer_dma.h"),
        ("mt_timebase.c", "source/firmware/platform/mt_timebase.c"),
        ("mt_timebase.h", "source/firmware/platform/mt_timebase.h"),
        ("mt_stream_diag.h", "source/firmware/platform/mt_stream_diag.h"),
    ):
        (out / name).write_text(read(image / source), encoding="utf-8", newline="\n")
    for path, digest in inputs.items():
        if str(image) in path and path != str(receipt_path):
            if receipt["inputs_before"].get(path) != digest:
                raise ValueError("Source differs from image receipt: " + path)
    (out / "temp").mkdir()
    env = dict(os.environ, ZIG_LOCAL_CACHE_DIR=str(out / "zig-local-cache"),
               ZIG_GLOBAL_CACHE_DIR=str(out / "zig-global-cache"),
               TMP=str(out / "temp"), TEMP=str(out / "temp"))
    commands = []

    def run(name, argv):
        result = subprocess.run([str(x) for x in argv], cwd=out, env=env,
                                capture_output=True, timeout=180)
        (out / (name + ".stdout")).write_bytes(result.stdout)
        (out / (name + ".stderr")).write_bytes(result.stderr)
        commands.append({"name": name, "argv": [str(x) for x in argv],
                         "exit_code": result.returncode})
        if result.returncode:
            raise ValueError(name + " failed; output retained")
        return result.stdout.decode("utf-8")

    version = run("version", [zig, "version"]).strip()
    run("compile", [zig, "cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                    "-Wno-unused-function", "-Wno-unused-parameter",
                    "cen.c", "adc_timer_dma.c", "mt_timebase.c", "-o", "cen.exe"])
    stdout = run("cen", [out / "cen.exe"])
    if any(sha(Path(path)) != digest for path, digest in inputs.items()):
        raise ValueError("Input changed during check")
    result = {
        "status": "PASS", "scope": __doc__, "image": str(image),
        "firmware_build": receipt["config"]["firmware_build"],
        "image_bin_sha256": receipt["artifacts"]["MotortesterV2-stream-candidate.bin"],
        "inputs": inputs, "commands": commands, "compiler_version": version, "stdout": stdout,
        "generated": {path.name: sha(path) for path in out.iterdir()
                      if path.is_file() and path.suffix in (".c", ".h", ".exe")},
        "negative_control": "Old validated-timestamp path rejected by unchanged20us gate",
        "not_verified": ["ARM/bus/CPU timing", "USB PHY and full lifecycle implementation",
                         "ADC conversion latency", "Physical sampling or voltage"],
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "stdout": stdout, "result": str(out / "result.json")}))


if __name__ == "__main__":
    main()
