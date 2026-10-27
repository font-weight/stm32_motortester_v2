"""Pin a new SF plan after source review; never invokes the board."""
from pathlib import Path
import hashlib, json, re, subprocess
r=Path.cwd();base=r/'build/v6m-board-01'; fw=r/'build/v6m-fw-01'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads((r/'build/v6l-board-01/plan.json').read_bytes())
review_path=r/'docs/verification/v2-serializer-local/critic-source.json'
review=json.loads(review_path.read_bytes())
assert review['status']=='PASS' and review['score']>=9.5
receipt=json.loads((fw/'receipt.json').read_bytes())
assert receipt['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and receipt['config']['firmware_build']==0x56325346
source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
image=fw/'MotortesterV2-stream-candidate.bin';elf=fw/'MotortesterV2-stream-candidate.elf';nm=fw/'image.nm'
backup=json.loads((base/'backup-verified.json').read_bytes())
assert backup['status']=='PASS' and sha(base/'before-flash-64k.bin')==backup['sha256']
symbols=nm.read_text('utf-8')
matches=re.findall(r'^([0-9a-fA-F]+)\s+00000088\s+B\s+mt_stream_diagnostics\s*$',symbols,re.M)
assert len(matches)==1, 'Inspect exact diagnostic symbol and update this extractor'
p.update(schema='motortester-v2-serializer-local-physical-plan-1',
    purpose='One exact SF flash; first one150k30s DATA1024 trial. Only after all gates pass,50k and100k five-second regressions on fresh boots. No automatic retry or rollback.',
    source_commit=source,candidate_path=image.relative_to(r).as_posix(),candidate_bytes=image.stat().st_size,
    candidate_sha256=sha(image),candidate_elf_sha256=sha(elf),candidate_nm_sha256=sha(nm),
    firmware_build='0x56325346',diagnostic_address='0x'+matches[0].upper(),
    rollback_image='build/v6m-board-01/before-flash-64k.bin',rollback_sha256=backup['sha256'],
    backup_expected_SE_prefix_bytes=42444,
    backup_expected_SE_prefix_sha256='c1d2c5909341b010d0869f6f7a818d8dd46525bd18d6075e0dda780a9e23b9df')
p.pop('backup_expected_SD_prefix_bytes');p.pop('backup_expected_SD_prefix_sha256')
p['before_flash']=[
    'Exact SF source/differential/actual-core/ARM review PASS>=9.5. Existing Windows package retained because host is unchanged and exact wire fixture matches; no new GUI test.',
    'One expected ST-Link, COM6 identity, no application/capture owner; user confirmed PA0 empty and application closed. Board power remains its USB only.',
    'Fresh64KiB SE backup verified against known42444-byte prefix; earlier backups retained.',
    'Final plan pins image, backup, helpers and existing package; independent exact-plan admission before Flash.']
p['flash_procedure']=[x.replace('all42444bytes','all'+str(image.stat().st_size)+'bytes') for x in p['flash_procedure']]
p['session_rules']=[x.replace('restore SD automatically','restore SE automatically') for x in p['session_rules']]
for s in p['sessions']:
    s['directory']=s['directory'].replace('v6l-board-01','v6m-board-01')
    s['trial_argv']=['.venv/Scripts/python.exe','-B','host/tools/v2_stream_probe.py','--port','COM6',
        '--output',s['directory']+'/run','--seconds',str(s['seconds']),'--build-id','0x56325346',
        '--sample-rate',str(s['sample_rate_hz']),'--source-commit',source,'--image-sha256',sha(image)]
p['software_review']={'path':review_path.relative_to(r).as_posix(),'sha256':sha(review_path),'score':review['score']}
p['windows_package']['reused_from_L']=True
p['windows_package']['reason']='Unchanged host and wire contract; new actual-core fixture must be byte-identical. Prior package review9.62 remains software-only.'
inputs={k:v for k,v in p['execution_inputs'].items() if k.startswith('host/') or k.startswith('build/v6lw1/')}
for path in [image,elf,nm,fw/'static-bound.json',r/'build/v6m-freeze.json',review_path,
             base/'backup-verified.json',base/'before-flash-64k.bin']:
    inputs[path.relative_to(r).as_posix()]=sha(path)
for name in ('program_and_verify.py','analyze_physical.py','decode_diagnostics.py','save_stopped_state.py',
             'root_read_stopped.py','root_read_fault.py','run_trial.py'):
    inputs[(base/name).relative_to(r).as_posix()]=sha(base/name)
for name,digest in inputs.items(): assert sha(r/name)==digest,name
p['execution_inputs']=inputs
p['program_argv']=[p['cli_path'],'-c','ID=0','SWD','HOTPLUG','-P',p['candidate_path'],'0x08000000','-V']
p['readback_argv']=[p['cli_path'],'-c','ID=0','SWD','HOTPLUG','-Dump','0x08000000',hex(p['candidate_bytes']),'build/v6m-board-01/readback.bin']
target=base/'plan.json'
with target.open('x',encoding='utf-8') as f:json.dump(p,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'plan_sha256':sha(target),'source':source,'bytes':p['candidate_bytes'],
    'image_sha256':p['candidate_sha256'],'diagnostic_address':p['diagnostic_address']}))
