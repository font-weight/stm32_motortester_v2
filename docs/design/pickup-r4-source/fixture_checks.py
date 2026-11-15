"""Adapted from unchanged P1 fixture_checks.py, commit47c22d67993e6609bbfb1b793b41b441fc4e397c.
R3 input divider substituted; polynomial algebra rechecked.
PICKUP-FIXTURE-R3. Low-voltage electronic fixture, not real pickup/HV qualification.
Measured generator full step is0 to2 V. Known injection capacitor10nF.
Reports early CH1 peak and voltage2ms after that peak; finite source resistance means
CH1 is zero at the mathematical initial instant, unlike the idealzero-R charge step.
Scope resistance ±1% and extra probe capacitance0..30pF are explicit assumptions,
not specifications asserted for an unidentified oscilloscope or probe.
"""
from pathlib import Path
from itertools import product
import numpy as np,json
from numpy.polynomial import Polynomial as Poly
from scipy.signal import residue
from scipy.optimize import brentq
P=Path(__file__).parent;s=Poly([0,1.]);one=Poly([1.]);RP=1/(1/75000+1/82000);RIN=1030000+RP

def model(mode,ci=10e-9,ck=10e-9,rb=10e6,rin=RIN,rret=14.7e6,c9=1e-6,rscope=None,cc=100e-12,rs=50):
 if rscope is None:rscope=1e6 if mode=='pickup_alone' else 10e6
 c0=ck+cc;g=1/rb+1/rscope
 if mode=='with_R3':
  g+=1/rret;a=one+s*rin*c9;n=s*ci*a;d=n+(one+s*rs*ci)*((s*c0+g)*a+s*c9)
 else:n=s*ci;d=n+(one+s*rs*ci)*(s*c0+g)
 # H(s)/s is the unit-step transfer.
 r,p,k=residue(n.coef[1:][::-1],d.coef[::-1])
 def f(t):return float(2*np.real(np.sum(r*np.exp(p*t))))
 def df(t):return float(2*np.real(np.sum(r*p*np.exp(p*t))))
 tp=0 if rs==0 else brentq(df,0,1e-3,xtol=1e-15)
 peak=f(tp);after=f(tp+.002)
 return {'peak_V':peak,'peak_time_us':tp*1e6,'voltage_2ms_after_peak_V':after,'droop2ms_percent':100*(1-after/peak),'V_at2ms_after_generator_edge':f(.002)}
res={'revision':'PICKUP-FIXTURE-R3','scope':__doc__,'nominal_source_full_step_V':2,'nominal':{},'corners':{}}
for mode in ['pickup_alone','with_R3']:
 res['nominal'][mode]={str(rs)+'ohm':model(mode,rs=rs) for rs in [0,50,1000,1050]}
 cases=[]
 for signs in product([-1,1],repeat=(8 if mode=='with_R3' else 5)):
  ci=10e-9*(1+.05*signs[0]);ck=10e-9*(1+.05*signs[1]);rb=10e6*(1+.01*signs[2]);rscope=(1e6 if mode=='pickup_alone' else 10e6)*(1+.01*signs[3]);cc=100e-12+(0 if signs[4]<0 else 30e-12)
  rin=RIN*(1+.01*signs[5]) if mode=='with_R3' else RIN;rret=14.7e6*(1+.01*signs[6]) if mode=='with_R3' else 14.7e6;c9=1e-6*(1+.05*signs[7]) if mode=='with_R3' else 1e-6
  for rs in [0,50,1050]:
   v=model(mode,ci,ck,rb,rin,rret,c9,rscope,cc,rs);v.update({'signs':signs,'total_source_R_ohm':rs,'total_cable_and_probe_C_pF':cc*1e12});cases.append(v)
 res['corners'][mode]={'case_count':len(cases),'scope':'Endpoint exploration withCtest/Ck/C9±5%, applicableR±1%, modeled100pFcableplus0..30pFprobe, totalRs0/50/1050ohm. Not unknown-instrument tolerance guarantee.','peak_min_case':min(cases,key=lambda x:x['peak_V']),'peak_max_case':max(cases,key=lambda x:x['peak_V']),'droop_min_case':min(cases,key=lambda x:x['droop2ms_percent']),'droop_max_case':max(cases,key=lambda x:x['droop2ms_percent']),'peak_time_max_us':max(x['peak_time_us'] for x in cases),'voltage2ms_min_V':min(x['voltage_2ms_after_peak_V'] for x in cases),'voltage2ms_max_V':max(x['voltage_2ms_after_peak_V'] for x in cases)}
(P/'fixture_checks.json').write_text(json.dumps(res,indent=2)+'\n');print(json.dumps(res,indent=2))
