"""Minimal publication checks, not a simulation/qualification of ignition use."""
import hashlib
import json
import math
from pathlib import Path
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
PDF=ROOT/'готовые документы/Ёмкостной датчик_сборка_P1.pdf'
OUT=ROOT/'docs/verification/pickup-guide-20261106'
Ct=10e-9
Cp=10e-9+100e-12
Rp=1/(1/10e6+1/1e6)
Rs=50.
# Source step 2 V -> Rs -> series Ct -> (Cp || Rp). No board/HV model.
a=Rs*Rp*Ct*Cp
b=Ct*(Rs+Rp)+Cp*Rp
d=math.sqrt(b*b-4*a)
slow=-2/(b+d) # Numerically stable small root.
fast=(-b-d)/(2*a)
tpeak=math.log(fast/slow)/(slow-fast)
A=2*Ct*Rp/(a*(slow-fast))
def v(t):return A*(math.exp(slow*t)-math.exp(fast*t))
calc={'scope':'Standalone low-voltage fixture only; no physical measurements',
 'Ct_F':Ct,'Cp_F':Cp,'Rp_ohm':Rp,'Rs_ohm':Rs,
 'peak_s':tpeak,'peak_V':v(tpeak),'V_2ms_after_peak':v(tpeak+.002),
 'equation':'H(s)=s*Ct*Rp/[1+s*(Ct*(Rs+Rp)+Cp*Rp)+s^2*Rs*Rp*Ct*Cp]'}
arch=json.loads((ROOT/'docs/design/pickup-r4-source/fixture_checks.json').read_text(encoding='utf-8'))
target=arch['nominal']['pickup_alone']['50ohm']
assert abs(calc['peak_V']-target['peak_V'])<1e-9
assert abs(calc['V_2ms_after_peak']-target['voltage_2ms_after_peak_V'])<1e-9
assert round(calc['peak_V'],3)==.995
assert round(calc['V_2ms_after_peak'],3)==.892
r=PdfReader(PDF);assert len(r.pages)==9
texts=[p.extract_text() for p in r.pages]
assert all(len(t)>500 for t in texts)
assert all('\ufffd' not in t and '\x00' not in t for t in texts)
links=[str(a.get_object()['/A']['/URI']) for a in r.pages[-1].get('/Annots',[]) if '/A' in a.get_object()]
assert len(links)==3
for n,t in enumerate(texts,1):assert f'{n} / 9' in t
result={'pdf':PDF.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(PDF.read_bytes()).hexdigest(),
 'page_count':len(texts),'text_chars':[len(t) for t in texts],'links':links,
 'standalone_fixture':calc,'limits':'Text/math checks do not replace PNG visual review or physical tests.'}
(OUT/'author-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
