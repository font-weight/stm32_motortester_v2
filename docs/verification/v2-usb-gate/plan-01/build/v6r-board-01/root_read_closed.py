"""Root-only SWD read after closed owner and matching saved END/STOP_ACK.

No reset/halt/flash or ADC_DR reads. New trace is not live-polled.
"""
from pathlib import Path
import hashlib,json,subprocess,sys,time
from datetime import datetime,timezone
r=Path.cwd();base=r/'build/v6r-board-01';p=base/'150000'
plan=json.loads((base/'plan.json').read_bytes());result=json.loads((p/'run/result.json').read_bytes())
wire=json.loads((p/'physical-analysis.json').read_bytes())
assert wire['offline_validation_status']=='PASS' and wire['owners_closed'] is True
assert (result.get('owners_closed') is True or (result.get('cleanup_finished') is True and result['final_state']['phase']=='closed'))
assert wire['terminal'] and wire['ack'] and wire['stop']
assert wire['ack']['payload']['terminal_sequence']==wire['terminal']['sequence']
assert wire['ack']['payload']['prefix_end']==wire['terminal']['payload']['prefix_end']
assert wire['ack']['request_id']==wire['stop']['request_id']
cli=plan['cli_path'];assert hashlib.sha256(Path(cli).read_bytes()).hexdigest()==plan['cli_sha256_from_H_template']
reads=[('diagnostics-first',int(plan['diagnostic_address'],16),136),('diagnostics-second',int(plan['diagnostic_address'],16),136),
    ('progress-first',int(plan['progress_address'],16),64),('progress-second',int(plan['progress_address'],16),64),
    ('gate-first',int(plan['gate_address'],16),24),('gate-second',int(plan['gate_address'],16),24),
    ('tim3',0x40000400,48),('adc',0x40012408,12),('dma',0x40020008,16),('rcc',0x4002100C,20)]
for name,address,count in reads:
    target=p/(name+'.bin');assert not target.exists()
    cmd=[cli,'-c','ID=0','SWD','HOTPLUG','-Dump',hex(address),hex(count),str(target.relative_to(r))]
    started=datetime.now(timezone.utc).isoformat();t=time.monotonic()
    run=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
    log=run.stdout.decode('utf-8',errors='replace');(p/(name+'.stdout.bin')).write_bytes(run.stdout);(p/(name+'.log')).write_text(log,encoding='utf-8')
    (p/(name+'.invocation.json')).write_text(json.dumps(dict(argv=cmd,started_utc=started,exit_code=run.returncode,wall_seconds=time.monotonic()-t),indent=2)+'\n',encoding='utf-8')
    assert run.returncode==0 and plan['probe_serial'] in log and 'succeded' in log and target.stat().st_size==count,log
    print(name+' saved '+str(count)+' bytes',flush=True)
cmd=[sys.executable,'-I','-B',str(base/'decode_diagnostics.py'),str(p/'diagnostics-first.bin'),str(p/'diagnostics-second.bin'),'--sample-rate','150000','--generation',str(wire['generation']),'--nonce','0x'+wire['nonce_hex']]
run=subprocess.run(cmd,capture_output=True,timeout=10);(p/'diagnostics-decoded.json').write_bytes(run.stdout);(p/'diagnostics-decoder-stderr.txt').write_bytes(run.stderr)
assert run.returncode==0,run.stdout.decode(errors='replace')
assert json.loads(run.stdout)['errors']==[]
run=subprocess.run([sys.executable,'-I','-B',str(base/'save_stopped_state.py'),'--session-dir',str(p),'--sample-rate','150000'],capture_output=True,timeout=10)
(p/'register-decoder-console.txt').write_bytes(run.stdout+run.stderr);assert run.returncode==0,run.stdout.decode(errors='replace')
# Decoder invocation is bound by the plan; field layout remains owned by its versioned header.
cmd=[sys.executable,'-I','-B','host/tools/decode_stream_progress.py',str(p/'progress-first.bin'),str(p/'progress-second.bin'),
    '--legacy',str(p/'diagnostics-decoded.json'),'--nonce','0x'+wire['nonce_hex'],'--generation',str(wire['generation']),
    '--image-sha256',plan['candidate_sha256'],'--build-id',plan['firmware_build']]
run=subprocess.run(cmd,capture_output=True,timeout=10);(p/'progress-decoded.json').write_bytes(run.stdout);(p/'progress-decoder-stderr.txt').write_bytes(run.stderr)
assert run.returncode==0,run.stdout.decode(errors='replace')
# Paired24 bank is a pre-CLOSING record; the64 snapshot is later, not simultaneous.
cmd=[sys.executable,'-I','-B','host/tools/decode_usb_gate.py',str(p/'gate-first.bin'),str(p/'gate-second.bin'),
    '--progress-first',str(p/'progress-first.bin'),'--progress-second',str(p/'progress-second.bin'),
    '--legacy',str(p/'diagnostics-decoded.json'),'--nonce','0x'+wire['nonce_hex'],
    '--generation',str(wire['generation']),'--image-sha256',plan['candidate_sha256'],'--build-id',plan['firmware_build']]
run=subprocess.run(cmd,capture_output=True,timeout=10);(p/'gate-decoded.json').write_bytes(run.stdout);(p/'gate-decoder-stderr.txt').write_bytes(run.stderr)
assert run.returncode==0,run.stdout.decode(errors='replace')
facts=dict(program_readback_bytes=plan['candidate_bytes'],starts=1,SWD_or_halt_during_active=False,
    SWD_only_after_owner_close_and_matching_END_ACK=True,legacy_dump_independent_calls=2,progress_dump_independent_calls=2,gate_dump_independent_calls=2,
    ADC_DR_read=False,rollback_performed=False,retained_image='V2SK/0x5632534b',
    source='Root operator used this helper after saved owner closure and matching terminal evidence; chronology/logs retained')
(p/'hardware-procedure-facts.json').write_text(json.dumps(facts,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(diagnostic_evidence_saved=True,physical_probe=result['status'],nonce=wire['nonce_hex'])))
