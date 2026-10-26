"""Root runs only the admitted first trial after actual USB replug. No SWD/reset."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, subprocess, os, time
r=Path.cwd(); base=r/'build/v6l-board-01'; plan=base/'plan.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads(plan.read_bytes()); approval=json.loads((r/'docs/verification/v2-batch1024/critic-flash.json').read_bytes())
assert approval['status']=='PASS' and approval['plan_sha256']==sha(plan)
for name,digest in p['execution_inputs'].items():assert sha(r/name)==digest,name
verified=json.loads((base/'readback-verified.json').read_bytes())
assert verified['byte_equal'] and verified['sha256']==p['candidate_sha256']
assert 'Application started.' in (base/'reset.log').read_text('utf-8')
s=p['sessions'][0]; assert s['sample_rate_hz']==150000 and s['seconds']==30 and s['mode']==5
trial=r/s['directory'];trial.mkdir(exist_ok=False)
steering={'actual_user_replug_reply':'готово. После проверки сохрани результат и заверши работу',
    'scope':'Execute only the already admitted first150k30s trial. After evidence saving stop; do not run50/100, reset, retry or rollback automatically.',
    'Fs50000':'NOT_RUN_USER_LIMIT','Fs100000':'NOT_RUN_USER_LIMIT'}
(base/'user-limit.json').write_text(json.dumps(steering,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
start=datetime.now(timezone.utc).isoformat(); clock=time.monotonic()
with (trial/'trial-console.txt').open('xb') as log:
    result=subprocess.run(s['trial_argv'],env=dict(os.environ,**s['trial_env']),stdout=log,stderr=subprocess.STDOUT,timeout=60)
receipt={'argv':s['trial_argv'],'started_utc':start,'finished_utc':datetime.now(timezone.utc).isoformat(),
    'wall_seconds':time.monotonic()-clock,'exit_code':result.returncode,
    'console_sha256':sha(trial/'trial-console.txt'),'plan_sha256':sha(plan),
    'actual_user_replug_reply':steering['actual_user_replug_reply'],'attempt_count':1,
    'root_observed_no_SWD_or_halt_during_trial':True}
(trial/'trial-invocation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print((trial/'trial-console.txt').read_text('utf-8',errors='replace'))
print(json.dumps(receipt,ensure_ascii=False))
