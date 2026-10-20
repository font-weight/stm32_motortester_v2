"""Focused native execution of the exact V2 gate/ISR/bridge C bodies.

The logical MMIO/NVIC model deliberately asserts a pending endpoint IRQ even
with CTRM=0 (RM0008). No timing, ARM ABI, USB PHY or complete TinyUSB claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def function(text, name):
    match = re.search(r"(?m)^[^\n;{}]*\b" + name + r"\([^;{}]*\)\s*\{", text)
    if not match:
        raise ValueError("Missing function: " + name)
    start = match.start()
    # The pinned sources close each multiline function at column zero. Raw
    # brace counting is wrong for the ISR's #if/#else alternative while bodies.
    rest = text[match.end():]
    same_line = rest.split("\n", 1)[0]
    if "}" in same_line:
        end = match.end() + same_line.index("}") + 1
    else:
        closing = re.search(r"(?m)^}", rest)
        if not closing:
            raise ValueError("Missing pinned function boundary: " + name)
        end = match.end() + closing.end()
    return text[start:end] + "\n"


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("Run python -I -B")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--zig", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out, image = args.output.resolve(), args.image.resolve()
    if out.exists() or not out.is_relative_to(root / "build"):
        raise ValueError("Use a new build/ output")
    out.mkdir()
    self_path = Path(__file__).resolve()
    inputs = {str(self_path): hashlib.sha256(self_path.read_bytes()).hexdigest()}

    def read(path):
        data = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(data).hexdigest()
        return data.decode("utf-8")

    dcd = read(image / "patched/dcd_stm32_fsdev.c")
    stm = read(image / "patched/fsdev_stm32.h")
    common = read(image / "patched/fsdev_common.h")
    bridge = read(image / "patched/v2/transport/mt_usb_bridge.c")
    epoch_folder = image / "source/firmware/transport"
    epoch_h = read(epoch_folder / "mt_usb_epoch.h")
    epoch_c = read(epoch_folder / "mt_usb_epoch.c")
    (out / "mt_usb_epoch.h").write_text(epoch_h, encoding="utf-8")
    (out / "mt_usb_epoch.c").write_text(epoch_c, encoding="utf-8")
    preamble = read(Path(__file__).with_name("usb_gate_model.c"))
    constants = "\n".join(re.findall(r"(?m)^#define U_[^\n]+", common)) + "\n"
    bodies = ["static volatile bool mt_ctr_deferred, mt_irq_held;\n",
              "bool mt_usb_fsdev_irq_held(void);\n"]
    for name in ("fsdev_int_enable", "fsdev_int_disable"):
        bodies.append(function(stm, name))
    for name in ("ep_write",):
        bodies.append(function(common, name))
    for name in ("mt_usb_fsdev_ctr_deferred", "mt_usb_fsdev_irq_held",
                 "mt_usb_fsdev_lifecycle_pending", "mt_usb_fsdev_irq_hold",
                 "mt_usb_fsdev_irq_grant", "dcd_int_enable", "dcd_int_disable",
                 "dcd_int_handler"):
        bodies.append(function(dcd, name))
    for name in ("permitted", "mt_usb_bridge_dispatch", "mt_usb_bridge_app_enter"):
        bodies.append(function(bridge, name))
    body = "\n".join(bodies)
    # Only MMIO instrumentation changes extracted bodies. The model implements
    # ISTR rc_w0 and read-only CTR aggregation rather than ordinary C assignment.
    body, writes = re.subn(r"FSDEV_REG->ISTR = ([^;]+);",
                          r"model_istr_write(\1);", body)
    reads = body.count("FSDEV_REG->ISTR")
    body = body.replace("FSDEV_REG->ISTR", "model_istr_read()")
    if writes != 8 or reads != 5:
        raise ValueError(f"Unexpected ISTR instrumentation: {writes=} {reads=}")
    code = preamble.replace("/* CONSTANTS */", constants).replace("/* BODIES */", body)
    source = out / "gate.c"
    source.write_text(code, encoding="utf-8", newline="\n")
    zig = args.zig.resolve(strict=True)
    inputs[str(zig)] = hashlib.sha256(zig.read_bytes()).hexdigest()
    version = subprocess.run([str(zig), "version"], capture_output=True, check=True).stdout.decode().strip()
    commands = []
    (out / "temp").mkdir()
    env = dict(os.environ, ZIG_LOCAL_CACHE_DIR=str(out / "zig-local-cache"),
               ZIG_GLOBAL_CACHE_DIR=str(out / "zig-global-cache"),
               TMP=str(out / "temp"), TEMP=str(out / "temp"))

    def run(name, argv, expected=0):
        process = subprocess.run([str(x) for x in argv], cwd=out,
                                 capture_output=True, timeout=180, env=env)
        (out / (name + ".stdout")).write_bytes(process.stdout)
        (out / (name + ".stderr")).write_bytes(process.stderr)
        commands.append({"name": name, "argv": [str(x) for x in argv],
                         "exit_code": process.returncode})
        if (process.returncode != 0) != (expected != 0):
            raise ValueError(name + " unexpected exit; output retained")
        return process.stdout.decode("utf-8")

    flags = ["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-function", "-Wno-unused-parameter"]
    run("compile", [zig, *flags, "gate.c", "mt_usb_epoch.c", "-o", "gate.exe"])
    output = run("gate", [out / "gate.exe"])
    # The same executable model must fail when the original missing NVIC hold
    # is restored at the ISR boundary; a vacuous passing model is rejected.
    mutant, replacements = re.subn(r"(?m)^  mt_usb_fsdev_irq_hold\(\);$",
                                   "  /* missing IRQ hold */", code)
    if replacements != 1:
        raise ValueError("ISR hold site changed")
    (out / "mutant.c").write_text(mutant,
                                encoding="utf-8", newline="\n")
    run("compile-mutant", [zig, *flags, "mutant.c", "mt_usb_epoch.c", "-o", "mutant.exe"])
    run("mutant", [out / "mutant.exe"], expected=1)
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected
           for path, expected in inputs.items()):
        raise ValueError("Native input changed during check")
    result = {
        "status": "PASS", "scope": __doc__, "compiler": {"path": str(zig), "version": version},
        "image": str(image), "inputs": inputs, "commands": commands,
        "istr_instrumentation": {"rc_w0_writes": writes, "reads": reads},
        "stdout": output, "missing_irq_hold_control": "REJECTED",
        "generated": {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                      for name in ("gate.c", "mt_usb_epoch.c", "mt_usb_epoch.h",
                                   "mutant.c", "gate.exe", "mutant.exe")},
        "not_verified": ["Hardware interrupt routing/latency", "Complete TinyUSB control transfers",
                         "USB enumeration", "ADC service timing", "Physical losslessness"],
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "stdout": output, "result": str(out / "result.json")}))


if __name__ == "__main__":
    main()
