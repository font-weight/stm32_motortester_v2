"""Three focused negative checks of the V2 image analyzer; no target or COM use."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.flags.optimize:
        raise ValueError("Run python -I -B")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    image = args.image.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(root / "build") or output.exists() or output.is_relative_to(image):
        raise ValueError("Use a new build/ output outside the input image")
    output.mkdir(parents=True)
    path = root / "firmware/v2-stream/check_static.py"
    spec = importlib.util.spec_from_file_location("static_under_test", path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    rows = []
    def rejected(name, operation, message):
        try:
            operation()
        except ValueError as exc:
            if message not in str(exc):
                raise
            rows.append({"name": name, "status": "PASS", "rejection": str(exc)})
        else:
            raise ValueError("Control was not rejected: " + name)
    original = copy.deepcopy(checker.CALLBACKS)
    try:
        del checker.CALLBACKS["mt_live_device_step"]
        rejected("unresolved_indirect_call", lambda: checker.analyze(image), "Unresolved indirect call")
        checker.CALLBACKS = copy.deepcopy(original)
        checker.CALLBACKS["mt_live_device_step"].append("mt_live_device_step")
        rejected("recursive_callback_graph", lambda: checker.analyze(image), "Recursive stack graph")
    finally:
        checker.CALLBACKS = original
    # Preserve the original image. A changed, rehashed .su models an incorrect
    # compiler frame claim, so the independent instruction/SP walk must reject it.
    altered = output / "altered-frame"
    shutil.copytree(image, altered)
    su = altered / "objects/24-mt_live_device.su"
    lines = su.read_text("utf-8").splitlines()
    matches = [i for i, line in enumerate(lines) if ":mt_live_device_step\t" in line]
    if len(matches) != 1:
        raise ValueError("Unexpected stack-usage row")
    index = matches[0]
    name, size, kind = lines[index].split("\t")
    lines[index] = "\t".join((name, str(int(size) + 8), kind))
    su.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    receipt_path = altered / "receipt.json"
    receipt = json.loads(receipt_path.read_text("utf-8"))
    receipt["analysis_inputs"][su.relative_to(altered).as_posix()] = hashlib.sha256(su.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    rejected("frame_claim_vs_machine_code", lambda: checker.analyze(altered), "CFG/.su disagreement")
    result = {"status": "PASS", "checks": rows, "input_image": str(image),
              "analyzer_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "scope": "Static analyzer rejection controls; no firmware execution or timing evidence"}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
