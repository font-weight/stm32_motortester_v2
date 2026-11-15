"""R3 matched passive pickup loading; illustrative capacitance, no kV calibration."""
from pathlib import Path
import json,numpy as np
from scipy.signal import residue
P=Path(__file__).parent
r=json.loads((P.parent/'calculations/results.json').read_text());v=r['nominal_SI']
Rin=v['R1']+v['R2']+v['R17']+1/(1/v['R3']+1/v['R4']);C9=v['C9']
g=1/(v['R10']+v['R11'])+1/10e6
cs=1e-12;ck=10e-9;cc=100e-12;ct=cs+ck+cc;tau=Rin*C9
# Exact two-pole charge transfer with the board AC coupling capacitor included.
den=[ct*tau,ct+g*tau+C9,g]
a,p,k=residue([cs*tau,0],den);kinf=cs/ct
droop=100*(1-np.sum(a*np.exp(p*.002)).real/kinf)
result={'scope':__doc__,'assumptions':'Cs=1pF illustrative only, Csh10nF,Ccable100pF,Rbleed10M; real Cs unknown. Board LP filtering omitted in the slow2ms droop approximation.','R3_AC_input_ohm':r['input_loading']['AC_midband_ohm'],'R3_ACS_gain':r['nominal']['AC_SENSITIVE']['gain_V_per_V'],'R3_ACS_input_mV_per_code12':r['nominal']['AC_SENSITIVE']['nominal_input_V_per_12bit_LSB']*1e3,'R3_ACS_input_mV_per_saved10_step':r['nominal']['AC_SENSITIVE']['nominal_input_V_per_retained10bit_step']*1e3,'droop2ms_pct':droop,'disconnected_tau_s':10e6*(ck+cc),'isolated_step_charge_ratio_UNCALIBRATED':kinf,'no_HV_rating':True}
(P/'matched_math.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(result)
