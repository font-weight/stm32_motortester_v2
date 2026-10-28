from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[2]
def pin(rel):
    p=root/rel;b=p.read_bytes();return {'path':rel,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def pins(rows):return [pin(p) for p in rows]
arm='build/v6s-fw-02';native='build/v6s-native-01';host='build/v6s-host-identity-01'
receipt=json.loads((root/arm/'receipt.json').read_text('utf8'))
nr=json.loads((root/native/'result.json').read_text('utf8'))
assert receipt['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and nr['status']=='PASS'
production=['firmware/v2-stream/'+p for p in ('README.md','build_windows.py','config.json','check_static.py',
    'overlays/board_inputs.py','overlays/postcopy-handoff.json','overlays/v2-postcopy-app-mt_live_adc.h.patch',
    'overlays/v2-postcopy-app-mt_live_adc.c.patch','overlays/v2-postcopy-app-mt_live_runtime.c.patch',
    'progress/mt_stream_progress.c','progress/mt_stream_progress.h','progress/mt_usb_gate.c','progress/mt_usb_gate.h')]
arm_rows=['receipt.json','static-bound.json','config.json','generated/mt_firmware_build.h','generated/board.c',
    'MotortesterV2-stream-candidate.bin','MotortesterV2-stream-candidate.elf','image.map','image.nm','size.stdout',
    'patched/v2/app/mt_live_adc.h','patched/v2/app/mt_live_adc.c','patched/v2/app/mt_live_runtime.c',
    'objects/21-mt_live_runtime.su','objects/22-mt_live_adc.su','objects/board.d',
    'objects/29-mt_stream_progress.d','objects/30-mt_usb_gate.d',
    'disassembly-21-mt_live_runtime.stdout','disassembly-22-mt_live_adc.stdout']
native_rows=['result.json','source-equivalence.json','model.c','compile.stdout','compile.stderr','model.stdout','model.stderr',
    'actual-gate.bin','actual-progress.bin','actual-legacy.bin','companion.json','generated/mt_firmware_build.h']
host_candidates=[root/'build/v6s-host-identity-01/result.json',root/'build/v6s-host-identity-01/identity-result.json']
host_result=next((p for p in host_candidates if p.exists()),None)
assert host_result is not None,'Host final result missing'
hr=json.loads(host_result.read_text('utf8'));assert hr['status']=='PASS'
data={
    'schema':'motortester-V2-06s-source-freeze-1','date':'2026-10-28',
    'status':'POSTCOPY_HANDOFF_CANDIDATE_FROZEN_FOR_INDEPENDENT_REVIEW',
    'firmware_build':'0x5632534c','baseline_build':'0x5632534b','product':'Motortester V2 Postcopy SL',
    'production_files':pins(production),
    'native_source_files':pins(['tests/v2-stream-firmware/check_postcopy_handoff.py','tests/v2-stream-firmware/postcopy_handoff_model.c']),
    'protected_legacy_tests':pins(['tests/v2-stream-firmware/check_usb_gate.py','tests/v2-stream-firmware/usb_gate_model.c']),
    'ARM_evidence':pins([arm+'/'+p for p in arm_rows]),
    'native_evidence':pins([native+'/'+p for p in native_rows]),
    'root_host_evidence':pins(['docs/streaming-postcopy-handoff.md','host/tools/decode_stream_progress.py','host/tools/decode_usb_gate.py',
        'host/tests/stream_progress_decoder_check.py','host/tests/usb_gate_decoder_check.py','host/tests/postcopy_identity_check.py',
        host_result.relative_to(root).as_posix()]),
    'author_evidence':pins(['build/v6s-design/contract-draft.md','build/v6s-design/implementation-plan.md',
        'build/v6s-analysis/author-audit.md','build/v6s-analysis/make_freeze.py']),
    'failed_attempts':{'ARM01':{'status':'FAILED_CONFIG_PREFLIGHT','compiler_started':False,
        'reason':'Config selected authorized SL while board_inputs expected-build pin remained SK; changed only reviewed pin then built new ARM02.',
        'evidence':pins(['build/v6s-fw-01/attempt.json','build/v6s-fw-01/preflight.stderr'])},
        'native_failed_attempts':[],'successful_ARM_builds':1,'native_executions':1},
    'resources':{'BIN_path':arm+'/MotortesterV2-stream-candidate.bin','BIN_bytes':49532,
        'BIN_sha256':receipt['artifacts']['MotortesterV2-stream-candidate.bin'],
        'ELF_path':arm+'/MotortesterV2-stream-candidate.elf','ELF_sha256':receipt['artifacts']['MotortesterV2-stream-candidate.elf'],
        'text':49404,'data':128,'bss':12156,'all_new_static_private_alignment_bytes':0,
        'legacy136_address':'0x20002f1c','progress64_address':'0x20002fa4','gate24_address':'0x20002fe4',
        'ram_bytes':20480,'stack_reserve_bytes':8192,'static_plus_stack_reserved_bytes':20476,'spare_bytes':4,
        'pending_stack_receipt_bytes':88,'conditional_stack_upper_bytes':6348,'conditional_stack_aligned_bytes':6352,
        'physical_stack_or_WCET_verified':False},
    'verification':{'ARM_status':receipt['status'],'native_status':nr['status'],'native_input_drift':nr['input_drift'],
        'source_equality':'Old adapter/service and runtime helpers exact; original runtime after explicit new-block removal; all other source and objects SK unchanged except generated identity.',
        'host_status':hr['status'],'hardware_executed':False,'old_broad_suites_repeated':False},
    'hook_map':{
        'selection':'postcopy_hint before original ADC service; modes1-4/noneligible still original service',
        'ownership':'actual mt_live_adc_acquire -> private512 receipt -> <=4 publish_next128; no RX/read before terminal disposition',
        'write':'selected handoff consumes grant/TX opportunity before barriers; actual guarded prepared step, old finalTIME+flush+Q certificate',
        'loss':'fresh pre/post perchunk observed loss; raw lifecycle forces existing pending2 quarantine; never clean END or later TX from lost queue data',
        'diagnostics':'Existing N prepare span, legacy TX stamp and Q span retained; existing firstclose136/64/24 ABIs unchanged'},
    'fixture_scope':{'origin':'SYNTHETIC_NATIVE_C_SETUP_NOT_PHYSICAL','generation':3,'nonce_hex':'00000000000001f7',
        'legacy_module_not_executed':True,'actual_N64_G24':True,'firmware_build':'0x5632534c','fixtures':nr['fixtures']},
    'limits':['Sustainable150k remains unverified; R2 failure is not repaired by software-test PASS.',
        'Native MMIO/TIME/USB/IRQ/actor stimuli and legacy API/setup are synthetic, not physical identity or timing.',
        'Deadline3413 and grant6/<500 unchanged;500 is continuation admission, not IRQ WCET.',
        'Observed-loss allows old-session queue writes before next fresh check; quarantine prohibits later wire/new-session publication.',
        'Exact-image stack bound is conditional, not physical watermark; no COM/SWD/Reset/Flash performed.'],
    'independent_source_review':'PENDING_SEPARATE_GATE','hardware_executed':False,'flash_approved':False}
(root/'build/v6s-freeze.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps(pin('build/v6s-freeze.json')))
