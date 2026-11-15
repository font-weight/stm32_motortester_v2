"""Fresh R5.2 single-copper layout. Run with KiCad 10 bundled Python.

Electrical nets and values are read from the immutable R5.1 XML; no old PCB
placement or track is imported. Dimensions here are millimetres, top view.
"""
from pathlib import Path
import json, math, sys, zipfile, xml.etree.ElementTree as ET
import pcbnew as p

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'hardware/v2-input/r52-lut-20261102'
WORK=ROOT/'build/analog-r52-pcb'
DATA=Path(__file__).resolve().parent/'data'
WORK.mkdir(parents=True,exist_ok=True)
SRC=ROOT/'docs/design/analog-r5-1/kicad'
SOURCE_ARCHIVE=ROOT/'docs/design/analog-r5-1/Analog_LUT_R5_1_2026-10-29_REVIEW.zip'
ARCHIVE_KICAD='Analog_LUT_R5_1_2026-10-29/kicad'
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'LUT.pretty').mkdir(exist_ok=True)
X=ET.parse(SRC/'analog-input-r5.net.xml').getroot()
components={c.attrib['ref']:c for c in X.findall('./components/comp')}
netnodes={n.attrib['name']:[(q.attrib['ref'],q.attrib['pin']) for q in n.findall('node')] for n in X.findall('./nets/net')}
pin_net={t:n for n,ns in netnodes.items() for t in ns}
aliases=['AGND','X1','X2','ADC_DRV','AC_SER','ADC_TARGET','R_SER','BLEED_MID','SUM','AC_NODE','CORE_IN','CH1','INV_D','BIAS_D','DRIVE','IN_A','BUF','Y1','LP1','Y2','LP2','V_A','NC']
alias={a:n for a,n in zip(aliases,netnodes)}
board=p.BOARD()
mm=p.FromMM
v=lambda x,y:p.VECTOR2I(mm(x),mm(y))
ns={}
for i,name in enumerate(netnodes,1):
    ns[name]=p.NETINFO_ITEM(board,name,i); board.Add(ns[name])
ds=board.GetDesignSettings()
ds.m_MinClearance=mm(.75);ds.m_TrackMinWidth=mm(1.0)
ds.m_CopperEdgeClearance=mm(1.0);ds.m_HoleClearance=mm(.35)

def line(owner,a,b,layer,width=.15):
    q=p.PCB_SHAPE() if owner is board else p.PCB_SHAPE(owner)
    q.SetShape(p.SHAPE_T_SEGMENT);q.SetStart(v(*a));q.SetEnd(v(*b))
    q.SetLayer(layer);q.SetWidth(mm(width));owner.Add(q)
def rect(owner,x0,y0,x1,y1,layer,width=.15):
    for a,b in [((x0,y0),(x1,y0)),((x1,y0),(x1,y1)),((x1,y1),(x0,y1)),((x0,y1),(x0,y0))]:line(owner,a,b,layer,width)
def pad(fp,num,x,y,w,h,drill=.8):
    q=p.PAD(fp);q.SetNumber(str(num));q.SetPosition(v(x,y))
    q.SetSize(v(w,h));q.SetShape(p.PAD_SHAPE_CIRCLE if w==h else p.PAD_SHAPE_OVAL)
    q.SetAttribute(p.PAD_ATTRIB_PTH);q.SetDrillSize(v(drill,drill))
    layers=p.LSET.AllCuMask();layers.AddLayer(p.B_Mask)
    q.SetLayerSet(layers);fp.Add(q);return q

def makefp(ref):
    fp=p.FOOTPRINT(board);fp.SetReference(ref);fp.SetValue(components[ref].findtext('value'))
    fp.SetAttributes(p.FP_THROUGH_HOLE);fp.SetLayer(p.F_Cu)
    if ref.startswith('R'):
        name='R_025W_P10.16_LUT';body=(6.5,2.5);pitch=10.16;ps=(2.6,2.6);court=(13.8,4.2);drill=.8
    elif ref in ['C1','C2','C4']:
        name='Film_K73_P4_LUT';body=(11,7);pitch=4;ps=(2.6,2.6);court=(12.2,8.2);drill=.9
    elif ref=='C3':
        name='Film_P6.5_LUT';body=(13,10);pitch=6.5;ps=(2.6,2.6);court=(14.2,11.2);drill=.9
    elif ref=='C9':
        name='MKP_P5_7.2x11_LUT';body=(7.2,11);pitch=5;ps=(2.6,2.6);court=(8.4,12.2);drill=.8
    elif ref=='C5':
        name='C5_0805_LUT';body=(2,1.25);court=(3.8,2.8);fp.SetAttributes(p.FP_SMD)
        for n,x in [(1,-1),(2,1)]:
            q=p.PAD(fp);q.SetNumber(str(n));q.SetAttribute(p.PAD_ATTRIB_SMD)
            q.SetPosition(v(x,0));q.SetSize(v(1.2,1.6));q.SetShape(p.PAD_SHAPE_RECT)
            ls=p.LSET();ls.AddLayer(p.F_Cu);ls.AddLayer(p.F_Mask);ls.AddLayer(p.F_Paste);q.SetLayerSet(ls);fp.Add(q)
    elif ref.startswith('C'):
        pitch=2.5 if ref=='C8' else 2.54
        name='Radial_P2.50_LUT' if ref=='C8' else 'Radial_P2.54_LUT'
        body=(4,2.6);ps=(1.7,2.6);court=(5.2,3.8);drill=.8
    elif ref=='U1':
        name='SOIC14_Adapter_18x18_Rows15.24';body=(18,18);court=(19.2,19.2)
        for i in range(7):
            pad(fp,i+1,-7.62,-7.62+2.54*i,2.6,1.7,1.0)
            pad(fp,14-i,7.62,-7.62+2.54*i,2.6,1.7,1.0)
        line(fp,(-2,-9),(2,-9),p.F_SilkS,.4)
    elif ref in ['S2','JP1']:
        count=3 if ref=='S2' else 2;name=f'Shunt_1x{count}_P2.54_LUT'
        body=(2.54*count,3);court=(2.54*count+2,8)
        for i in range(count):pad(fp,i+1,(i-(count-1)/2)*2.54,0,1.7,3,1)
    elif ref=='S1':
        name='DC_AC_Wire_2x3_P5.08';body=(14,9);court=(16,11)
        for i in range(6):pad(fp,i+1,((i%3)-1)*5.08,(-2.54 if i<3 else 2.54),2.8,2.8,1.1)
    else:
        name='Wire_P5.08_LUT';body=(8,4);pitch=5.08;ps=(3.0,3.0);court=(10,7);drill=1.1
    if ref not in ['U1','S1','S2','JP1','C5']:
        pad(fp,1,-pitch/2,0,*ps,drill);pad(fp,2,pitch/2,0,*ps,drill)
    rect(fp,-body[0]/2,-body[1]/2,body[0]/2,body[1]/2,p.F_Fab,.15)
    rect(fp,-court[0]/2,-court[1]/2,court[0]/2,court[1]/2,p.F_CrtYd,.05)
    fp.SetFPID(p.LIB_ID('LUT',name))
    fp.Reference().SetPosition(v(0,-court[1]/2-1.2));fp.Reference().SetLayer(p.F_SilkS)
    fp.Reference().SetTextSize(v(1.2,1.2));fp.Reference().SetTextThickness(mm(.2))
    fp.Value().SetVisible(False)
    for q in fp.Pads():q.SetNet(ns[pin_net[(ref,q.GetNumber())]])
    p.PCB_IO_KICAD_SEXPR().FootprintSave(str(OUT/'LUT.pretty'),fp)
    fp.GetField('Datasheet').SetText(components[ref].findtext('datasheet') or '')
    fp.GetField('Datasheet').SetVisible(False)
    path=p.KIID_PATH();path.push_back(p.KIID('f1c772b0-891d-5755-a79a-3c4c6f206837'));path.push_back(p.KIID(components[ref].findtext('tstamps').split()[0]));fp.SetPath(path)
    return fp

# New placement, not read from the prior PCB. Rotation follows KiCad degrees.
positions={
'U1':(90,52,0),'J1':(18,31,90),'S1':(28,18,0),'C9':(34,32,0),
'R10':(23,49,270),'R11':(23,65,270),'R17':(45,26,0),
'R1':(48,40,0),'R2':(62,40,0),'R3':(62,28,270),'R4':(57,55,270),
'R18':(67,47,0),'C11':(77.5,47,0),'C6':(77.5,55.5,0),'C7':(80,28,0),
'J3':(74,17,0),'R12':(89,24,0),'C10':(104,45.65,90),'R14':(113,45.65,90),
'R15':(110,22,270),'R16':(125,22,270),'S2':(118,35,0),
'R5':(57,71,0),'R6':(74,66,90),'C1':(61,85,0),'C8':(62,77,0),'C2':(83,73,0),
'R7':(93,84,0),'R8':(105,66,90),'C3':(108,91,0),'C4':(117,67,0),
'R9':(124,82,0),'C5':(137,82,0),'JP1':(135,68,0),'J2':(144,59,90)
}
override=DATA/'placement.json'
if override.exists():positions.update(json.loads(override.read_text()))
fps={}
for ref in components:
    fp=makefp(ref);x,y,a=positions[ref];fp.SetOrientationDegrees(a);fp.SetPosition(v(x,y))
    if ref=='C5':fp.Flip(v(x,y),False)
    board.Add(fp);fps[ref]=fp
for q in fps.values():
    q.Reference().SetTextAngle(p.EDA_ANGLE(0,p.DEGREES_T))
wirefile=DATA/'jumpers.json'
wires=json.loads(wirefile.read_text()) if wirefile.exists() else []
wire_groups=[]
for w in wires:
    ref=w['ref'];a,b=w['ends'];dx,dy=b[0]-a[0],b[1]-a[1]
    fp=p.FOOTPRINT(board);fp.SetReference(ref);fp.SetValue('Insulated wire')
    fp.SetAttributes(p.FP_THROUGH_HOLE|p.FP_BOARD_ONLY|p.FP_EXCLUDE_FROM_POS_FILES)
    fp.SetDuplicatePadNumbersAreJumpers(True)
    for x,y in [(0,0),(dx,dy)]:pad(fp,1,x,y,2.6,2.6,1.0).SetNet(ns[alias[w['net']]])
    line(fp,(0,0),(dx,dy),p.F_Fab,.6)
    # Courtyard follows the real straight wire, not its whole bounding box.
    length=math.hypot(dx,dy);ux,uy=dx/length,dy/length;nx,ny=-uy,ux
    corners=[(ux*t+nx*s,uy*t+ny*s) for t,s in [(-1.8,-1.8),(1.8,-1.8),(1.8,-.8),(length-1.8,-.8),(length-1.8,-1.8),(length+1.8,-1.8),(length+1.8,1.8),(length-1.8,1.8),(length-1.8,.8),(1.8,.8),(1.8,1.8),(-1.8,1.8)]]
    for j in range(len(corners)):line(fp,corners[j],corners[(j+1)%len(corners)],p.F_CrtYd,.05)
    name=ref+'_wire';fp.SetFPID(p.LIB_ID('LUT',name))
    fp.Reference().SetPosition(v(0,-3));fp.Reference().SetTextSize(v(1.2,1.2));fp.Reference().SetTextThickness(mm(.2));fp.Reference().SetLayer(p.F_SilkS);fp.Value().SetVisible(False)
    p.PCB_IO_KICAD_SEXPR().FootprintSave(str(OUT/'LUT.pretty'),fp)
    fp.SetPosition(v(*a));board.Add(fp);fps[ref]=fp
    wire_groups.append([ref+'.A',ref+'.B'])
rect(board,10,10,152,108,p.Edge_Cuts,.1)
for i,(x,y) in enumerate([(15,15),(147,15),(15,103),(147,103)],1):
    fp=p.FOOTPRINT(board);fp.SetReference(f'H{i}');fp.SetValue('M3');fp.SetAttributes(p.FP_BOARD_ONLY|p.FP_EXCLUDE_FROM_BOM|p.FP_EXCLUDE_FROM_POS_FILES)
    q=p.PAD(fp);q.SetNumber('');q.SetAttribute(p.PAD_ATTRIB_NPTH);q.SetShape(p.PAD_SHAPE_CIRCLE);q.SetSize(v(3.2,3.2));q.SetDrillSize(v(3.2,3.2));q.SetLayerSet(p.LSET.AllCuMask());fp.Add(q)
    fp.Reference().SetVisible(False);fp.Value().SetVisible(False);fp.SetPosition(v(x,y));board.Add(fp)

def track(net,width,points):
    for a,b in zip(points,points[1:]):
        if a==b:continue
        q=p.PCB_TRACK(board);q.SetStart(v(*a));q.SetEnd(v(*b));q.SetWidth(mm(width));q.SetLayer(p.B_Cu);q.SetNet(ns[net]);board.Add(q)
def point(ref,n):
    q=next(q for q in fps[ref].Pads() if q.GetNumber()==str(n));pos=q.GetPosition();return [p.ToMM(pos.x),p.ToMM(pos.y)]
pre=[]
for a,b in [(1,2),(6,7),(8,9)]:pre.append({'net':pin_net[('U1',str(a))],'width':1.2,'points':[point('U1',a),point('U1',b)]})
for a,b in [(13,1),(14,2)]:pre.append({'net':pin_net[('U1',str(a))],'width':1.2,'points':[point('U1',a),point('C10',b)]})
# Keep the gain feedback compact: deterministic local connections, before any
# global routing, avoid a long detour around another signal's route.
for n,mid in [(1,(108,46.92)),(2,(108,44.38))]:
    pre.append({'net':pin_net[('C10',str(n))],'width':1.2,'points':[point('C10',n),list(mid),point('R14',n)]})
pre.append({'net':pin_net[('R14','2')],'width':1.2,'points':[point('R14',2),[113,35],[115.46,32],point('S2',1)]})
pre.append({'net':'V_A','width':1.2,'points':[point('U1',4),[78.5,52]]})
pre.append({'net':'V_A','width':1.2,'points':[point('U1',4),[84,52],[86,54],[86,62],[88,64],point('C6',1)]})
pre.append({'net':alias['Y1'],'width':1.2,'points':[point('C2',1),[65,55.5],[72,55.5],[72.7,54.8],[80.24,54.8],[80.5,54.54],point('U1',5)]})
pre.append({'net':alias['Y1'],'width':1.2,'points':[point('C2',1),[65,61.92],point('R6',2)]})
pre.append({'net':alias['BIAS_D'],'width':1.2,'points':[point('R15',2),[111.92,29],[119,29],[120.54,30.54],point('S2',3)]})
pre.append({'net':'AGND','width':1.2,'points':[point('C11',2),[71.73,52.5]]})
pre.append({'net':'AGND','width':1.2,'points':[point('U1',11),[94.75,52],[94.75,60.52],point('C6',2)]})
groups=[['U1.1','U1.2'],['U1.6','U1.7'],['U1.8','U1.9'],
        ['U1.13','C10.1','R14.1'],['U1.14','C10.2','R14.2','S2.1'],
        ['U1.4','C6.1','W2.B'],['C2.1','U1.5','R6.2'],['R15.2','S2.3'],['U1.11','C6.2']]+wire_groups
for t in pre:track(**t)
rp=[]
for ref,fp in fps.items():
    for qi,q in enumerate(fp.Pads()):
        pos=q.GetPosition();sz=q.GetSize()
        rp.append({'ref':ref,'pin':('AB'[qi] if ref.startswith('W') else q.GetNumber()),'net':q.GetNetname(),'x':p.ToMM(pos.x),'y':p.ToMM(pos.y),'w':p.ToMM(sz.x),'h':p.ToMM(sz.y),'shape':'rect' if ref=='C5' else ('circle' if sz.x==sz.y else 'oval'),'angle':-q.GetOrientationDegrees()})
order=['BUF','IN_A','INV_D','LP1','LP2','Y1','Y2','X1','X2','DRIVE','ADC_DRV','ADC_TARGET','BIAS_D','SUM','R_SER','CH1','AC_SER','AC_NODE','CORE_IN','BLEED_MID','V_A']
inp={'bounds':[11,11,151,107],'grid':.5,'track_width':1.2,'clearance':.80,'pads':rp,'pretracks':pre,'connected_pad_groups':groups,'forest':True,'max_detour_ratio':{alias[n]:1.8 for n in ['BUF','IN_A','INV_D','DRIVE','LP1','LP2','Y1','Y2','X1','X2','ADC_DRV','V_A']},'route_order':[alias[a] for a in order],'skip_nets':['AGND',alias['NC']],'obstacles':[[x-3,y-3,x+3,y+3] for x,y in [(15,15),(147,15),(15,103),(147,103)]]}
(WORK/'router-input.json').write_text(json.dumps(inp,indent=2))
routefile=DATA/'routes.json'
if routefile.exists():
    for t in json.loads(routefile.read_text())['routes']:track(t['net'],t['width'],t['points'])

if '--zone' in sys.argv:
    z=p.ZONE(board);z.SetLayer(p.B_Cu);z.SetNet(ns['AGND']);z.SetLocalClearance(mm(1.0));z.SetMinThickness(mm(1.0))
    z.SetPadConnection(p.ZONE_CONNECTION_FULL);z.SetThermalReliefGap(mm(1));z.SetThermalReliefSpokeWidth(mm(1.2));z.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
    poly=z.Outline();poly.NewOutline()
    for x,y in [(11.5,11.5),(150.5,11.5),(150.5,106.5),(11.5,106.5)]:poly.Append(mm(x),mm(y))
    board.Add(z)
    ko=p.ZONE(board);ko.SetLayer(p.B_Cu);ko.SetIsRuleArea(True);ko.SetDoNotAllowZoneFills(True);ko.SetDoNotAllowTracks(False);ko.SetDoNotAllowVias(True);ko.SetDoNotAllowPads(False)
    poly=ko.Outline();poly.NewOutline()
    for x,y in [(59,34),(75,34),(75,52),(59,52)]:poly.Append(mm(x),mm(y))
    board.Add(ko)

# Assembly markings are on documentation/silkscreen layers, never on a second
# copper layer. Wire labels name the physical insulated jumpers required below.
label_positions={'C11':(73,43.5),'C6':(94,64),'C10':(107.4,45.65),'R14':(116.5,45.65),'R8':(109,65),'W3':(78.8,64),'JP1':(135,64)}
fps['S1'].Reference().SetVisible(False)
for ref,xy in label_positions.items():
    if ref in fps:fps[ref].Reference().SetPosition(v(*xy))
def label(text,x,y,size=1.15,layer=p.F_SilkS):
    q=p.PCB_TEXT(board);q.SetText(text);q.SetPosition(v(x,y));q.SetLayer(layer)
    q.SetTextSize(v(size,size));q.SetTextThickness(mm(.18));board.Add(q)
for text,x,y in [('GND',24,28.46),('CH1',24,33.54),('+3V3',69.5,21),('GND',79,21),
                 ('GND',137,56.46),('PA0',137,61.54),('1-2 WIDE',118,37.5),('2-3 SENS',130,32),
                 ('JP1: ADC LINK',135,74),('R5.2 / CH1 / LUT',94,98),('TOP: PARTS + WIRES',93,102),
                 ('1',84.8,44.38)]:label(text,x,y)
for i in range(1,7):
    x,y=point('S1',i);label(str(i),x+1.8,y-1.4,.85)
label('S1: DC / AC',30,12,1.2)

pcb=OUT/'analog-input-r52.kicad_pcb';p.SaveBoard(str(pcb),board)
# Preserve the electrical schematic, with only physical footprint assignments
# redirected to the new local library. Values and all wires remain untouched.
sch=(SRC/'analog-input-r5.kicad_sch').read_text(encoding='utf-8')
for ref,c in components.items():
    old=c.findtext('footprint');ident=fps[ref].GetFPID();new=str(ident.GetLibNickname())+':'+str(ident.GetLibItemName())
    sch=sch.replace('"'+old+'"','"'+new+'"')
(OUT/'analog-input-r52.kicad_sch').write_text(sch,encoding='utf-8')
# Read the two original library assets directly from the immutable archive.
# No dependency on a previous session's temporary extraction directory.
with zipfile.ZipFile(SOURCE_ARCHIVE) as archive:
    for name in ['AnalogLUTR5.kicad_sym','sym-lib-table']:
        (OUT/name).write_bytes(archive.read(ARCHIVE_KICAD+'/'+name))
(OUT/'fp-lib-table').write_text('(fp_lib_table (version 7) (lib (name "LUT")(type "KiCad")(uri "${KIPRJMOD}/LUT.pretty")(options "")(descr "R5.2 single copper LUT")))\n')
project={'meta':{'filename':'analog-input-r52.kicad_pro','version':1},'board':{'design_settings':{'rules':{'min_clearance':.75,'min_track_width':1.0,'min_copper_edge_clearance':1.0,'min_hole_clearance':.35},'drc_exclusions':[]}},'net_settings':{'classes':[{'name':'Default','clearance':.75,'track_width':1.2,'via_diameter':2.4,'via_drill':1.0,'microvia_diameter':.3,'microvia_drill':.1,'diff_pair_width':1.2,'diff_pair_gap':.8,'diff_pair_via_gap':.8}]}}
(OUT/'analog-input-r52.kicad_pro').write_text(json.dumps(project,indent=2))
(OUT/'analog-input-r52.kicad_dru').write_text('(version 1)\n(rule "LUT min trace" (constraint track_width (min 1mm)))\n(rule "LUT clearance" (constraint clearance (min 0.75mm)))\n(rule "Copper edge" (constraint edge_clearance (min 1mm)))\n')
(WORK/'placement-used.json').write_text(json.dumps(positions,indent=2))
print(json.dumps({'board':str(pcb),'parts':len(fps),'router_pads':len(rp),'routes_loaded':routefile.exists(),'zone':'--zone' in sys.argv}))
