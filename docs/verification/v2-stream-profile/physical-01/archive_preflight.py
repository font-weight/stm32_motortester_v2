"""Preserve the exact S9 diagnostic plan and fresh rollback data."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[2]
folder=root/'build/v6f-board-01'
dest=root/'docs/verification/v2-stream-profile/preflight-01'
sha=lambda b:hashlib.sha256(b).hexdigest()
names=['prepare_plan.py','plan.json','preflight.json','decoder-inputs.json','decode_diagnostics.py',
       'before-flash-64k.bin','before-flash-read.txt','ports-before.json','processes-before.json','probe-list.txt']
selection=[(folder/name,dest/name) for name in names]
selection.append((root/'build/v5-board-stream-04/check_ready.py',dest/'rollback-check-ready-reference.py'))
entries=[]
for source,target in selection:
    raw=source.read_bytes()
    assert not target.exists() or target.read_bytes()==raw,target
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():target.write_bytes(raw)
    assert target.read_bytes()==source.read_bytes()==raw
    entries.append(dict(source=source.relative_to(root).as_posix(),copy=target.relative_to(root).as_posix(),
                        bytes=len(raw),sha256=sha(raw),copy_sha256=sha(target.read_bytes()),byte_equal=True))
manifest=dict(schema='v2-06f2-preflight-evidence-1',status='ARCHIVED_BYTE_VERIFIED',
              source_commit='195fbcd2f9921acab1926f7940df9e446c02c392',files=entries,
              file_count=len(entries),total_bytes=sum(e['bytes'] for e in entries),
              flash_performed=False,physical_trial_performed=False,
              rollback_helper_note='Execute original path in plan. Archived copy is a reference only; its parent-derived repository root differs.')
target=dest.parent/'preflight-evidence.json'
raw=(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n').encode()
assert not target.exists() or target.read_bytes()==raw,target
target.write_bytes(raw)
print(json.dumps({'files':len(entries),'bytes':manifest['total_bytes'],'manifest_sha256':sha(raw)}))
