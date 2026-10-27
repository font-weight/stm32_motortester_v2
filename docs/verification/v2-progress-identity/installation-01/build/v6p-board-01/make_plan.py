"""Pin SI's one30s stream trial; never accesses hardware."""
from pathlib import Path
import hashlib,json,re,subprocess
r=Path.cwd();base=r/'build/v6p-board-01';fw=r/'build/v6p-fw-01'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads((r/'build/v6o-board-01/plan.json').read_bytes())
review_path=r/'docs/verification/v2-progress-identity/critic-source.json'
review=json.loads(review_path.read_bytes());assert review['status']=='PASS' and review['score']>=9.5
receipt=json.loads((fw/'receipt.json').read_bytes())
assert receipt['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and receipt['config']['firmware_build']==0x56325349
source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
image=fw/'MotortesterV2-stream-candidate.bin';elf=fw/'MotortesterV2-stream-candidate.elf';nm=fw/'image.nm'
backup=json.loads((base/'backup-verified.json').read_bytes())
assert backup['status']=='PASS' and sha(base/'before-flash-64k.bin')==backup['sha256']
assert backup['prefix_bytes']==44212 and backup['prefix_sha256']=='99fcd38af9ac4e4feb8b7b4fa0bd577a77d8103773c0951e6b6a433e22deddf2'
symbols=nm.read_text('utf-8')
def address(name,size):
    matches=re.findall(r'^([0-9a-fA-F]+)\s+'+f'{size:08x}'+r'\s+B\s+'+name+r'\s*$',symbols,re.M)
    assert len(matches)==1,name
    return '0x'+matches[0].upper()
p.update(schema='motortester-v2-progress-identity-physical-plan-1',
    status='ROOT_REVIEWED_AWAITING_INDEPENDENT_EXACT_ADMISSION',
    purpose='One exact SI flash/readback and one150k DATA1024 requested30s stability trial. Preserve frozen64/136, wire/raw/CRC/Open/Stop and all failed evidence. No50/100, automatic retry or rollback. A single successful trial is limited to observed conditions, not analog qualification.',
    source_commit=source,candidate_path=image.relative_to(r).as_posix(),candidate_bytes=image.stat().st_size,
    candidate_sha256=sha(image),candidate_elf_sha256=sha(elf),candidate_nm_sha256=sha(nm),
    firmware_build='0x56325349',diagnostic_address=address('mt_stream_diagnostics',136),
    progress_address=address('mt_stream_progress',64),progress_bytes=64,
    rollback_image='build/v6p-board-01/before-flash-64k.bin',rollback_sha256=backup['sha256'],
    backup_expected_SH_prefix_bytes=44212,backup_expected_SH_prefix_sha256=backup['prefix_sha256'],
    expected_pnp_id='USB\\VID_1209&PID_0001&MI_00\\6&D2DE68C&0&0000')
p.pop('backup_expected_SE_prefix_bytes',None);p.pop('backup_expected_SE_prefix_sha256',None)
p.pop('backup_expected_SF_prefix_bytes',None);p.pop('backup_expected_SF_prefix_sha256',None)
p.pop('backup_expected_SG_prefix_bytes',None);p.pop('backup_expected_SG_prefix_sha256',None)
p['before_flash']=[
    'Exact SI shared-identity/actual-C-observer/decoder/ARM review PASS>=9.5; host/wire unchanged, reuse existing package. P1-M2-01 stable150k remains open; P1-O2-02 requires an actual valid64B record.',
    'Expected ST-Link and COM6 identity, no application/capture owner. User previously confirmed PA0 empty, USB-only board power; current resume authorizes this continuation.',
    'Fresh64KiB SH backup with known44212byte prefix verified; retain all previous evidence.',
    'Final plan pins image, backup, helpers and prior package; independent exact admission before Flash.']
p['flash_procedure']=[
    'Root only: one program with verify; independent complete readback must equal every candidate byte.',
    'One Reset/Run only after equality; actual fresh user USB-board replug required before COM open.',
    'Do not restore an older image merely because the diagnostic acquisition reports queue-full.']
p['session_rules']=[
    'One START in a fresh boot/replug. Discovery0.2 then freshnonce HELLO0.3 mode5; exactSIbuild/CAPS before START.',
    'Existing physical probe asks for30s Record. It may FAIL early; preserve traffic/journal/companion and report actual outcome.',
    'No SWD/halt during activeCOM. After closedowner, offline validate END/ACK/nonce/gen/CRC/indices/raw; only with coherent matching terminal allow root_read_closed.',
    'Read legacy136 twice, progress64 twice, then stopped TIM3/ADC/DMA/RCC. Never readADC_DR. Decode both identities against sameSIbuild/nonce/gen and pinnedimage.',
    'Interpret64 checkpoint/fault/partial/unknown/invalidclock/saturation separately. FIFOacceptedbytes do not prove wire-delivered samples or CPUfraction. Preserve firstfault beforedrain.',
    'On failure stop this plan, retain evidence and installedSI if link/stop permit. No automaticretry/reset/rollback; no50/100.',
    'For this30s attempt require normalStop, no source fault/gap, selected raw/CRC/Open, coherentEND/ACK and stopped registers. Diagnostic validity alone does not qualify throughput or analog input.']
s=p['sessions'][0];assert s['sample_rate_hz']==150000
s.update(seconds=30,directory='build/v6p-board-01/150000',START_limit=1,fresh_Reset_Run_and_actual_user_replug_required=True)
s['trial_argv']=['.venv/Scripts/python.exe','-B','host/tools/v2_stream_probe.py','--port','COM6','--output',s['directory']+'/run','--seconds','30','--build-id','0x56325349','--sample-rate','150000','--source-commit',source,'--image-sha256',sha(image)]
p['sessions']=[s]
p['software_review']={'path':review_path.relative_to(r).as_posix(),'sha256':sha(review_path),'score':review['score']}
p['windows_package']['reused_from_L']=True
p['windows_package']['reason']='No host/wire or GUI change; firmware repairs observer build binding using shared generated identity; late grant is unchanged and decoder accepts explicitSI. Existing Windows acceptance retained separately.'
inputs={k:v for k,v in p['execution_inputs'].items() if k.startswith('host/') or k.startswith('build/v6lw1/')}
for path in [image,elf,nm,fw/'static-bound.json',r/'build/v6p-freeze.json',review_path,base/'backup-verified.json',base/'before-flash-64k.bin',r/'host/tools/decode_stream_progress.py']:
    inputs[path.relative_to(r).as_posix()]=sha(path)
for name in ('program_and_verify.py','analyze_physical.py','decode_diagnostics.py','save_stopped_state.py','root_read_closed.py','run_trial.py'):
    inputs[(base/name).relative_to(r).as_posix()]=sha(base/name)
for name,digest in inputs.items():assert sha(r/name)==digest,name
p['execution_inputs']=inputs
p['program_argv']=[p['cli_path'],'-c','ID=0','SWD','HOTPLUG','-P',p['candidate_path'],'0x08000000','-V']
p['readback_argv']=[p['cli_path'],'-c','ID=0','SWD','HOTPLUG','-Dump','0x08000000',hex(p['candidate_bytes']),'build/v6p-board-01/readback.bin']
with (base/'plan.json').open('x',encoding='utf-8') as f:json.dump(p,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'plan_sha256':sha(base/'plan.json'),'source':source,'bytes':p['candidate_bytes'],'image_sha256':p['candidate_sha256'],'legacy_address':p['diagnostic_address'],'progress_address':p['progress_address']}))
