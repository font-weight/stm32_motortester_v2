"""Read-only dimensions, copper widths, sides and physical wire courses.

Run with KiCad's Python. This measures the saved PCB, not the router proposal;
it does not establish analogue performance or fit of the user's real parts.
"""
from pathlib import Path
from collections import Counter
import hashlib, json, math
import pcbnew as p

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT/'hardware/v2-input/r53-compact-20261102/analog-input-r53.kicad_pcb'
OUT = ROOT/'build/analog-r53-compact/board-metrics.json'

def main():
    raw = BOARD.read_bytes()
    board = p.LoadBoard(str(BOARD))
    xy = lambda q: [p.ToMM(q.x), p.ToMM(q.y)]
    points = [xy(q) for d in board.GetDrawings() if d.GetLayer()==p.Edge_Cuts
              for q in [d.GetStart(),d.GetEnd()]]
    xs,ys=zip(*points)
    size=[max(xs)-min(xs),max(ys)-min(ys)]
    parts=[];wires=[];holes=Counter()
    for f in sorted(board.GetFootprints(),key=lambda f:f.GetReference()):
        pads=[]
        for pad in f.Pads():
            drill=p.ToMM(pad.GetDrillSize().x)
            if drill>0:holes[round(drill,3)]+=1
            pads.append({'number':pad.GetNumber(),'xy_mm':xy(pad.GetPosition()),
                         'net':pad.GetNetname(),'drill_mm':drill,'size_mm':xy(pad.GetSize())})
        row={'ref':f.GetReference(),'value':f.GetValue(),'xy_mm':xy(f.GetPosition()),
             'side':board.GetLayerName(f.GetLayer()),'pads':pads}
        parts.append(row)
        if row['ref'].startswith('W'):
            segments=[[xy(g.GetStart()),xy(g.GetEnd())] for g in f.GraphicalItems()
                      if isinstance(g,p.PCB_SHAPE) and g.GetShape()==p.SHAPE_T_SEGMENT
                      and g.GetLayer() in [p.F_Fab,p.B_Fab]]
            wires.append(dict(row,segments_mm=segments,
                course_length_mm=sum(math.dist(a,b) for a,b in segments),
                native_duplicate_pad_jumpers=f.GetDuplicatePadNumbersAreJumpers()))
    tracks=list(board.GetTracks())
    info={'board_sha256':hashlib.sha256(raw).hexdigest(),'size_mm':size,
          'area_mm2':math.prod(size),'previous_size_mm':[142,98],
          'area_reduction_factor':142*98/math.prod(size),
          'tracks':len(tracks),'widths_mm':dict(Counter(p.ToMM(t.GetWidth()) for t in tracks)),
          'track_layers':dict(Counter(board.GetLayerName(t.GetLayer()) for t in tracks)),
          'vias':sum(isinstance(t,p.PCB_VIA) for t in tracks),
          'zones':[{'net':z.GetNetname(),'layer':board.GetLayerName(z.GetLayer()),
                    'clearance_mm':p.ToMM(z.GetLocalClearance())} for z in board.Zones() if not z.GetIsRuleArea()],
          'holes_by_diameter_mm':dict(holes),'hole_count':sum(holes.values()),
          'parts':parts,'wires':wires,
          'scope':'Saved CAD geometry only; real component fit, LUT tolerance and analogue response remain unverified.'}
    assert BOARD.read_bytes()==raw
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:info[k] for k in ['size_mm','area_reduction_factor','tracks','widths_mm','track_layers','vias','hole_count']}))

if __name__=='__main__':main()
