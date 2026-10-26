"""Root-operated read-only backup of the stopped, connected SD board. No reset/program/START."""
from pathlib import Path
import subprocess, hashlib, json, time
from datetime import datetime, timezone

r=Path.cwd(); out=r/'build/v6l-board-01'
cli=Path('C:/Program Files (x86)/STMicroelectronics/STM32 ST-LINK Utility/ST-LINK Utility/ST-LINK_CLI.exe')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(cli)=='7fb012b5e26abf45342caa05c6bc33936f8a379b67797cc55658ffb8bf15e95f'
assert (out/'probe-list.txt').read_text('utf-8-sig').count('ST-LINK Probe ')==1
processes=json.loads((out/'processes-before.json').read_text('utf-8-sig'))
assert processes == [], 'A Python/Motortester process is active; inspect before SWD'
port=json.loads((out/'ports-before.json').read_text('utf-8-sig'))
assert port['DeviceID']=='COM6' and port['PNPDeviceID']==r'USB\VID_1209&PID_0001&MI_00\6&D2DE68C&0&0000'
target=out/'before-flash-64k.bin'; assert not target.exists()
cmd=[str(cli),'-c','ID=0','SWD','HOTPLUG','-Dump','0x08000000','0x10000',str(target.relative_to(r))]
start=time.monotonic(); result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20)
(out/'backup.stdout.bin').write_bytes(result.stdout)
log=result.stdout.decode('utf-8',errors='replace'); (out/'backup.log').write_text(log,encoding='utf-8')
(out/'backup-invocation.json').write_text(json.dumps({'argv':cmd,'exit_code':result.returncode,
    'wall_seconds':time.monotonic()-start,'utc':datetime.now(timezone.utc).isoformat()},indent=2)+'\n',encoding='utf-8')
assert result.returncode==0 and '57005400120000393333574E' in log and 'succeded' in log,log
raw=target.read_bytes(); old=r/'build/v6k-fw-01/MotortesterV2-stream-candidate.bin'
assert len(raw)==65536 and len(old.read_bytes())==39448
assert sha(old)=='244c3af19647ffa24d43973c1d55d24e3b5ce70c494bf781067e13aa60a2daa5'
assert raw[:39448]==old.read_bytes(), 'Board differs from saved SD; no flash authorized by this helper'
receipt={'status':'PASS','operation':'Read-only fresh64KiB SD backup; no reset/program/START',
    'backup_bytes':len(raw),'backup_sha256':sha(target),'prefix_bytes':39448,'prefix_equal_exact_SD':True,
    'prefix_sha256':sha(old),'probe_SN':'57005400120000393333574E','COM':'COM6',
    'app_or_capture_process_observed':False,'ADC_input':'User confirmed PA0 empty',
    'log_sha256':sha(out/'backup.stdout.bin')}
(out/'backup-verified.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps(receipt))
