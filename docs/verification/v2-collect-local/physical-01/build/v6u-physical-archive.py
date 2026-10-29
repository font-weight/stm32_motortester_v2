"""Archive the completed single SN trial; no new measurement or decoding."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, shutil

r=Path.cwd(); b=r/'build/v6u-board-01'; trial=b/'150000'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda p:json.loads(p.read_bytes())
invocation=load(trial/'trial-invocation.json')
analysis=load(trial/'physical-analysis.json')
receipt=load(trial/'run/result.json')
first_swd=load(trial/'diagnostics-first.invocation.json')
assert receipt['owners_closed'] and analysis['offline_validation_status']=='PASS'
assert invocation['finished_utc'] < first_swd['started_utc']
assert load(b/'150000-user-replug.json')['actual_user_reply']=='готово'
facts={
 'schema':'v2-06u2-root-chronology-1',
 'recorded_utc':datetime.now(timezone.utc).isoformat(),
 'operator':'root',
 'source_commit':'308406d8627fc2aedc6e8eb7abd833e1f229102f',
 'plan_sha256':sha(b/'plan.json'),
 'installation_manifest_sha256':sha(r/'docs/verification/v2-collect-local/installation-01/manifest.json'),
 'actual_SN_reply_record_sha256':sha(b/'150000-user-replug.json'),
 'fresh_pretrial_inventory_sha256':sha(b/'pretrial-inventory.json'),
 'one_trial_started_utc':invocation['started_utc'],
 'one_trial_finished_utc':invocation['finished_utc'],
 'first_SWD_read_started_utc':first_swd['started_utc'],
 'root_observed_sequence':['New actual SN cold-cycle reply received (not old SL reply)', 'Fresh COM6/code0 and one ST-Link, no app/capture owners', 'One run_trial invocation, one150k mode5 requested30s START', 'Waited for trial process to complete with PASS and owners_closed', 'One offline saved-data analysis PASS with coherent normal END/STOP/ACK and fresh Open', 'Only then root_read_closed: independent pairs136/64/24 and stopped registers', 'No additional START, reset, flash or rollback'],
 'SWD_or_halt_during_active':False,
 'ADC_DR_read':False,
 'retained_image':'SN/0x5632534e, stopped after normal host STOP',
 'physical_scope':'One30s150k mode5 DATA1024 record with PA0 unconnected, Windows10 COM6. No external timing/analog calibration or long-duration claim.',
 'unknown_produced_tail_preserved':True,
 'diagnostic_cap_is_checkpoint_not_stop':True,
 'limits':['Historical N64/G24 stop observation near250ms, not end of30s', 'Legacy max queue occupancy8 is not an overflow fault', 'One passing trial does not certify all operating conditions,50/100SN,GUI load or analog input', 'physical-analysis.md heading V2-06s is a retained cosmetic label from frozen helper; exact SN/build is explicit in body/JSON'],
}
fp=trial/'root-chronology.json';assert not fp.exists()
fp.write_text(json.dumps(facts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
dest=r/'docs/verification/v2-collect-local/physical-01';dest.mkdir(exist_ok=False)
paths=sorted(x for x in trial.rglob('*') if x.is_file())
paths += [b/'150000-user-replug.json',b/'pretrial-inventory.json',b/'com-inventory.json',r/'build/v6u-physical-archive.py']
rows=[]
for src in paths:
 target=dest/src.relative_to(r);target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(src,target)
 assert src.read_bytes()==target.read_bytes()
 rows.append({'source':src.relative_to(r).as_posix(),'archive':target.relative_to(r).as_posix(),'bytes':src.stat().st_size,'sha256':sha(src)})
references=[]
for name in ('production-01','plan-01','installation-01'):
 p=r/f'docs/verification/v2-collect-local/{name}/manifest.json'
 references.append({'path':p.relative_to(r).as_posix(),'sha256':sha(p)})
manifest={'schema':'v2-06u2-physical-evidence-1','scope':'Completed one150k30s SN trial. Probe/offline PASS; independent physical review separate. No analog/tail completeness/universal stability claim.','references':references,'files':rows}
mp=dest/'manifest.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':len(rows),'bytes':sum(x['bytes'] for x in rows),'manifest_sha256':sha(mp)}))
