"""Pin exact O author evidence; report generation only, no execution/hardware."""
from pathlib import Path
import hashlib,json,re

root=Path(__file__).resolve().parents[2]
def read(rel):return json.loads((root/rel).read_text('utf8'))
def pin(rel):
    p=root/rel
    return {'path':rel,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def write(rel,obj):(root/rel).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf8',newline='\n')
fw='build/v6o-fw-01';native='build/v6o-native-01'
r=read(fw+'/receipt.json');n=read(native+'/result.json');b=read('build/v6n-fw-01/receipt.json')
assert r['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and n['status']=='PASS'
assert not r['input_drift'] and not n['input_drift']
assert r['config']['firmware_build']==0x56325348
assert r['elf_audit']['layout']['static_end']==b['elf_audit']['layout']['static_end']
assert r['static_bound']['upper_bound_bytes']==6156
assert (root/fw/'patched/v2/app/mt_live_runtime.c').read_bytes()==(root/'build/v6o-analysis/mt_live_runtime.c').read_bytes()
for path,h in r['inputs_before'].items():
    p=Path(path);assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==h,path
for path,h in n['inputs'].items():
    p=Path(path);assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==h,path
symbols={}
for line in (root/fw/'image.nm').read_text('utf8').splitlines():
    m=re.match(r'^([0-9a-f]+) ([0-9a-f]+) [A-Za-z] (\S+)$',line)
    if m:symbols[m[3]]={'address':'0x'+m[1].upper(),'bytes':int(m[2],16)}
assert symbols['mt_stream_progress']=={'address':'0x20002FA4','bytes':64}
assert symbols['mt_stream_diagnostics']=={'address':'0x20002F1C','bytes':136}
sections={s['name']:s['size'] for s in r['elf_audit']['layout']['alloc_sections']}
audit={
 'schema':'motortester-V2-06o-author-audit-1','date':'2026-10-27','status':'SOFTWARE_CANDIDATE_NOT_PHYSICAL_ACCEPTANCE',
 'baseline':pin('build/v6n-freeze.json'),'runtime':pin(fw+'/patched/v2/app/mt_live_runtime.c'),
 'scope':'Only scheduling hint, actual-ticket classification and fresh pre/post deferred grant barriers; same single grant budget and old early/fallback paths.',
 'evidence_boundaries':{
  'actual_runtime_model':'Extracted candidate runtime bodies and actual epoch module execute. ADC/core/USB/clock/scope callbacks are explicit logical seams.',
  'metadata_authority':'Hint checks mode/state/phase/count/queue-used/intents only; it is not a queue/ownership identity validator. Actual unchanged prepare and full guarded ticket remain authoritative.',
  'N64':'Observer C/header and legacy136 byte-identical SG; N instrumentation disabled only in logical native order model and enabled in exact ARM.',
  'physical':'No author hardware access, no150k throughput or deadline/WCET qualification.',
 },
 'changed_boundaries':[
  {'point':'post-ADC before RX','condition':'Only STREAMING/mode5/new full-batch scheduling hint skips old early grant; original fresh TIME/stable before RX is retained.'},
  {'point':'after prepare, before late grant','order':'Consume attempt marker; fresh live_time, synchronize_loss, usable/stable; enter app scope/actor; stable; unchanged grant_irq.'},
  {'point':'after late grant','order':'Fresh live_time/stable; leave scope on all outcomes; prepared epoch/serial and original core ticket are revalidated under original write-through-final-commit guard.'},
  {'point':'hint cancellation','order':'PREPARED DATA failing new STREAMING/READY1024 metadata remains cached for ordinary path next pass; EMPTY/control/ERROR retain original guarded handling.'},
  {'point':'scope/pre-admission failure','order':'Zero actual grant calls permitted; consumed marker prevents second current-step reset. Next ordinary pass retains fallback, including raw lifecycle.'},
 ],
 'unchanged':'TIME backend/checks, ADC/DMA, queue/ownership, serializer, core commit/CRC/Stop/HELLO, wire, DCD6/<500 continuation and N64/legacy136 algorithms.',
 'resources':{'bin_bytes':(root/fw/'MotortesterV2-stream-candidate.bin').stat().st_size,'data_bytes':sections['.data'],'bss_bytes':sections['.bss'],'new_static_bytes':0,'stack_reserve_bytes':8192,'static_plus_reserve':sections['.data']+sections['.bss']+8192,'RAM_bytes':20480,'spare_above_reserve':20480-sections['.data']-sections['.bss']-8192,'runtime_frame_bytes':328,'runtime_frame_equal_SG':True,'conditional_stack':r['static_bound'],'not_physical_stack_high_water':True},
 'records':{'progress64':symbols['mt_stream_progress'],'legacy136':symbols['mt_stream_diagnostics']},
 'risks':['Deferred grant also delays older in-flight IN in the selected pass.','Queue full can be detected inside ADC service before this pass reaches grant.','Current snapshot does not identify hold budget/time/final cause or quantify grant-window aging.','Additional TIME checks and changed IRQ timing have cost; no CPU-share or WCET inference.'],
 'verification':{'ARM':'build/v6o-fw-01 first attempt PASS; no failed author ARM outputs.','native':'build/v6o-native-01 first targeted attempt PASS; no old suites repeated.','root_decoder':'build/v6o-decoder-01 root-owned targeted run once, reused N C fixture with explicit synthetic SG/SH bindings; not a native SH or hardware trace.','COM_SWD_Reset_Flash_by_author':False},
 'source_equivalence':pin(native+'/source-equivalence.json')
}
write('build/v6o-analysis/author-audit.json',audit)
prod=['firmware/v2-stream/'+p for p in ('README.md','build_windows.py','config.json','overlays/board_inputs.py','overlays/late-grant.json','overlays/v2-late-grant-app-mt_live_runtime.c.patch')]
checks=['tests/v2-stream-firmware/check_deferred_grant.py','tests/v2-stream-firmware/deferred_grant_model.c']
evidence=[fw+'/'+p for p in ('receipt.json','static-bound.json','image.map','image.nm','image.dis','objects/21-mt_live_runtime.su','MotortesterV2-stream-candidate.bin','MotortesterV2-stream-candidate.elf')]
evidence += [native+'/'+p for p in ('result.json','source-equivalence.json','model.c','model.exe','compile.stdout','compile.stderr','model.stdout','model.stderr')]
root_owned=['docs/streaming-late-grant.md','host/tools/decode_stream_progress.py','host/tests/stream_progress_decoder_check.py','build/v6o-decoder-01/result.json']
frozen={'schema':'motortester-V2-06o-source-freeze-1','date':'2026-10-27','status':'SOFTWARE_CANDIDATE_FROZEN_FOR_INDEPENDENT_REVIEW','firmware_build':'0x56325348','baseline_build':'0x56325347','product':'Motortester V2 Late Grant SH','production_files':[pin(p) for p in prod],'native_source_files':[pin(p) for p in checks],'evidence':[pin(p) for p in evidence],'root_owned_evidence':[pin(p) for p in root_owned],'proposal_history':[pin('build/v6n-followup/analysis-r1.md'),pin('build/v6n-followup/analysis.md')],'author_audit':pin('build/v6o-analysis/author-audit.json'),'generation_scripts':[pin('build/v6o-analysis/prepare_late_grant.py'),pin('build/v6o-analysis/freeze_candidate.py')],'resources':audit['resources'],'records':audit['records'],'exact_inputs':'Complete compiler/toolchain/overlay/dependency/object/analysis pins in ARM receipt; source and model/seams in native result/source-equivalence. All recorded inputs rechecked at freeze.','verification':audit['verification'],'hardware_verified':False,'stable150k_established':False,'flash_approved':False}
write('build/v6o-freeze.json',frozen)
print(json.dumps(pin('build/v6o-freeze.json')))
