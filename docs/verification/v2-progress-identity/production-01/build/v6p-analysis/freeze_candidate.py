"""Freeze P software evidence, including preserved negative-command failure; no tests/hardware."""
from pathlib import Path
import hashlib,json,re

root=Path(__file__).resolve().parents[2]
def read(rel):return json.loads((root/rel).read_text('utf8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pin(rel):
    p=root/rel;return {'path':rel,'bytes':p.stat().st_size,'sha256':digest(p)}
def write(rel,obj):(root/rel).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf8',newline='\n')
fw='build/v6p-fw-01';first='build/v6p-native-01';completion='build/v6p-native-02'
r=read(fw+'/receipt.json');n=read(first+'/result.json');c=read(completion+'/result.json');previous=read('build/v6o-fw-01/receipt.json')
assert r['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and c['status']=='PASS'
assert n['status']=='FAILED' and n['error']=='ValueError: Negative compile failed for wrong reason'
assert all(not x['input_drift'] for x in (r,n,c))
assert c['positive_native_model_executions_total']==c['ARM_executions_total']==1
assert r['config']['firmware_build']==0x56325349
for name,h in r['inputs_before'].items():assert Path(name).is_file() and digest(Path(name))==h,name
for name,h in c['inputs'].items():assert Path(name).is_file() and digest(Path(name))==h,name
assert r['elf_audit']['layout']['static_end']==previous['elf_audit']['layout']['static_end']
assert r['static_bound']['upper_bound_bytes']==6156
symbols={}
for line in (root/fw/'image.nm').read_text('utf8').splitlines():
    m=re.match(r'^([0-9a-f]+) ([0-9a-f]+) [A-Za-z] (\S+)$',line)
    if m:symbols[m[3]]={'address':'0x'+m[1].upper(),'bytes':int(m[2],16)}
assert symbols['mt_stream_progress']=={'address':'0x20002FA4','bytes':64}
assert symbols['mt_stream_diagnostics']=={'address':'0x20002F1C','bytes':136}
sections={s['name']:s['size'] for s in r['elf_audit']['layout']['alloc_sections']}
proof=read(first+'/source-equivalence.json');assert proof['status']=='PASS'
assert len(proof['unchanged_SH_patched_sources'])==52 and len(proof['unchanged_nonbinding_objects'])==31
audit={
 'schema':'motortester-V2-06p-author-audit-1','date':'2026-10-27','status':'OBSERVER_BINDING_SOFTWARE_CANDIDATE_NOT_THROUGHPUT_FIX',
 'motivation':pin('build/v6o-followup/analysis.md'),
 'single_identity':{'source':'Validated config.json.firmware_build','generated_header':pin(fw+'/generated/mt_firmware_build.h'),'consumers':['generated/board.c','patched/v2/platform/mt_stream_progress.h included by actual mt_stream_progress.c'],'no_independent_observer_literal':True,'missing_macro_no_default':True,'allowlist_is_review_constraint_not_separate_compiled_id':True},
 'source_and_machine_proof':{'evidence':pin(first+'/source-equivalence.json'),'SH_unchanged_patched_files':52,'SH_unchanged_nonbinding_objects':31,'observer_C_body_byte_identical_SH':True,'bind_allocated_machine_bytes':'Identical SH except one0x56325347 literal replaced by exact config0x56325349','other_observer_alloc_sections_geometry_and_bytes_preserved':True,'board_linked_build_matches_config':True,'shared_header_compiler_dependencies_both_consumers_checked':True},
 'resources':{'bin_bytes':(root/fw/'MotortesterV2-stream-candidate.bin').stat().st_size,'data_bytes':sections['.data'],'bss_bytes':sections['.bss'],'new_static_bytes':0,'stack_reserve_bytes':8192,'static_plus_reserve':sections['.data']+sections['.bss']+8192,'RAM_bytes':20480,'spare_above_reserve':20480-sections['.data']-sections['.bss']-8192,'conditional_stack':r['static_bound'],'not_physical_stack_high_water':True},
 'records':{'progress64':symbols['mt_stream_progress'],'legacy136':symbols['mt_stream_diagnostics'],'layout_counters_flags_frozen_semantics_unchanged':True},
 'verification':{
  'ARM':'build/v6p-fw-01 PASS first execution; not repeated.',
  'actual_C':'One actual observer model execution in native01: SI accepted, SG/SH/foreign/gen/nonce rejected; FIFO count classes, known partial/unknown handling and CLOSING/FROZEN immutability pass. Exact ARM generated header used.',
  'preserved_failure':'native01 aggregate FAILED solely because Zig wrapper rejected -fsyntax-only with implicit-c under Werror before the intended #error. Native C model/fixtures and source proof succeeded. Original runner archived byte-exact in analysis/check_progress_binding-r1.py.',
  'addressed_repair':'native02 repeated ONLY the missing-macro compiler probe using -c/-o; required #error observed. It pins native01 C/fixtures/inputs and archived/current runner delta. No actual C or ARM rerun.',
  'root_decoder':'Root-owned decoder01 PASS once on actual SI C64 plus synthetic C legacy136, clean profile and19 negatives. Not actual legacy module execution or hardware identity.',
  'counts':{'ARM':1,'actual_C_model':1,'negative_compiler_probe_attempts':2,'root_decoder':1},
  'full_runtime_ADC_USB_not_executed':True,'COM_SWD_Reset_Flash_by_author':False
 },
 'native_fixture':{'record64':pin(first+'/actual-progress.bin'),'companion136':pin(first+'/actual-legacy.bin'),'companion_identity':pin(first+'/companion.json'),'origin':'Actual observer C output and explicit synthetic native legacy setup; DWT/USB seams, no physical session'},
 'limits':['Correct observer binding does not fix queue-full or establish stable150k.','SI reactivates observer hot-path work absent from SH/O2; timing overhead is not subtracted or ignored.','Conditional ELF stack/RAM evidence is not physical high-water or WCET.','O2 zero64 remains INVALID; prior PASS/failed physical outputs stay preserved.','Fresh source/physical-plan review and separate hardware evidence are still required.']
}
write('build/v6p-analysis/author-audit.json',audit)
production=['firmware/v2-stream/'+p for p in ('README.md','build_windows.py','config.json','overlays/board_inputs.py','progress/mt_stream_progress.h','progress/mt_stream_progress.c','progress/ABI.md')]
sources=['tests/v2-stream-firmware/progress_binding_model.c','tests/v2-stream-firmware/check_progress_binding.py']
arm=[fw+'/'+p for p in ('receipt.json','static-bound.json','generated/mt_firmware_build.h','generated/board.c','objects/board.d','objects/29-mt_stream_progress.d','objects/29-mt_stream_progress.su','image.nm','image.map','image.dis','MotortesterV2-stream-candidate.bin','MotortesterV2-stream-candidate.elf')]
native=[first+'/'+p for p in ('result.json','source-equivalence.json','model.c','model.exe','model.stdout','model.stderr','compile.stdout','compile.stderr','compile-missing-build-negative.stdout','compile-missing-build-negative.stderr','actual-progress.bin','actual-legacy.bin','companion.json')]
native += [completion+'/'+p for p in ('result.json','compile-missing-build-negative.stdout','compile-missing-build-negative.stderr')]
root_owned=['docs/streaming-progress-identity.md','host/tools/decode_stream_progress.py','host/tests/stream_progress_decoder_check.py','build/v6p-decoder-01/result.json','build/v6p-decoder-01/fixture-decoded.json']
frozen={'schema':'motortester-V2-06p-source-freeze-1','date':'2026-10-27','status':'OBSERVER_BINDING_CANDIDATE_FROZEN_FOR_INDEPENDENT_REVIEW','firmware_build':'0x56325349','baseline_build':'0x56325348','product':'Motortester V2 Build Binding SI','production_files':[pin(p) for p in production],'native_source_files':[pin(p) for p in sources],'ARM_evidence':[pin(p) for p in arm],'native_evidence':[pin(p) for p in native],'root_owned_evidence':[pin(p) for p in root_owned],'generation_and_repair_scripts':[pin('build/v6p-analysis/'+p) for p in ('check_progress_binding-r1.py','complete_negative_probe.py','freeze_candidate.py')],'author_audit':pin('build/v6p-analysis/author-audit.json'),'resources':audit['resources'],'records':audit['records'],'verification':audit['verification'],'exact_inputs':'Full compiler/toolchain/generated header/board/observer dependencies and image analysis in ARM receipt; actual C inputs in preserved native01 and addressed-completion02. Archived r1 runner explains intentional current-runner delta. All current ARM/completion input pins rechecked at freeze.','hardware_verified':False,'stable150k_established':False,'flash_approved':False}
write('build/v6p-freeze.json',frozen)
print(json.dumps(pin('build/v6p-freeze.json')))
