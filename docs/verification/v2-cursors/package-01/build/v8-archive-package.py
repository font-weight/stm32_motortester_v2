from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, shutil

root=Path.cwd(); folder=root/'build/v8w'
dest=root/'docs/verification/v2-cursors/package-01'; dest.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report=json.loads((folder/'build-report.json').read_text(encoding='utf-8'))
source=json.loads((root/'docs/verification/v2-cursors/source-01/manifest.json').read_text(encoding='utf-8'))
assert report['status']=='PASS'
assert all(sha(root/p)==h for p,h in source['source_pins'].items())
paths=[folder/p for p in ('build-report.json','build.log','SHA256SUMS.txt',
       'license-input-restoration.json','dist/MotortesterV2/build-manifest.json')]
paths+=sorted(p for p in (folder/'frozen-cursors').iterdir() if p.is_file())
paths+=[root/'build/v8-archive-package.py']
rows=[]
for src in paths:
    target=dest/src.relative_to(root); target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(src,target); assert src.read_bytes()==target.read_bytes()
    rows.append({'source':src.relative_to(root).as_posix(),'archive':target.relative_to(root).as_posix(),
                 'bytes':src.stat().st_size,'sha256':sha(src)})
external=[]
for rel in ('MotortesterV2-windows-x64.zip','source.zip','dist/MotortesterV2/MotortesterV2.exe',
            'dist/MotortesterV2/MotortesterV2Inspect.exe'):
    p=folder/rel
    external.append({'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p),
                     'storage':'Local build artifact, not duplicated in Git'})
assert external[0]['sha256']==report['portable_sha256']
assert external[1]['sha256']==report['source_sha256']
assert all(item['sha256']==report['executable_sha256'][Path(item['path']).name] for item in external[2:])
manifest={'schema':'v2-08-package-evidence-1','recorded_utc':datetime.now(timezone.utc).isoformat(),
    'source_commit':report['source_commit'],
    'command':'.venv/Scripts/python.exe -B host/packaging/v2/build_windows.py --output build/v8w --verification cursors',
    'exit_code':0,'files':rows,'local_deliverables':external,'source_pins':source['source_pins'],
    'scope':'One frozen Windows DEMO cursor run; no COM/SWD/firmware or full legacy suite.',
    'root_visual_review':{'method':'view_image: all three native01 and all three frozen-cursors PNGs',
        'finding':'Visible A/B lines, signed readouts and controls; final frozen X axis explicitly states local origin. No overlapping labels.',
        'limits':'Native01 preceded final local-axis-label/9g text changes; frozen covers final version. No physical150k GUI, calibrated timing/voltage or clean-OS claim.'}}
mp=dest/'manifest.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':len(rows),'bytes':sum(p['bytes'] for p in rows),'manifest_sha256':sha(mp)}))
