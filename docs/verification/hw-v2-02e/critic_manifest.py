"""Verify a fixed review snapshot; --write is only for the assigned critic."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
MANIFEST = HERE / 'manifest.json'
BASE = '50dcb5f4e0ff38a93e1ef718efbfd2fbb8133725'
TEXT = {'.md', '.py', '.json', '.svg', '.csv', '.txt'}


def digest(path):
    raw = path.read_bytes()
    normalized = raw.replace(b'\r\n', b'\n') if path.suffix in TEXT else raw
    return {'mode': 'sha256-crlf-to-lf' if path.suffix in TEXT else 'sha256-raw',
            'sha256': hashlib.sha256(normalized).hexdigest(),
            'observed_raw_sha256': hashlib.sha256(raw).hexdigest()}


def write():
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE], cwd=ROOT, text=True).splitlines()
    new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    guide = json.loads((HERE / 'guide-evidence.json').read_text(encoding='utf-8'))
    files = set(changed + new + list(guide['source_files']))
    files.update(['AGENTS.md', 'docs/quality-gate.md', 'docs/legacy-notice.md',
                  'docs/mvp-spec.md', 'docs/verification/hw-v2-02d/critic_check.py',
                  'docs/verification/hw-v2-02d/model-notes.md',
                  'hardware/v2-input/p1-lv/measurement-template.csv'])
    files.discard(MANIFEST.relative_to(ROOT).as_posix())
    records = {name: digest(ROOT / name) for name in sorted(files) if (ROOT / name).is_file()}
    output = {'iteration': 'HW-V2-02e', 'base_sha': BASE, 'critic': '/root/p1_r3_critic',
              'verdict': 'PASS', 'score': 9.74,
              'hash_policy': 'Primary sha256 normalizes CRLF to LF for listed text suffixes only; all other bytes stay exact. Binary artifacts use raw SHA256. observed_raw_sha256 records the reviewed Windows working-tree bytes but is not the portable pass criterion. No claim that these SHA256 values are Git object IDs.',
              'text_suffixes': sorted(TEXT),
              'verification_command': '.venv/Scripts/python.exe -B docs/verification/hw-v2-02e/critic_manifest.py',
              'excluded': ['manifest.json itself to avoid a hash cycle', 'build render pages: individually hashed in guide-evidence.json'],
              'files': records}
    MANIFEST.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'manifest_written': len(records)}))


def verify():
    output = json.loads(MANIFEST.read_text(encoding='utf-8'))
    failed = []
    raw_different = []
    for name, expected in output['files'].items():
        path = ROOT / name
        if not path.exists():
            failed.append(name + ': missing')
            continue
        actual = digest(path)
        if actual['mode'] != expected['mode'] or actual['sha256'] != expected['sha256']:
            failed.append(name + ': content changed')
        elif actual['observed_raw_sha256'] != expected['observed_raw_sha256']:
            raw_different.append(name)
    print(json.dumps({'result': 'FAIL' if failed else 'PASS', 'files': len(output['files']),
                      'failed': failed, 'same_content_different_line_endings': raw_different}, ensure_ascii=False))
    return bool(failed)


if __name__ == '__main__':
    if sys.argv[1:] == ['--write']:
        write()
    else:
        raise SystemExit(verify())
