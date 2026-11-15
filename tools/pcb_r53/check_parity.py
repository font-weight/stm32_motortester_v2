"""Read-only R5.1 -> R5.3 schematic/PCB electrical parity check.

Run with the installed KiCad Python. Only parity.json is written permanently;
the freshly exported netlist is private temporary data. No board is saved.
"""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import pcbnew

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "docs/design/analog-r5-1/kicad/analog-input-r5.net.xml"
BASE = ROOT / "hardware/v2-input/r53-compact-20261102/analog-input-r53"
SCH = BASE.with_suffix(".kicad_sch")
PCB = BASE.with_suffix(".kicad_pcb")
CLI = Path("D:/Programs/bin/kicad-cli.exe")
WORK = ROOT / "build/analog-r53-compact"
REPORT = WORK / "parity.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_netlist(path):
    root = ET.parse(path).getroot()
    components = {c.get("ref"): c for c in root.findall("./components/comp")}
    pins = {}
    duplicates = []
    for net in root.findall("./nets/net"):
        for node in net.findall("node"):
            key = (node.get("ref"), node.get("pin"))
            if key in pins:
                duplicates.append(list(key))
            pins[key] = net.get("name")
    return components, pins, duplicates


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    paths = [OLD, SCH, PCB]
    before = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    with tempfile.TemporaryDirectory(prefix="motortester-r52-parity-") as temp:
        exported = Path(temp) / "current.xml"
        command = [str(CLI), "sch", "export", "netlist", "--format", "kicadxml",
                   "--output", str(exported), str(SCH)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("KiCad export failed: " + result.stderr + result.stdout)
        old, old_pins, old_duplicates = read_netlist(OLD)
        new, new_pins, new_duplicates = read_netlist(exported)
        exported_sha = digest(exported)
    errors = []
    if len(old) != 35:
        errors.append({"type": "unexpected_source_count", "actual": len(old)})
    if set(old) != set(new):
        errors.append({"type": "schematic_reference_set", "missing": sorted(set(old) - set(new)),
                       "added": sorted(set(new) - set(old))})
    for ref in sorted(set(old) & set(new)):
        if old[ref].findtext("value") != new[ref].findtext("value"):
            errors.append({"type": "schematic_value", "ref": ref,
                           "expected": old[ref].findtext("value"),
                           "actual": new[ref].findtext("value")})
    if old_duplicates or new_duplicates:
        errors.append({"type": "duplicate_netlist_pins", "old": old_duplicates, "new": new_duplicates})
    for key in sorted(set(old_pins) | set(new_pins)):
        if old_pins.get(key) != new_pins.get(key):
            errors.append({"type": "schematic_pin_net", "ref_pin": list(key),
                           "expected": old_pins.get(key), "actual": new_pins.get(key)})

    board = pcbnew.LoadBoard(str(PCB))
    footprints = defaultdict(list)
    for footprint in board.GetFootprints():
        footprints[footprint.GetReference()].append(footprint)
    extras = []
    for ref, fps in footprints.items():
        if ref not in old:
            allowed = re.fullmatch(r"(?:H|W)\d+", ref) is not None
            extras.append({"ref": ref, "count": len(fps), "allowed_board_only_reference": allowed})
            if not allowed:
                errors.append({"type": "unexpected_board_extra", "ref": ref})
    root_uuid = re.search(r'\(uuid\s+"([^\"]+)"\)', SCH.read_text(encoding="utf-8")).group(1)
    path_errors = []
    path_records = []
    pads_checked = 0
    for ref in sorted(old):
        fps = footprints.get(ref, [])
        if len(fps) != 1:
            errors.append({"type": "board_reference_count", "ref": ref, "actual": len(fps)})
            continue
        fp = fps[0]
        if fp.GetValue() != old[ref].findtext("value"):
            errors.append({"type": "board_value", "ref": ref, "actual": fp.GetValue(),
                           "expected": old[ref].findtext("value")})
        expected_numbers = {pin for r, pin in old_pins if r == ref}
        counts = Counter(p.GetNumber() for p in fp.Pads())
        if set(counts) != expected_numbers or any(n != 1 for n in counts.values()):
            errors.append({"type": "board_pad_numbers", "ref": ref,
                           "expected": sorted(expected_numbers), "actual_counts": dict(counts)})
        for pad in fp.Pads():
            key = (ref, pad.GetNumber())
            pads_checked += 1
            if pad.GetNetname() != old_pins.get(key):
                errors.append({"type": "board_pin_net", "ref_pin": list(key),
                               "expected": old_pins.get(key), "actual": pad.GetNetname()})
        stamps = new[ref].findtext("tstamps", "").split()
        sheet_path = new[ref].find("sheetpath").get("tstamps", "/")
        # KiCad PCB association contains the schematic root and symbol UUID.
        # Exported XML's root sheetpath may be '/' rather than spelling out root UUID.
        parts = [part for part in sheet_path.split("/") if part]
        if not parts or parts[0] != root_uuid:
            parts.insert(0, root_uuid)
        accepted = ["/" + "/".join(parts + [stamp]) for stamp in stamps]
        actual = fp.GetPath().AsString()
        record = {"ref": ref, "actual": actual, "accepted": accepted,
                  "exported_sheetpath": sheet_path, "matches_root_and_symbol": actual in accepted}
        path_records.append(record)
        if actual not in accepted:
            path_errors.append(record)
    after = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    changed = [p for p in before if before[p] != after[p]]
    if changed:
        errors.append({"type": "inputs_changed_during_check", "paths": changed})
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "logical net labels/pad assignments and schematic association only; does not prove routed copper continuity or DRC clearance",
        "input_sha256": before,
        "exported_netlist_sha256": exported_sha,
        "export_cli_stdout": result.stdout.strip(),
        "source_component_count": len(old), "new_schematic_component_count": len(new),
        "source_pin_count": len(old_pins), "board_original_pad_count_checked": pads_checked,
        "board_only_extras": extras,
        "new_schematic_root_uuid": root_uuid,
        "schematic_and_board_electrical_errors": errors,
        "schematic_and_board_electrical_parity_pass": not errors,
        "pcb_schematic_path_records": path_records,
        "pcb_schematic_path_errors": path_errors,
        "pcb_schematic_paths_pass": not path_errors,
        "all_checks_pass": not errors and not path_errors,
        "all_inputs_unchanged_during_check": not changed,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["source_component_count", "source_pin_count",
          "board_original_pad_count_checked", "schematic_and_board_electrical_parity_pass",
          "pcb_schematic_paths_pass", "all_checks_pass", "all_inputs_unchanged_during_check"]}))
    print("Electrical errors:", len(errors), "path errors:", len(path_errors))


if __name__ == "__main__":
    main()
