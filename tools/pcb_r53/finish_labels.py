"""Assembly-only labels after compact routing freeze; no copper moves.

This mutates the final PCB's text only. Recheck DRC and regenerate print/evidence
after running it. References inside resistor bodies suit a separate LUT assembly
map: component values remain in the BOM, not crowded onto the copper artwork.
"""
from pathlib import Path
import pcbnew as p

ROOT=Path(__file__).resolve().parents[2]
BOARD=ROOT/'hardware/v2-input/r53-compact-20261102/analog-input-r53.kicad_pcb'
mm=p.FromMM
def v(x,y):return p.VECTOR2I(mm(x),mm(y))

def main():
    b=p.LoadBoard(str(BOARD))
    # Reuse standalone texts. Removing SWIG-owned PCB_TEXT in KiCad 10 can
    # invalidate live wrapper pointers; editing these objects avoids that.
    text_pool=[d for d in b.GetDrawings() if isinstance(d,p.PCB_TEXT)]
    for item in text_pool:item.SetText('')
    text_pool=iter(text_pool)
    fps={f.GetReference():f for f in b.GetFootprints()}
    def xy(ref):
        q=fps[ref].GetPosition();return p.ToMM(q.x),p.ToMM(q.y)
    def caption(text,x,y,size=1.0,layer=p.F_SilkS):
        t=next(text_pool,None)
        if t is None:
            t=p.PCB_TEXT(b);b.Add(t)
        t.SetText(text);t.SetPosition(v(x,y));t.SetLayer(layer)
        t.SetTextSize(v(size,size));t.SetTextThickness(mm(.15))
    for ref,f in fps.items():
        r=f.Reference();r.SetTextSize(v(1,1));r.SetTextThickness(mm(.15));r.SetTextAngle(p.EDA_ANGLE(0,p.DEGREES_T))
        x,y=xy(ref)
        if ref.startswith('R') or ref=='U1':r.SetPosition(v(x,y))
        elif ref in ['C1','C2','C4']:r.SetPosition(v(x,y+2.7))
        elif ref=='C3':r.SetPosition(v(x,y))
        elif ref=='C9':r.SetPosition(v(x,y-4.1))
        elif ref=='C6':r.SetPosition(v(x+4,y))
        elif ref=='C7':r.SetPosition(v(x+4.0,y))
        elif ref=='C8':r.SetPosition(v(x,y-2.4))
        elif ref=='C10':
            r.SetPosition(v(x-1.8,y));r.SetTextAngle(p.EDA_ANGLE(90,p.DEGREES_T))
        elif ref=='C11':r.SetPosition(v(x,y+2.6))
        elif ref=='S1':r.SetVisible(False);r.SetPosition(v(x,y+9));caption('S1',x,y+9.0)
        elif ref=='S2':r.SetPosition(v(x,y-3.4))
        elif ref=='JP1':r.SetPosition(v(x-3.6,y))
        elif ref=='J1':r.SetPosition(v(x,y));r.SetTextSize(v(.9,.9))
        elif ref=='J2':r.SetPosition(v(x,y-4))
        elif ref=='J3':r.SetPosition(v(x,y+2.6))
        if ref.startswith('W'):
            # Actual wire side is retained. Put its reference halfway along
            # its documented course; final visual review may adjust crowded text.
            pads=list(f.Pads());a,bp=[q.GetPosition() for q in pads]
            r.SetPosition(v((p.ToMM(a.x)+p.ToMM(bp.x))/2+1.5,(p.ToMM(a.y)+p.ToMM(bp.y))/2))
            if f.GetLayer()==p.B_Cu:
                # Assembly annotation on the bottom inspection map; the LUT
                # master contains B.Cu only, with no printed legend on copper.
                r.SetLayer(p.B_Fab)
            if ref=='W1':r.SetPosition(v(65.5,45.5))
            if ref=='W2':r.SetPosition(v(40.5,25))
        if ref in ['S1','S2','JP1','J1','J2','J3']:
            for pad in f.Pads():
                pos=pad.GetPosition();px,py=p.ToMM(pos.x),p.ToMM(pos.y)
                # Fab-layer numbering remains visible on the paper map and
                # cannot create silkscreen/pad clearance violations.
                caption(pad.GetNumber(),px,py-2.0,.8,p.F_Fab)
    x,y=xy('S2');caption('1-2 WIDE / 2-3 SENS',x,y+4.2,.75,p.F_Fab)
    x,y=xy('U1');caption('1',x-7.62,y-9.0,.85,p.F_Fab)
    p.SaveBoard(str(BOARD),b)

if __name__=='__main__':main()
