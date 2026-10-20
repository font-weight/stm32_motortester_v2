"""HW-V2-02/P1: arithmetic and ideal linear model, never a hardware test.

Run with Python >=3.10, standard library only:
    python hardware/v2-input/p1-lv/model.py
This writes calculations.json alongside this file. No connection to the MCU.

All voltages refer to AGND. The source is ideal and low impedance. Neither
the hypothetical pickup source nor this model calibrates ignition voltage.
The step solver integrates ideal linear transfer functions with RK4. It has
no op-amp macro-model, clamps, ADC sample-and-hold or parasitic SPICE network.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path


R_INPUT_PARTS = (499_000.0, 499_000.0)
R_UP, R_DOWN = 249_000.0, 332_000.0
VDDA = 3.3  # Assumed; the actual board reference has not been measured.
SECTIONS = (
    (4_870.0, 4_870.0, 11.8e-9, 10e-9),
    (2_030.0, 2_030.0, 68e-9, 10e-9),
)
R_OUT, C_OUT = 330.0, 1e-9
CP_NOMINAL = 20e-12  # Hypothetical TOTAL capacitance SUM -> AC ground.
R_TOL, C_TOL = 0.001, 0.02
R_OUT_TOL = 0.01  # R9 is 1%; divider and Sallen-Key resistors are 0.1%.


def divider(r1=R_INPUT_PARTS[0], r2=R_INPUT_PARTS[1],
            rup=R_UP, rdown=R_DOWN, vdda=VDDA):
    """SUM = k*U_CH1 + offset; loading includes the powered bias network.

    Rin seen at CH1 is a Thevenin resistance to the nonzero Vopen, not a
    resistor to AGND. Rth is SUM's resistance with all voltage sources zero.
    """
    rin = r1 + r2
    rbias = 1 / (1 / rup + 1 / rdown)
    rth = 1 / (1 / rin + 1 / rup + 1 / rdown)
    k = rth / rin
    offset = vdda * rth / rup
    vopen = vdda * rdown / (rup + rdown)
    return {
        "k_v_per_v": k,
        "offset_v": offset,
        "r_sum_thevenin_ohm": rth,
        "r_input_thevenin_ohm": rin + rbias,
        "v_open_bnc_v": vopen,
        "current_out_of_bnc_into_grounded_source_a": vopen / (rin + rbias),
        "a_v_per_code_assuming_12bit_4096": vdda / (4096 * k),
        "b_v_assuming_12bit_4096": -offset / k,
    }


def section_parameters(section):
    r1, r2, cf, cg = section
    a2 = r1 * r2 * cf * cg
    a1 = (r1 + r2) * cg
    return 1 / math.sqrt(a2), math.sqrt(a2) / a1


def section_h(frequency, section):
    r1, r2, cf, cg = section
    s = 2j * math.pi * frequency
    return 1 / (1 + s * (r1 + r2) * cg + s * s * r1 * r2 * cf * cg)


def response(frequency, sections=SECTIONS, cp=CP_NOMINAL, rth=None,
             r_out=R_OUT, c_out=C_OUT):
    """Transfer normalized to its DC value; excludes divider's DC gain."""
    if rth is None:
        rth = divider()["r_sum_thevenin_ohm"]
    s = 2j * math.pi * frequency
    return (section_h(frequency, sections[0]) * section_h(frequency, sections[1])
            / ((1 + s * rth * cp) * (1 + s * r_out * c_out)))


def step_trace(start_v, end_v, dt_s, duration_s=0.002, cp=CP_NOMINAL):
    """Integrate six states: BUF, SK1/dSK1dt, SK2/dSK2dt and ADC.

    BUF includes SUM's hypothetical RC pole; the buffer itself is ideal.
    Each SK ODE is y''=w0^2*(input-y)-w0/Q*y'. Every op-amp output
    is reported so an ideal overshoot cannot hide behind the final RC.
    Extremes are not clipped; rail excursion invalidates linear operation.
    """
    dc = divider()
    initial = dc["offset_v"] + dc["k_v_per_v"] * start_v
    target = dc["offset_v"] + dc["k_v_per_v"] * end_v
    tau_in, tau_out = dc["r_sum_thevenin_ohm"] * cp, R_OUT * C_OUT
    w1, q1 = section_parameters(SECTIONS[0])
    w2, q2 = section_parameters(SECTIONS[1])
    state = (initial, initial, 0.0, initial, 0.0, initial)

    def derivative(z):
        b, y1, v1, y2, v2, adc = z
        return ((target - b) / tau_in,
                v1, w1 * w1 * (b - y1) - w1 / q1 * v1,
                v2, w2 * w2 * (y1 - y2) - w2 / q2 * v2,
                (y2 - adc) / tau_out)

    extrema = [[initial, initial] for _ in range(4)]
    # Keep about 1000 plotted samples; extrema use EVERY integration step.
    stride = max(1, round(2e-6 / dt_s))
    trace = [[0.0, initial, initial, initial, initial]]
    count = round(duration_s / dt_s)
    for n in range(count):
        k1 = derivative(state)
        k2 = derivative(tuple(z + dt_s * d / 2 for z, d in zip(state, k1)))
        k3 = derivative(tuple(z + dt_s * d / 2 for z, d in zip(state, k2)))
        k4 = derivative(tuple(z + dt_s * d for z, d in zip(state, k3)))
        state = tuple(z + dt_s * (a + 2*b + 2*c + d) / 6
                      for z, a, b, c, d in zip(state, k1, k2, k3, k4))
        outputs = (state[0], state[1], state[3], state[5])
        for mm, output in zip(extrema, outputs):
            mm[0], mm[1] = min(mm[0], output), max(mm[1], output)
        if (n + 1) % stride == 0 or n + 1 == count:
            trace.append([(n + 1) * dt_s, *outputs])
    return {
        "start_ch1_v": start_v, "end_ch1_v": end_v,
        "dt_s": dt_s, "duration_s": duration_s,
        "ideal_dc_target_v": target,
        "final_output_v": state[5],
        "final_dc_residual_v": state[5] - target,
        "nodes": {
            name: {"min_v": mm[0], "max_v": mm[1],
                   "headroom_to_ideal_0_v": mm[0],
                   "headroom_to_ideal_vdda_v": VDDA - mm[1]}
            for name, mm in zip(("BUF", "SK1", "SK2", "ADC"), extrema)
        },
        "trace_columns": ["t_s", "BUF_v", "SK1_v", "SK2_v", "ADC_v"],
        "trace": trace,
    }


def dc_test_source(fraction, vdda=VDDA, r10=33_000.0, r11=1000.0,
                   pot=10_000.0, p1_resistors=(*R_INPUT_PARTS, R_UP, R_DOWN),
                   meter_ohm=None):
    """Own-rail test source with a continuous pot, loaded by powered P1.

    fraction is the wiper fraction of total pot resistance from AGND.
    R10 feeds the TOP of the whole pot; R11 is after the wiper. The meter
    (if present) shunts CH1 to AGND. At fraction=0, R11 still separates
    CH1 from ground: exact zero uses a separate direct grounding jumper.
    """
    p1 = divider(*p1_resistors, vdda=vdda)
    bottom = fraction * pot
    top = r10 + (1 - fraction) * pot
    v_source = vdda * bottom / (top + bottom)
    r_source = r11 + bottom * top / (bottom + top)
    r_p1, v_p1 = p1["r_input_thevenin_ohm"], p1["v_open_bnc_v"]
    conductance = 1 / r_source + 1 / r_p1
    if meter_ohm is not None:
        conductance += 1 / meter_ohm
    ch1 = (v_source / r_source + v_p1 / r_p1) / conductance
    return {
        "wiper_fraction_from_ground": fraction,
        "source_unloaded_v": v_source, "source_thevenin_ohm": r_source,
        "ch1_loaded_v": ch1,
        "adc_ideal_dc_v": p1["offset_v"] + p1["k_v_per_v"] * ch1,
    }


def build():
    dc = divider()
    rth = dc["r_sum_thevenin_ohm"]
    result = {
        "schema": "HW-V2-02/P1-ideal-linear-v1",
        "evidence_level": "CALCULATION_ONLY_NOT_MEASURED",
        "not_an_allowed_input_rating": True,
        "assumptions": {
            "vdda_v": VDDA, "vdda_corner_v": [3.2, 3.4],
            "divider_and_sallen_key_resistor_relative_tolerance": R_TOL,
            "output_resistor_relative_tolerance": R_OUT_TOL,
            "filter_capacitor_relative_tolerance": C_TOL,
            "sum_parasitic_capacitance_hypothetical_f": [10e-12, 20e-12, 30e-12],
            "adc_bits": 12, "adc_code_denominator": 4096,
            "first_proposed_bench_source_low_impedance_v": [0.0, 1.0],
        },
        "limitations": [
            "Not SPICE and not a measured circuit: ideal op amps and stiff VDDA.",
            "No op-amp offset/bias/noise/bandwidth, output swing or saturation recovery.",
            "No protection, ESD, unpowered/back-power states or ignition transients.",
            "No ADC sampling-switch/current model; output RC is continuous-time only.",
            "Hypothetical SUM capacitance lumps layout/op-amp effects; no measured C.",
            "Corners are component bounds, not a complete uncertainty/accuracy budget.",
            "Resistor voltage/temperature coefficients and self-heating are not included.",
            "Pickup is normalized small-signal Cs/Cg/R sensitivity; not ignition kV.",
            "BNC is DC biased when open; its Thevenin resistance is not grounded.",
            "Rail margins below are only against ideal 0..VDDA, not op-amp linear limits.",
        ],
        "dc_nominal": dc,
        "dc_points": [],
    }
    r_corners = list(itertools.product((-1, 1), repeat=4))
    for vin in (-10.0, -1.0, 0.0, 1.0, 10.0):
        adc = dc["offset_v"] + dc["k_v_per_v"] * vin
        corners = []
        for vdda in (3.2, 3.4):
            for signs in r_corners:
                r = [value * (1 + R_TOL * sign)
                     for value, sign in zip((*R_INPUT_PARTS, R_UP, R_DOWN), signs)]
                corner = divider(*r, vdda=vdda)
                v = corner["offset_v"] + corner["k_v_per_v"] * vin
                corners.append((v, v / vdda * 4096))
        result["dc_points"].append({
            "ch1_v": vin, "adc_nominal_v": adc,
            "ideal_fractional_code": adc / VDDA * 4096,
            "adc_corner_min_max_v": [min(x[0] for x in corners), max(x[0] for x in corners)],
            "fractional_code_corner_min_max": [min(x[1] for x in corners), max(x[1] for x in corners)],
            "corners_count": len(corners),
        })
    result["sum_pole"] = [
        {"capacitance_f": c, "rth_ohm": rth, "f_hz": 1 / (2 * math.pi * rth * c)}
        for c in (10e-12, 20e-12, 30e-12)
    ]
    result["sensitivity_to_sum_leakage"] = [
        {"injected_sum_current_a": i,
         "sum_offset_v": i * rth,
         "input_referred_offset_v": i * rth / dc["k_v_per_v"]}
        for i in (10e-12, 1e-9, 5e-9, 100e-9)
    ]
    dc_test = {
        "topology": "VDDA--33k--pot10k_top; pot_bottom=AGND; wiper--1k--TEST",
        "zero": "CH1 directly jumpered to AGND; pot bottom through 1k is not zero",
        "jp_adc_open": True,
        "meter_input_hypothesis_ohm": 10e6,
        "meter_actual_spec": "TBD, 10Mohm is an example, not verified RM102 property",
        "corners": "R10/R11 ±1%; pot total ±20%; P1 R ±0.1%; VDDA 3.2/3.4",
        "points": [],
    }
    for fraction in (0.0, 0.5, 1.0):
        nominal = dc_test_source(fraction)
        with_meter = dc_test_source(fraction, meter_ohm=10e6)
        corners = []
        for vdda, s10, s11, spot in itertools.product((3.2, 3.4), (-1, 1), (-1, 1), (-1, 1)):
            for signs in r_corners:
                resistors = tuple(value*(1+R_TOL*sign)
                                  for value, sign in zip((*R_INPUT_PARTS, R_UP, R_DOWN), signs))
                corners.append(dc_test_source(fraction, vdda=vdda,
                    r10=33_000*(1+0.01*s10), r11=1000*(1+0.01*s11),
                    pot=10_000*(1+0.2*spot), p1_resistors=resistors)["ch1_loaded_v"])
        dc_test["points"].append({
            **nominal, "with_hypothetical_10m_meter_ch1_v": with_meter["ch1_loaded_v"],
            "rise_after_removing_10m_meter_v": nominal["ch1_loaded_v"]-with_meter["ch1_loaded_v"],
            "ch1_corner_min_max_v": [min(corners), max(corners)],
            "corners_count": len(corners),
        })
    # Passive positive-resistance source; max voltage is attained at top
    # wiper. This bound includes loaded P1, not just the unloaded pot ratio.
    upper = max(p["ch1_corner_min_max_v"][1] for p in dc_test["points"])
    assert upper < 1.0, upper
    dc_test["maximum_across_listed_corners_v"] = upper
    dc_test["less_than_1v_in_listed_linear_corners"] = True
    dc_test["does_not_cover"] = "wiring error, missing ground, pot failure, wrong component, external source"
    result["own_rail_dc_test"] = dc_test
    # P1 small-signal loading alone. At DC it has Vopen, so this model does NOT
    # imply that the biased P1 is a suitable replacement for the grounded P0.
    result["pickup_sensitivity"] = {
        "meaning": "Normalized incremental response after a hypothetical source step",
        "formula": "H(s)=s*R*Cs/(1+s*R*(Cs+Cg)); droop=1-exp(-t/tau)",
        "p1_bias_excluded_from_incremental_model": True,
        "p1_replacement_for_p0": False,
        "duration_s": 0.002, "cases": [],
    }
    for cs, cg, r in itertools.product(
            (0.2e-12, 1e-12, 5e-12), (50e-12, 200e-12, 500e-12),
            (dc["r_input_thevenin_ohm"], 10e6, 100e6, 200e6)):
        tau = r * (cs + cg)
        result["pickup_sensitivity"]["cases"].append({
            "cs_f": cs, "cg_f": cg, "load_ohm": r,
            "initial_gain_v_per_v": cs / (cs + cg), "tau_s": tau,
            "remaining_after_2ms_fraction": math.exp(-0.002 / tau),
            "droop_after_2ms_fraction": 1 - math.exp(-0.002 / tau),
        })
    frequencies = (0, 100, 1000, 1500, 2000, 3000, 10000, 25000, 47000, 50000)
    # Independent resistor/capacitor corners of both sections (2^8), plus
    # each output-RC corner (2^2). SUM's Rth/C are held nominal in this table.
    filter_corners = []
    for signs in itertools.product((-1, 1), repeat=8):
        sections = []
        for index, section in enumerate(SECTIONS):
            sections.append(tuple(
                value * (1 + (R_TOL if j < 2 else C_TOL) * signs[4*index+j])
                for j, value in enumerate(section)))
        filter_corners.append(sections)
    result["filter"] = {
        "topology": "low-Q unity Sallen-Key first, high-Q second, 330ohm/1nF last",
        "section_components": [
            {"r1_ohm": a, "r2_ohm": b, "cf_f": c, "cg_f": d,
             "f0_hz": section_parameters(s)[0] / (2 * math.pi),
             "Q": section_parameters(s)[1]}
            for s in SECTIONS for a, b, c, d in (s,)
        ],
        "output_rc_pole_hz": 1 / (2 * math.pi * R_OUT * C_OUT),
        "corners_scope": "2^10 filter R/C corners; SK resistors ±0.1%, R9 ±1%, C ±2%; nominal SUM capacitance/Rth; ideal op amps",
        "normalized_to_dc": True, "response": [],
    }
    for f in frequencies:
        mag = abs(response(f))
        corners = [
            abs(response(f, sections=section, r_out=R_OUT*(1+R_OUT_TOL*rs),
                         c_out=C_OUT*(1+C_TOL*cs)))
            for section in filter_corners for rs, cs in itertools.product((-1, 1), repeat=2)
        ]
        result["filter"]["response"].append({
            "frequency_hz": f, "gain": mag, "db": 20 * math.log10(mag),
            "filter_only_corner_db_min_max": [20 * math.log10(min(corners)),
                                             20 * math.log10(max(corners))],
        })
    steps, refinements = [], []
    for start, end in ((-1.0, 1.0), (1.0, -1.0), (-10.0, 10.0), (10.0, -10.0)):
        coarse = step_trace(start, end, 0.1e-6)
        fine = step_trace(start, end, 0.05e-6)
        # These are two numerical resolutions of the same ideal model,
        # never two independent physical measurements.
        error = max(
            abs(coarse["nodes"][name][kind] - fine["nodes"][name][kind])
            for name in coarse["nodes"] for kind in ("min_v", "max_v"))
        matched_trace_error = max(
            abs(x-y)
            for a, b in zip(coarse["trace"], fine["trace"])
            for x, y in zip(a[1:], b[1:]))
        refinements.append({
            "start_ch1_v": start, "end_ch1_v": end,
            "coarse_dt_s": coarse["dt_s"], "fine_dt_s": fine["dt_s"],
            "max_extrema_change_v": error,
            "max_matched_trace_change_v": matched_trace_error,
            "final_dc_residual_v": fine["final_dc_residual_v"],
        })
        steps.append(fine)
    result["steps_nominal_ideal"] = steps
    residual = max(abs(s["final_dc_residual_v"]) for s in steps)
    refinement = max(r["max_matched_trace_change_v"] for r in refinements)
    # Analytic unity DC of filter cascade vs integrated settled result; and
    # convergence under halving dt. Tolerances assess numerical implementation.
    assert abs(response(0).real - 1) < 1e-14
    assert residual < 1e-5, residual
    assert refinement < 1e-5, refinement
    result["numerical_checks"] = {
        "analytic_normalized_dc": response(0).real,
        "dc_convergence_limit_v": 1e-5,
        "max_dc_residual_v": residual,
        "dt_refinement_limit_v": 1e-5,
        "max_trace_change_v": refinement,
        "step_dt_refinements": refinements,
        "result": "PASS_NUMERICAL_SELF_CHECKS_ONLY",
    }
    return result


if __name__ == "__main__":
    result = build()
    output = Path(__file__).with_name("calculations.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Written {output.name}: arithmetic + ideal linear model, NOT measured.")
    print(json.dumps({"dc_nominal": result["dc_nominal"],
                      "numerical_checks": result["numerical_checks"]}, indent=2))
