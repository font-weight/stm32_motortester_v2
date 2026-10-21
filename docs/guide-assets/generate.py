"""Reproduce the explanatory figures with the bundled Python and Pillow.

SVG and PNG share the same drawing primitives. No hardware is contacted.
The functional maps explain the existing netlists; they are not wiring diagrams.
"""

from html import escape
from pathlib import Path
import math
import os

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parent
FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
INK = "#173340"
TEAL = "#007e87"
GRAY = "#54656e"
LINE = "#94abb2"
RED = "#a4412d"
LIGHT = "#eef7f7"
PALE = "#f4f6f7"


class Figure:
    def __init__(self, name, height):
        self.name, self.width, self.height = name, 1600, height
        self.image = Image.new("RGB", (1600, height), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{height}" '
            f'viewBox="0 0 1600 {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
        ]

    def font(self, size=32, bold=False):
        return ImageFont.truetype(str(FONT_DIR / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)

    def text(self, x, y, value, size=32, color=INK, bold=False, anchor="start"):
        """Position text using a common top edge, avoiding renderer-specific baselines."""
        font = self.font(size, bold)
        bbox = self.draw.textbbox((0, 0), value, font=font)
        width = self.draw.textlength(value, font=font)
        px = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
        self.draw.text((px, y - bbox[1]), value, fill=color, font=font)
        # Segoe UI SVG ascender is approximately 0.8 em above its text baseline.
        self.svg.append(
            f'<text x="{x}" y="{y + size * .8}" font-family="Segoe UI, sans-serif" '
            f'font-size="{size}" font-weight="{"700" if bold else "400"}" '
            f'fill="{color}" text-anchor="{anchor}">{escape(value)}</text>'
        )

    def lines(self, x, y, values, size=32, color=INK, bold=False, anchor="start", gap=13):
        for index, value in enumerate(values):
            self.text(x, y + index * (size + gap), value, size, color, bold, anchor)

    def rect(self, x, y, width, height, fill="white", stroke=LINE, radius=16, line_width=3):
        self.draw.rounded_rectangle(
            (x, y, x + width, y + height), radius=radius, fill=fill,
            outline=stroke, width=line_width,
        )
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{line_width}"/>'
        )

    def box(self, x, y, width, height, values, fill=LIGHT, color=INK, size=34):
        self.rect(x, y, width, height, fill)
        total = len(values) * size + (len(values) - 1) * 14
        for index, value in enumerate(values):
            assert self.draw.textlength(value, font=self.font(size, index == 0)) <= width - 28, value
            self.text(
                x + width / 2, y + (height - total) / 2 + index * (size + 14),
                value, size, color, index == 0, "middle",
            )

    def line(self, points, color=TEAL, width=4, dashed=False):
        if dashed:
            for first, last in zip(points, points[1:]):
                dx, dy = last[0] - first[0], last[1] - first[1]
                length = math.hypot(dx, dy)
                for d in range(0, math.ceil(length), 18):
                    a, b = d / length, min(d + 10, length) / length
                    self.draw.line(
                        (first[0] + a * dx, first[1] + a * dy,
                         first[0] + b * dx, first[1] + b * dy),
                        fill=color, width=width,
                    )
        else:
            self.draw.line(points, fill=color, width=width, joint="curve")
        coords = " ".join(f"{x},{y}" for x, y in points)
        dash = 'stroke-dasharray="10 8"' if dashed else ""
        self.svg.append(
            f'<polyline points="{coords}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" {dash}/>'
        )

    def arrow(self, points, color=TEAL, width=5):
        self.line(points, color, width)
        a, b = points[-2:]
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        triangle = [b] + [
            (b[0] - 18 * math.cos(angle) + side * 9 * math.sin(angle),
             b[1] - 18 * math.sin(angle) - side * 9 * math.cos(angle))
            for side in (-1, 1)
        ]
        self.draw.polygon(triangle, fill=color)
        self.svg.append(
            '<polygon points="' + " ".join(f"{x},{y}" for x, y in triangle)
            + f'" fill="{color}"/>'
        )

    def circle(self, x, y, radius=7, fill=TEAL, stroke=TEAL):
        self.draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill, outline=stroke, width=3)
        self.svg.append(
            f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'
        )

    def save(self):
        self.svg.append("</svg>")
        (OUT / f"{self.name}.svg").write_text("\n".join(self.svg) + "\n", encoding="utf-8")
        self.image.save(OUT / f"{self.name}.png", dpi=(254, 254))
        print(self.name)


def signal_chain():
    f = Figure("signal-path", 900)
    f.box(40, 90, 410, 240, ["Будущий датчик", "и кабель", "ёмкостной съём"], fill=PALE)
    f.box(590, 90, 420, 240, ["Аналоговый тракт", "нагрузка и смещение", "фильтрация"])
    f.box(1150, 90, 410, 240, ["STM32 · PA0", "встроенный АЦП", "коды 0…4095"])
    f.arrow([(450, 210), (590, 210)])
    f.text(520, 150, "U_CH1", 33, TEAL, True, "middle")
    f.text(520, 245, "разъём", 27, GRAY, anchor="middle")
    f.arrow([(1010, 210), (1150, 210)])
    f.text(1080, 150, "U_ADC", 33, TEAL, True, "middle")
    f.box(1150, 500, 410, 220, ["USB самой платы", "пакеты данных", "COM в Windows"])
    f.arrow([(1355, 330), (1355, 500)])
    f.text(1380, 390, "raw", 34, TEAL, True)
    f.box(590, 500, 420, 220, ["Приложение V2", "U_CH1 = a × code + b", "если профиль известен"], size=31)
    f.arrow([(1150, 610), (1010, 610)])
    f.box(40, 500, 410, 220, ["Файл записи", "raw, время, разрывы", "и профиль входа"], size=31)
    f.arrow([(590, 610), (450, 610)])
    f.lines(
        40, 780,
        ["U_CH1 — на входном разъёме; U_ADC — на выводе PA0; raw — исходные коды.",
         "Это разные величины. Напряжение на свече в кВ приложение не вычисляет."],
        31, GRAY,
    )
    f.save()


def p1_map():
    f = Figure("p1-map", 1190)
    f.rect(40, 20, 1520, 110, PALE)
    f.lines(68, 40, ["J3: V_A / AGND → питание U1 (pins 4 / 11) и местного TEST.",
                     "V_A должна быть общей с VDDA/Vref+ АЦП; источник и монтаж требуют проверки."], 31, GRAY)
    f.box(40, 205, 430, 250, ["J1: CH1 / AGND", "JP_TEST: TEST или ноль", "TEST: R10–RV1–R11"], size=30)
    f.box(585, 205, 430, 250, ["Делитель", "R1 → IN_MID → R2", "R3 к V_A; R4 к AGND"], size=31)
    f.box(1130, 205, 430, 250, ["U1A · буфер", "SUM → повторитель", "на выходе BUF"], size=33)
    f.arrow([(470, 330), (585, 330)])
    f.text(527, 275, "CH1", 30, TEAL, True, "middle")
    f.arrow([(1015, 330), (1130, 330)])
    f.text(1072, 275, "SUM", 30, TEAL, True, "middle")
    f.arrow([(1345, 455), (1345, 580)])
    f.text(1370, 495, "BUF", 31, TEAL, True)
    f.box(1130, 580, 430, 220, ["U1B · первый ФНЧ", "R5/R6: X1 → Y1", "C1a/C1b и C2"], size=31)
    f.box(585, 580, 430, 220, ["U1C · второй ФНЧ", "R7/R8: X2 → Y2", "C3 и C4"], size=31)
    f.arrow([(1130, 690), (1015, 690)])
    f.text(1072, 633, "LP1", 31, TEAL, True, "middle")
    f.box(40, 580, 430, 220, ["Выходная цепь", "R9: 330 Ом", "C5: 1 нФ к AGND"], size=31)
    f.arrow([(585, 690), (470, 690)])
    f.text(527, 633, "LP2", 31, TEAL, True, "middle")
    f.line([(255, 800), (255, 930), (590, 930)])
    f.text(270, 870, "ADC_NODE", 31, TEAL, True)
    f.circle(590, 930, 10, "white")
    f.circle(715, 930, 10, "white")
    f.text(652, 847, "JP_ADC", 32, INK, True, "middle")
    f.text(652, 967, "снята", 32, RED, True, "middle")
    f.arrow([(725, 930), (1130, 930)])
    f.text(920, 873, "ADC_TARGET", 31, TEAL, True, "middle")
    f.box(1130, 850, 430, 170, ["J2: к PA0 и AGND", "после проверки"], fill=PALE, size=31)
    f.lines(40, 1050,
            ["U1D: повторитель BUF, выход наружу не используется. Общая земля — AGND.",
             "Функциональная карта P1-LV. Не монтажная схема и не вход ёмкостного датчика."],
            30, GRAY)
    f.save()


def dc_shift():
    f = Figure("offset-example", 1110)
    f.text(800, 25, "U_SUM = 0,1198910 × U_CH1 + 1,6814714 В", 40, INK, True, "middle")
    f.text(800, 85, "Условная статическая модель при V_A = 3,300 В", 32, GRAY, anchor="middle")
    left, top, width, height = 165, 190, 1260, 560
    xmin, xmax, ymin, ymax = -16, 16, -0.7, 4.0

    def xy(x, y):
        return left + (x-xmin)/(xmax-xmin)*width, top + (ymax-y)/(ymax-ymin)*height

    y33, y0 = xy(0, 3.3)[1], xy(0, 0)[1]
    f.rect(left, top, width, height, "#fff1eb", stroke=LINE, radius=0, line_width=1)
    f.rect(left, y33, width, y0-y33, "#eaf7f3", stroke="#eaf7f3", radius=0, line_width=1)
    for x in (-10, 0, 10):
        f.line([xy(x, ymin), xy(x, ymax)], "#c0d0d2", 2)
        f.text(xy(x, 0)[0], 773, str(x).replace("-", "−"), 30, GRAY, anchor="middle")
    for y, label in ((0, "0"), (1.65, "1,65"), (3.3, "3,30")):
        f.line([xy(xmin, y), xy(xmax, y)], "#9fbdb9", 2)
        f.text(145, xy(0, y)[1]-17, label, 31, GRAY, anchor="end")
    f.text(170, 135, "U_SUM, В", 32, TEAL, True)
    f.text(1450, 776, "U_CH1, В", 32, TEAL, True, "end")
    f.text(190, y33+20, "Коридор АЦП: 0…V_A", 30, GRAY)
    k, b = .1198910081743869, 1.6814713896457766
    crosses = [(0-b)/k, (3.3-b)/k]
    f.line([xy(xmin, k*xmin+b), xy(crosses[0], 0)], RED, 4, True)
    f.line([xy(crosses[0], 0), xy(crosses[1], 3.3)], TEAL, 6)
    f.line([xy(crosses[1], 3.3), xy(xmax, k*xmax+b)], RED, 4, True)
    for x in (-10, 0, 10):
        f.circle(*xy(x, k*x+b), 8)
    z = xy(0, b)
    f.text(z[0]+25, z[1]+35, "0 В → 1,681 В", 32, TEAL, True)
    f.lines(40, 850,
            ["Пример: −10 В → 0,483 В; 0 В → 1,681 В; +10 В → 2,880 В.",
             "При постоянном уровне идеальные буферы и ФНЧ дают U_ADC = U_SUM.",
             "Выход за 0…V_A не даёт достоверного результата: возникает насыщение."],
            31, GRAY)
    f.text(40, 1035, "±10 В здесь — расчётные точки, а не разрешение подключать такое напряжение.", 31, RED, True)
    f.save()


def p0_map():
    f = Figure("p0-map", 1170)
    f.box(40, 70, 280, 180, ["BNC · CH1", "U_CH1", "экран: AGND"], size=31)
    f.box(450, 70, 320, 180, ["R1 + R2", "51 + 51 кОм", "всего 102 кОм"], size=31)
    f.box(1090, 70, 470, 180, ["OPA140 · буфер", "проектное питание ±15 В", "выход BUF"], size=31)
    f.arrow([(320, 160), (450, 160)])
    f.circle(380, 160)
    f.arrow([(770, 160), (1090, 160)])
    f.text(930, 103, "HI_Z", 33, TEAL, True, "middle")
    f.circle(930, 160)
    f.line([(380, 160), (380, 355)])
    f.box(40, 355, 470, 225, ["RLOAD → AGND", "10 / 100 МОм", "стоит до 102 кОм"], size=33)
    f.line([(930, 160), (930, 355)])
    f.box(620, 355, 940, 225,
          ["Два ограничителя PAD1", "HI_Z ↔ CLAMP_P10 / CLAMP_N10",
           "LM4040A-10: шины ±10 В относительно AGND"], fill=PALE, size=32)
    f.arrow([(1545, 250), (1580, 250), (1580, 680), (1330, 680), (1330, 710)])
    f.text(1440, 630, "BUF", 32, TEAL, True)
    f.box(1090, 710, 470, 210, ["Смещение + диапазоны", "TLV9064 · VDDA", "±0,5 / ±2 / ±10 В*"], size=31)
    f.box(540, 710, 410, 210, ["ФНЧ", "две секции", "около 3 кГц*"], size=33)
    f.arrow([(1090, 815), (950, 815)])
    f.text(1020, 745, "GAIN_OUT", 25, TEAL, True, "middle")
    f.box(40, 710, 360, 210, ["Выход к ADC", "330 Ом + 1 нФ", "ADC_NODE"], size=32)
    f.arrow([(540, 815), (400, 815)])
    f.text(470, 755, "LP2", 31, TEAL, True, "middle")
    f.lines(40, 980,
            ["* Проектные диапазоны и полоса; физическая проверка не выполнена.",
             "P0 — отдельный высокоомный проект. Питание ±15 В пока не подготовлено.",
             "Защита при выключении и пригодность для зажигания остаются непроверенными."],
            31, GRAY)
    f.save()


def opamp_follower():
    f = Figure("opamp-follower", 880)
    triangle = [(580, 230), (580, 530), (890, 380)]
    f.draw.polygon(triangle, fill=LIGHT, outline=INK, width=5)
    f.svg.append(
        '<polygon points="580,230 580,530 890,380" '
        f'fill="{LIGHT}" stroke="{INK}" stroke-width="5"/>'
    )
    f.text(602, 300, "+", 50, INK, True)
    f.text(602, 420, "−", 50, INK, True)
    f.text(700, 356, "ОУ", 48, TEAL, True)
    f.arrow([(130, 330), (580, 330)])
    f.text(130, 250, "Сигнал → вход «+»", 35, TEAL, True)
    f.arrow([(890, 380), (1420, 380)])
    f.text(1110, 300, "Выход → дальше", 35, TEAL, True)
    f.circle(1050, 380)
    f.arrow([(1050, 380), (1050, 600), (480, 600), (480, 440), (580, 440)])
    f.text(720, 635, "Обратная связь: выход соединён со входом «−»", 33, INK, anchor="middle")
    f.line([(735, 170), (735, 305)], GRAY, 4)
    f.line([(735, 455), (735, 535)], GRAY, 4)
    f.text(735, 100, "V_A", 37, GRAY, True, "middle")
    f.text(760, 185, "питание", 30, GRAY)
    f.text(735, 550, "AGND", 31, GRAY, True, "middle")
    f.lines(60, 730,
            ["Идеально: U_выход ≈ U_вход. Повторитель отделяет делитель от следующей нагрузки.",
             "Вход «−» и нижняя шина питания AGND — разные выводы."],
            32, GRAY)
    f.save()


def op_symbol(f, x, y, width=180, height=180, ref="ОУ"):
    vertices = [(x, y-height/2), (x, y+height/2), (x+width, y)]
    f.draw.polygon(vertices, fill=LIGHT, outline=INK, width=4)
    f.svg.append(
        '<polygon points="' + " ".join(f"{a},{b}" for a, b in vertices)
        + f'" fill="{LIGHT}" stroke="{INK}" stroke-width="4"/>'
    )
    for sign, center in (("+", y-37), ("−", y+37)):
        bounds=f.font(38, True).getbbox(sign)
        f.text(x+16, center-(bounds[3]-bounds[1])/2, sign, 38, INK, True)
    f.text(x+66, y-16, ref, 33, TEAL, True)


def resistor_horizontal(f, x1, x2, y, ref, value=None):
    center = (x1+x2)/2
    f.line([(x1, y), (center-50, y)], INK, 4)
    f.rect(center-50, y-18, 100, 36, "white", INK, radius=0, line_width=4)
    f.line([(center+50, y), (x2, y)], INK, 4)
    f.text(center, y-106 if value else y-70, ref, 34, INK, True, "middle")
    if value:
        f.text(center, y-61, value, 32, INK, anchor="middle")


def resistor_vertical(f, x, y1, y2, ref, value):
    center=(y1+y2)/2
    f.line([(x, y1), (x, center-39)], INK, 4)
    f.rect(x-18, center-39, 36, 78, "white", INK, radius=0, line_width=4)
    f.line([(x, center+39), (x, y2)], INK, 4)
    f.lines(x+40, center-42, [ref, value], 32, INK)


def ground_symbol(f, x, y):
    f.line([(x, y-18), (x, y)], INK, 4)
    for delta, half in ((0, 26), (10, 18), (20, 8)):
        f.line([(x-half, y+delta), (x+half, y+delta)], INK, 4)
    f.text(x+40, y-8, "AGND", 31, GRAY)


def divider():
    f=Figure("p1-divider", 730)
    y=310
    f.text(80, 248, "CH1", 36, TEAL, True)
    resistor_horizontal(f, 80, 430, y, "R1", "510 кОм")
    resistor_horizontal(f, 430, 790, y, "R2", "510 кОм")
    f.text(435, 354, "IN_MID", 31, TEAL, True, "middle")
    f.line([(790, y), (1180, y)], INK, 4)
    f.circle(820, y, fill=INK, stroke=INK)
    f.text(955, 259, "SUM", 36, TEAL, True, "middle")
    f.text(820, 25, "V_A", 36, GRAY, True, "middle")
    resistor_vertical(f, 820, 80, 310, "R3", "240 кОм")
    resistor_vertical(f, 820, 310, 520, "R4", "330 кОм")
    ground_symbol(f, 820, 540)
    op_symbol(f, 1180, 347, ref="U1A")
    # The inputs are separate from the power rails; only functional signal pins
    # are shown here, consistent with the dedicated follower illustration.
    f.line([(1360, 347), (1520, 347)], INK, 4)
    f.text(1480, 282, "BUF", 36, TEAL, True, "middle")
    f.circle(1420, 347, fill=INK, stroke=INK)
    f.line([(1420, 347), (1420, 527), (1100, 527), (1100, 384), (1180, 384)], INK, 4)
    f.lines(40, 615,
            ["SUM задаётся тремя ветвями: от CH1, от V_A и к AGND.",
             "U1A повторяет SUM и отделяет делитель от следующей нагрузки."],
            33, GRAY)
    f.save()


def sallen_key():
    f=Figure("sallen-key", 780)
    y=340
    f.text(80, 280, "IN", 36, TEAL, True)
    resistor_horizontal(f, 80, 510, y, "Ra")
    resistor_horizontal(f, 510, 880, y, "Rb")
    f.line([(880, y), (1120, y)], INK, 4)
    f.circle(520, y, fill=INK, stroke=INK)
    f.circle(900, y, fill=INK, stroke=INK)
    f.text(520, 377, "X", 36, TEAL, True, "middle")
    f.text(900, 280, "Y", 36, TEAL, True, "middle")
    # Cf connects intermediate node X to OUT; it does not go to ground.
    f.line([(520, y), (520, 130), (965, 130)], INK, 4)
    f.line([(965, 103), (965, 157)], INK, 4)
    f.line([(981, 103), (981, 157)], INK, 4)
    f.line([(981, 130), (1440, 130), (1440, 377)], INK, 4)
    f.text(973, 61, "Cf", 36, TEAL, True, "middle")
    op_symbol(f, 1120, 377)
    f.line([(1300, 377), (1530, 377)], INK, 4)
    f.circle(1440, 377, fill=INK, stroke=INK)
    f.text(1490, 310, "OUT", 36, TEAL, True, "middle")
    f.circle(1350, 377, fill=INK, stroke=INK)
    f.line([(1350, 377), (1350, 545), (1040, 545), (1040, 414), (1120, 414)], INK, 4)
    f.line([(900, y), (900, 460)], INK, 4)
    f.line([(873, 460), (927, 460)], INK, 4)
    f.line([(873, 476), (927, 476)], INK, 4)
    f.line([(900, 476), (900, 565)], INK, 4)
    f.text(942, 447, "Cg", 36, TEAL, True)
    ground_symbol(f, 900, 583)
    f.lines(40, 657,
            ["Ra/Rb — резисторы. Cf соединяет X с OUT; Cg соединяет Y с AGND.",
             "Точки обозначают соединения. Замена подключения Cf меняет работу фильтра."],
            32, GRAY)
    f.save()


if __name__ == "__main__":
    signal_chain()
    p1_map()
    dc_shift()
    p0_map()
    opamp_follower()
    divider()
    sallen_key()
