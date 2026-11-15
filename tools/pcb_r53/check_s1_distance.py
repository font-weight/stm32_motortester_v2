"""CAD-only S1 copper separation; run after ground_analysis --final-check.

Source constraint: external switch/harness >=25 mm from U1, IN_A and
feedback. This checks the pads, not the user's real external wire dressing.
"""
from pathlib import Path
import json,sys
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'build/analog-r52-pcb/deps'))
sys.path.insert(0,str(root/'build/analog-r53-compact/deps'))
from shapely.geometry import Polygon,LineString,box
from shapely.ops import unary_union,nearest_points
g=json.loads((root/'build/analog-r53-compact/ground-analysis/geometry.json').read_text())
def shape(rows):return unary_union([Polygon(r['outer'],r['holes']) for r in rows])
s1=unary_union([shape(p['copper']) for p in g['pads'] if p['ref']=='S1' and p['pin']!='6'])
def netshape(nets):
    return unary_union([shape(p['copper']) for p in g['pads'] if p['net'] in nets]
        +[LineString([t['a'],t['b']]).buffer(t['width']/2,quad_segs=32)
          for t in g['tracks'] if t['net'] in nets])
u=next(f for f in g['footprints'] if f['ref']=='U1')['position']
targets={'IN_A':netshape(['Net-(U1A-+)']),'feedback_A':netshape(['Net-(U1A--)']),
         'feedback_B':netshape(['Net-(U1B--)']),'feedback_C':netshape(['Net-(U1C--)']),
         'INV_D':netshape(['Net-(S2-COM)']),'U1_reserved_body':box(u[0]-9,u[1]-9,u[0]+9,u[1]+9)}
r={'board_sha256':g['board_sha256'],'minimum_required_mm':25,
   'scope':'Connected S1 pad copper boundaries to full feedback/IN_A copper and reserved 18x18 U1 body. Real harness, switch and solder shape unverified; wires must leave to the left.',
   'distances':{}}
for name,t in targets.items():
    a,b=nearest_points(s1,t)
    r['distances'][name]={'mm':s1.distance(t),'nearest_s1_xy':list(a.coords)[0],
                           'nearest_target_xy':list(b.coords)[0]}
r['all_cad_distances_at_least_25mm']=all(d['mm']>=25 for d in r['distances'].values())
(root/'build/analog-r53-compact/s1-distance.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps(r,indent=2))
assert r['all_cad_distances_at_least_25mm']
