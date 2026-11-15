"""Independent R5.1 netlist and scalar frequency audit; standard library only.

This preserves the calculations used for independent_analog_audit.json.
No archive Python module is executed, and no CAD, firmware or host file is
modified. The schematic is parsed only to compare component values; topology
is compared using its supplied XML netlist. Physical validation is out of scope.
"""
from pathlib import Path
import ast
import cmath
import json
import math
import re
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1] / "design" / "analog-r5-1"

xml = ET.parse(ROOT / "kicad/analog-input-r5.net.xml").getroot()
actual_nodes = {
    item.attrib["name"]: {
        f"{node.attrib['ref']}.{node.attrib['pin']}" for node in item.findall("node")
    }
    for item in xml.findall("nets/net")
}
baseline = json.loads((ROOT / "calculations/baseline-r2-netlist.json").read_text())
matched = {
    name: next(
        (actual_name for actual_name, pins in actual_nodes.items() if pins == set(expected)),
        None,
    )
    for name, expected in baseline["nodes"].items()
}
assert all(matched.values()) and len(actual_nodes) == len(matched)

values = {
    item.attrib["ref"]: item.findtext("value")
    for item in xml.findall("components/comp")
}
numeric = {}
for reference, value in values.items():
    if reference[0] in "RC":
        match = re.match(r"([0-9.]+)([pnumkM]?)", value)
        numeric[reference] = float(match[1]) * {
            "p": 1e-12, "n": 1e-9, "u": 1e-6,
            "m": 1e-3, "k": 1e3, "M": 1e6,
        }.get(match[2], 1.0)

# Read the literal only. Importing/executing the supplied model is unnecessary.
tree = ast.parse((ROOT / "calculations/model_r4.py").read_text())
nominal = next(
    ast.literal_eval(item.value)
    for item in tree.body
    if isinstance(item, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "NOMINAL" for t in item.targets)
)
assert set(numeric) == set(nominal)
assert all(math.isclose(numeric[key], nominal[key], rel_tol=1e-14) for key in numeric)

r = numeric | {"C10": 96e-12, "C11": 104e-12}
rb = 1 / (1 / r["R3"] + 1 / r["R4"])
rref = 1 / (1 / r["R15"] + 1 / r["R16"])
rseries = r["R1"] + r["R2"]
gdc = rb / (rseries + rb)
gac = rb / (rseries + r["R17"] + rb)
kd = 1 + r["R14"] / rref
offset_dc = 3.3 * (1 / (1 / rseries + 1 / r["R3"] + 1 / r["R4"])) / r["R3"]
offset_ac = 3.3 * r["R4"] / (r["R3"] + r["R4"])


def response(frequency_hz, mode):
    """CH1-to-ADC response of the reduced circuit, ideal opamps, SI units.

    SUM has the model's assumed 20 pF shunt. The measured-part assignments
    C10=96/C11=104 pF are reported values, not independent metrology here.
    """
    s = 2j * math.pi * frequency_hz
    ztop = rseries + (
        r["R17"] + 1 / (s * r["C9"]) if mode.startswith("AC") else 0
    )
    yload = 1 / rb + s * 20e-12 + 1 / (r["R18"] + 1 / (s * r["C11"]))
    transfer = (1 / (1 + ztop * yload)) / (1 + s * r["R18"] * r["C11"])
    if mode.endswith("SENSITIVE"):
        transfer *= 1 + (r["R14"] / (1 + s * r["R14"] * r["C10"])) / rref
    for a1, a2, cf, cg in [
        (r["R5"], r["R6"], r["C1"] + r["C8"], r["C2"]),
        (r["R7"], r["R8"], r["C3"], r["C4"]),
    ]:
        transfer /= 1 + s * cg * (a1 + a2) + s * s * a1 * a2 * cf * cg
    return transfer / (1 + s * r["R9"] * r["C5"])


def cutoff(mode, gain):
    # Bracket is the upper edge of this circuit; no SciPy dependency needed.
    low, high = 1000.0, 100000.0
    for _ in range(80):
        middle = (low + high) / 2
        if abs(response(middle, mode)) / gain > 2 ** -0.5:
            low = middle
        else:
            high = middle
    return (low + high) / 2


result = {
    "scope": "Independent netlist and analytical check only; no physical/capture/manufacture claim",
    "node_sets_matched": len(matched),
    "model_values_match_actual_netlist_nominals": True,
    "model_baseline_values_are_not_used": True,
    "resistor_reference_ohm": rref,
    "sensitive_gain_stage": kd,
    "parasitic_SUM_AGND_F": 20e-12,
    "actual_values": {"C10_F": r["C10"], "C11_F": r["C11"]},
    "modes": {},
}
for mode, gain, zero in [
    ("DC_WIDE", gdc, offset_dc),
    ("AC_WIDE", gac, offset_ac),
    ("AC_SENSITIVE", gac * kd, offset_ac),
]:
    result["modes"][mode] = {
        "gain_CH1_to_ADC": gain,
        "nominal_offset_at3p3_V": zero,
        "upper_cutoff_Hz": cutoff(mode, gain),
        "amplitude_at1kHz_rel_passband": abs(response(1000, mode)) / gain,
        "phase_at1kHz_deg": math.degrees(cmath.phase(response(1000, mode))),
        "ideal_code_step_ADC12_4096_VCH1": 3.3 / 4096 / gain,
    }
result["ac_lowfreq_pole_Hz_ideal_noHF_C"] = 1 / (
    2 * math.pi * r["C9"] * (rseries + r["R17"] + rb)
)
result["old_handoff_cutoff_Hz"] = 17840
result["stale_baseline_component_values"] = {
    key: {"baseline": baseline["values"][key], "actual": values[key]}
    for key in numeric
    if baseline["values"].get(key) != values[key]
}

# Cross-check the supplied XML's component values against the actual schematic.
tokens = re.findall(
    r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+',
    (ROOT / "kicad/analog-input-r5.kicad_sch").read_text(encoding="utf-8"),
)
stack = []
schematic = None
for token in tokens:
    if token == "(":
        node = []
        if stack:
            stack[-1].append(node)
        stack.append(node)
    elif token == ")":
        node = stack.pop()
        if not stack:
            schematic = node
    else:
        stack[-1].append(json.loads(token) if token.startswith('"') else token)
schematic_values = {}
for child in schematic:
    if isinstance(child, list) and child and child[0] == "symbol":
        properties = {
            item[1]: item[2]
            for item in child
            if isinstance(item, list) and item and item[0] == "property"
        }
        if "Reference" in properties and "Value" in properties:
            schematic_values[properties["Reference"]] = properties["Value"]
assert all(schematic_values[key] == value for key, value in values.items())
result["schematic_components_match_xml_values"] = len(values)

# Historical execution note, retained from the already produced result.
result["scipy_attempt"] = (
    "First arithmetic attempt failed before any calculation: ModuleNotFoundError scipy. "
    "Repeated with standard-library bisection only."
)
(OUT / "independent_analog_audit.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))
