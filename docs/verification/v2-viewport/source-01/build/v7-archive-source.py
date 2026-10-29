from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil
r=Path.cwd(); dest=r/'docs/verification/v2-viewport/source-01'
dest.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
unit={'status':'PASS','provenance':'Root saved the actual exec tool console result; not a second test run',
 'tests':['test_held_live_raw_survives_ring_eviction_and_one_wheel_expands_edges','test_live_raw_copy_rejects_wrong_length_and_envelope_codes','test_actual_drag_and_wheel_change_selection_without_resetting_y','test_rapid_navigation_coalesces_and_rejects_stale_render'],
 'command_prefix':'.venv/Scripts/python.exe -B -m unittest test_gui_stream.StreamPanelTests.',
 'environment':{'PYTHONPATH':'host;host/tests'},'exit_code':0,'stdout':'....\nRan 4 tests in 1.913s\nOK',
 'limits':'Run after raw-hold/pause fixes; later UI-only changes were event label and FullViewportUpdate. Final native03 covers final UI. No whole inherited suite or COM.'}
up=r/'build/v7-unit-result.json';assert not up.exists()
up.write_text(json.dumps(unit,indent=2)+'\n',encoding='utf-8')
paths=[up,r/'build/v7-archive-source.py']
for name in ('v7-view-native-01','v7-view-native-02','v7-view-native-03'):
 paths+=sorted(x for x in (r/'build'/name).iterdir() if x.is_file())
sources=['host/motortester/gui_stream.py','host/motortester/v2/stream_ui.py',
 'host/motortester/v2/stream_viewport_smoke.py','host/tests/test_gui_stream.py',
 'host/packaging/v2/build_windows.py','host/packaging/v2/launcher.py',
 'host/packaging/v2/viewport_package_check.py']
paths+=[r/p for p in sources]
rows=[]
for src in paths:
 target=dest/src.relative_to(r);target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(src,target);assert src.read_bytes()==target.read_bytes()
 rows.append({'source':src.relative_to(r).as_posix(),'archive':target.relative_to(r).as_posix(),'bytes':src.stat().st_size,'sha256':sha(src)})
record={'schema':'v2-07-viewport-source-evidence-1','recorded_utc':datetime.now(timezone.utc).isoformat(),
 'scope':'Bounded manual live raw, pause worker polling, full viewport repaint, saved detail-to-overview; Windows DEMO, no hardware.',
 'failed_attempt':'native01 waited for receiver advancement but not slower GUI metadata; native02 added matching GUI predicate. No production change between01/02.',
 'final_attempt':'native03 also crosses saved detail/overview boundary and requires FullViewportUpdate; no claim of reproducing exact user saved-file paint fault on old build.',
 'files':rows,'source_pins':{p:sha(r/p) for p in sources}}
mp=dest/'manifest.json';mp.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':len(rows),'bytes':sum(x['bytes'] for x in rows),'manifest_sha256':sha(mp)}))
