"""One-time local fill relief relocation; no tracks or footprints moved.

The saved R5.3 generator contains the same final polygon. After applying,
refill/save zones and repeat DRC and the ground connectivity analysis.
"""
from pathlib import Path
import pcbnew as p
root=Path(__file__).resolve().parents[2]
path=root/'hardware/v2-input/r53-compact-20261102/analog-input-r53.kicad_pcb'
b=p.LoadBoard(str(path))
zones=[z for z in b.Zones() if z.GetIsRuleArea()]
assert len(zones)==1
z=zones[0];poly=z.Outline();poly.RemoveAllContours();poly.NewOutline()
for x,y in [(46.5,26),(52,26),(52,31),(46.5,31)]:poly.Append(p.FromMM(x),p.FromMM(y))
p.SaveBoard(str(path),b)
