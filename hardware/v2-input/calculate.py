"""HW-V2-01 P0: nominal circuit calculations, not a hardware simulation/test.

Voltages are relative to AGND. The pickup model describes a hypothetical
capacitive source; its gain is never a calibration from CH1 to ignition kV.
Only the Python standard library is required. Output goes to stdout.
"""
import itertools
import json
import math


def transfer(resistors, vdda, gain, mid_ratio=0.5):
    """Buffered CH1 -> passive summer -> gain about Vmid; ideal DC op amps."""
    rin, rbias, rground = resistors
    conductance = 1 / rin + 1 / rbias + 1 / rground
    k = (1 / rin) / conductance
    beta = (1 / rbias) / conductance
    return gain * k, vdda * (gain * beta + (1 - gain) * mid_ratio)


def filter_section(frequency, resistance, c_feedback, c_ground):
    """Unity-gain Sallen-Key: C_feedback joins first R junction to output."""
    s = 2j * math.pi * frequency
    return 1 / (
        1 + s * 2 * resistance * c_ground
        + s * s * resistance * resistance * c_feedback * c_ground
    )


def main():
    vdda = 3.3  # Assumed, not measured.
    resistors = (100e3, 24.9e3, 33.2e3)
    result = {
        "status": "calculation_only_not_measured",
        "model": "HW-V2-01 P0; ideal op amps, linear unclipped operation",
        "vdda_assumed_v": vdda,
        "ranges": [],
    }
    for name, half_range, gain, rg in [
        ("R10", 10.0, 1.0, None),
        ("R2", 2.0, 5.0, 47.5e3),
        ("R0_5", 0.5, 20.0, 10e3),
    ]:
        g, bias = transfer(resistors, vdda, gain)
        endpoints = []
        # DC resistor-only corners: ±0.1%; excludes Vref, leakage, op amp,
        # temperature, capacitor tolerances, noise and sensor loading.
        for signs in itertools.product((-1, 1), repeat=7):
            factors = [1 + 0.001 * sign for sign in signs]
            r = [value * factor for value, factor in zip(resistors, factors)]
            mid_ratio = factors[4] / (factors[3] + factors[4])
            actual_gain = 1 if rg is None else 1 + 190e3 * factors[5] / (rg * factors[6])
            gc, bc = transfer(r, vdda, actual_gain, mid_ratio)
            endpoints.extend((bc - gc * half_range, bc + gc * half_range))
        result["ranges"].append({
            "id": name, "proposed_ch1_half_range_v": half_range,
            "gain_v_per_v": g, "adc_bias_v": bias,
            "adc_endpoint_v": [bias - g * half_range, bias + g * half_range],
            "nominal_a_v_per_code": vdda / (4096 * g),
            "nominal_b_v": -bias / g,
            "resistor_only_endpoint_corner_v": [min(endpoints), max(endpoints)],
        })

    # Current injection from a capacitive pickup, with ideal equipotential input.
    cs, cg, plateau_s = 1e-12, 200e-12, 2e-3
    result["illustrative_pickup"] = {
        "cs_f": cs, "cg_including_cable_input_f": cg,
        "plateau_s": plateau_s, "high_frequency_gain": cs / (cs + cg),
        "loads": [
            {"r_ohm": r, "tau_s": r * (cs + cg),
             "droop_fraction": 1 - math.exp(-plateau_s / (r * (cs + cg))),
             "offset_at_12pa_v": 12e-12 * r}
            for r in (10e6, 100e6, 200e6, 1e9)
        ],
        "r_for_5_percent_droop_ohm":
            -plateau_s / ((cs + cg) * math.log(0.95)),
        "100m_parallel_10m_probe_ohm": 1 / (1 / 100e6 + 1 / 10e6),
    }
    rs, input_cap = 102e3, 15e-12
    result["input_series_pole"] = {
        "rs_ohm": rs, "cap_budget_f_not_measured": input_cap,
        "fc_hz": 1 / (2 * math.pi * rs * input_cap),
    }

    sections = [(4.87e3, 11.8e-9, 10e-9), (2.03e3, 68e-9, 10e-9)]
    result["anti_alias_filter"] = {
        "topology": "two unity-gain Sallen-Key sections, low Q first",
        "sections": [
            {"r1_r2_ohm": r, "c_feedback_f": cf, "c_ground_f": cg,
             "f0_hz": 1 / (2 * math.pi * r * math.sqrt(cf * cg)),
             "q": math.sqrt(cf / cg) / 2}
            for r, cf, cg in sections
        ],
        "response": [],
    }
    for f in (100, 1000, 1500, 2000, 3000, 10000, 25000, 47000, 50000):
        h = math.prod(abs(filter_section(f, *section)) for section in sections)
        result["anti_alias_filter"]["response"].append(
            {"frequency_hz": f, "gain": h, "db": 20 * math.log10(h)})

    r_iso, c_ext, r_adc, c_adc = 330.0, 1e-9, 1000.0, 8e-12
    sample_s = 71.5 / 12e6
    # First-order charge-sharing estimate; not a transistor-level ADC model.
    initial_lsb = 4096 * c_adc / (c_ext + c_adc)
    result["adc"] = {
        "sample_time_s": sample_s, "conversion_total_s": (71.5 + 12.5) / 12e6,
        "period_s": 1 / 50e3, "output_rc_pole_hz": 1 / (2 * math.pi * r_iso * c_ext),
        "resistive_quarter_lsb_settle_s": (r_iso + r_adc) * c_adc * math.log(2**14),
        "initial_charge_sharing_lsb": initial_lsb,
        "approx_residual_lsb":
            initial_lsb * math.exp(-sample_s / (r_iso * (c_ext + c_adc))),
    }
    # An analytical overload case for a powered bench module, NOT input rating.
    fault, clamp_assumption, feed, rail, shunt = 24.0, 11.5, 10e3, 15.0, 10.0
    fault_current = (fault - clamp_assumption) / rs
    result["illustrative_powered_overload"] = {
        "not_an_allowed_input_rating": True, "source_v": fault,
        "assumed_clamp_v": clamp_assumption, "series_current_a": fault_current,
        "series_resistors_total_w": fault_current**2 * rs,
        "shunt_total_current_a": (rail - shunt) / feed + fault_current,
        "shunt_power_w": shunt * ((rail - shunt) / feed + fault_current),
        "does_not_cover": "unpowered/sequence/ESD/ignition energy/diode transient",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
