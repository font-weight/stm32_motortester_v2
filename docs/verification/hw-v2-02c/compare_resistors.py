"""Compare P1 resistor proposals; standard library, no device or legacy build.

All resistances are ohms and capacitances farads. The eight tuples in each
case are series constituents of logical R1..R8. R9..R12 stay single resistors.
This is ideal arithmetic, not a new schematic or a measured input rating.
"""
from itertools import product
import json
import math
from pathlib import Path

V_A = 3.3
CAPS = ((11.8e-9, 10e-9), (68e-9, 10e-9))
OLD = [(499000,), (499000,), (249000,), (332000,),
       (4870,), (4870,), (2030,), (2030,)]
SINGLE = [(510000,), (510000,), (240000,), (330000,),
          (4700,), (4700,), (2000,), (2000,)]
COMPOSITE = [(470000, 30000), (470000, 30000), (240000, 9100),
             (330000, 2000), (4700, 180), (4700, 180),
             (2000, 30), (2000, 30)]


def dc(r):
    """Ideal low-impedance CH1 source; U_ADC=k*U_CH1+bias on DC."""
    rs = r[0] + r[1]
    g = 1 / rs + 1 / r[2] + 1 / r[3]
    return 1 / (rs * g), V_A / (r[2] * g)


def section(r1, r2, cf, cg):
    a2, a1 = r1 * r2 * cf * cg, (r1 + r2) * cg
    return {"f0_hz": 1 / (2 * math.pi * math.sqrt(a2)),
            "q": math.sqrt(a2) / a1}


def magnitude(f, r):
    """Two ideal Sallen-Key sections only, normalized to DC gain=1.

    Excludes SUM parasitics, output RC, real op-amp limits and ADC loading.
    f0 of one section is not the cascade's -3 dB frequency.
    """
    s, h = 2j * math.pi * f, 1.0
    for i, (cf, cg) in zip((4, 6), CAPS):
        r1, r2 = r[i:i+2]
        h /= 1 + s * (r1 + r2) * cg + s * s * r1 * r2 * cf * cg
    return abs(h)


def compare(parts, tolerance):
    r = [sum(p) for p in parts]
    k, bias = dc(r)
    old_k, old_bias = dc([sum(p) for p in OLD])
    # Series bounds are exact: all constituents at the same relative limit.
    # Therefore 16 equivalent divider corners cover ZERO at fixed V_A.
    zeros = [dc([v * (1 + tolerance * sign)
                 for v, sign in zip(r[:4], signs)])[1]
             for signs in product((-1, 1), repeat=4)]
    lo, hi = 100.0, 10000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if magnitude(mid, r) > 1 / math.sqrt(2):
            lo = mid
        else:
            hi = mid
    return {
        "series_constituents_R1_to_R8_ohm": parts,
        "equivalent_R1_to_R8_ohm": r,
        "physical_fixed_resistor_count_including_R9_to_R12": sum(map(len, parts)) + 4,
        "RV1_count_separate": 1,
        "R1_to_R8_relative_tolerance": tolerance,
        "k_v_per_v": k, "zero_adc_v": bias,
        "gain_change_from_original_percent": 100 * (k / old_k - 1),
        "zero_change_from_original_mv": 1000 * (bias - old_bias),
        "zero_adc_resistor_corner_bounds_v": [min(zeros), max(zeros)],
        "filter_sections": [section(*r[i:i+2], *caps)
                            for i, caps in zip((4, 6), CAPS)],
        "ideal_two_section_cascade_minus3db_hz": (lo + hi) / 2,
    }


def build():
    return {
        "scope": "HW-V2-02c arithmetic comparison, no hardware acceptance",
        "assumptions": {
            "V_A_v": V_A, "ideal_low_impedance_source": True,
            "ideal_opamps": True, "capacitors_nominal_f": CAPS,
            "filter_tolerance_sweep_performed": False,
            "dc_corners": "resistor bounds at exactly 3.300 V; no supply/temperature/noise errors",
            "excluded": ["parasitics", "output RC", "ADC load", "transient rail checks",
                         "physical measurements", "hardware connection approval"],
        },
        "cases": {
            "original_reference": compare(OLD, 0.001),
            "A_single_E24": compare(SINGLE, 0.01),
            "B_all_composite": compare(COMPOSITE, 0.01),
            "hybrid_composite_divider": compare(COMPOSITE[:4] + SINGLE[4:], 0.01),
        },
        "alternative_for_each_R1_or_R2": {
            "series_ohm": [470000, 30000], "parallel_ohm": [1000000, 1000000],
            "series_equivalent_ohm": 470000 + 30000,
            "parallel_equivalent_ohm": 1 / (1 / 1000000 + 1 / 1000000),
            "bounds_both_topologies_at_1pct_ohm": [500000 * .99, 500000 * 1.01],
            "guaranteed_tolerance_improved": False,
        },
    }


if __name__ == "__main__":
    output = Path(__file__).with_name("comparison.json")
    output.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Wrote {output.name}; ideal arithmetic only.")
