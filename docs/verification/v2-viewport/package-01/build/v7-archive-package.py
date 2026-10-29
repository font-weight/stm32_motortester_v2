from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, shutil

root = Path.cwd()
folder = root / 'build/v7w'
dest = root / 'docs/verification/v2-viewport/package-01'
dest.mkdir(parents=True, exist_ok=False)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
report = json.loads((folder / 'build-report.json').read_text(encoding='utf-8'))
assert report['status'] == 'PASS'
source = json.loads((root / 'docs/verification/v2-viewport/source-01/manifest.json').read_text(encoding='utf-8'))
assert all(sha(root / p) == value for p, value in source['source_pins'].items())
paths = [folder / p for p in ('build-report.json', 'build.log', 'SHA256SUMS.txt',
    'license-input-restoration.json', 'dist/MotortesterV2/build-manifest.json')]
paths += sorted(p for p in (folder / 'frozen-viewport').iterdir() if p.is_file())
paths += [root / 'build/v7-archive-package.py']
rows = []
for src in paths:
    target = dest / src.relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    assert src.read_bytes() == target.read_bytes()
    rows.append({'source': src.relative_to(root).as_posix(),
        'archive': target.relative_to(root).as_posix(),
        'bytes': src.stat().st_size, 'sha256': sha(src)})
external = []
for rel in ('MotortesterV2-windows-x64.zip', 'source.zip',
            'dist/MotortesterV2/MotortesterV2.exe',
            'dist/MotortesterV2/MotortesterV2Inspect.exe'):
    path = folder / rel
    external.append({'path': path.relative_to(root).as_posix(),
        'bytes': path.stat().st_size, 'sha256': sha(path),
        'storage': 'local build artifact; not duplicated in Git'})
assert external[0]['sha256'] == report['portable_sha256']
assert external[1]['sha256'] == report['source_sha256']
assert all(item['sha256'] == report['executable_sha256'][Path(item['path']).name]
           for item in external[2:])
manifest = {'schema': 'v2-07-viewport-package-evidence-1',
    'recorded_utc': datetime.now(timezone.utc).isoformat(),
    'source_commit': report['source_commit'],
    'scope': 'One relocated frozen Windows viewport DEMO check; no COM/SWD, no firmware changes, no whole inherited suite.',
    'command': '.venv/Scripts/python.exe -B host/packaging/v2/build_windows.py --output build/v7w --verification viewport',
    'exit_code': 0, 'files': rows, 'local_deliverables': external,
    'source_pins': source['source_pins'],
    'root_visual_review': {'method': 'view_image, all four held/paused/tail/file PNGs in native03 and frozen-viewport',
        'finding': 'Curves and visible edges present; holding/follow labels and controls readable; no text overlap.',
        'limits': 'Static rendered snapshots plus numeric event checks; original user saved-file defect was not independently reproduced on the old build. No physical 150k GUI or clean-OS claim.'}}
mp = dest / 'manifest.json'
mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'files': len(rows), 'bytes': sum(x['bytes'] for x in rows),
    'manifest_sha256': sha(mp)}, indent=2))
