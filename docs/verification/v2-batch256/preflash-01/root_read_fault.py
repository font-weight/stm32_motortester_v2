"""Root-operated post-closed-session SWD reads from the admitted plan only."""
from pathlib import Path
import argparse, json, subprocess, hashlib, sys, time
r=Path.cwd();base=r/'build/v6k-board-01'
a=argparse.ArgumentParser();a.add_argument('--sample-rate',type=int,choices=(50000,100000,150000),required=True);fs=a.parse_args().sample_rate
p=base/str(fs);plan=json.loads((base/'plan.json').read_text('utf-8'));result=json.loads((p/'run/result.json').read_text('utf-8'));wire=json.loads((p/'physical-analysis.json').read_text('utf-8'))
assert result['status']=='FAIL' and result.get('cleanup_finished') is True and result['final_state']['phase']=='closed'
assert wire['offline_validation_status']=='PASS' and wire['owners_closed'] is True
assert wire['terminal']['payload']['reason']==1 and wire['ack']['payload']['terminal_sequence']==wire['terminal']['sequence'] and wire['ack']['payload']['prefix_end']==wire['terminal']['payload']['prefix_end']
cli=plan['cli_path']; assert hashlib.sha256(Path(cli).read_bytes()).hexdigest()==plan['cli_sha256_from_H_template']
reads=[('diagnostics-first',int(plan['diagnostic_address'],16),136),('diagnostics-second',int(plan['diagnostic_address'],16),136),('tim3',0x40000400,48),('adc',0x40012408,12),('dma',0x40020008,16),('rcc',0x4002100C,20)]
for name,address,count in reads:
    target=p/(name+'.bin');assert not target.exists()
    cmd=[cli,'-c','ID=0','SWD','HOTPLUG','-Dump',hex(address),hex(count),str(target.relative_to(r))]
    t=time.monotonic();run=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
    log=run.stdout.decode('utf-8',errors='replace');(p/(name+'.stdout.bin')).write_bytes(run.stdout);(p/(name+'.log')).write_text(log,encoding='utf-8')
    (p/(name+'.invocation.json')).write_text(json.dumps(dict(argv=cmd,exit_code=run.returncode,wall_seconds=time.monotonic()-t),indent=2)+'\n',encoding='utf-8')
    assert run.returncode==0 and '57005400120000393333574E' in log and 'succeded' in log and target.stat().st_size==count,log
    print(name+' saved '+str(count)+' bytes',flush=True)
cmd=[sys.executable,'-I','-B',str(base/'decode_diagnostics.py'),str(p/'diagnostics-first.bin'),str(p/'diagnostics-second.bin'),'--sample-rate',str(fs),'--generation',str(wire['generation']),'--nonce','0x'+wire['nonce_hex']]
run=subprocess.run(cmd,capture_output=True,timeout=10);(p/'diagnostics-decoded.json').write_bytes(run.stdout);(p/'diagnostics-decoder-stderr.txt').write_bytes(run.stderr)
assert run.returncode==0,run.stdout.decode(errors='replace')
diag=json.loads(run.stdout);assert diag['errors']==[] # faults/warnings retained as negative evidence
run=subprocess.run([sys.executable,'-I','-B',str(base/'save_stopped_state.py'),'--session-dir',str(p),'--sample-rate',str(fs)],capture_output=True,timeout=10)
(p/'register-decoder-console.txt').write_bytes(run.stdout+run.stderr);assert run.returncode==0,run.stdout.decode(errors='replace')
facts=dict(program_readback_bytes=plan['candidate_bytes'],user_confirmed_SD_replug=True,starts=1,SWD_or_halt_during_active=False,SWD_only_after_owner_close_and_fault_END_followed_by_matching_STOP_ACK=True,legacy_dump_independent_calls=2,ADC_DR_read=False,rollback_performed=False,retained_image='V2SD/0x56325344',source='Root operator invoked this helper only after recorded owner closure and fault END followed by matching STOP_ACK; invocation chronology/logs retained',helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(p/'hardware-procedure-facts.json').write_text(json.dumps(facts,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(Fs=fs,diagnostic_record_and_stopped_registers_valid=True,physical_trial='FAIL',nonce=wire['nonce_hex'])))
