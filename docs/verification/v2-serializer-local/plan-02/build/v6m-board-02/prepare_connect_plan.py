"""One explicit continuation after zero-byte COM-open failure; no hardware calls."""
from pathlib import Path
import hashlib,json
r=Path.cwd();old=r/'build/v6m-board-01';base=r/'build/v6m-board-02'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name in ('analyze_physical.py','decode_diagnostics.py','save_stopped_state.py','root_read_stopped.py','root_read_fault.py','run_trial.py'):
    s=(old/name).read_text('utf-8').replace('build/v6m-board-01','build/v6m-board-02')
    if name=='run_trial.py':
        s=s.replace('v2-serializer-local/critic-flash.json','v2-serializer-local/critic-connect.json')
        s=s.replace("readback=json.loads((base/'readback-verified.json').read_bytes())", "readback=json.loads((r/p['parent_readback_receipt']).read_bytes())")
        s=s.replace("reset=base/('reset.log' if s['order']==1 else str(fs)+'-reset.log')", "reset=(r/p['parent_reset_log']) if s['order']==1 else base/(str(fs)+'-reset.log')")
        marker="s=next(x for x in p['sessions'] if x['sample_rate_hz']==fs)"
        s=s.replace(marker, """parent=json.loads((r/p['parent_failed_result']).read_bytes())
assert parent['cleanup_finished'] and parent['final_state']['phase']=='closed'
assert parent['traffic']['host_bytes']==parent['traffic']['device_bytes']==parent['traffic']['chunks']==0
inventory=json.loads((base/'com-inventory.json').read_bytes())
assert any(x['DeviceID']==p['port'] and x['PNPDeviceID']==p['expected_pnp_id'] for x in inventory)
"""+marker)
    with (base/name).open('x',encoding='utf-8',newline='\n') as f:f.write(s)
p=json.loads((old/'plan.json').read_bytes())
p['schema']='motortester-v2-serializer-local-connect-continuation-1'
p['purpose']='One new open attempt and at most one first START150k after actual USB replug and COM inventory; preceding open failed with zero wire. No new Flash/Reset for first150k. Then only after allPASS,50/100 freshboot/replug5s. KeepSF.'
p['parent_plan']='build/v6m-board-01/plan.json';p['parent_plan_sha256']=sha(old/'plan.json')
p['parent_failed_result']='build/v6m-board-01/150000/run/result.json'
p['parent_readback_receipt']='build/v6m-board-01/readback-verified.json'
p['parent_reset_log']='build/v6m-board-01/reset.log'
p['expected_pnp_id']=r'USB\VID_1209&PID_0001&MI_00\6&D2DE68C&0&0000'
p['first_trial_new_flash_allowed']=False;p['first_trial_new_reset_allowed']=False
p['first_trial_open_attempt_limit']=1
p['before_capture']=['Original failed result closed with zero traffic; prior START count0, not a throughput failure.',
    'Same exactSF verified readback and image; no source or Windows-package change.',
    'New actual10sUSB replug reply and fresh COM inventory; root records order explicitly.',
    'No Flash/Reset/rollback for this first150k continuation. Stop on failure and preserve both attempts.']
p.pop('before_flash');p.pop('flash_procedure');p.pop('program_argv');p.pop('readback_argv')
for s in p['sessions']:
    s['directory']=s['directory'].replace('v6m-board-01','v6m-board-02')
    s['trial_argv']=[x.replace('build/v6m-board-01/','build/v6m-board-02/') for x in s['trial_argv']]
    if s['order']==1:s['fresh_Reset_Run_and_actual_user_replug_required']='Prior verifiedReset plus new actualUSB replug; no priorSTART occurred'
p['session_rules'].append('First150k: no reset, require parentzero-wire failure and newreplug/inventory. Later50/100 require freshReset/Run/replug and allprecedingPASS. Noautomatic retry after another failure.')
inputs={k:v for k,v in p['execution_inputs'].items() if not k.endswith('.py') or not k.startswith('build/v6m-board-01/')}
for name in ('analyze_physical.py','decode_diagnostics.py','save_stopped_state.py','root_read_stopped.py','root_read_fault.py','run_trial.py'):
    inputs[(base/name).relative_to(r).as_posix()]=sha(base/name)
for path in (old/'plan.json',old/'150000/run/result.json',old/'150000/run/traffic.bin',old/'150000/connect-failure-proof.json',old/'readback-verified.json',old/'readback.bin',old/'reset.log',old/'usb-boot-01/read-values.json'):
    inputs[path.relative_to(r).as_posix()]=sha(path)
for name,digest in inputs.items():assert sha(r/name)==digest,name
p['execution_inputs']=inputs
with (base/'plan.json').open('x',encoding='utf-8') as f:json.dump(p,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'plan_sha256':sha(base/'plan.json'),'newFlash':False,'newResetFor150k':False}))
