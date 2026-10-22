"""Read-only checks of the reviewed document package; no author regeneration."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    guide = json.loads((HERE / 'guide-evidence.json').read_text(encoding='utf-8'))
    results = []

    def check(name, ok, detail):
        results.append({'name': name, 'pass': bool(ok), 'detail': detail})
        assert ok, (name, detail)

    doc = ROOT / guide['document']['path']
    check('final_docx_sha256', sha(doc.read_bytes()) == guide['document']['sha256'], sha(doc.read_bytes()))
    source_matches = {p: sha((ROOT / p).read_bytes()) == value for p, value in guide['source_files'].items()}
    check('guide_sources_match_evidence', all(source_matches.values()), source_matches)
    page_matches = {p: sha((ROOT / guide['render_path'] / p).read_bytes()) == value
                    for p, value in guide['page_png_sha256'].items()}
    check('all_29_personally_reviewed_pages_match_evidence', len(page_matches) == 29 and all(page_matches.values()), page_matches)
    with zipfile.ZipFile(doc) as z:
        media = {p: sha(z.read(p)) for p in z.namelist() if p.startswith('word/media/')}
        check('embedded_media_matches_sources', media == guide['embedded_media_sha256'] and
              all(v in guide['source_files'].values() for v in media.values()), media)
        xml = ET.fromstring(z.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        counts = {'tables': len(xml.findall('.//w:tbl', ns)), 'figures': len(xml.findall('.//w:drawing', ns))}
        check('docx_table_figure_counts', counts == {'tables': 14, 'figures': 13}, counts)
    arithmetic = json.loads((HERE / 'critic-check.json').read_text(encoding='utf-8'))
    calc = ROOT / 'hardware/v2-input/p1-lv/calculations.json'
    check('independent_arithmetic_is_current', sha(calc.read_bytes()) == arithmetic['calculations_sha256'],
          {'sha256': sha(calc.read_bytes()), 'comparisons': len(arithmetic['checks'])})

    # Only changed Markdown plus this iteration's evidence/README and the guide;
    # no HTTP requests, and anchor meaning is reviewed separately by the critic.
    changed = subprocess.check_output(['git', 'diff', '--name-only', '--', '*.md'], cwd=ROOT, text=True).splitlines()
    new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', '*.md'], cwd=ROOT, text=True).splitlines()
    paths = sorted(set(changed + new))
    missing = []
    count = 0
    for name in paths:
        p = ROOT / name
        for match in re.finditer(r'!?\[[^\]\n]*\]\(([^\s\)]+)(?:\s+"[^"\n]*")?\)', p.read_text(encoding='utf-8')):
            target = match.group(1).strip('<>')
            if re.match(r'^[a-zA-Z][\w+.-]*:', target) or target.startswith('#'):
                continue
            target = urllib.parse.unquote(target.split('#')[0])
            if not target:
                continue
            count += 1
            if not (p.parent / target).exists():
                missing.append({'source': name, 'target': target})
    check('changed_markdown_local_targets_exist', not missing, {'files': paths, 'links': count, 'missing': missing})
    diff = subprocess.run(['git', 'diff', '--check'], cwd=ROOT, capture_output=True, text=True)
    check('git_diff_check', diff.returncode == 0, {'returncode': diff.returncode, 'stdout': diff.stdout})
    output = {'scope': 'Package identity and local link checks, no rendering/model regeneration or physical tests',
              'result': 'PASS', 'checks': results}
    (HERE / 'critic-final-check.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'result': 'PASS', 'checks': len(results), 'pages': len(page_matches), 'local_links': count}))


if __name__ == '__main__':
    main()
