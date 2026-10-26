"""Bind the already-built SE image, host package and read-only backup. No hardware."""
from pathlib import Path
import json, hashlib

r=Path.cwd(); out=r/'build/v6l-board-01'; p=json.loads((out/'plan-draft.json').read_bytes())
sha=lambda name:hashlib.sha256((r/name).read_bytes()).hexdigest()
source=json.loads((r/'docs/verification/v2-batch1024/critic-source.json').read_bytes())
package=json.loads((r/'build/v6lw1/build-report.json').read_bytes())
backup=json.loads((out/'backup-verified.json').read_bytes())
assert source['status']=='PASS' and source['score']>=9.5 and package['status']=='PASS' and backup['status']=='PASS'
p['source_commit']=package['source_commit']; p['rollback_sha256']=backup['backup_sha256']
p['status']='ROOT_REVIEWED_AWAITING_INDEPENDENT_EXACT_ADMISSION'
p['software_review']={'path':'docs/verification/v2-batch1024/critic-source.json','sha256':sha('docs/verification/v2-batch1024/critic-source.json'),'score':source['score']}
p['windows_package']={'build_report':'build/v6lw1/build-report.json','build_report_sha256':sha('build/v6lw1/build-report.json'),
    'zip':'build/v6lw1/MotortesterV2-windows-x64.zip','zip_sha256':package['portable_sha256'],
    'exe_sha256':package['executable_sha256']['MotortesterV2.exe'],
    'independent_acceptance_required_in_exact_plan_review':True}
paths=[p['candidate_path'],'build/v6l-fw-04/MotortesterV2-stream-candidate.elf',
    'build/v6l-fw-04/image.nm','build/v6l-fw-04/static-bound.json','build/v6l-freeze.json',
    'docs/verification/v2-batch1024/critic-source.json','build/v6lw1/build-report.json',
    'build/v6lw1/MotortesterV2-windows-x64.zip','build/v6lw1/dist/MotortesterV2/MotortesterV2.exe',
    'build/v6l-board-01/backup-verified.json',p['rollback_image'],
    'host/tools/v2_stream_probe.py','host/tools/verify_stream_trial.py',
    'host/motortester/stream_wire.py','host/motortester/stream_endpoint.py',
    'host/motortester/stream_model.py','host/motortester/stream_recording.py',
    'host/motortester/stream_bridge.py','host/motortester/stream_serial.py',
    'host/motortester/v2/stream_device.py']
paths += ['build/v6l-board-01/'+name for name in (
    'program_and_verify.py','analyze_physical.py','decode_diagnostics.py',
    'save_stopped_state.py','root_read_stopped.py','root_read_fault.py')]
p['execution_inputs']={name:sha(name) for name in paths}; del p['helper_hashes']
cli=p['cli_path']; common=[cli,'-c','ID=0','SWD','HOTPLUG']
p['program_argv']=common+['-P',p['candidate_path'],'0x08000000','-V']
p['readback_argv']=common+['-Dump','0x08000000',hex(p['candidate_bytes']),'build/v6l-board-01/readback.bin']
p['reset_argv']=common+['-Rst','-Run']
for s in p['sessions']:
    directory=f"build/v6l-board-01/{s['sample_rate_hz']}"
    s['directory']=directory; s['expected_CAPS']=[s['mode'],s['mode'],0,12,s['sample_rate_hz'],1,s['max_block'],1,s['retained_bits'],2 if s['mode']==5 else 1]
    s['trial_argv']=['.venv/Scripts/python.exe','-B','host/tools/v2_stream_probe.py','--port','COM6','--output',directory+'/run',
        '--seconds',str(s['seconds']),'--build-id',p['firmware_build'],'--sample-rate',str(s['sample_rate_hz']),
        '--source-commit',p['source_commit'],'--image-sha256',p['candidate_sha256']]
    s['trial_env']={'PYTHONPATH':'host'};s['START_limit']=1
    s['fresh_Reset_Run_and_actual_user_replug_required']=True
with (out/'plan.json').open('x',encoding='utf-8') as stream:
    stream.write(json.dumps(p,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'plan_sha256':sha('build/v6l-board-01/plan.json'),'status':p['status']}))
