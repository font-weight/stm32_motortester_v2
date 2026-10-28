"""Preserve newly produced installation evidence; do not operate hardware."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, shutil

r = Path.cwd()
b = r / 'build/v6u-board-01'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
question = 'SN записана: все 49 744 байта совпали при чтении памяти. Отключите от компьютера USB платы и USB ST-Link на 10 секунд. Затем подключите USB платы, подождите 5 секунд и подключите USB ST-Link. Провода между ними не трогайте, PA0 оставьте пустым, приложение пока не открывайте. Напишите «готово» — после этого выполню одну 30-секундную запись на 150 000 отсчётов/с с пакетами по 1024. Это нужно, чтобы Windows обновила USB-соединение после новой прошивки.'
record = {
 'schema': 'v2-06u-installation-root-facts-1',
 'recorded_utc': datetime.now(timezone.utc).isoformat(),
 'operator': 'root',
 'source_commit': '308406d8627fc2aedc6e8eb7abd833e1f229102f',
 'plan_sha256': sha(b/'plan.json'),
 'plan_review_sha256': sha(r/'docs/verification/v2-collect-local/critic-flash.json'),
 'fresh_inventory': 'preflash-inventory.json',
 'fresh_probe': 'preflash-probe-verified.json',
 'sequence': ['Fresh Windows inventory: expected COM6/code0, one ST-Link, no app/capture owners', 'Read-only full64KiB current SL and probe serial: equal saved backup', 'One SN program with verification', 'One separate full49744-byte readback: byte-equal SN', 'One Reset/Run', 'New actual cold-cycle question sent to user'],
 'reset_log_sha256': sha(b/'reset.log'),
 'START_sent': False,
 'COM_opened': False,
 'automatic_rollback': False,
 'new_user_reply_received_at_this_record': False,
 'new_user_question_text_whitespace_normalized': question,
 'prior_SL_ready_not_reused': True,
 'physical150k_accepted': False,
 'next': 'Wait for new actual reply after SN Reset; preserve chronology and fresh inventory, then one150k30s trial only.'
}
rp=b/'installation-root-facts.json'
assert not rp.exists()
rp.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
dest=r/'docs/verification/v2-collect-local/installation-01'
dest.mkdir(exist_ok=False)
names=['preflash_probe.py','preflash-current64k.bin','preflash-inventory.json','preflash-probe-invocation.json','preflash-probe-verified.json','preflash-probe.log','preflash-probe.stdout.bin','program-invocation.json','program.log','program.stdout.bin','readback-invocation.json','readback-verified.json','readback.bin','readback.log','readback.stdout.bin','reset-invocation.json','reset.log','reset.stdout.bin','installation-root-facts.json']
paths=[b/n for n in names]+[r/'build/v6u-installation-archive.py',r/'docs/reviews/v2-06u-flash-review.md',r/'docs/verification/v2-collect-local/critic-flash.json']
rows=[]
for src in paths:
 target=dest/src.relative_to(r)
 target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(src,target)
 assert src.read_bytes()==target.read_bytes()
 rows.append({'source':src.relative_to(r).as_posix(),'archive':target.relative_to(r).as_posix(),'bytes':src.stat().st_size,'sha256':sha(src)})
manifest={'schema':'v2-06u-installation-delta-1','scope':'One SN program/full readback/reset. No START or physical150k result. Fresh user cold-cycle reply pending at archive creation.','plan_archive':{'path':'docs/verification/v2-collect-local/plan-01/manifest.json','sha256':sha(r/'docs/verification/v2-collect-local/plan-01/manifest.json')},'files':rows}
mp=dest/'manifest.json'
mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':len(rows),'bytes':sum(x['bytes'] for x in rows),'manifest_sha256':sha(mp)}))
