"""Repair ONLY the failed native01 compiler-negative command; never rerun its C model."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess

root=Path(__file__).resolve().parents[2]
old=root/'build/v6p-native-01';out=root/'build/v6p-native-02'
assert not out.exists();out.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
pin=lambda p:{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
r=json.loads((old/'result.json').read_text('utf8'))
assert r['status']=='FAILED' and r['error']=='ValueError: Negative compile failed for wrong reason'
assert not r['input_drift']
assert [c['exit_code'] for c in r['commands']]==[0,0,0,1]
assert 'PASS exact SI generated identity reaches ACTIVE/FROZEN' in (old/'model.stdout').read_text('utf8')
assert 'argument unused during compilation' in (old/'compile-missing-build-negative.stderr').read_text('utf8')
prior=root/'build/v6p-analysis/check_progress_binding-r1.py'
current=root/'tests/v2-stream-firmware/check_progress_binding.py'
old_cmd="'-Imissing-id','-fsyntax-only','platform/mt_stream_progress.c'"
new_cmd="'-Imissing-id','-c','platform/mt_stream_progress.c','-o','missing-id.o'"
assert prior.read_text('utf8').count(old_cmd)==1
assert prior.read_text('utf8').replace(old_cmd,new_cmd)==current.read_text('utf8')
inputs={}
for name,digest in r['inputs'].items():
    p=Path(name)
    if p==current:p=prior
    assert p.is_file() and sha(p)==digest,str(p)
    inputs[str(p)]=digest
inputs[str(current)]=sha(current)
for folder in ('platform','protocol','acquisition','transport','generated','missing-id'):
    for p in (old/folder).rglob('*'):
        if p.is_file() and p.suffix in ('.h','.c'):
            q=out/p.relative_to(old);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes());inputs[str(p)]=sha(p)
(out/'tusb.h').write_bytes((old/'tusb.h').read_bytes());inputs[str(old/'tusb.h')]=sha(old/'tusb.h')
command=list(r['commands'][-1]['argv']);index=command.index('-fsyntax-only');command[index]='-c';command+=['-o','missing-id.o']
(out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
result={'schema':'motortester-progress-binding-addressed-completion-1','status':'RUNNING','scope':__doc__,'inputs':inputs,'command':command,'positive_native_model_executions_total':1,'ARM_executions_total':1,'previous_failed_result':pin(old/'result.json'),'original_runner':pin(prior),'current_runner':pin(current)}
try:
    q=subprocess.run(command,cwd=out,env=env,capture_output=True,timeout=180)
    (out/'compile-missing-build-negative.stdout').write_bytes(q.stdout);(out/'compile-missing-build-negative.stderr').write_bytes(q.stderr)
    result['expected_negative_exit_code']=q.returncode
    assert q.returncode!=0 and b'Progress trace requires generated target build identity' in q.stderr
    assert not (out/'missing-id.o').exists()
    result.update(status='PASS',meaning='Native01 actual C binding/freeze groups passed. Only its malformed Zig negative command was corrected; required missing-macro rejection now confirmed. No C model or ARM rerun.',actual_C_evidence=[pin(old/p) for p in ('model.exe','model.c','model.stdout','compile.stdout','compile.stderr','source-equivalence.json','actual-progress.bin','actual-legacy.bin','companion.json')],shared_generated_header=pin(root/'build/v6p-fw-01/generated/mt_firmware_build.h'),image_receipt=pin(root/'build/v6p-fw-01/receipt.json'),not_physical=True)
finally:
    drift=[p for p,h in inputs.items() if not Path(p).is_file() or sha(Path(p))!=h]
    result['input_drift']=drift
    if drift:result['status']='FAILED_INPUT_DRIFT'
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps(pin(out/'result.json')))
