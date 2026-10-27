"""Root: read boot diagnostics after closed, zero-traffic open failure; no reset/halt."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,struct
r=Path.cwd();b=r/'build/v6m-board-01';out=b/'usb-boot-01';out.mkdir(exist_ok=False)
receipt=json.loads((b/'150000/run/result.json').read_bytes())
assert receipt['cleanup_finished'] is True and receipt['final_state']['phase']=='closed'
assert receipt['traffic']['host_bytes']==receipt['traffic']['device_bytes']==0
plan=json.loads((b/'plan.json').read_bytes());cli=plan['cli_path']
assert hashlib.sha256(Path(cli).read_bytes()).hexdigest()==plan['cli_sha256_from_H_template']
reads=[('main',0x200005bc,16),('boot',0x20002e68,148),('rcc',0x40021000,40),('fault',0xe000ed24,28)]
result={}
for name,address,count in reads:
    target=out/(name+'.bin');cmd=[cli,'-c','ID=0','SWD','HOTPLUG','-Dump',hex(address),hex(count),str(target.relative_to(r))]
    start=datetime.now(timezone.utc).isoformat();q=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
    log=q.stdout.decode('utf-8',errors='replace');(out/(name+'.log')).write_text(log,encoding='utf-8')
    (out/(name+'-invocation.json')).write_text(json.dumps({'argv':cmd,'started_utc':start,'exit_code':q.returncode},indent=2)+'\n',encoding='utf-8')
    assert q.returncode==0 and plan['probe_serial'] in log and 'succeded' in log and target.stat().st_size==count,log
    result[name]=[hex(x) for x in struct.unpack('<'+'I'*(count//4),target.read_bytes())]
(out/'read-values.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
