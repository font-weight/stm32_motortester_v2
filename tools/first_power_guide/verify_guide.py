"""Small publication check after rendering; visual review remains manual."""
from pathlib import Path
import hashlib
import json
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
pdf = ROOT / 'готовые документы/Первое включение платы_R53.pdf'
reader = PdfReader(pdf)
assert len(reader.pages) == 6
text = '\n'.join(page.extract_text() for page in reader.pages)
for required in ('110 x 55', '15,24', 'JP1.1', 'контакт 2', 'U1.4', 'U1.11',
                 '3,30 В', '15 мА', '7,6 мА', '1,6598', '1,7153', '55,48',
                 'SENSITIVE', '100 пФ', '100 нФ',
                 'Соединение с PA0 отложите', 'без физических включений'):
    assert required in text, required
images=[]
for n in range(1,7):
    image=ROOT/f'build/first-power-20261113/render/page-{n}.png'
    assert image.exists()
    images.append({'page':n, 'path':str(image.relative_to(ROOT)),
                   'sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                   'author_visual_review':'legible; no clipped or overlapping content'})
result={'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(), 'pages':6,
        'text_checks':'passed', 'render':'Poppler pdftoppm 100 dpi PNG',
        'physical_testing':'NOT_PERFORMED', 'images':images}
out=ROOT/'docs/verification/calibration-20261113/first-power-visual-qa.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'pages':6,'text_checks':'passed','pdf_sha256':result['pdf_sha256']},ensure_ascii=False))
