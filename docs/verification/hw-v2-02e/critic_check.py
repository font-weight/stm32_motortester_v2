"""Independent targeted r3 checks; no import or regeneration of the author model.

KCL routines from the independent r2 critic are reused for unchanged topology.
New tolerance combinations use individual C1a/b; peak location uses a grid and
golden-section refinement, independent of the author's polynomial-root method.
This is arithmetic only, not a circuit measurement or a complete uncertainty model.
"""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'hardware/v2-input/p1-lv/calculations.json'
spec = importlib.util.spec_from_file_location('r2_critic',
    ROOT / 'docs/verification/hw-v2-02d/critic_check.py')
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)


def section(f, ra, rb, cf, cg):
    # Two KCL equations: X, Y; ideal output=Y. Solve determinant explicitly.
    s = 2j*math.pi*f
    a, b = 1/ra+1/rb+s*cf, -1/rb-s*cf
    c, d = -1/rb, 1/rb+s*cg
    return -(c/ra)/(a*d-b*c)


def response(f, values):
    r5,r6,c1a,c1b,c2,r7,r8,c3,c4,r9,c5 = values
    s = 2j*math.pi*f
    rth = 1/(1/1.02e6+1/240e3+1/330e3)
    return abs(section(f,r5,r6,c1a+c1b,c2)*section(f,r7,r8,c3,c4)/
        ((1+s*rth*20e-12)*(1+s*r9*c5)))


def cutoff(values):
    left, right = 100, 10000
    for _ in range(50):
        mid = (left+right)/2
        if response(mid,values)**2 > .5:
            left = mid
        else:
            right = mid
    return (left+right)/2


def peak(values):
    # All relevant resonance features are broad (section Q<1.38). Bracket
    # each local maximum on a 100-Hz grid, then refine; include DC explicitly.
    freqs = list(range(0,10001,100))
    mags = [response(f,values) for f in freqs]
    candidates = [(mags[0],0.0),(mags[-1],10000.0)]
    for n in range(1,len(freqs)-1):
        if mags[n]>=mags[n-1] and mags[n]>=mags[n+1]:
            left,right = freqs[n-1],freqs[n+1]
            ratio = (math.sqrt(5)-1)/2
            a,b = right-ratio*(right-left),left+ratio*(right-left)
            fa,fb = response(a,values),response(b,values)
            for _ in range(70):
                if fa < fb:
                    left,a,fa = a,b,fb
                    b = left+ratio*(right-left)
                    fb = response(b,values)
                else:
                    right,b,fb = b,a,fa
                    a = right-ratio*(right-left)
                    fa = response(a,values)
            f=(left+right)/2
            candidates.append((response(f,values),f))
    return max(candidates)


def main():
    data=json.loads(SOURCE.read_text(encoding='utf-8'))
    checks=[]
    def compare(name, actual, expected, tolerance=1e-10):
        difference=abs(actual-expected)
        checks.append(dict(name=name,actual=actual,expected=expected,
                           absolute_error=difference,tolerance=tolerance))
        assert difference<=tolerance, checks[-1]
    assert data['schema']=='HW-V2-02e/P1-LV-r3-ideal-linear-v3'
    fixed=(510e3,510e3,240e3,330e3)
    compare('nominal_zero',r2.sum_node(0,3.3),data['dc_nominal']['offset_v'])
    for p,q in zip(data['own_rail_dc_test']['points'],(0,.5,1)):
        compare(f'test_nominal_{q}',r2.test_source(q,3.3,fixed,33000,1000,10000),p['ch1_loaded_v'])
        values=[]
        for signs in itertools.product((-1,1),repeat=7):
            parts=tuple(r*(1+.01*s) for r,s in zip(fixed,signs))
            for supply in (3.2,3.4):
                values.append(r2.test_source(q,supply,parts,
                    33000*(1+.01*signs[4]),1000*(1+.01*signs[5]),
                    10000*(1+.20*signs[6])))
        compare(f'test_min_{q}',min(values),p['ch1_corner_min_max_v'][0])
        compare(f'test_max_{q}',max(values),p['ch1_corner_min_max_v'][1])
        compare(f'test_count_{q}',len(values),p['corners_count'],0)
    load=data['r12_rail_load']
    compare('R12_min_current',3.2/10100,load['current_min_max_a_at_3p2_3p4_v'][0])
    compare('R12_max_current',3.4/9900,load['current_min_max_a_at_3p2_3p4_v'][1])
    compare('R12_max_power',3.4**2/9900,load['maximum_power_w_at_3p4_v'])
    nominal=(4700,4700,10e-9,1.8e-9,10e-9,2000,2000,68e-9,10e-9,330,1e-9)
    tolerances=(.01,.01,.05,.05,.05,.01,.01,.05,.05,.01,.05)
    fdata=data['filter']
    compare('nominal_halfpower',cutoff(nominal),fdata['half_power_nominal_hz'],1e-7)
    gain,frequency=peak(nominal)
    compare('nominal_peak_db',20*math.log10(gain),fdata['peak_nominal']['db'],1e-10)
    compare('nominal_peak_frequency',frequency,fdata['peak_nominal']['frequency_hz'],.001)
    variants=[tuple(v*(1+t*s) for v,t,s in zip(nominal,tolerances,signs))
              for signs in itertools.product((-1,1),repeat=11)]
    compare('physical_corner_count',len(variants),fdata['corners_count'],0)
    cutoffs=[cutoff(v) for v in variants]
    for label,calculated,expected in zip(('min','max'),(min(cutoffs),max(cutoffs)),
            fdata['half_power_filter_only_corner_min_max_hz']):
        compare('halfpower_'+label,calculated,expected,1e-7)
    peaks=[peak(v) for v in variants]
    largest=max(peaks)
    compare('largest_peak_db',20*math.log10(largest[0]),fdata['largest_peak_among_corners']['db'],1e-10)
    compare('largest_peak_frequency',largest[1],fdata['largest_peak_among_corners']['frequency_hz'],.001)
    # The independent physical-node RK4 formulation was checked in r2.
    # Its nominal results are unchanged; r3 only adds a labelled illustration.
    assert data['step_at_largest_frequency_peak_corner']['not_worst_case_transient_bound'] is True
    result={'base_sha':'50dcb5f4e0ff38a93e1ef718efbfd2fbb8133725',
            'python':platform.python_version(),'platform':platform.platform(),
            'calculations_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'independence':'No import of author model. KCL helpers from r2 critic, numerical grid/golden peak search.',
            'limitations':'Only stated component corners; no physical stability, ADC, power, tolerance interior global bound or calibration.',
            'checks':checks,'result':'PASS_TARGETED_ARITHMETIC'}
    Path(__file__).with_name('critic-check.json').write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'result':result['result'],'checks':len(checks),
                      'halfpower':[min(cutoffs),max(cutoffs)],
                      'peak_db':20*math.log10(largest[0])},indent=2))


if __name__=='__main__':
    main()
