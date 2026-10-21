"""Independent read-only checks for the P1-LV r2 calculation artifact.

Run from the repository root with Python >=3.10. Uses resistor/capacitor
nodal equations rather than importing the author's model. Writes only
critic-check.json beside this script. No instrument or device is accessed.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "hardware/v2-input/p1-lv/calculations.json"


def solve(matrix, rhs):
    """Small Gaussian elimination with pivoting for real or complex KCL."""
    a = [list(row) + [value] for row, value in zip(matrix, rhs)]
    for col in range(len(a)):
        p = max(range(col, len(a)), key=lambda n: abs(a[n][col]))
        a[col], a[p] = a[p], a[col]
        pivot = a[col][col]
        assert abs(pivot) > 1e-30
        a[col] = [x / pivot for x in a[col]]
        for row in range(len(a)):
            if row != col:
                factor = a[row][col]
                a[row] = [x - factor*y for x, y in zip(a[row], a[col])]
    return [row[-1] for row in a]


def sum_node(ch1, supply, parts=(510e3, 510e3, 240e3, 330e3)):
    r1, r2, ru, rd = parts
    # Include IN_MID explicitly rather than reducing the two input R first.
    return solve([[1/r1+1/r2, -1/r2],
                  [-1/r2, 1/r2+1/ru+1/rd]], [ch1/r1, supply/ru])[1]


def test_source(q, supply, parts, r10, r11, pot, meter=None):
    r1, r2, ru, rd = parts
    rs = r1+r2
    # SUM, CH1, WIPER. q=0 is a pinned wiper, not a grounded CH1.
    gm = 0 if meter is None else 1/meter
    if q == 0:
        return solve([[1/rs+1/ru+1/rd, -1/rs],
                      [-1/rs, 1/rs+1/r11+gm]], [supply/ru, 0])[1]
    bottom, top = q*pot, r10+(1-q)*pot
    return solve([[1/rs+1/ru+1/rd, -1/rs, 0],
                  [-1/rs, 1/rs+1/r11+gm, -1/r11],
                  [0, -1/r11, 1/r11+1/top+1/bottom]],
                 [supply/ru, 0, supply/top])[1]


def section_h(f, section):
    ra, rb, cf, cg = section
    s = 2j*math.pi*f
    # Unknown X/Y. Ideal follower output=Y; Cf from X to that output.
    return solve([[1/ra+1/rb+s*cf, -1/rb-s*cf],
                  [-1/rb, 1/rb+s*cg]], [1/ra, 0])[1]


def response(f, sections, rout=330, cout=1e-9):
    rth = 1/(1/1.02e6+1/240e3+1/330e3)
    s = 2j*math.pi*f
    return section_h(f, sections[0])*section_h(f, sections[1])/(
        (1+s*rth*20e-12)*(1+s*rout*cout))


def transient(start, end):
    """RK4 on physical node voltages (not output/derivative states).

    Independent KCL formulation: X is capacitor-Cf node, Y follower input.
    Includes the same explicitly hypothetical SUM capacitance and output RC.
    """
    initial = sum_node(start, 3.3)
    target = sum_node(end, 3.3)
    rth = 1/(1/1.02e6+1/240e3+1/330e3)
    z = [initial]*6  # BUF, X1, Y1, X2, Y2, ADC
    dt = 0.05e-6
    minimum = [initial]*4
    maximum = [initial]*4

    def derivative(v):
        b, x1, y1, x2, y2, adc = v
        dy1 = (x1-y1)/(4700*10e-9)
        dx1 = dy1-((x1-b)/4700+(x1-y1)/4700)/11.8e-9
        dy2 = (x2-y2)/(2000*10e-9)
        dx2 = dy2-((x2-y1)/2000+(x2-y2)/2000)/68e-9
        return [(target-b)/(rth*20e-12), dx1, dy1, dx2, dy2,
                (y2-adc)/(330*1e-9)]

    for _ in range(round(0.002/dt)):
        a = derivative(z)
        b = derivative([x+dt*y/2 for x,y in zip(z,a)])
        c = derivative([x+dt*y/2 for x,y in zip(z,b)])
        d = derivative([x+dt*y for x,y in zip(z,c)])
        z = [x+dt*(a0+2*b0+2*c0+d0)/6
             for x,a0,b0,c0,d0 in zip(z,a,b,c,d)]
        for n,value in enumerate((z[0],z[2],z[4],z[5])):
            minimum[n] = min(minimum[n], value)
            maximum[n] = max(maximum[n], value)
    return {"min_v": minimum, "max_v": maximum, "final_adc_v": z[5]}


def main():
    artifact = json.loads(DATA.read_text(encoding="utf-8"))
    assert artifact["dc_nominal"]["k_v_per_v"] < 0.12, "r2 artifact expected"
    parts = (510e3, 510e3, 240e3, 330e3)
    sections = ((4700,4700,11.8e-9,10e-9), (2000,2000,68e-9,10e-9))
    measured_errors = []

    def compare(label, actual, reference, tolerance=1e-11):
        error = abs(actual-reference)
        assert error <= tolerance, (label, actual, reference, error)
        measured_errors.append({"name": label, "absolute_error": error,
                                "limit": tolerance})

    zero = sum_node(0, 3.3)
    gain = sum_node(1, 3.3)-zero
    compare("gain", gain, artifact["dc_nominal"]["k_v_per_v"])
    compare("zero", zero, artifact["dc_nominal"]["offset_v"])
    dc_bounds = []
    for point in artifact["dc_points"]:
        values = [sum_node(point["ch1_v"], supply,
                          tuple(r*(1+sign*.01) for r,sign in zip(parts, signs)))
                  for supply in (3.2,3.4)
                  for signs in itertools.product((-1,1), repeat=4)]
        bounds = [min(values),max(values)]
        for n in range(2):
            compare(f"dc {point['ch1_v']} bound {n}", bounds[n],
                    point["adc_corner_min_max_v"][n])
        dc_bounds.append({"ch1_v":point["ch1_v"], "sum_corner_v":bounds})

    test_points = []
    for point in artifact["own_rail_dc_test"]["points"]:
        q = point["wiper_fraction_from_ground"]
        nominal = test_source(q,3.3,parts,33e3,1e3,10e3)
        with_meter = test_source(q,3.3,parts,33e3,1e3,10e3,10e6)
        values = [test_source(q,supply,
                      tuple(r*(1+.01*s) for r,s in zip(parts, signs)),
                      33e3*(1+.05*s10),1e3*(1+.05*s11),10e3*(1+.2*sp))
                  for supply,s10,s11,sp in itertools.product((3.2,3.4),(-1,1),(-1,1),(-1,1))
                  for signs in itertools.product((-1,1),repeat=4)]
        bounds = [min(values),max(values)]
        compare(f"test {q} nominal",nominal,point["ch1_loaded_v"])
        compare(f"test {q} meter",with_meter,point["with_hypothetical_10m_meter_ch1_v"])
        for n in range(2):
            compare(f"test {q} bound {n}",bounds[n],point["ch1_corner_min_max_v"][n])
        test_points.append({"q":q,"nominal_v":nominal,"bounds_v":bounds})

    # Changed frequency response, all 2^10 specified component corners at the
    # author's listed frequencies. Rth and SUM capacitance are held nominal.
    for point in artifact["filter"]["response"]:
        f = point["frequency_hz"]
        compare(f"frequency {f}",abs(response(f,sections)),point["gain"])
        gains = []
        for signs in itertools.product((-1,1),repeat=10):
            sec = [tuple(v*(1+(0.01 if j<2 else 0.02)*signs[4*i+j])
                         for j,v in enumerate(section)) for i,section in enumerate(sections)]
            gains.append(abs(response(f,sec,330*(1+.01*signs[8]),1e-9*(1+.02*signs[9]))))
        bounds = [20*math.log10(min(gains)),20*math.log10(max(gains))]
        for n in range(2):
            compare(f"frequency {f} bound {n}",bounds[n],
                    point["filter_only_corner_db_min_max"][n],1e-10)

    compare("half-power nominal",abs(response(artifact["filter"]["half_power_nominal_hz"],sections)),
            math.sqrt(.5))
    cutoff_bounds = artifact["filter"]["half_power_filter_only_corner_min_max_hz"]
    for side,f in enumerate(cutoff_bounds):
        gains = []
        for signs in itertools.product((-1,1),repeat=10):
            sec = [tuple(v*(1+(0.01 if j<2 else 0.02)*signs[4*i+j])
                         for j,v in enumerate(section)) for i,section in enumerate(sections)]
            gains.append(abs(response(f,sec,330*(1+.01*signs[8]),1e-9*(1+.02*signs[9]))))
        compare(f"half-power corner boundary {side}",
                min(gains) if side==0 else max(gains),math.sqrt(.5))

    # One largest listed positive transition checks the changed pole placement
    # and extrema; reversed transition follows linear-system symmetry.
    step = transient(-10,10)
    author_step = next(s for s in artifact["steps_nominal_ideal"] if s["start_ch1_v"] == -10)
    for n,name in enumerate(("BUF","SK1","SK2","ADC")):
        for side in ("min_v","max_v"):
            compare(f"step {name} {side}",step[side][n],author_step["nodes"][name][side],1e-9)
    compare("step final",step["final_adc_v"],author_step["final_output_v"],1e-9)

    selection = []
    for name,nominal,low,high,digit in (("R10",33000,32010,33990,10),
                                      ("R11",1000,970,1030,1),
                                      ("R12",10000,9700,10300,10)):
        true_bound = [low-(.005*low+3*digit),high+(.005*high+3*digit)]
        assert true_bound[0] >= .95*nominal and true_bound[1] <= 1.05*nominal
        selection.append({"ref":name,"display_ohm":[low,high],
                          "conditional_true_bound_ohm":true_bound,
                          "manufacturer_5pct_bound_ohm":[.95*nominal,1.05*nominal]})
    output = {
        "status":"PASS_INDEPENDENT_NUMERICAL_CHECKS_ONLY",
        "evidence_level":"CALCULATION_NOT_MEASURED",
        "author_calculations_sha256":hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "independent_method":"Gaussian KCL including IN_MID; complex SK KCL; physical node-state transient RK4",
        "dc_gain":gain,"dc_zero_v":zero,"dc_bounds":dc_bounds,
        "test_points":test_points,"transition_minus10_to10":step,
        "selection":selection,
        "comparisons":measured_errors,
        "limitations":["No hardware or device accessed", "No proof of RM102 actual accuracy or calibration",
                       "Only the specified ideal model and listed corners, not complete hardware uncertainty",
                       "Does not qualify ADC connection, ignition input or transient protection"]}
    path = Path(__file__).with_name("critic-check.json")
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":output["status"],"comparisons":len(measured_errors),
                      "dc_gain":gain,"dc_zero_v":zero,"selection":selection},ensure_ascii=False))


if __name__ == "__main__":
    main()
