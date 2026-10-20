"""Exact CRC equivalence against upstream C and actual saved wire/raw; no hardware."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("Run python -I -B")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("image", "traffic", "zig", "output"):
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

    receipt_path = image / "receipt.json"
    receipt = json.loads(read(receipt_path))
    if receipt["status"] != "BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE":
        raise ValueError("Image must finish its static check first")
    helper_path = Path(__file__).with_name("check_usb_gate.py").resolve()
    read(helper_path)
    spec = importlib.util.spec_from_file_location("extract_crc", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    old_prefix = helper.function(read(image / "source/firmware/protocol/mt_live_device.c"), "crc_codes")
    new_prefix = helper.function(read(image / "patched/v2/protocol/mt_live_device.c"), "crc_codes")
    model = read(Path(__file__).with_name("crc_equivalence_model.c").resolve())
    (out / "check.c").write_text(model.replace("/* PREFIX_FUNCTIONS */",
        old_prefix.replace("crc_codes(", "oracle_crc_codes(") + new_prefix),
        encoding="utf-8", newline="\n")
    for name, source in (
        ("wire.c", "patched/v2/protocol/mt_wire.c"),
        ("oracle.c", "source/firmware/protocol/mt_wire.c"),
        ("mt_wire.h", "source/firmware/protocol/mt_wire.h"),
        ("mt_v2_crc32.h", "patched/v2/protocol/mt_v2_crc32.h"),
    ):
        (out / name).write_text(read(image / source), encoding="utf-8", newline="\n")
    for path, digest in inputs.items():
        if str(image) in path and path != str(receipt_path):
            if receipt["inputs_before"].get(path) != digest:
                raise ValueError("Source differs from image receipt: " + path)

    sys.path.insert(0, str(root / "host"))
    from motortester import stream_wire
    read(Path(stream_wire.__file__).resolve())
    traffic = args.traffic.resolve(strict=True)
    inputs[str(traffic)] = sha(traffic)
    raw = traffic.read_bytes()
    partial = [bytearray(), bytearray()]
    frames, samples = [], bytearray()
    position, chunks = 0, 0
    header = struct.Struct("<BdI")
    while position < len(raw):
        direction, _, size = header.unpack_from(raw, position)
        position += header.size
        if direction not in (0, 1) or not 0 < size <= len(raw) - position:
            raise ValueError("Invalid saved traffic chunk")
        for byte in raw[position:position + size]:
            partial[direction].append(byte)
            if len(partial[direction]) > stream_wire.MAX_ENCODED:
                raise ValueError("Oversized wire vector")
            if byte == 0:
                frame = bytes(partial[direction])
                partial[direction].clear()
                if len(frame) == 1:
                    continue
                decoded = stream_wire.decode_frame(frame, "device" if direction else "host")
                frames.append(frame)
                if direction and decoded.kind == stream_wire.Kind.DATA:
                    samples.extend(stream_wire.decode_payload(decoded).raw_samples)
        position += size
        chunks += 1
    if any(partial) or not frames or not samples:
        raise ValueError("Expected complete actual wire/raw vectors")
    (out / "actual-frames.bin").write_bytes(struct.pack("<I", len(frames)) + b"".join(
        struct.pack("<I", len(frame)) + frame for frame in frames))
    (out / "actual-codes.bin").write_bytes(
        struct.pack("<II", len(samples) // 2, zlib.crc32(samples)) + samples)
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
    flags = ["cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror"]
    names = ("mt_wire_crc32", "mt_wire_encode_revision", "mt_wire_decode_revision",
             "mt_wire_encode", "mt_wire_decode")
    run("compile-oracle", [zig, *flags, *("-D" + n + "=oracle_" + n for n in names),
                           "-c", "oracle.c", "-o", "oracle.o"])
    run("compile", [zig, *flags, "check.c", "wire.c", "oracle.o", "-o", "check.exe"])
    stdout = run("crc", [out / "check.exe"])
    if any(sha(Path(path)) != digest for path, digest in inputs.items()):
        raise ValueError("Input changed during check")
    result = {
        "status": "PASS", "scope": __doc__, "image": str(image),
        "firmware_build": receipt["config"]["firmware_build"],
        "image_bin_sha256": receipt["artifacts"]["MotortesterV2-stream-candidate.bin"],
        "inputs": inputs, "commands": commands, "compiler_version": version, "stdout": stdout,
        "actual_vectors": {"traffic_chunks": chunks, "wire_frames": len(frames),
                           "raw_codes": len(samples) // 2,
                           "raw_sha256": hashlib.sha256(samples).hexdigest(),
                           "raw_crc32": zlib.crc32(samples)},
        "generated": {path.name: sha(path) for path in out.iterdir()
                      if path.is_file() and path.suffix in (".c", ".h", ".o", ".exe", ".bin")},
        "not_verified": ["Physical throughput or timing", "USB/ADC scheduling margin",
                         "Physical sample losslessness", "Voltage calibration"],
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "stdout": stdout, "result": str(out / "result.json")}))


if __name__ == "__main__":
    main()
