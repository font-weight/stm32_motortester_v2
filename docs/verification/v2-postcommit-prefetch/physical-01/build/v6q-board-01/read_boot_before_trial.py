"""Read four boot flags after COM enumeration failure, before any Q2 START.

No reset, flash, halt, COM access, ADC_DR or acquisition commands.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,struct,time
r=Path.cwd();base=r/'build/v6q-board-01';out=base/'connection-01'
out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=json.loads((base/'plan.json').read_bytes())
assert not (base/'150000').exists()
pre=json.loads((base/'trial-preflight.json').read_bytes())
assert pre['owners']==[] and pre['ports']==[]
for name in ('trial-preflight.json','com-inventory.json'):
    (out/name).write_bytes((base/name).read_bytes())
cli=Path(plan['cli_path']);assert sha(cli)==plan['cli_sha256_from_H_template']
dump=out/'boot-flags.bin'
argv=[str(cli),'-c','ID=0','SWD','HOTPLUG','-Dump','0x200005bc','0x10',str(dump.relative_to(r))]
start=datetime.now(timezone.utc).isoformat();tick=time.monotonic()
run=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
log=run.stdout.decode('utf-8',errors='replace');(out/'boot-flags.stdout.bin').write_bytes(run.stdout)
(out/'boot-flags.log').write_text(log,encoding='utf-8')
(out/'boot-flags.invocation.json').write_text(json.dumps(dict(argv=argv,started_utc=start,
    finished_utc=datetime.now(timezone.utc).isoformat(),wall_seconds=time.monotonic()-tick,
    exit_code=run.returncode),indent=2)+'\n',encoding='utf-8')
assert run.returncode==0 and plan['probe_serial'] in log and 'succeded' in log
assert dump.stat().st_size==16
values=dict(zip(('mt_main_last_runtime','mt_main_usb_init_result','mt_main_irq_admitted','mt_main_boot_failure'),struct.unpack('<4I',dump.read_bytes())))
report=dict(scope='Read-only pre-START boot flags after enumeration failure; not a stream test',
    expected_image=plan['candidate_sha256'],nm_sha256=plan['candidate_nm_sha256'],
    address='0x200005bc',bytes=16,sha256=sha(dump),values=values,
    START_sent=False,COM_opened=False,Reset_Flash_halt_performed=False,
    actual_user_reply='готово',question_item_id='["request_user_input_async","call_59decd1ac5554adda09f2363acf9f9a4",0]',
    outcome='No COM6; do not consume the one permitted acquisition. Need USB enumeration recovery.')
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
