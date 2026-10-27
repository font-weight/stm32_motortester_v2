"""Root: execute one admitted trial only after this boot's actual replug reply."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, os, subprocess, time

r=Path.cwd(); base=r/'build/v6m-board-02'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--sample-rate',type=int,choices=(150000,50000,100000),required=True)
fs=ap.parse_args().sample_rate
plan_path=base/'plan.json'; p=json.loads(plan_path.read_bytes())
admission=json.loads((r/'docs/verification/v2-serializer-local/critic-connect.json').read_bytes())
assert admission['status']=='PASS' and admission['score']>=9.5 and admission['plan_sha256']==sha(plan_path)
for name,digest in p['execution_inputs'].items():assert sha(r/name)==digest,name
readback=json.loads((r/p['parent_readback_receipt']).read_bytes())
assert readback['byte_equal'] and readback['sha256']==p['candidate_sha256']
parent=json.loads((r/p['parent_failed_result']).read_bytes())
assert parent['cleanup_finished'] and parent['final_state']['phase']=='closed'
assert parent['traffic']['host_bytes']==parent['traffic']['device_bytes']==parent['traffic']['chunks']==0
inventory=json.loads((base/'com-inventory.json').read_bytes())
assert any(x['DeviceID']==p['port'] and x['PNPDeviceID']==p['expected_pnp_id'] for x in inventory)
s=next(x for x in p['sessions'] if x['sample_rate_hz']==fs)
reset=(r/p['parent_reset_log']) if s['order']==1 else base/(str(fs)+'-reset.log')
assert 'Application started.' in reset.read_text('utf-8')
reply_path=base/(str(fs)+'-user-replug.json')
reply=json.loads(reply_path.read_bytes())
assert reply['sample_rate_hz']==fs and reply['actual_user_reply'] and reply['reset_log_sha256']==sha(reset)
for preceding in p['sessions'][:s['order']-1]:
    before=base/str(preceding['sample_rate_hz'])
    evidence=json.loads((before/'physical-analysis.json').read_bytes())
    diagnostics=json.loads((before/'diagnostics-decoded.json').read_bytes())
    registers=json.loads((before/'registers-decoded.json').read_bytes())
    assert evidence['probe_status']=='PASS' and evidence['offline_validation_status']=='PASS' and evidence['normal_stop_exchange']
    assert diagnostics['errors']==[] and diagnostics['warnings']==[] and diagnostics['raw']['flags']==0
    assert registers['all_checks'] is True
trial=r/s['directory']; trial.mkdir(exist_ok=False)
start=datetime.now(timezone.utc).isoformat();clock=time.monotonic()
with (trial/'trial-console.txt').open('xb') as log:
    result=subprocess.run(s['trial_argv'],env=dict(os.environ,**s['trial_env']),stdout=log,stderr=subprocess.STDOUT,timeout=60)
receipt={'argv':s['trial_argv'],'started_utc':start,'finished_utc':datetime.now(timezone.utc).isoformat(),
    'wall_seconds':time.monotonic()-clock,'exit_code':result.returncode,'console_sha256':sha(trial/'trial-console.txt'),
    'plan_sha256':sha(plan_path),'user_replug_record_sha256':sha(reply_path),'attempt_count':1}
(trial/'trial-invocation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print((trial/'trial-console.txt').read_text('utf-8',errors='replace'))
print(json.dumps(receipt,ensure_ascii=False))
