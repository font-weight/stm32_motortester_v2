"""Root-only exact-plan Flash/readback/reset. Never opens COM or sends START."""
from pathlib import Path
import hashlib, json, subprocess, time
from datetime import datetime, timezone

r=Path.cwd(); out=r/'build/v6n-board-01'; plan_path=out/'plan.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=json.loads(plan_path.read_bytes())
review=json.loads((r/'docs/verification/v2-stream-progress/critic-flash.json').read_bytes())
assert review['status']=='PASS' and review['score']>=9.5
assert review['plan_sha256']==sha(plan_path), 'Admission must bind this exact final plan'
assert p['status']=='ROOT_REVIEWED_AWAITING_INDEPENDENT_EXACT_ADMISSION'
for name,digest in p['execution_inputs'].items():
    assert sha(r/name)==digest, 'Pinned input changed: '+name
candidate=r/p['candidate_path']; backup=r/p['rollback_image']
assert candidate.stat().st_size==p['candidate_bytes'] and sha(candidate)==p['candidate_sha256']
assert backup.stat().st_size==65536 and sha(backup)==p['rollback_sha256']
assert sha(Path(p['cli_path']))==p['cli_sha256_from_H_template']
assert not (out/'program-invocation.json').exists(), 'One flash only; no automatic repeat'

def run(name,argv,expected):
    stamp=datetime.now(timezone.utc).isoformat(); start=time.monotonic()
    result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=35)
    log=result.stdout.decode('utf-8',errors='replace')
    (out/(name+'.stdout.bin')).write_bytes(result.stdout)
    (out/(name+'.log')).write_text(log,encoding='utf-8')
    (out/(name+'-invocation.json')).write_text(json.dumps({'argv':argv,'started_utc':stamp,
        'wall_seconds':time.monotonic()-start,'exit_code':result.returncode},indent=2)+'\n',encoding='utf-8')
    assert result.returncode==0 and p['probe_serial'] in log and all(s in log for s in expected),log

run('program',p['program_argv'],['Verification...OK','Programming Complete.'])
target=out/'readback.bin'; assert not target.exists()
run('readback',p['readback_argv'],['succeded'])
assert target.read_bytes()==candidate.read_bytes(), 'Readback differs: stop without reset or automatic rollback'
(out/'readback-verified.json').write_text(json.dumps({'status':'PASS','bytes':target.stat().st_size,
    'sha256':sha(target),'candidate_sha256':sha(candidate),'byte_equal':True,
    'plan_sha256':sha(plan_path)},indent=2)+'\n',encoding='utf-8')
run('reset',p['reset_argv'],['MCU Reset.','Application started.'])
print(json.dumps({'status':'FLASH_READBACK_RESET_PASS','bytes':target.stat().st_size,
    'next':'Fresh actual user USB-board replug required before any COM/START.','START_sent':False}))
