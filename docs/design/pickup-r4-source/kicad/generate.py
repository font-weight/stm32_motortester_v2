#!/usr/bin/env python3
"""Portable deterministic source for the separate passive pickup accessory.

All symbols and drawing geometry are authored here. No external symbol libraries
or vendor files are required. Run from any working directory; only this script's
directory is written. This is a low-voltage bench-verification design, not a
physical-safety approval, an HV probe rating, or a fabrication drawing.
"""
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
import csv
import json

OUT = Path(__file__).resolve().parent
NAME = 'passive-ht-pickup'
LIBNAME = 'PickupAccessory'
NAMESPACE = 'pickup-accessory/2026-10-26/rev-r3/'

def uid(s):
    return str(uuid5(NAMESPACE_URL, NAMESPACE + s))

def q(s):
    return json.dumps(str(s), ensure_ascii=False)

def effects(size=1.5, extra=''):
    return f'(effects (font (size {size} {size})) {extra})'

def prop(name, value, x=0, y=0, hide=False, left=False, size=1.5):
    extra = ('(hide yes)' if hide else '') + (' (justify left)' if left else '')
    return f'(property {q(name)} {q(value)} (at {x} {y} 0) {effects(size, extra)})'

def line(points, width=.254):
    return '(polyline (pts ' + ' '.join(f'(xy {x} {y})' for x,y in points) + f') (stroke (width {width}) (type default)) (fill (type none)))'

def circle(x,y,r,fill='none'):
    return f'(circle (center {x} {y}) (radius {r}) (stroke (width .254) (type default)) (fill (type {fill})))'

def pin(number,x,y,angle,length=2.54):
    return f'(pin passive line (at {x} {y} {angle}) (length {length}) (name "" {effects(.9)}) (number {q(number)} {effects(.9)}))'

symbols = {}
def symbol(name, ref, body):
    symbols[name] = f'(symbol "{LIBNAME}:{name}" (pin_names (offset .508)) (exclude_from_sim no) (in_bom yes) (on_board no) {prop("Reference",ref)} {prop("Value",name)} {prop("Footprint","",hide=True)} {prop("Datasheet","",hide=True)} (symbol "{name}_1_1" {body}))'

symbol('Electrode', 'E', line([(0,8.89),(0,-8.89)],.508) + pin(1,10.16,0,180,10.16))
symbol('Capacitor', 'C', line([(-3.175,.762),(3.175,.762)]) + line([(-3.175,-.762),(3.175,-.762)]) + pin(1,0,5.08,270,4.318) + pin(2,0,-5.08,90,4.318))
symbol('Resistor', 'R', '(rectangle (start -1.27 3.81) (end 1.27 -3.81) (stroke (width .254) (type default)) (fill (type background)))' + pin(1,0,6.35,270) + pin(2,0,-6.35,90))
symbol('BNC', 'J', circle(0,0,4.445) + circle(0,0,1.016) + line([(-2.54,0),(-1.016,0)]) + pin(1,-10.16,0,0,7.62) + pin(2,0,-10.16,90,5.715))
symbol('ReferenceLead', 'J', circle(0,0,1.27) + line([(1.27,0),(2.54,0)]) + pin(1,7.62,0,180,5.08))

rootid = uid(NAME)
items = []
counter = 0

def ident(kind):
    global counter
    counter += 1
    return uid(f'{NAME}/{counter}/{kind}')

def text(value,x,y,size=1.5):
    items.append(f'(text {q(value)} (at {x} {y} 0) {effects(size,"(justify left top)")} (uuid {q(ident("text"))}))')

def graphic(points, dashed=False, width=.254):
    items.append('(polyline (pts ' + ' '.join(f'(xy {x} {y})' for x,y in points) + f') (stroke (width {width}) (type {"dash" if dashed else "default"})) (fill (type none)) (uuid {q(ident("graphic"))}))')

def box(x1,y1,x2,y2,dashed=False):
    graphic([(x1,y1),(x2,y1),(x2,y2),(x1,y2),(x1,y1)],dashed)

def wire(x1,y1,x2,y2):
    items.append(f'(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid {q(ident("wire"))}))')

def label(value,x,y):
    items.append(f'(label {q(value)} (at {x} {y} 0) {effects(1.65,"(justify left bottom)")} (uuid {q(ident("label"))}))')

def junction(x,y):
    items.append(f'(junction (at {x} {y}) (diameter 1) (color 0 0 0 0) (uuid {q(ident("junction"))}))')

def component(lib,ref,value,x,y,rx,ry,vx,vy,left=False,mpn='',note=''):
    items.append(f'(symbol (lib_id "{LIBNAME}:{lib}") (at {x} {y} 0) (unit 1) (exclude_from_sim no) (in_bom yes) (on_board no) (dnp no) (uuid {q(ident(ref))}) {prop("Reference",ref,rx,ry,left=left,size=1.75)} {prop("Value",value,vx,vy,left=left,size=1.5)} {prop("Footprint","",x,y,True)} {prop("Datasheet","",x,y,True)} {prop("ManufacturerPartNumber",mpn,x,y,True)} {prop("DesignNote",note,x,y,True)} (instances (project {q(NAME)} (path {q("/"+rootid)} (reference {q(ref)}) (unit 1)))))')

# A compact, self-contained A4 landscape drawing. Native KiCad title block is
# also present in source, but exports omit it in favor of this readable layout.
text('ПАССИВНЫЙ ЕМКОСТНЫЙ HT-ПРОБНИК',12,11,2.8)
text('Отдельный аксессуар к R3 - проект для низковольтной стендовой проверки',12,18,1.7)
graphic([(12,25),(285,25)],width=.4)
text('E1: один металлический электрод Ø10 мм. C1: 10 нФ ±5%, MKP, 100 VDC.',12,29,1.65)
text('R1: 10 МОм ±1%, 0,25 Вт, металлоплёночный. W1: фиксированный экранированный кабель 1 м.',12,35,1.65)

# External HT geometry is deliberately non-electrical and has no reference,
# electrical pin, fictitious capacitance value, or BOM entry.
text('ВНЕШНИЙ HT-ПРОВОД',12,47,1.65)
text('Условная геометрия,\nне элемент схемы',12,52,1.35)
box(17.78,63.5,35.56,110.49)
box(20.32,66.04,33.02,107.95)
graphic([(26.67,68.58),(26.67,105.41)],width=.8)
text('Жила',12,114,1.4)
text('Целая двойная\nизоляция',12,119,1.4)
graphic([(35.56,74.93),(53.34,74.93)],dashed=True)
graphic([(35.56,85.09),(53.34,85.09)],dashed=True)
graphic([(35.56,95.25),(53.34,95.25)],dashed=True)
text('Связь C неизвестна.\nНе отдельная деталь.\nКонтакта с жилой НЕТ.',40,133,1.3)

# Head boundary is a placement requirement, not an insulation or dimensional
# drawing. Both fitted shunts are immediately at the electrode/head.
box(55.88,60.96,180.34,127,dashed=True)
text('ГОЛОВКА: C1 и R1 непосредственно у E1',59.69,64.77,1.55)
component('Electrode','E1','Ø10 мм',63.5,80.01,71.12,91.44,71.12,96.52)
component('Capacitor','C1','10 нФ ±5%',101.6,100.33,107.95,96.52,107.95,101.6,True,mpn='WIMA MKP2D021001B00JSSD',note='Fixed shunt SIG to SHIELD, immediately at head; MKP 100 VDC; not an HV/CAT rating.')
text('MKP 100 VDC',107.95,105.41,1.3)
component('Resistor','R1','10 МОм ±1%',147.32,100.33,153.67,96.52,153.67,101.6,True,note='Fixed shunt SIG to SHIELD, immediately at head; metal film, 0.25 W; no series resistor.')
text('0,25 Вт',153.67,105.41,1.3)
wire(73.66,80.01,101.6,80.01)
wire(101.6,80.01,147.32,80.01)
wire(147.32,80.01,243.84,80.01)
wire(101.6,80.01,101.6,95.25)
wire(147.32,80.01,147.32,93.98)
wire(101.6,105.41,101.6,116.84)
wire(147.32,106.68,147.32,116.84)
wire(101.6,116.84,147.32,116.84)
wire(147.32,116.84,175.26,116.84)
wire(175.26,116.84,175.26,92.71)
wire(175.26,92.71,254,92.71)
wire(254,92.71,254,90.17)
for x,y in [(101.6,80.01),(147.32,80.01),(147.32,116.84)]:
    junction(x,y)
label('SIG',81.28,80.01)
label('SHIELD',107.95,116.84)

# W1 is a physical assembly item in the BOM, represented by the two conductors
# above, not a fictitious 3rd electrical net or an unconnected cable component.
box(185.42,73.66,236.22,99.06,dashed=True)
text('W1: кабель 1 м',186.69,64.77,1.65)
text('Центральная жила',187.96,83.82,1.3)
text('Экран',187.96,94.615,1.3)
text('Жилы показаны раздельно;\nразмеры условные.',184.15,105.41,1.35)
component('BNC','J1','BNC',254,80.01,254,64.77,269.24,95.25,note='Pin 1 center SIG; pin 2 shell SHIELD. Symbol pin numbers are this drawing contract; select a physical BNC and verify its terminals.')
text('1: центр = SIG\n2: корпус = SHIELD',259.08,105.41,1.25)
text('К входу R3\nCH1 / AGND',240.03,122,1.55)
component('ReferenceLead','J2','GND_REF',224.79,116.84,224.79,111.76,224.79,123.19,note='Separate vehicle-reference pigtail and clip at the instrument/BNC end, connected to SHIELD only: approximately 0.5 m insulated flexible 0.5 square mm wire. Connect to verified vehicle ground with engine stopped; verify shared R3/USB/oscilloscope ground. Not protective isolation.')
wire(254,92.71,254,116.84)
wire(254,116.84,232.41,116.84)
junction(254,92.71)

text('C1: WIMA MKP2D021001B00JSSD. J2 у BNC: около 0,5 м гибкого изолированного провода 0,5 мм² + зажим.',92.71,135.89,1.3)
graphic([(12,149.86),(285,149.86)],width=.4)
text('ОГРАНИЧЕНИЯ ПРОЕКТА',12,153,1.9)
text('Только низковольтный стенд. Физически не проверено; рисунок не задаёт изоляционные расстояния и не разрешает работу на HV.',12,160,1.4)
text('Головка только снаружи исправного, чистого и сухого HT-провода с двойной изоляцией; E1 не касается жилы.',12,165,1.4)
text('SHIELD = AGND R3 = общая земля прибора, НЕ развязка. Шина AGND сама по себе не задаёт массу автомобиля.',12,170,1.4)
text('J2: отдельный изолированный провод к проверенной массе автомобиля; соединять при остановленном двигателе.',12,175,1.4)
text('Общая земля R3/USB/осциллографа должна быть проверена. J2 не является защитной изоляцией.',12,180,1.4)
text('100 VDC - только рейтинг C1, не HV/CAT-рейтинг аксессуара. Нет последовательного R, клампа, переключателя и PCB.',12,185,1.4)
graphic([(12,194),(285,194)],width=.4)
text('ACC-PU-01  |  REV R3  |  2026-10-26  |  Схема не в масштабе  |  Не допуск к эксплуатации',12,198,1.35)

header = f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0") (uuid {q(rootid)}) (paper "A4") (title_block (title "Passive HT pickup accessory - low-voltage bench-verification project") (date "2026-10-26") (rev "R3 MATCH / NOT PHYSICALLY APPROVED") (company "Accessory, separate from R3") (comment 1 "No direct HV/CAT rating. SHIELD is shared instrument AGND; no isolation barrier.")) (lib_symbols '
(OUT / (NAME + '.kicad_sch')).write_text(header + ''.join(symbols.values()) + ')\n' + '\n'.join(items) + '\n(embedded_fonts no))\n', encoding='utf-8')
(OUT / (LIBNAME + '.kicad_sym')).write_text('(kicad_symbol_lib (version 20241209) (generator "kicad_symbol_editor") (generator_version "9.0") ' + ''.join(s.replace(f'"{LIBNAME}:','"',1) for s in symbols.values()) + ')\n', encoding='utf-8')
(OUT / 'sym-lib-table').write_text(f'(sym_lib_table (version 7) (lib (name "{LIBNAME}") (type "KiCad") (uri "${{KIPRJMOD}}/{LIBNAME}.kicad_sym") (options "") (descr "Original self-contained passive accessory symbols")))\n', encoding='utf-8')
(OUT / (NAME + '.kicad_pro')).write_text(json.dumps({'meta':{'filename':NAME+'.kicad_pro','version':1},'erc':{'erc_exclusions':[]}},indent=2)+'\n', encoding='utf-8')
rows = [
 ['E1','1','Один металлический электрод Ø10 мм','', 'Один вывод SIG. Не касается HT-жилы; геометрия и безопасность физически не проверены.'],
 ['C1','1','10 нФ ±5%, MKP, 100 VDC','WIMA MKP2D021001B00JSSD','Шунт SIG-SHIELD непосредственно в головке. 100 VDC не является рейтингом аксессуара.'],
 ['R1','1','10 МОм ±1%, 0,25 Вт, металлоплёночный','','Шунт SIG-SHIELD непосредственно в головке. Конкретный MPN не выбран.'],
 ['W1','1','Фиксированный экранированный кабель, 1 м','','Центральная жила SIG, экран SHIELD; электрически представлен проводами. Конкретный кабель не выбран.'],
 ['J1','1','BNC','','Центр SIG, корпус SHIELD. Условные номера схемы 1/2 не заменяют проверку физического разъёма.'],
 ['J2','1','GND_REF у приборного/BNC-конца: около 0,5 м гибкого изолированного провода 0,5 мм² + зажим','','Ответвление только от SHIELD у BNC, не от головки, SIG или E1. К проверенной массе автомобиля; соединять при остановленном двигателе. Общая земля R3/USB/осциллографа должна быть проверена. Не защитная изоляция.'],
]
with (OUT/'bom.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f,lineterminator='\n'); w.writerow(['Reference','Quantity','Specification','ManufacturerPartNumber','Notes']); w.writerows(rows)
print(f'Generated {NAME} source, local symbol library and BOM in {OUT}')
