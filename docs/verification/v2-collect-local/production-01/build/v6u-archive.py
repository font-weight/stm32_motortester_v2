"""Preserve U delta and reference exact S evidence without duplicating it."""
from pathlib import Path
import hashlib,json
r=Path.cwd(); out=r/'docs/verification/v2-collect-local/production-01'
assert not out.exists(); out.mkdir(parents=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
bp=r/'docs/verification/v2-postcopy-handoff/production-01/manifest.json'
assert sha(bp)=='52d9583a07114eb7e9afb2de632a84701ffb2bab8efe1484006b933896ed7bb7'
baseline=json.loads(bp.read_bytes()); byhash={x['sha256']:x for x in baseline['files']}
freeze_path=r/'build/v6u-freeze.json'
assert sha(freeze_path)=='fe206f96e8c7d5ea6704542870f051278dda18be9570f50faca393e3d4f6cf95'
freeze=json.loads(freeze_path.read_bytes()); paths={freeze_path,Path(__file__).resolve()}
def collect(obj):
    if isinstance(obj,dict):
        if {'path','bytes','sha256'}<=obj.keys():
            p=r/obj['path'];assert p.stat().st_size==obj['bytes'] and sha(p)==obj['sha256'],str(p)
            paths.add(p)
        for v in obj.values():collect(v)
    elif isinstance(obj,list):
        for v in obj:collect(v)
collect(freeze)
for name in ('v6u-analysis','v6u-native-01','v6u-host-identity-01'):
    for p in (r/'build'/name).rglob('*'):
        if not p.is_file() or any(x in ('zig-cache','zig-global','temp','__pycache__') for x in p.parts):continue
        if p.suffix.lower() in ('.exe','.pdb','.o','.pyc'):continue
        paths.add(p)
for name in ('size.stdout','image.nm','image.map','image.dis','receipt.json','static-bound.json',
             'MotortesterV2-stream-candidate.bin','MotortesterV2-stream-candidate.elf',
             'disassembly-28-mt_batch1024.stdout'):
    paths.add(r/'build/v6u-fw-01'/name)
rows=[]
for p in sorted(paths):
    assert p.is_relative_to(r) and p.is_file()
    digest=sha(p); rel=p.relative_to(r).as_posix(); row={'source':rel,'bytes':p.stat().st_size,'sha256':digest}
    previous=byhash.get(digest)
    if previous:
        old=r/previous['archive'];assert old.read_bytes()==p.read_bytes(),str(p)
        row.update(storage='baseline_reference',archive=previous['archive'])
    else:
        dest=out/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
        assert dest.read_bytes()==p.read_bytes();row.update(storage='delta_copy',archive=dest.relative_to(r).as_posix())
    rows.append(row)
m={'schema':'motortester-v2-06u-delta-evidence-1','scope':'Exact saved delta; archive is not another test or acceptance',
   'baseline_manifest':bp.relative_to(r).as_posix(),'baseline_manifest_sha256':sha(bp),'files':rows}
target=out/'manifest.json';target.write_text(json.dumps(m,indent=2)+'\n',encoding='utf8')
print(json.dumps({'files':len(rows),'delta_files':sum(x['storage']=='delta_copy' for x in rows),
 'delta_bytes':sum(x['bytes'] for x in rows if x['storage']=='delta_copy'),'manifest_sha256':sha(target)}))
