"""Pin one H2 board trial after exact independent software acceptance."""
import json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'build/v6h-board-01'
def sha(p):return hashlib.sha256((root/p).read_bytes()).hexdigest()
def save(n,v):(out/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
source='8243fb3224a1e24980848a8ce02431ec41f5bd9c'
review=root/'docs/verification/v2-usb-turnover/critic-source.json'
r=json.loads(review.read_text('utf-8'))
assert r['status']=='PASS' and r['score']>=9.5
assert r['source_commit']==source
image='build/v6h-fw-01/MotortesterV2-stream-candidate.bin'
elf='build/v6h-fw-01/MotortesterV2-stream-candidate.elf'
assert (root/image).stat().st_size==37224
assert sha(image)=='e7f6f07fc6a43e6b109af6e5c652db1322a0e5023e328007b2c50d303f12536e'
assert sha(elf)=='f129421a4dfb3baf3d30dbefc0923dcdfcf6ec4ddb0e02293c0ece78fb6d14ed'
backup=out/'before-flash-64k.bin';sa=root/'build/v6g-fw-02/MotortesterV2-stream-candidate.bin'
assert backup.stat().st_size==65536 and backup.read_bytes().startswith(sa.read_bytes())
assert sha('build/v6h-board-01/before-flash-64k.bin')=='4a1060f0062620580d8ac1e74aba001a2935bd58dcc6cccbb5fcbef957826f4a'
assert sha('build/v6g-board-01/before-flash-64k.bin')=='95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e'
preflight={'source_commit':source,'backup_bytes':65536,'backup_sha256':sha('build/v6h-board-01/before-flash-64k.bin'),'backup_prefix_equal_SA':True,'candidate_bytes':37224,'candidate_sha256':sha(image),'candidate_elf_sha256':sha(elf),'software_review_sha256':sha('docs/reviews/v2-06h-review.md'),'software_archive_sha256':sha('docs/verification/v2-usb-turnover/software-evidence.json'),'expected_sn':'57005400120000393333574E','probe':'ID=0','no_SB_flash_or_START_yet':True}
save('preflight.json',preflight)
old=json.loads((root/'build/v6g-board-01/plan.json').read_text('utf-8'))
replacements={'v6g-board-01':'v6h-board-01','v6g-fw-02':'v6h-fw-01','a7b45bccf54f3155de03389aa5e49b237905c994':source,'0x56325341':'0x56325342','0x910c':hex(37224),'8e8a5f2597a573ffaecfc054b01de726975ec5de07a33b06c4e56f5de75b3558':sha(image)}
def convert(x):
    if isinstance(x,str):
        for a,b in replacements.items():x=x.replace(a,b)
        return x
    if isinstance(x,list):return [convert(a) for a in x]
    if isinstance(x,dict):return {a:convert(b) for a,b in x.items()}
    return x
plan=convert(old)
args=plan['trial_argv'];args[args.index('--seconds')+1]='30'
plan.update(iteration='V2-06h2',purpose='One 30-second Record trial of the exact early-grant candidate at100k; not indefinite reliability qualification',source_commit=source,candidate_bytes=37224,candidate_sha256=sha(image),candidate_elf_sha256=sha(elf),preflight_sha256=sha('build/v6h-board-01/preflight.json'),software_review_sha256=preflight['software_review_sha256'],target_record_seconds_after_preview=30,trial_tool_sha256=sha('host/tools/v2_stream_probe.py'),diagnostic_decoder='build/v6h-board-01/decode_diagnostics.py',diagnostic_decoder_sha256=sha('build/v6h-board-01/decode_diagnostics.py'),rollback_image='build/v6h-board-01/before-flash-64k.bin',rollback_sha256=preflight['backup_sha256'],rollback_ready_helper='build/v6h-board-01/check_sa_ready.py',rollback_ready_helper_sha256=sha('build/v6h-board-01/check_sa_ready.py'),rollback_ready_argv=['.venv/Scripts/python.exe','-B','build/v6h-board-01/check_sa_ready.py','--output','build/v6h-board-01/rollback-ready.json'])
plan['acceptance'][0]='Program verify and independent byte-equal readback of all37224 bytes'
plan['acceptance'][1]='Exact build/CAPS before one START; target Record30 seconds after Preview; actual duration/overshoot and whole-command wall preserved'
plan['rollback_policy']={
    'automatic_after_failed_trial':False,
    'retain_candidate_if':'Boot/communication and stopped acquisition are confirmed, even if the stream trial failed',
    'restore_only_if':['Programming/readback cannot be completed correctly','Candidate fails to boot or communication remains unavailable after the planned USB replug','Source stopping cannot be confirmed'],
    'recovery_target':'Fresh complete SA snapshot, not automatic S4 rollback',
    'procedure':'Record concrete reason; program fresh SA64KiB with verify, independent full readback equals snapshot, Reset/Run and user replug; SA-only READY helper without START',
    'record_reason_before_restore':True,
    'working_S4_only_if':'User needs ordinary verified50k or a separate concrete recovery need makes SA unsuitable',
    'working_S4_path':'build/v6g-board-01/before-flash-64k.bin',
    'working_S4_sha256':'95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e',
    'user_instruction':'Do not restore old firmware without necessity'
}
plan['trial_limit_notes']={
    'record_seconds_not_total_wall':True,
    'DWT_wrap_assumption':'Check actual procedure wall/no debugger halt separately;30s target alone does not prove the whole procedure stays below59.65s. Do not infer elapsed seconds from rawDWT across wraps.',
    'audit_log_cap_bytes':16777216,
    'nominal_DATA_wire_bytes_in_30s':7195312.5,
    'audit_overhead':'13 bytes per nonempty chunk plus control traffic; no mathematical cap guarantee from assumed batch size. Audit overflow is host logging failure, not device queue-full.',
    'USB_early_grant_window':'May age before a newly published transfer; no second reset; source throughput remains a hypothesis until this trial.'
}
plan['owner_close_gate']='PASS requires owners_closed=true; FAIL requires cleanup_finished=true and final_state.phase=closed. No SWD before this gate.'
assert sha(plan['program_argv'][0])==plan['cli_sha256']
save('plan.json',plan)
print(json.dumps({'preflight_sha256':sha('build/v6h-board-01/preflight.json'),'plan_sha256':sha('build/v6h-board-01/plan.json')},indent=2))
