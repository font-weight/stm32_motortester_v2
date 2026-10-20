"""Build the separately reviewed V2S4 transport candidate; never flash hardware."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

UPSTREAM = "c10884fa39ad1a10ce0fcfc9d6e17f170e1e0bf0"
FIRMWARE_TREE = "cffe4ee61a7e47885c825521ea6fd679abd75fdf"
TOOLCHAIN = (
    "C:/ST/STM32CubeIDE_1.15.0/STM32CubeIDE/plugins/"
    "com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32."
    "12.3.rel1.win32_1.0.100.202403111256/tools"
)
REMOVE = {
    "firmware/boot/mt_device_main.c", "firmware/acquisition/acquisition.c",
    *("firmware/app/" + x + ".c" for x in
      ("mt_capture_link", "mt_adc_control", "mt_control", "mt_control_rx", "mt_runtime")),
    *("firmware/protocol/" + x + ".c" for x in ("mt_stream", "mt_session", "mt_command")),
    "firmware/transport/mt_tx.c", "firmware/transport/mt_usb_cdc.c",
}
ADD = [
    "firmware/boot/mt_stream_main.c", "firmware/app/mt_live_runtime.c",
    "firmware/app/mt_live_adc.c", "firmware/platform/mt_live_clock.c",
    "firmware/protocol/mt_live_device.c", "firmware/acquisition/mt_sample_queue.c",
    "firmware/platform/mt_stream_diag.c",
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_patch(raw, patch_raw, pins):
    """Exact unified hunks, no fuzz/offset; final pinned SHA validates the result."""
    require(hashlib.sha256(raw).hexdigest() == pins["source_sha256"], "Patch input SHA")
    require(hashlib.sha256(patch_raw).hexdigest() == pins["patch_sha256"], "Patch SHA")
    old = raw.decode("utf-8").splitlines(keepends=True)
    patch = patch_raw.decode("utf-8").splitlines(keepends=True)
    result, cursor, index = [], 0, 0
    while index < len(patch):
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", patch[index])
        if not match:
            index += 1
            continue
        start = int(match[1]) - 1
        require(start >= cursor, "Patch hunk ordering")
        result.extend(old[cursor:start])
        cursor, removed, added = start, 0, 0
        index += 1
        while index < len(patch) and not patch[index].startswith("@@"):
            line = patch[index]
            require(line[:1] in (" ", "+", "-"), "Unsupported patch line")
            if line[0] in (" ", "-"):
                require(cursor < len(old) and old[cursor] == line[1:], "Patch context differs")
                cursor += 1
                removed += 1
            if line[0] in (" ", "+"):
                result.append(line[1:])
                added += 1
            index += 1
        require(removed == int(match[2] or 1) and added == int(match[4] or 1),
                "Patch hunk geometry")
    result.extend(old[cursor:])
    output = "".join(result).encode("utf-8")
    require(hashlib.sha256(output).hexdigest() == pins["result_sha256"], "Patch output SHA")
    return output


def main():
    require(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,
            "Run python -I -B; optimized assertions are forbidden")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New directory, normally build/v5-fw-01")
    parser.add_argument("--toolchain", default=TOOLCHAIN)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    tc = Path(args.toolchain).resolve(strict=True)
    out = Path(args.output).resolve()
    require(not out.exists(), "Use a new output directory; failed outputs are retained")
    require(out.is_relative_to(root / "build"), "Output must be inside repository build/")
    require(not any(p.is_symlink() for p in (out, *out.parents)), "No symlink output")
    git = Path(shutil.which("git") or "").resolve(strict=True)
    config_raw = (here / "config.json").read_bytes()
    config, board_c, timing_c = load(here / "overlays/board_inputs.py").generate(config_raw)
    tool_pins = json.loads((here / "toolchain-win.json").read_text("utf-8"))
    inputs = {str(p): digest(p) for p in here.rglob("*") if p.is_file()}
    inputs[str(Path(sys.executable).resolve())] = digest(Path(sys.executable).resolve())
    inputs[str(git)] = digest(git)
    for relative, expected in tool_pins["files"].items():
        path = tc / relative
        require(path.is_file() and digest(path) == expected, "Toolchain differs: " + relative)
        inputs[str(path)] = expected
    tools = {name: tc / "bin" / ("arm-none-eabi-" + name + ".exe")
             for name in ("gcc", "as", "ld", "readelf", "nm", "size", "objcopy", "objdump")}
    out.mkdir(parents=True)
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH",
                                  "COMPILER_PATH", "GCC_EXEC_PREFIX", "LIBRARY_PATH")}
    env.update(LANG="C", LC_ALL="C", TZ="UTC", SOURCE_DATE_EPOCH="1792472471",
               PYTHONDONTWRITEBYTECODE="1")
    # All compiler input/output paths are ASCII relative paths: native Windows
    # GCC's CRT otherwise cannot open a checkout under a Cyrillic user directory.
    receipt = {
        "schema": "motortester-v2-stream-build-receipt-1", "status": "RUNNING",
        "upstream_commit": UPSTREAM, "firmware_tree": FIRMWARE_TREE,
        "local_head": None, "config": config, "inputs_before": inputs,
        "commands": [], "objects": [], "dependencies": {},
        "hardware_verified": False, "timing_qualified": False, "flash_approved": False,
        "instrumentation_profile": "foreground-dwt-v1",
        "scope": "V2 transport candidate; no-input experiment requires separate exact-image review",
        "unverified": ["Physical HSE frequency/mode and USB pull-up",
                       "ADC/USB service latency and 1 ms transaction bound",
                       "Physical sample loss and unknown produced endpoint",
                       "Analogue input and voltage calibration"],
    }

    def save():
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    def run(label, argv, text=True):
        argv = [str(a) for a in argv]
        row = {"label": label, "argv": argv, "cwd": str(out)}
        receipt["commands"].append(row)
        process = subprocess.run(argv, cwd=out, env=env, capture_output=True, timeout=180)
        row["exit_code"] = process.returncode
        (out / (label + ".stdout")).write_bytes(process.stdout)
        (out / (label + ".stderr")).write_bytes(process.stderr)
        save()
        require(process.returncode == 0, label + " failed; stderr retained")
        return process.stdout.decode("utf-8") if text else process.stdout

    try:
        receipt["local_head"] = run("local-head", [git, "-C", root, "rev-parse", "HEAD"]).strip()
        receipt["local_status"] = run("local-status", [git, "-C", root, "status", "--porcelain"])
        tree = run("upstream-tree", [git, "-C", root, "rev-parse", UPSTREAM + ":firmware"]).strip()
        require(tree == FIRMWARE_TREE, "Upstream firmware tree differs")
        archive = out / "upstream-source.tar"
        run("archive", [git, "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                        "-C", root, "archive", "--format=tar", "--output=" + str(archive),
                        UPSTREAM, "firmware", "tests/boot-link"])
        with tarfile.open(archive) as tar:
            require(all(m.isfile() or m.isdir() for m in tar), "Unexpected archive member")
            tar.extractall(out / "source", filter="data")
        receipt["archive_sha256"] = digest(archive)
        for path in (out / "source").rglob("*"):
            if path.is_file():
                inputs[str(path)] = digest(path)
        for folder in ("objects", "patched", "generated", "recipe"):
            (out / folder).mkdir()
        for path in here.rglob("*"):
            if path.is_file():
                target = out / "recipe" / path.relative_to(here)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        (out / "generated/board.c").write_text(board_c, encoding="ascii", newline="\n")
        (out / "generated/timing.c").write_text(timing_c, encoding="ascii", newline="\n")
        (out / "config.json").write_bytes(config_raw)
        for name, path in tools.items():
            run("version-" + name, [path, "--version"])
        for name in ("cc1", "as"):
            selected = Path(run("selected-" + name, [tools["gcc"], "-print-prog-name=" + name]).strip()).resolve()
            require(str(selected) in inputs, "Unpinned compiler child: " + str(selected))
        source = out / "source"
        helpers = source / "firmware/third_party/usb/patches"
        vendor = source / "firmware/third_party/usb/vendor"
        def patch(source_bytes, manifest, patch_name=None):
            spec = json.loads((helpers / manifest).read_text("utf-8")) if isinstance(manifest, str) else manifest
            return apply_patch(source_bytes, (helpers / (patch_name or spec["patch"])).read_bytes(), spec)
        usbd = patch((vendor / "tinyusb/src/device/usbd.c").read_bytes(),
                     "setup-accounting.json", "0001-setup-rejection-accounting.patch")
        fsdev = patch((vendor / "tinyusb/src/portable/st/stm32_fsdev/dcd_stm32_fsdev.c").read_bytes(),
                      "f103-reset-cleanup.json", "0002-f103-reset-completion-cleanup.patch")
        usb_pins = json.loads((helpers / "usb005-patches.json").read_text("utf-8"))["inputs"]
        usbd = patch(usbd, usb_pins["core"])
        fsdev = patch(patch(fsdev, usb_pins["fsdev"]), "stream-ctr-fairness.json")
        (out / "patched/usbd.c").write_bytes(usbd)
        (out / "patched/dcd_stm32_fsdev.c").write_bytes(fsdev)
        # Preserve the canonical archive. V2 patches are a second, independently
        # pinned layer over exactly the inputs named in the overlay manifest.
        receipt["v2_overlays"] = []
        for name, schema in (("usb-nvic.json", "motortester-v2-usb-nvic-overlay-1"),
                             ("adc-cen.json", "motortester-v2-adc-cen-overlay-1"),
                             ("crc32.json", "motortester-v2-crc32-overlay-1")):
            v2_patches = json.loads((here / "overlays" / name).read_text("utf-8"))
            require(v2_patches["schema"] == schema, "Unexpected V2 overlay schema")
            receipt["v2_overlays"].extend(v2_patches["patches"])
            for row in v2_patches["patches"]:
                target = out / "patched" / row["target"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(apply_patch(
                    (out / row["source"]).read_bytes(),
                    (here / "overlays" / row["patch"]).read_bytes(), row))
        (out / "patched/v2/protocol/mt_v2_crc32.h").write_bytes(
            (here / "overlays/mt_v2_crc32.h").read_bytes())
        # Keep quoted relative header includes inside one coherent V2 tree.
        # Unchanged headers are byte copies of the pinned archive; never replace
        # the two explicit API overlays or mutate the canonical source tree.
        for area in ("boot", "platform", "app", "protocol", "transport", "acquisition"):
            for original in (source / "firmware" / area).rglob("*.h"):
                target = out / "patched/v2" / original.relative_to(source / "firmware")
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(original.read_bytes())
        # Quoted relative includes must resolve to the V2 header alongside the
        # patched translation unit, never silently fall back to the old gate.
        for original, target in (
            ("firmware/third_party/usb/vendor/tinyusb/src/portable/st/stm32_fsdev/fsdev_common.h",
             "fsdev_common.h"),
            ("firmware/platform/mt_stream_diag.h", "v2/platform/mt_stream_diag.h"),
        ):
            copied = out / "patched" / target
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes((source / original).read_bytes())
        manifest = json.loads((source / "firmware/build/inputs.json").read_text("utf-8"))
        standard = next(r["flags"] for r in manifest["components"]
                        if r["source"] == "firmware/app/mt_runtime.c")
        entries = [r for r in manifest["components"] if r["source"] not in REMOVE]
        require(len(entries) == 20, "Unexpected retained component count")
        entries += [{"source": path, "flags": standard} for path in ADD]
        includes = ["-Ipatched/v2/" + p for p in
                    ("boot", "platform", "app", "protocol", "transport", "acquisition")]
        includes += ["-Isource/firmware/" + p for p in
                    ("boot", "platform", "app", "protocol", "transport", "acquisition")]
        for relative in ("tinyusb/src", "cmsis-device-f1/Include", "cmsis-core/CMSIS/Core/Include",
                         "tinyusb/src/portable/st/stm32_fsdev"):
            includes += ["-isystem", "source/firmware/third_party/usb/vendor/" + relative]
        objects = []
        def compile_c(name, path, flags):
            obj = "objects/" + name + ".o"
            dep = "objects/" + name + ".d"
            run("compile-" + name, [tools["gcc"], *flags,
                "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-fno-stack-protector",
                "-fno-lto", "-fno-pic", "-fno-pie", "-fno-jump-tables", "-fno-tree-switch-conversion",
                "-DCFG_MT_USB_CTR_FAIRNESS=1", "-DCFG_MT_STREAM_DIAGNOSTICS=1",
                *includes, "-MD", "-MT", "v2_object", "-MF", dep, "-c", path, "-o", obj])
            # -MT removes drive-colon ambiguity. GCC make escaping is deliberately
            # decoded here, rather than treating a Windows path as a POSIX shell.
            text = (out / dep).read_text("utf-8").replace("\\\n", " ").split(":", 1)[1]
            dependencies = re.findall(r"(?:\\.|[^\s])+", text)
            for item in dependencies:
                item = re.sub(r"\\([ #\\])", r"\1", item)
                dependency = Path(item)
                if not dependency.is_absolute():
                    dependency = out / dependency
                dependency = dependency.resolve()
                digest_now = digest(dependency)
                if dependency.is_relative_to(out / "patched") or dependency.is_relative_to(out / "generated"):
                    inputs.setdefault(str(dependency), digest_now)
                require(inputs.get(str(dependency)) == digest_now,
                        "Unpinned compiler dependency: " + str(dependency))
                receipt["dependencies"][str(dependency)] = digest_now
            objects.append(obj)
            run("disassembly-" + name, [tools["objdump"], "-dr", obj])
        for index, row in enumerate(entries):
            src = row["source"]
            path = src.replace("@patched/", "patched/") if src.startswith("@") else "source/" + src
            path = {
                "source/firmware/app/mt_live_runtime.c": "patched/v2/app/mt_live_runtime.c",
                "source/firmware/app/mt_live_adc.c": "patched/v2/app/mt_live_adc.c",
                "source/firmware/platform/adc_timer_dma.c": "patched/v2/platform/adc_timer_dma.c",
                "source/firmware/protocol/mt_wire.c": "patched/v2/protocol/mt_wire.c",
                "source/firmware/protocol/mt_live_device.c": "patched/v2/protocol/mt_live_device.c",
                "source/firmware/transport/mt_usb_bridge.c": "patched/v2/transport/mt_usb_bridge.c",
            }.get(path, path)
            compile_c(f"{index:02}-{Path(src).stem}", path, row["flags"])
        reset = "objects/reset.o"
        run("compile-reset", [tools["gcc"], "-mcpu=cortex-m3", "-mthumb", "-mfloat-abi=soft",
            "-ffreestanding", "-fno-lto", "-Wa,--noexecstack", "-c",
            "source/firmware/boot/mt_reset_stm32f103c8.S", "-o", reset])
        objects.append(reset)
        compile_c("board", "generated/board.c", standard)
        compile_c("timing", "generated/timing.c", standard)
        require(len(objects) == 30, "Unexpected link input count")
        checker = load(source / "tests/boot-link/tools/run_boot_link_tests.py")
        vectors_path = source / "tests/boot-link/vector_map.json"
        require(digest(vectors_path) == checker.VECTOR_SHA, "Vector map differs")
        vectors = json.loads(vectors_path.read_text("utf-8"))["rows"][:59]
        input_audit = []
        for index, obj in enumerate(objects):
            parsed = checker.ELF(out / obj)
            input_audit.append(checker.audit_input_metadata(parsed))
            checker.check_attributes(run(f"attributes-{index}", [tools["readelf"], "-A", obj]))
        receipt["input_audit"] = input_audit
        receipt["vector_relocations"] = checker.check_vector_relocations(checker.ELF(out / reset), vectors)
        elf = "MotortesterV2-stream-candidate.elf"
        run("link", [tools["ld"], "--fatal-warnings", "--no-gc-sections", "--orphan-handling=error",
            "--defsym=__boot_stack_bytes=8192", "-T", "source/firmware/boot/stm32f103c8.ld",
            "-Map=image.map", "-o", elf, *objects])
        disassembly = run("final-disassembly", [tools["objdump"], "-dr", elf])
        (out / "image.dis").write_text(disassembly, encoding="utf-8", newline="\n")
        symbols = run("final-symbols", [tools["nm"], "-S", "-n", elf])
        (out / "image.nm").write_text(symbols, encoding="utf-8", newline="\n")
        parsed = checker.ELF(out / elf)
        receipt["elf_audit"] = {
            "layout": checker.check_layout(parsed, 8192),
            "vectors": checker.check_vectors(parsed, vectors),
            "reset": checker.check_reset(parsed, disassembly),
        }
        require(not run("undefined", [tools["nm"], "-u", elf]).strip(), "Undefined symbols")
        receipt["size"] = run("size", [tools["size"], elf])
        for kind, suffix in (("binary", "bin"), ("ihex", "hex")):
            run("export-" + suffix, [tools["objcopy"], "-O", kind, elf,
                                    "MotortesterV2-stream-candidate." + suffix])
        receipt["objects"] = [{"path": p, "sha256": digest(out / p)} for p in objects]
        receipt["artifacts"] = {p.name: digest(p) for p in out.glob("MotortesterV2-stream-candidate.*")}
        analysis_files = [out / name for name in ("image.map", "image.dis", "image.nm")]
        analysis_files += sorted((out / "objects").glob("*.su"))
        receipt["analysis_inputs"] = {
            p.relative_to(out).as_posix(): digest(p) for p in analysis_files}
        save()
        static = load(here / "check_static.py").analyze(out)
        (out / "static-bound.json").write_text(json.dumps(static, indent=2) + "\n", encoding="utf-8")
        receipt["static_bound"] = {
            "report_sha256": digest(out / "static-bound.json"),
            "status": static["status"], "upper_bound_bytes": static["upper_bound_bytes"],
            "aligned_minimum_bytes": static["aligned_minimum_bytes"]}
        receipt["status"] = "BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE"
    except BaseException as exc:
        receipt.update(status="FAILED", error=type(exc).__name__ + ": " + str(exc))
        raise
    finally:
        drift = [p for p, expected in inputs.items()
                 if not Path(p).is_file() or digest(Path(p)) != expected]
        receipt["input_drift"] = drift
        if drift:
            receipt["status"] = "FAILED_INPUT_DRIFT"
        save()
        require(not drift, "Inputs changed during build")
    print(json.dumps({"status": receipt["status"], "receipt": str(out / "receipt.json")}))


if __name__ == "__main__":
    main()
