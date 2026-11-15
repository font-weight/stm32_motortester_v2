"""Create a 1:1 four-page R5.3 print set from frozen native KiCad geometry.

Run with Codex bundled Python (reportlab, pypdf). The board is read-only.
Native B.Cu vectors are translated or reflected, never scaled. Reflection is
used ONLY on the inspection page; toner page retains KiCad top-view geometry.
"""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import copy
import hashlib
import json
import subprocess
import tempfile
import pdfplumber
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "hardware/v2-input/r53-compact-20261102"
BOARD = DIR / "analog-input-r53.kicad_pcb"
OUT = DIR / "print"
CLI = Path("D:/Programs/bin/kicad-cli.exe")
KIPY = Path("D:/Programs/bin/python.exe")
POPPLER = Path("C:/Users/Alexandr/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe")
BX, BY = 34 * mm, 120 * mm
PW, PH = A4


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata():
    code = r'''
import pcbnew,sys,json
b=pcbnew.LoadBoard(sys.argv[1]);edges=[];parts=[];holes=[];wires=[]
def pt(p):return [pcbnew.ToMM(p.x),pcbnew.ToMM(p.y)]
for d in b.GetDrawings():
 if d.GetLayer()==pcbnew.Edge_Cuts:edges += [pt(d.GetStart()),pt(d.GetEnd())]
for f in b.GetFootprints():
 ref=f.GetReference();pads=[]
 for p in f.Pads():
  h=pcbnew.ToMM(p.GetDrillSize().x)
  entry={'ref':ref,'number':p.GetNumber(),'xy':pt(p.GetPosition()),'drill':h}
  pads.append(entry)
  if h>0:holes.append(entry)
 parts.append({'ref':ref,'xy':pt(f.GetPosition()),'label_xy':pt(f.Reference().GetPosition()),'pads':pads,'bottom':f.GetLayer()==pcbnew.B_Cu})
 if ref.startswith('W'):
  segments=[[pt(g.GetStart()),pt(g.GetEnd())] for g in f.GraphicalItems() if g.GetLayer() in [pcbnew.F_Fab,pcbnew.B_Fab] and isinstance(g,pcbnew.PCB_SHAPE) and g.GetShape()==pcbnew.SHAPE_T_SEGMENT]
  wires.append({'ref':ref,'ends':[p['xy'] for p in pads],'bottom':f.GetLayer()==pcbnew.B_Cu,'segments':segments})
print(json.dumps({'edges':edges,'parts':parts,'holes':holes,'wires':wires}))
'''
    run = subprocess.run([str(KIPY), "-c", code, str(BOARD)], capture_output=True, text=True, check=True)
    data = json.loads(run.stdout)
    xs, ys = zip(*data["edges"])
    data["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
    data["size"] = [max(xs)-min(xs), max(ys)-min(ys)]
    assert 0 < data["size"][0] < 170 and 0 < data["size"][1] < 100
    return data


def native_pdf(path, layers, sketch=False, drill=2):
    command = [str(CLI), "pcb", "export", "pdf", "--layers", layers,
               "--mode-single", "--scale", "1", "--black-and-white",
               "--exclude-value", "--no-property-popups", "--drill-shape-opt", str(drill),
               "--output", str(path)]
    if sketch:
        command.append("--sketch-pads-on-fab-layers")
    command.append(str(BOARD))
    subprocess.run(command, check=True, capture_output=True, text=True)
    reader = PdfReader(path)
    assert len(reader.pages) == 1
    return reader.pages[0]


def line(c, text, y, bold=False, size=9):
    c.setFont("ArialBold" if bold else "Arial", size)
    c.drawString(18 * mm, y * mm, text)


def ruler(c):
    x, y = 34 * mm, 108 * mm
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.22 * mm)
    c.line(x, y, x + 100 * mm, y)
    for tick in range(0, 101, 10):
        height = 3 if tick % 50 == 0 else 1.8
        c.line(x + tick * mm, y, x + tick * mm, y - height * mm)
    c.setFont("Arial", 8)
    c.drawString(x, y - 7 * mm, "0")
    c.drawRightString(x + 100 * mm, y - 7 * mm, "100 мм")
    c.drawString(34 * mm, 96 * mm, "После печати измерьте линейку: должно быть ровно 100 мм.")


def map_xy(data, point):
    xmin, ymin, xmax, ymax = data["bbox"]
    return BX + (point[0] - xmin) * mm, BY + (ymax - point[1]) * mm


def overlays(c, data, page):
    if page not in (2, 3, 4):
        return
    if page == 2:
        c.setStrokeColorRGB(0.05, 0.6, 1.0)
        c.setLineWidth(0.55 * mm)
        c.setDash(1.5 * mm, 0.8 * mm)
        xmin, ymin, xmax, ymax = data['bbox']
        for w in data['wires']:
            if w['bottom']:
                for a,b in w['segments']:
                    c.line(BX+(xmax-a[0])*mm,BY+(ymax-a[1])*mm,
                           BX+(xmax-b[0])*mm,BY+(ymax-b[1])*mm)
        c.setDash()
        # Ground landing pads are merged into the pour and invisible in a
        # copper-only view. Blue circles identify real Ø3 mm solder locations;
        # these are surface pads, not holes. Keep labels off the copper drawing.
        callouts={'W8':(-18,53),'W4':(-18,39),'W6':(90,48),
                  'W9':(90,34),'W5':(90,21),'W7':(90,5)}
        for w in data['wires']:
            if not w['bottom']:continue
            c.setStrokeColorRGB(0.05,0.5,0.85);c.setFillColorRGB(0.04,0.24,0.55)
            c.setLineWidth(.15*mm)
            for px,py in w['ends']:
                c.circle(BX+(xmax-px)*mm,BY+(ymax-py)*mm,1.5*mm,stroke=1,fill=0)
            dx,dy=callouts[w['ref']]
            tx,ty=BX+dx*mm,BY+dy*mm
            segment=max(w['segments'],key=lambda ab:(ab[1][0]-ab[0][0])**2+(ab[1][1]-ab[0][1])**2)
            mx=sum(pt[0] for pt in segment)/2;my=sum(pt[1] for pt in segment)/2
            c.line(tx+2*mm,ty-1*mm,BX+(xmax-mx)*mm,BY+(ymax-my)*mm)
            c.setFont('ArialBold',8);c.drawString(tx,ty,w['ref'])
        c5 = next(p for p in data["parts"] if p["ref"] == "C5")
        xmin, ymin, xmax, ymax = data["bbox"]
        x = BX + (xmax - c5["xy"][0]) * mm
        y = BY + (ymax - c5["xy"][1]) * mm
        c.setStrokeColorRGB(0.1, 0.4, 0.85)
        c.setFillColorRGB(0.05, 0.25, 0.55)
        c.setLineWidth(0.25 * mm)
        c.rect(x - mm, y - 0.625 * mm, 2 * mm, 1.25 * mm, stroke=1, fill=0)
        c.line(27 * mm, y + 2 * mm, x - 1.5 * mm, y)
        c.setFont("ArialBold", 7)
        c.drawString(18 * mm, y + 5 * mm, "C5 / 0805")
        c.drawString(18 * mm, y + 2 * mm, "снизу")
    elif page == 3:
        c.setStrokeColorRGB(0.04, 0.24, 0.55)
        c.setLineWidth(0.55 * mm)
        c.setDash(1.5 * mm, 0.8 * mm)
        for w in data["wires"]:
            if not w['bottom']:
                for segment in w['segments']:
                    a, b = [map_xy(data, p) for p in segment]
                    c.line(*a, *b)
        c.setDash()
        c.setFillColorRGB(0.04, 0.24, 0.55)
        c.setFont("ArialBold", 5.5)
        c5 = next(p for p in data["parts"] if p["ref"] == "C5")
        x, y = map_xy(data, c5["xy"])
        c.rect(x - mm, y - 0.625 * mm, 2 * mm, 1.25 * mm, stroke=1, fill=0)
        c.drawCentredString(x, y - 3 * mm, "C5 СНИЗУ")
    else:
        c.setStrokeColorRGB(0, 0, 0)
        c.setFillColorRGB(0, 0, 0)
        c.setLineWidth(0.12 * mm)
        for hole in data["holes"]:
            x, y = map_xy(data, hole["xy"])
            radius = hole["drill"] * mm / 2
            c.circle(x, y, radius, stroke=1, fill=0)
            cross = max(radius, 0.65 * mm)
            c.line(x - cross, y, x + cross, y)
            c.line(x, y - cross, x, y + cross)
        c.setFont("Arial", 6.3)
        for part in data["parts"]:
            if part["bottom"]:
                continue
            x, y = map_xy(data, part["label_xy"])
            if part["ref"].startswith("H"):
                x += 5 * mm if part["xy"][0] < (data["bbox"][0] + data["bbox"][2]) / 2 else -5 * mm
            if part['ref']=='C10':
                c.saveState();c.translate(x,y);c.rotate(90)
                c.drawCentredString(0,-2,part['ref']);c.restoreState()
            else:c.drawCentredString(x, y - 2, part["ref"])
        u1 = next(p for p in data["parts"] if p["ref"] == "U1")
        p4 = next(p for p in u1["pads"] if p["number"] == "4")
        p11 = next(p for p in u1["pads"] if p["number"] == "11")
        a, b = map_xy(data, p4["xy"]), map_xy(data, p11["xy"])
        assert abs(p11["xy"][0] - p4["xy"][0] - 15.24) < 1e-6
        c.setStrokeColorRGB(0.05, 0.28, 0.55)
        c.setFillColorRGB(0.05, 0.28, 0.55)
        c.setLineWidth(0.15 * mm)
        c.line(a[0], a[1], b[0], b[1])
        for x in (a[0], b[0]):
            c.line(x, a[1] - 1.2 * mm, x, a[1] + 1.2 * mm)
        c.setFont("ArialBold", 5.7)
        c.drawCentredString((a[0] + b[0]) / 2, a[1] + 1.1 * mm, "15,24 мм")


def make_text_pages(path, data, board_sha, annotations=False):
    c = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    titles = ["1. ЛУТ: шаблон переноса тонера", "2. Осмотр меди снизу",
              "3. Монтаж: вид сверху", "4. Примерка и сверление: вид сверху"]
    for page, title in enumerate(titles, 1):
        if annotations:
            overlays(c, data, page)
            c.showPage()
            continue
        c.setTitle("R5.3 - печатные карты 1:1")
        line(c, "МОТОРТЕСТЕР V2 / АНАЛОГОВЫЙ ВХОД R5.3", 281, True, 9)
        line(c, title, 270, True, 16)
        line(c, "A4, масштаб 100% (1:1). Отключите «вписать», «уместить» и зеркальность.", 260, False, 9)
        line(c, f"Габарит платы: {data['size'][0]:g} × {data['size'][1]:g} мм. Карты в натуральном размере.", 254)
        if page == 1:
            line(c, "Печатать для ЛУТ только эту страницу. Это B.Cu в виде сверху, без зеркала.", 244, True)
            line(c, "Приложите отпечатанную сторону бумаги тонером к меди; перенос сам зеркалит рисунок.", 238, False, 8.5)
            line(c, "Чёрное = оставить медь. Белые центры отверстий служат ориентиром сверления.", 232)
        elif page == 2:
            line(c, "НЕ ШАБЛОН ЛУТ. Здесь изображение уже зеркальное: физический вид снизу.", 244, True)
            line(c, "Сравнивайте с медью, когда смотрите на обратную сторону готовой платы.", 238)
            line(c, "Синий пунктир = изолированные провода снизу, если они есть; это не медные дорожки.", 232, False, 8.5)
            line(c, "Синие круги W4-W9 = места пайки Ø3 мм, без отверстий. Не сверлить.", 226, False, 8.5)
        elif page == 3:
            line(c, "Сверху: выводные детали и обозначенные верхние монтажные перемычки.", 244, True, 8.8)
            line(c, "Установить все перемычки W на указанной стороне: см. страницы 2 и 3.", 238)
            line(c, "Синий пунктир = провода, не медь. C5 (0805) устанавливается снизу.", 232)
        else:
            line(c, "Приложите реальные детали к распечатке до изготовления платы.", 244, True)
            line(c, "Кресты отмечают центры отверстий; окружности показывают их диаметр.", 238)
            line(c, "Ряды переходника U1: 15,24 мм. Шаг контактов U1: 2,54 мм.", 232)
        ruler(c)
        if page == 1:
            notes = ["Контроль ориентации: J1 (вход) слева на этом отпечатке.",
                     "Не печатайте из PNG-превью: используйте этот PDF с масштабом 100%.",
                     "До травления проверьте размеры и расположение своих деталей по странице 4."]
        elif page == 2:
            notes = ["Контроль ориентации: вход J1 теперь справа — это физический вид снизу.",
                     "Проверьте отсутствие замыканий, обрывов и непротравленных перемычек.",
                     "Форма рисунка не подтверждает работоспособность или защиту аналогового входа."]
        elif page == 3:
            notes = ["Номера площадок важнее положения на рисунке; вид снизу зеркален этому виду.",
                     "S2: 1-2 = WIDE; 2-3 = SENSITIVE, только вместе с AC. JP1 отключает сигнал АЦП.",
                     "Схему подключения внешних разъёмов и S1 смотрите в монтажной инструкции."]
        else:
            counts = Counter(round(h["drill"], 3) for h in data["holes"])
            hole_text = "; ".join(f"Ø{format(d, 'g').replace('.', ',')} мм: {n} шт." for d, n in sorted(counts.items()))
            mounting_refs = ", ".join(sorted(p['ref'] for p in data['parts'] if p['ref'].startswith('H')))
            notes = [hole_text,
                     "Ø0,8: все R и C6-C11. Ø0,9: C1-C4. Ø1: U1, S2, JP1 и W1-W3.",
                     f"Ø1,1: J1, J2, J3 и S1. Ø3,2: {mounting_refs}. C5 и W4-W9 не сверлить.",
                     f"Всего на карте: {len(data['holes'])} отверстий. Перемычек W: {len(data['wires'])}.",
                     "Требуют примерки: C10/C11, остальные фактические корпуса и выступы адаптера U1."]
        for i, note in enumerate(notes):
            line(c, note, 85 - i * 6, False, 8.3)
        line(c, "Плата не проверена физически. Изготовление - после проверки посадок и итогового комплекта.", 52, False, 8)
        line(c, "Шаблон не устанавливает допустимые напряжения и не разрешает подключение к автомобилю.", 46, False, 8)
        line(c, "Источник: неизменённая схема R5.1; новая компоновка R5.3, 02.11.2026.", 30, False, 7.6)
        line(c, "SHA-256 PCB: " + board_sha[:32] + "...", 24, False, 7.6)
        c.setFont("Arial", 8)
        c.drawRightString(192 * mm, 15 * mm, f"{page} / 4")
        c.showPage()
    c.save()


def place_native(target, native, bbox, mirror=False):
    xmin, ymin, xmax, ymax = bbox
    src = copy.deepcopy(native)
    height = float(src.mediabox.height)
    source_bottom = height - ymax * mm
    src.cropbox = RectangleObject([(xmin - 0.6) * mm, source_bottom - 0.6 * mm,
                                  (xmax + 0.6) * mm, height - (ymin - 0.6) * mm])
    if mirror:
        matrix = (-1, 0, 0, 1, BX + xmax * mm, BY - source_bottom)
    else:
        matrix = (1, 0, 0, 1, BX - xmin * mm, BY - source_bottom)
    target.merge_transformed_page(src, Transformation(matrix), over=True)
    return list(matrix)


def main():
    global BX, BY
    OUT.mkdir(exist_ok=True)
    before = sha(BOARD)
    data = metadata()
    BX = (210-data["size"][0])/2*mm
    BY = (340-data["size"][1])/2*mm
    pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
    pdfmetrics.registerFont(TTFont("ArialBold", "C:/Windows/Fonts/arialbd.ttf"))
    final = OUT / "R53_LUT_assembly_fit_1to1.pdf"
    with tempfile.TemporaryDirectory(prefix="r53-print-") as temp:
        temp = Path(temp)
        copper = native_pdf(temp / "copper.pdf", "B.Cu", drill=1)
        inspection = native_pdf(temp / "inspection.pdf", "B.Cu,B.Fab,B.Silkscreen", drill=1)
        assembly = native_pdf(temp / "assembly.pdf", "F.Fab,F.Silkscreen,Edge.Cuts", sketch=True)
        fit = native_pdf(temp / "fit.pdf", "F.Fab,Edge.Cuts", drill=0)
        make_text_pages(temp / "base.pdf", data, before)
        make_text_pages(temp / "overlays.pdf", data, before, annotations=True)
        base = PdfReader(temp / "base.pdf")
        overlay = PdfReader(temp / "overlays.pdf")
        writer = PdfWriter()
        matrices = []
        for i, native in enumerate((copper, inspection, assembly, fit)):
            target = base.pages[i]
            matrices.append(place_native(target, native, data["bbox"], mirror=i == 1))
            target.merge_page(overlay.pages[i], over=True)
            writer.add_page(target)
        writer.add_metadata({"/Title": "R5.3 - ЛУТ, монтаж, примерка. Масштаб 1:1",
                             "/Author": "Motortester V2", "/Subject": "PCB SHA256 " + before})
        with final.open("wb") as fp:
            writer.write(fp)
    assert sha(BOARD) == before, "Input board changed during read-only export"
    reread = PdfReader(final)
    assert len(reread.pages) == 4
    for page in reread.pages:
        assert abs(float(page.mediabox.width) - PW) < 1e-3
        assert abs(float(page.mediabox.height) - PH) < 1e-3
    # Verify vectors in the finished PDF, independently of the nominal constants:
    # the full board edge and ruler must retain their physical lengths after merge.
    with pdfplumber.open(final) as parsed:
        edges = parsed.pages[3].edges
        horizontal = [e for e in edges if abs(e.get("height", 0)) < 0.01]
        vertical = [e for e in edges if abs(e.get("width", 0)) < 0.01]
        w_error = min(abs(e["width"] / mm - data["size"][0]) for e in horizontal)
        h_error = min(abs(e["height"] / mm - data["size"][1]) for e in vertical)
        ruler_errors = []
        for page in parsed.pages:
            ruler_errors.append(min(abs(e["width"] / mm - 100) for e in page.edges
                                    if abs(e.get("height", 0)) < 0.01))
        assert max([w_error, h_error] + ruler_errors) < 0.001
    subprocess.run([str(POPPLER), "-r", "160", "-png", str(final), str(OUT / "preview")], check=True)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "board_sha256": before, "board_not_modified": sha(BOARD) == before,
        "output_pdf_sha256": sha(final), "output_pdf": final.name,
        "pages": 4, "page_mm": [210, 297], "board_mm": data["size"],
        "source_board_bbox_mm": data["bbox"], "board_bottom_left_on_page_mm": [BX / mm, BY / mm],
        "native_scale": 1, "merge_affine_matrices": matrices,
        "mirror_pages_only": [2], "toner_page": 1,
        "toner_native_layers": "B.Cu", "toner_drill_shape_option": 1,
        "inspection_native_layers": "B.Cu,B.Fab,B.Silkscreen",
        "fit_native_drill_shape_option": 0, "fit_holes": "Exact source drill diameter circle and center cross overlay",
        "ruler_vector_length_points": 100 * mm, "ruler_length_mm": 100,
        "finished_pdf_vector_checks_mm": {"board_width_error": w_error, "board_height_error": h_error,
                                           "ruler_errors_each_page": ruler_errors},
        "note": "PDF coordinate scale and transforms checked; physical printer scale and toner transfer still require user ruler check. Visual review recorded separately.",
        "holes_by_diameter_mm": dict(sorted(Counter(str(round(h["drill"], 3)) for h in data["holes"]).items())),
        "wires": data["wires"],
        "mandatory_jumpers": [w['ref'] for w in data['wires']],
    }
    (OUT / "print-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pdf": str(final), "sha256": sha(final), "board_sha256": before, "pages": 4}, ensure_ascii=False))


if __name__ == "__main__":
    main()
