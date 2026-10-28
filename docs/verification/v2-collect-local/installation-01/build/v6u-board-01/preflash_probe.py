"""Root-only fresh read of stopped SL before the admitted SN installation."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, subprocess, time

r = Path.cwd()
b = r / 'build/v6u-board-01'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
p = json.loads((b / 'plan.json').read_bytes())
inv = json.loads((b / 'preflash-inventory.json').read_text('utf-8-sig'))
assert not inv['owners']
assert any(x['DeviceID'] == p['port'] and x['PNPDeviceID'] == p['expected_pnp_id'] and x['ConfigManagerErrorCode'] == 0 for x in inv['ports'])
previous = json.loads((r / 'build/v6s-board-01/150000/run/result.json').read_bytes())
assert previous['cleanup_finished'] and previous['final_state']['phase'] == 'closed'
assert sha(Path(p['cli_path'])) == p['cli_sha256_from_H_template']
target = b / 'preflash-current64k.bin'
assert not target.exists()
argv = [p['cli_path'], '-c', 'ID=0', 'SWD', 'HOTPLUG', '-Dump', '0x08000000', '0x10000', str(target.relative_to(r))]
stamp = datetime.now(timezone.utc).isoformat()
clock = time.monotonic()
proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
(b / 'preflash-probe.stdout.bin').write_bytes(proc.stdout)
log = proc.stdout.decode('utf-8', errors='replace')
(b / 'preflash-probe.log').write_text(log, encoding='utf-8')
(b / 'preflash-probe-invocation.json').write_text(json.dumps({'argv': argv, 'started_utc': stamp, 'wall_seconds': time.monotonic()-clock, 'exit_code': proc.returncode}, indent=2)+'\n', encoding='utf-8')
assert proc.returncode == 0 and p['probe_serial'] in log and 'succeded' in log, log
assert target.read_bytes() == (b / 'before-flash-64k.bin').read_bytes()
record = {'status': 'PASS', 'bytes': target.stat().st_size, 'sha256': sha(target), 'byte_equal_to_saved_SL': True, 'operation': 'Read only, no reset/program/COM', 'probe_serial': p['probe_serial'], 'inventory_sha256': sha(b / 'preflash-inventory.json')}
(b / 'preflash-probe-verified.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
print(json.dumps(record))
