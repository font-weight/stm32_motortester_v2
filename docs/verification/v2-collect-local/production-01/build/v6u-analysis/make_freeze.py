"""Pin the U delta and saved evidence; reference immutable SL rather than duplicate it."""
from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parents[2]

def pin(rel):
    p=root/rel;b=p.read_bytes()
    return {'path':rel,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def pins(rows):return [pin(p) for p in rows]
def load(rel):return json.loads((root/rel).read_text('utf8'))

arm='build/v6u-fw-01';native='build/v6u-native-01';host='build/v6u-host-identity-01'
receipt=load(arm+'/receipt.json');nr=load(native+'/result.json');hr=load(host+'/result.json')
audit=load('build/v6u-analysis/arm-audit.json')
assert receipt['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and receipt['input_drift']==[]
assert nr['status']==hr['status']=='PASS' and nr['input_drift']==hr['input_drift']==[]
assert receipt['config']['firmware_build']==0x5632534e
assert audit['status']=='PASS_MATERIAL_COMPILED_WORK_REDUCTION_NOT_WCET'

production=['firmware/v2-stream/'+p for p in ('README.md','config.json','overlays/board_inputs.py',
    'batch1024/production/mt_batch1024.c')]
arm_rows=['receipt.json','static-bound.json','config.json','generated/mt_firmware_build.h','generated/board.c',
    'MotortesterV2-stream-candidate.bin','MotortesterV2-stream-candidate.elf','image.map','image.nm','size.stdout',
    'patched/v2/protocol/mt_batch1024.c','patched/v2/protocol/mt_batch1024.h',
    'objects/28-mt_batch1024.o','objects/28-mt_batch1024.su',
    'objects/board.d','objects/29-mt_stream_progress.d','objects/29-mt_stream_progress.o',
    'disassembly-28-mt_batch1024.stdout','compile-28-mt_batch1024.stderr']
native_rows=['result.json','source-equivalence.json','sl.c','sn.c','mt_batch1024.h','model.c',
    'mt_wire.c','mt_wire.h','mt_v2_crc32.h','model.exe','model.stdout','model.stderr',
    'compile-sl.stdout','compile-sl.stderr','compile-sn.stdout','compile-sn.stderr',
    'compile-model.stdout','compile-model.stderr']
data={
    'schema':'motortester-V2-06u-source-freeze-1','date':'2026-10-28',
    'status':'EQUIVALENT_COLLECT_CANDIDATE_FROZEN_FOR_INDEPENDENT_REVIEW',
    'firmware_build':'0x5632534e','baseline_build':'0x5632534c',
    'product':'Motortester V2 Collect Local SN',
    'production_files':pins(production),
    'native_source_files':pins(['tests/v2-stream-firmware/check_collect_local.py',
                              'tests/v2-stream-firmware/collect_local_model.c']),
    'baseline_reference':{
        'source_commit':'695efd95e7c4ba72bfa6fb5fb511b85186be6266',
        'archive':'docs/verification/v2-postcopy-handoff/production-01/',
        'copy_policy':'Reference frozen SL inputs; do not duplicate the hundreds of unchanged recipe/base files in U delta archive.',
        'pins':pins(['build/v6s-freeze.json','build/v6s-fw-02/receipt.json',
                     'build/v6s-fw-02/patched/v2/protocol/mt_batch1024.c',
                     'build/v6s-fw-02/disassembly-28-mt_batch1024.stdout']),
        'unchanged_recipe_files':pins(['firmware/v2-stream/build_windows.py','firmware/v2-stream/check_static.py',
                                      'firmware/v2-stream/batch1024/production/mt_batch1024.h'])},
    'ARM_evidence':pins([arm+'/'+p for p in arm_rows]),
    'native_evidence':pins([native+'/'+p for p in native_rows]),
    'host_evidence':pins(['host/tools/decode_stream_progress.py','host/tools/decode_usb_gate.py',
        'host/tests/collect_identity_check.py',host+'/result.json',
        host+'/sn-synthetic-derived/derivation.json',host+'/sn-synthetic-derived/decoded.json']),
    'author_evidence':pins(['build/v6u-analysis/notes.md','build/v6u-analysis/author-audit.md',
        'build/v6u-analysis/analyze_arm.py','build/v6u-analysis/arm-audit.json',
        'build/v6u-analysis/make_freeze.py']),
    'failed_attempts':{
        'ARM':[],'native':[],'successful_ARM_builds':1,'native_executions':1,
        'offline_analysis':[{'status':'FAILED_OFFLINE_ANALYSIS_PARSER',
            'reason':'CRLF nm text was not normalized before end-anchored mt_board regex; no production/build/native change.',
            'preserved':pins(['build/v6u-analysis/analyze_arm-attempt-01.py',
                              'build/v6u-analysis/arm-audit-attempt-01.json'])}],
        'offline_analysis_runs':2,'repair':'Normalize CRLF for parser only; rerun saved-artifact analysis, not ARM/native.'},
    'resources':dict(audit['resources'],BIN_path=arm+'/MotortesterV2-stream-candidate.bin',
                     ELF_path=arm+'/MotortesterV2-stream-candidate.elf',
                     observer_addresses=audit['observer_addresses']),
    'compiled_reduction':{
        'SL_loop':['0x000000cc','0x0000014a'],'SN_aligned4_loop':['0x00000102','0x000001dc'],
        'listed_instruction_slots_per4':{'SL':160,'SN':61},
        'packed_STRB_per4':{'SL':8,'SN':5},'count_reloads_per4':{'SL':4,'SN':0},
        'count_bit_MUL_per4':{'SL':4,'SN':0},'canonical_CRC_table_loads_per4':{'SL':8,'SN':8},
        'CRC_already_local_in_SL':True,'optimization':'-Os unchanged',
        'scope':'Static listing/work reduction, not ISA retirement/cycles/WCET; validation/prologue/epilogue/tails excluded.'},
    'verification':{'native_status':nr['status'],'native_calls':4707,'completed_frames':28,
        'native_input_drift':nr['input_drift'],'ARM_input_drift':receipt['input_drift'],
        'unchanged_other_serializer_APIs':7,'unchanged_other_patched_files':54,
        'unchanged_objects_exact_bytes':31,'observer_object_delta':'Exactly one common build-ID literal',
        'generated_board_delta':'Common build ID and product only',
        'compiled_board_build_word':audit['common_identity'],
        'host_identity_status':hr['status'],'host_fixture_origin':'EXPLICIT_SYNTHETIC_DERIVATION_OF_ARCHIVED_SL_ACTUAL_C_TRIO',
        'new_actual_SN_observer_execution':False,'old_broad_suites_repeated':False},
    'limits':['Physical sustained150k remains open; no COM/SWD/Reset/Flash by the author.',
        'Prepare58/147ms S2 was inclusive wall; no CPU share or sufficient throughput improvement inferred.',
        'Static stack bound is conditional, not physical watermark; only4B beyond8192 reserve, no newstatic.',
        'Host SN identity fixture is derived synthetic data; actual common SN binding is established by ARM inputs/deps/object/BIN.',
        'T/preflush was NO-GO and has no image; U does not change whole-fit/grants/runtime/wire/ADC/TIME/queues.'],
    'independent_source_review':'PENDING_SEPARATE_GATE','hardware_executed':False,'flash_approved':False}
target=root/'build/v6u-freeze.json'
assert not target.exists(),'Freeze is append-only; make an explicit revision if required'
target.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps(pin('build/v6u-freeze.json')))
