"""Read-only comparisons and a review map; never a fabrication master."""
from pathlib import Path
import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as E
from collections import Counter
from tools.pcb_r53.repair_schematic_connections import parse, children, child
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt

ROOT = Path.cwd()
SOURCE = ROOT / 'build/r53-user-review-20261104/extracted/R53_ERC_CHECK'
OUT = ROOT / 'docs/verification/r53-user-20261104'
IMPORTED = ROOT / 'docs/design/r53-user-20261104/project'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def netlist(path):
    root = E.parse(path).getroot()
    values = {c.get('ref'): c.findtext('value') for c in root.findall('./components/comp')}
    groups = set()
    for n in root.findall('./nets/net'):
        groups.add(tuple(sorted((p.get('ref'), p.get('pin')) for p in n.findall('node'))))
    return values, groups

def main():
    if IMPORTED.exists():
        raise RuntimeError('Refuse to overwrite imported user files')
    shutil.copytree(SOURCE, IMPORTED)
    old_values, old_groups = netlist(ROOT / 'docs/design/analog-r5-1/kicad/analog-input-r5.net.xml')
    values, groups = netlist(OUT / 'netlist.xml')
    sch, _ = parse((SOURCE / 'analog-input-r53.kicad_sch').read_text('utf-8'))
    pcb, _ = parse((SOURCE / 'analog-input-r53.kicad_pcb').read_text('utf-8'))
    tracks = children(pcb, 'segment') + children(pcb, 'arc')
    drc = json.loads((OUT / 'drc-project.json').read_text('utf-8'))
    source_files = {str(p.relative_to(SOURCE)): sha(p) for p in sorted(SOURCE.rglob('*')) if p.is_file()}
    assert source_files == {str(p.relative_to(IMPORTED)): sha(p) for p in sorted(IMPORTED.rglob('*')) if p.is_file()}
    result = {
        'scope': 'CAD audit only; no CAD edit, no physical measurement',
        'user_confirmed_front_copper_is_wire_jumpers': True,
        'source_files_sha256': source_files,
        'component_values_identical_to_r51': values == old_values,
        'complete_pin_partitions_identical_to_r51': groups == old_groups,
        'components': len(values), 'pin_count': sum(map(len, groups)), 'net_groups': len(groups),
        'wires': len(children(sch, 'wire')), 'junctions': len(children(sch, 'junction')),
        'schematic_wire_width_mm': dict(Counter(child(child(w, 'stroke'), 'width')[1] for w in children(sch, 'wire'))),
        'track_widths_mm': dict(Counter(child(t, 'width')[1] for t in tracks)),
        'track_layers': dict(Counter(child(t, 'layer')[1] for t in tracks)),
        'via_count': len(children(pcb, 'via')),
        'outline_centerline': {'min_mm': [28, 25], 'max_mm': [138, 80], 'size_mm': [110, 55]},
        'drc_counts_by_severity': dict(Counter(v['severity'] for v in drc['violations'])),
        'drc_counts_by_type': dict(Counter(v['type'] for v in drc['violations'])),
        'unconnected_items': len(drc['unconnected_items']), 'schematic_parity_issues': len(drc['schematic_parity']),
        'drc_board_was_not_saved': True,
        'erc_report': 'erc.json', 'drc_report': 'drc-project.json',
        'gui_erc_status': 'User previously reported 0/0 and completion; no new automated GUI cycle in this audit',
    }
    (OUT / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')

    # Native SVG is rendered at its board-area scale. The small export rounding
    # error is irrelevant for this labelled overview; it must not be used for LUT.
    ns = 'http://www.w3.org/2000/svg'
    E.register_namespace('', ns)
    tag = lambda s: '{' + ns + '}' + s
    native = E.parse(OUT / 'overview-native.svg').getroot()
    svg = E.Element(tag('svg'), {'viewBox':'0 0 130 95', 'width':'1560', 'height':'1140'})
    E.SubElement(svg, tag('rect'), {'width':'130','height':'95','fill':'#ffffff'})
    def text(x,y,value,size=2.5,color='#192f3a'):
        E.SubElement(svg, tag('text'), {'x':str(x),'y':str(y),'font-family':'Arial', 'font-size':str(size),'fill':color}).text=value
    text(5,5,'R53 — проверка вашей разводки',3.3)
    text(5,9,'Вид сверху • A–F: места нарушений зазора • красные линии: верхние перемычки',2.15)
    board_group=E.SubElement(svg,tag('g'),{'transform':'translate(10,21)'})
    for element in list(native):
        board_group.append(element)
    # Board positions are original KiCad mm, not image pixels.
    markers=[('A',127.8,59.42,124,65), ('B',112.5,39.38,97,17),
             ('C',101.6,35.5,70,17), ('D',121,34.2,117,17),
             ('E',109.3,38.0,83,17), ('F',115.5,36.0,107,17)]
    for label,x,y,lx,ly in markers:
        px,py=10+x-28,21+y-25
        E.SubElement(svg,tag('circle'),{'cx':str(px),'cy':str(py),'r':'1.9','fill':'none','stroke':'#ffcf00','stroke-width':'.55'})
        E.SubElement(svg,tag('line'),{'x1':str(px),'y1':str(py),'x2':str(lx),'y2':str(ly),'stroke':'#172d38','stroke-width':'.22'})
        E.SubElement(svg,tag('circle'),{'cx':str(lx),'cy':str(ly),'r':'2.1','fill':'#ffcf00','stroke':'#172d38','stroke-width':'.18'})
        text(lx-.9,ly+.95,label,2.6)
    text(5,82,'A: R16, 0,45 мм   B: переход S2-WIDE, 0,689 мм   C: R12, 0,70 мм',2.3)
    text(5,87,'D: C7, 0,54 / 0,69 мм   E: U1.14, 0,73 мм   F: R14, 0,50 мм',2.3)
    text(5,92,'Минимум по правилам — 0,75 мм. Это карта замечаний, не шаблон для травления.',2.15)
    E.ElementTree(svg).write(OUT / 'clearance-map.svg',encoding='utf-8',xml_declaration=True)
    app=QApplication([])
    renderer=QSvgRenderer(str(OUT/'clearance-map.svg'))
    im=QImage(1560,1140,QImage.Format_ARGB32); im.fill(Qt.white)
    painter=QPainter(im);renderer.render(painter);painter.end()
    assert im.save(str(OUT/'clearance-map.png'))
    print(json.dumps({k:v for k,v in result.items() if k!='source_files_sha256'},ensure_ascii=False))

if __name__=='__main__':
    main()
