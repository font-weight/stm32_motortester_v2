"""Generate the P1-LV electrical drawing as SVG using only the standard library.

The named nets and SOIC-14 pin numbers follow netlist.md. This is a readable
engineering drawing, not an ERC-checked CAD model or a physical validation.
"""

import argparse
from html import escape
import os
from pathlib import Path


arguments = argparse.ArgumentParser(description=__doc__)
arguments.add_argument(
    "--png",
    action="store_true",
    help="Also render schematic.png using installed PySide6 (offscreen).",
)
options = arguments.parse_args()

WIDTH, HEIGHT = 1920, 1610
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
    f'viewBox="0 0 {WIDTH} {HEIGHT}">',
    '<style>text{font-family:"Segoe UI",Arial,sans-serif;fill:#142b35}'
    '.wire{fill:none;stroke:#234551;stroke-width:2.6;stroke-linecap:round;'
    'stroke-linejoin:round}.part{fill:#fff;stroke:#234551;stroke-width:2.6}'
    '.net{fill:#006e79;font-weight:600}.small{fill:#52666e}'
    '.warning{fill:#a13c2d;font-weight:600}</style>',
    '<rect width="1920" height="1610" fill="#f2f5f5"/>',
]


def text(x, y, label, size=20, cls="", anchor="start"):
    parts.append(
        f'<text x="{x}" y="{y}" font-size="{size}" class="{cls}" '
        f'text-anchor="{anchor}">{escape(label)}</text>'
    )


def path(coords, cls="wire"):
    data = " ".join(
        ("M" if index == 0 else "L") + f"{x},{y}"
        for index, (x, y) in enumerate(coords)
    )
    parts.append(f'<path d="{data}" class="{cls}"/>')


def dot(x, y):
    parts.append(f'<circle cx="{x}" cy="{y}" r="4.2" fill="#234551"/>')


def ring(x, y, radius=5):
    parts.append(
        f'<circle cx="{x}" cy="{y}" r="{radius}" fill="#fff" '
        'stroke="#234551" stroke-width="2.4"/>'
    )


def panel(x, y, w, h, title):
    parts.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
        'fill="#fff" stroke="#c3d2d6" stroke-width="1.5"/>'
    )
    text(x + 24, y + 37, title, 25)
    path([(x + 24, y + 54), (x + w - 24, y + 54)])


def net(x, y, name, anchor="start"):
    text(x, y, name, 21, "net", anchor)


def ground(x, y):
    path([(x, y - 14), (x, y)])
    for offset, half in ((0, 18), (7, 12), (14, 5)):
        path([(x - half, y + offset), (x + half, y + offset)])
    text(x + 24, y + 8, "AGND", 17, "net")


def resistor_h(x1, x2, y, ref, value, below=False):
    center = (x1 + x2) / 2
    path([(x1, y), (center - 34, y)])
    parts.append(
        f'<rect x="{center-34}" y="{y-11}" width="68" height="22" class="part"/>'
    )
    path([(center + 34, y), (x2, y)])
    text(center, y + 44 if below else y - 45, ref, 19, anchor="middle")
    text(center, y + 66 if below else y - 23, value, 19, anchor="middle")


def resistor_v(x, y1, y2, ref, value, label_dx=22, label_dy=0):
    center = (y1 + y2) / 2
    path([(x, y1), (x, center - 30)])
    parts.append(
        f'<rect x="{x-11}" y="{center-30}" width="22" height="60" class="part"/>'
    )
    path([(x, center + 30), (x, y2)])
    text(x + label_dx, center - 4 + label_dy, ref, 19)
    text(x + label_dx, center + 20 + label_dy, value, 19)


def cap_h(x1, x2, y, ref, value):
    center = (x1 + x2) / 2
    path([(x1, y), (center - 5, y)])
    path([(center + 5, y), (x2, y)])
    path([(center - 5, y - 16), (center - 5, y + 16)])
    path([(center + 5, y - 16), (center + 5, y + 16)])
    text(center, y - 26, f"{ref} · {value}", 19, anchor="middle")


def cap_v(x, y1, y2, ref, value, label_dx=22):
    center = (y1 + y2) / 2
    path([(x, y1), (x, center - 5)])
    path([(x, center + 5), (x, y2)])
    path([(x - 17, center - 5), (x + 17, center - 5)])
    path([(x - 17, center + 5), (x + 17, center + 5)])
    text(x + label_dx, center - 5, ref, 19)
    text(x + label_dx, center + 20, value, 19)


def opamp(x, y, ref, plus_pin, minus_pin, out_pin):
    # Inputs are at (x, y±25), output at (x+115, y).
    parts.append(
        f'<path d="M{x},{y-65} L{x},{y+65} L{x+115},{y} Z" class="part"/>'
    )
    text(x + 12, y - 18, "+", 23)
    text(x + 12, y + 33, "−", 23)
    text(x + 45, y + 7, ref, 20)
    text(x - 10, y - 33, str(plus_pin), 17, anchor="end")
    text(x - 10, y + 46, str(minus_pin), 17, anchor="end")
    text(x + 108, y - 12, str(out_pin), 17)


def tp(x, y, name, above=True):
    dot(x, y)
    end = y - 23 if above else y + 23
    path([(x, y), (x, end)])
    ring(x, end, 4.5)
    text(x, end - 10 if above else end + 23, name, 17, "small", "middle")


text(40, 54, "P1-LV • расчётный лабораторный проект", 35)
text(42, 90, "Не проверено физически · не для датчика зажигания · JP_ADC снята", 24, "warning")
text(42, 119, "Ревизия r2 · R1…R9 1% · R10…R12 5% с отбором · все R 0,25 Вт · одинаковые имена сетей соединены", 18, "small")

# Input divider and buffer.
panel(30, 145, 910, 380, "1. DC-вход и буфер")
parts.append('<rect x="70" y="312" width="45" height="94" rx="3" class="part"/>')
text(91, 290, "J1", 20, anchor="middle")
text(83, 340, "1", 16)
text(83, 390, "2", 16)
ring(115, 335)
ring(115, 385)
path([(115, 335), (170, 335)])
resistor_h(170, 310, 335, "R1", "510 кОм")
path([(310, 335), (350, 335)])
net(330, 369, "IN_MID", "middle")
resistor_h(350, 490, 335, "R2", "510 кОм")
path([(490, 335), (660, 335)])
tp(145, 335, "TP1")
net(135, 274, "CH1")
path([(115, 385), (145, 385), (145, 448)])
ground(145, 462)
net(525, 227, "V_A", "middle")
resistor_v(525, 240, 335, "R3", "240 кОм", label_dx=32, label_dy=-35)
dot(525, 335)
resistor_v(525, 335, 450, "R4", "330 кОм")
ground(525, 464)
net(570, 324, "SUM")
tp(610, 335, "TP2")
opamp(660, 360, "U1A", 3, 2, 1)
path([(775, 360), (880, 360)])
net(880, 335, "BUF", "end")
tp(850, 360, "TP3", above=False)
path([(805, 360), (805, 455), (625, 455), (625, 385), (660, 385)])
dot(805, 360)
text(54, 500, "J1: лабораторный CH1 / AGND; будущий BNC: центр / экран. Терминатора 50 Ом нет.", 17, "small")

# Power drawing. All four amplifiers are physically the same SOIC-14.
panel(970, 145, 920, 380, "2. Общее питание U1 и контрольные точки")
parts.append('<rect x="1010" y="247" width="45" height="191" rx="3" class="part"/>')
text(1032, 225, "J3", 20, anchor="middle")
text(1020, 280, "1", 16)
text(1020, 421, "2", 16)
ring(1055, 275)
ring(1055, 415)
path([(1055, 275), (1830, 275)])
path([(1055, 415), (1830, 415)])
net(1080, 253, "V_A")
net(1075, 448, "AGND")
tp(1190, 275, "TP7")
tp(1190, 415, "TP0", above=False)
cap_v(1250, 275, 415, "C6", "100 нФ")
cap_v(1610, 275, 415, "C7", "1 мкФ")
resistor_v(1770, 275, 415, "R12", "10 кОм", label_dx=22)
for px in (1250, 1450, 1610, 1770):
    dot(px, 275)
    dot(px, 415)
parts.append('<rect x="1370" y="313" width="160" height="66" rx="3" class="part"/>')
text(1450, 339, "U1 · питание", 19, anchor="middle")
text(1450, 364, "TLV9064IDR", 18, anchor="middle")
path([(1450, 275), (1450, 313)])
path([(1450, 379), (1450, 415)])
text(1463, 304, "4 · V+", 17)
text(1463, 403, "11 · V−", 17)
text(994, 483, "SOIC-14 (D), вид сверху. C6/C7 — у корпуса. V_A = проверенная VDDA/Vref+.", 17, "small")
text(994, 508, "Номинально 3,3 В. Источник/ток TBD. R12 — разрядная нагрузка, не аварийная защита.", 17, "small")


def filter_panel(origin_x, title, input_net, output_net, refs, value, cf):
    panel(origin_x, 550, 910 if origin_x == 30 else 920, 460, title)
    x0 = origin_x + 50
    y = 790
    net(x0, y - 22, input_net)
    resistor_h(x0, origin_x + 270, y, refs[0], value)
    path([(origin_x + 270, y), (origin_x + 330, y)])
    resistor_h(origin_x + 330, origin_x + 500, y, refs[1], value, below=True)
    path([(origin_x + 500, y), (origin_x + 630, y)])
    xnode, ynode = origin_x + 310, origin_x + 520
    dot(xnode, y)
    dot(ynode, y)
    net(xnode, y + 30, refs[2], "middle")
    net(ynode, y - 22, refs[3], "middle")
    opamp(origin_x + 630, y + 25, refs[4], refs[5], refs[6], refs[7])
    outx = origin_x + 825
    path([(origin_x + 745, y + 25), (outx + 35, y + 25)])
    net(outx + 35, y + 3, output_net, "end")
    tp(outx + 5, y + 25, refs[8], above=False)
    feedback_x = origin_x + 770
    path([(feedback_x, y + 25), (feedback_x, 929), (origin_x + 590, 929),
          (origin_x + 590, y + 50), (origin_x + 630, y + 50)])
    dot(feedback_x, y + 25)
    for idx, (name, capacitance) in enumerate(cf):
        cy = 668 + idx * 65
        path([(xnode, y), (xnode, cy)])
        cap_h(xnode, outx, cy, name, capacitance)
        path([(outx, cy), (outx, y + 25)])
    dot(outx, y + 25)
    if len(cf) > 1:
        dot(xnode, 733)
        dot(outx, 733)
    cap_v(ynode, y, 935, refs[9], "10 нФ")
    ground(ynode, 949)
    text(origin_x + 24, 991, "Cf соединяет X с выходом ОУ; Cg соединяет Y с AGND. Обратная связь замкнута.", 17, "small")


filter_panel(30, "3. ФНЧ: первая секция Sallen–Key", "BUF", "LP1",
             ("R5", "R6", "X1", "Y1", "U1B", 5, 6, 7, "TP4", "C2"),
             "4,7 кОм", (("C1a", "10 нФ"), ("C1b", "1,8 нФ")))
filter_panel(970, "4. ФНЧ: вторая секция Sallen–Key", "LP1", "LP2",
             ("R7", "R8", "X2", "Y2", "U1C", 10, 9, 8, "TP5", "C4"),
             "2 кОм", (("C3", "68 нФ"),))

# Local bounded DC test source and manual selection.
panel(30, 1040, 910, 500, "5. Местный DC_TEST и ручной выбор входа")
net(130, 1140, "V_A", "middle")
resistor_v(130, 1155, 1265, "R10", "33 кОм")
path([(130, 1265), (130, 1280)])
parts.append('<rect x="119" y="1280" width="22" height="90" class="part"/>')
text(172, 1383, "RV1 · 10 кОм", 19)
path([(130, 1370), (130, 1410)])
ground(130, 1424)
path([(141, 1325), (195, 1325)])
# Wiper arrow points into the potentiometer; no ambiguity with a separate tap.
parts.append('<path d="M141,1325 L154,1319 L154,1331 Z" fill="#234551"/>')
resistor_h(195, 335, 1325, "R11", "1 кОм")
path([(335, 1325), (400, 1325), (400, 1200), (530, 1200)])
net(378, 1305, "TEST")
text(610, 1130, "JP_TEST · 3 контакта", 20, anchor="middle")
parts.append('<rect x="515" y="1176" width="190" height="48" rx="3" class="part"/>')
for px, pnum in ((530, 1), (610, 2), (690, 3)):
    ring(px, 1200, 7)
    text(px, 1250, str(pnum), 16, anchor="middle")
text(530, 1163, "TEST", 18, "net", "middle")
text(690, 1163, "ZERO", 18, "net", "middle")
path([(610, 1207), (610, 1300)])
net(610, 1332, "CH1", "middle")
path([(697, 1200), (780, 1200), (780, 1258)])
ground(780, 1272)
text(360, 1383, "1–2: TEST    2–3: ноль (AGND)", 20)
text(360, 1412, "Перемычка снята: внешний J1.", 19)
text(54, 1472, "Только одна перемычка. В TEST/ZERO внешний источник к J1 не подключать.", 18, "warning")
text(54, 1501, "Напряжение измерять на нагруженном CH1. Нижнее положение RV1 не равно нулю.", 17, "small")
text(54, 1526, "Распиновку RV1 уточнить по выбранной детали. JP_TEST показана без перемычки.", 17, "small")

# ADC connection is deliberately open. Unused amplifier is closed loop.
panel(970, 1040, 920, 500, "6. Выход к ADC и определённое состояние U1D")
net(1010, 1153, "LP2")
resistor_h(1010, 1165, 1192, "R9", "330 Ом")
path([(1165, 1192), (1440, 1192)])
tp(1220, 1192, "TP6")
net(1260, 1168, "ADC_NODE")
cap_v(1220, 1192, 1285, "C5", "1 нФ")
ground(1220, 1299)
text(1468, 1135, "JP_ADC", 20, anchor="middle")
ring(1440, 1192, 7)
ring(1495, 1192, 7)
path([(1502, 1192), (1780, 1192)])
text(1468, 1232, "СНЯТА", 18, "warning", "middle")
net(1640, 1170, "ADC_TARGET", "middle")
parts.append('<rect x="1780" y="1166" width="60" height="99" rx="3" class="part"/>')
text(1810, 1143, "J2", 20, anchor="middle")
text(1800, 1198, "1", 17)
text(1800, 1246, "2", 17)
ring(1780, 1192)
ring(1780, 1240)
path([(1780, 1240), (1735, 1240), (1735, 1275)])
ground(1735, 1289)
text(1390, 1334, "J2 → подтверждённые PA0/ADC1_IN0 и AGND", 18, "small")

net(1020, 1425, "BUF")
path([(1070, 1420), (1210, 1420)])
opamp(1210, 1445, "U1D", 12, 13, 14)
path([(1325, 1445), (1380, 1445)])
path([(1350, 1445), (1350, 1515), (1160, 1515), (1160, 1470), (1210, 1470)])
dot(1350, 1445)
text(1400, 1441, "Выход pin14 не подключён наружу.", 19)
text(1400, 1472, "Все секции U1 питаются от pins 4 / 11.", 17, "small")
text(1400, 1501, "Это чертёж соединений; CAD/ERC не выполнены.", 17, "small")

text(40, 1580, "Все напряжения относительно AGND · нет защиты для неизвестного внешнего сигнала · параметры монтажа и питания TBD", 20, "warning")
parts.append("</svg>")
target = Path(__file__).with_name("schematic.svg")
target.write_text("\n".join(parts) + "\n", encoding="utf-8")
print(target)

if options.png:
    # No desktop window or device connection is created by this renderer.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    application = QGuiApplication([])
    # Qt's Windows offscreen plugin may start without a system font database.
    # Register the existing local fonts; do not copy or redistribute font files.
    if os.name == "nt":
        font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for font_name in ("segoeui.ttf", "segoeuib.ttf"):
            font_file = font_directory / font_name
            if not font_file.is_file() or QFontDatabase.addApplicationFont(str(font_file)) < 0:
                raise RuntimeError(f"Required Windows font could not be loaded: {font_file}")
    renderer = QSvgRenderer(str(target))
    if not renderer.isValid():
        raise RuntimeError("QtSvg could not load the generated SVG.")
    output_image = QImage(renderer.defaultSize(), QImage.Format.Format_ARGB32)
    output_image.fill(Qt.GlobalColor.white)
    painter = QPainter(output_image)
    renderer.render(painter)
    painter.end()
    output_path = target.with_suffix(".png")
    if not output_image.save(str(output_path)):
        raise RuntimeError(f"Could not save PNG: {output_path}")
    print(output_path)
