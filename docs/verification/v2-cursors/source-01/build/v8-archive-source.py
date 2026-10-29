from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, shutil

root=Path.cwd(); dest=root/'docs/verification/v2-cursors/source-01'
dest.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
receipt=root/'build/v8-unit-result.json'
assert not receipt.exists()
receipt.write_text(json.dumps({
    'status':'PASS','provenance':'Root transcription of actual exec console; not a second test run',
    'command':'.venv/Scripts/python.exe -B -m unittest -v test_stream_cursors',
    'environment':{'PYTHONPATH':'host;host/tests'},'exit_code':0,'test_count':3,
    'seconds':1.090,'tests':['test_coalescing_stale_source_and_stale_integrity_failure',
        'test_overview_uses_raw_and_keeps_indices_on_rebase','test_two_samples_signed_150k_large_index_and_missing'],
    'console_summary':'Ran 3 tests in 1.090s\nOK',
    'limits':'Before final two UI text changes: time_text6g->9g and explicit local-origin X axis. Final frozen check covers that version. No full inherited suite or COM.'
},indent=2)+'\n',encoding='utf-8')
paths=[receipt,root/'build/v8-archive-source.py']+sorted((root/'build/v8-native-01').iterdir())
rows=[]
for src in paths:
    if not src.is_file():continue
    target=dest/src.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(src,target);assert target.read_bytes()==src.read_bytes()
    rows.append({'source':src.relative_to(root).as_posix(),'archive':target.relative_to(root).as_posix(),
                 'bytes':src.stat().st_size,'sha256':sha(src)})
sources=['host/motortester/gui_stream.py','host/motortester/v2/stream_ui.py',
    'host/motortester/v2/stream_cursors.py','host/motortester/v2/stream_cursors_smoke.py',
    'host/tests/test_stream_cursors.py','host/packaging/v2/build_windows.py',
    'host/packaging/v2/launcher.py','host/packaging/v2/cursors_package_check.py']
manifest={'schema':'v2-08-source-evidence-1','recorded_utc':datetime.now(timezone.utc).isoformat(),
    'scope':'Two raw cursors, bounded async reads, integer indices, Windows DEMO; no physical actions.',
    'source_storage':'Implementation is committed normally in Git; source_pins describe exact working bytes including line endings, not redundant source copies.',
    'evidence_version_limit':'Unit/native01 precede final time_text6g->9g and explicit local-origin axis label. Final package receipt must bind final source commit and exact EXE.',
    'files':rows,'source_pins':{p:sha(root/p) for p in sources}}
mp=dest/'manifest.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':len(rows),'bytes':sum(x['bytes'] for x in rows),'manifest_sha256':sha(mp)}))
