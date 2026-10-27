"""Root: one exact-plan trial after the new image's actual USB replug."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,os,subprocess,time

r=Path.cwd();base=r/'build/v6n-board-01'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan_path=base/'plan.json';p=json.loads(plan_path.read_bytes())
review=json.loads((r/'docs/verification/v2-stream-progress/critic-flash.json').read_bytes())
assert review['status']=='PASS' and review['score']>=9.5 and review['plan_sha256']==sha(plan_path)
for name,digest in p['execution_inputs'].items():assert sha(r/name)==digest,name
readback=json.loads((base/'readback-verified.json').read_bytes())
assert readback['byte_equal'] and readback['sha256']==p['candidate_sha256']
reset=base/'reset.log';assert 'Application started.' in reset.read_text('utf-8')
reply_path=base/'150000-user-replug.json';reply=json.loads(reply_path.read_bytes())
assert reply['sample_rate_hz']==150000 and reply['actual_user_reply'] and reply['reset_log_sha256']==sha(reset)
inventory=json.loads((base/'com-inventory.json').read_bytes())
assert any(x['DeviceID']==p['port'] and x['PNPDeviceID']==p['expected_pnp_id'] for x in inventory)
assert len(p['sessions'])==1
s=p['sessions'][0];assert s['sample_rate_hz']==150000 and s['seconds']==3
trial=r/s['directory'];trial.mkdir(exist_ok=False)
started=datetime.now(timezone.utc).isoformat();clock=time.monotonic()
with (trial/'trial-console.txt').open('xb') as log:
    result=subprocess.run(s['trial_argv'],env=dict(os.environ,**s['trial_env']),stdout=log,stderr=subprocess.STDOUT,timeout=40)
receipt={'argv':s['trial_argv'],'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),
    'wall_seconds':time.monotonic()-clock,'exit_code':result.returncode,'console_sha256':sha(trial/'trial-console.txt'),
    'plan_sha256':sha(plan_path),'user_replug_record_sha256':sha(reply_path),'attempt_count':1}
(trial/'trial-invocation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print((trial/'trial-console.txt').read_text('utf-8',errors='replace'))
print(json.dumps(receipt,ensure_ascii=False))
