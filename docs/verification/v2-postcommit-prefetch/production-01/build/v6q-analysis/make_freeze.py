"""Compose existing immutable Q evidence; no builds, model or hardware calls."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[2]
def pin(rel):
    p=root/rel
    return {'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def pins(rels):return [pin(p) for p in rels]
fw='build/v6q-fw-01/';nt='build/v6q-native-01/'
r=json.loads((root/fw/'receipt.json').read_text('utf8'));n=json.loads((root/nt/'result.json').read_text('utf8'));s=json.loads((root/fw/'static-bound.json').read_text('utf8'))
assert r['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and n['status']=='PASS'
production=['firmware/v2-stream/'+p for p in ('README.md','build_windows.py','config.json','overlays/board_inputs.py','overlays/prefetch.json','overlays/v2-prefetch-app-mt_live_runtime.c.patch','overlays/v2-prefetch-protocol-mt_live_device.c.patch','overlays/v2-prefetch-protocol-mt_live_device.h.patch','progress/ABI.md','progress/mt_stream_progress.c','progress/mt_stream_progress.h')]
ar=['receipt.json','static-bound.json','config.json','generated/mt_firmware_build.h','generated/board.c','objects/board.d','objects/29-mt_stream_progress.d','objects/21-mt_live_runtime.su','objects/24-mt_live_device.su','image.nm','image.map','image.dis','MotortesterV2-stream-candidate.bin','MotortesterV2-stream-candidate.elf']
ar+=['patched/v2/'+p for p in ('app/mt_live_runtime.c','protocol/mt_live_device.c','protocol/mt_live_device.h')]
native=['result.json','source-equivalence.json','model.c','model.exe','model.stdout','model.stderr','compile.stdout','compile.stderr']
freeze={'schema':'motortester-V2-06q-source-freeze-1','date':'2026-10-27','status':'POSTCOMMIT_PREFETCH_CANDIDATE_FROZEN_FOR_INDEPENDENT_REVIEW','firmware_build':'0x5632534a','baseline_build':'0x56325349','product':r['config']['usb']['product'],
'production_files':pins(production),'native_source_files':pins(['tests/v2-stream-firmware/check_prefetch.py','tests/v2-stream-firmware/prefetch_model.c']),
'ARM_evidence':pins([fw+p for p in ar]),'native_evidence':pins([nt+p for p in native]),
'root_owned_evidence':pins(['docs/streaming-postcommit-prefetch.md','host/tools/decode_stream_progress.py','host/tests/stream_progress_decoder_check.py','build/v6q-decoder-01/result.json']),
'proposal_and_author_evidence':pins(['build/v6p-followup/analysis.md','build/v6q-analysis/proposal-review.md','build/v6q-analysis/prepare_prefetch.py','build/v6q-analysis/author-audit.md','build/v6q-analysis/make_freeze.py']),
'identity':{'sole_compiled_origin':'config.json.firmware_build -> generated/mt_firmware_build.h','board_dependency_and_linked_word_verified':True,'observer_C_ACTIVE_exact_SJ_header_verified':True,'observer_native_legacy136_setup':'SYNTHETIC; actual legacy module not run','N64_layout_unchanged':True},
'resources':{'flash_binary_bytes':(root/fw/'MotortesterV2-stream-candidate.bin').stat().st_size,'text':45244,'data':128,'bss':12132,'static_growth_bytes_vs_SI':0,'ram_bytes':20480,'stack_reserve_bytes':8192,'used_static_plus_stack_reserve':20452,'spare_above_reserved_stack_bytes':28,'conditional_stack_upper_bytes':s['upper_bound_bytes'],'aligned_minimum_bytes':s['aligned_minimum_bytes'],'legacy136_address':'0x20002f1c','progress64_address':'0x20002fa4','physical_stack_high_water_or_WCET_verified':False},
'verification':{'ARM_runs':1,'native_model_runs':1,'failed_Q_ARM_native_runs':[],'new_GUI_host_wire_hardware_runs':0,'source_equivalence':n['source_equivalence_sha256'],'ordinary_core':'All SI tokens after exact collector reinlining/removal of two new entry points','runtime':'All SI tokens after exact helper/dispatch removal','ADC_TIME_DCD_queue_wire_serializer_objects_unchanged':True,'root_decoder_runs':1,'root_decoder_scope':'Reused P actual-C64/136 SI fixture; SJ allowlist metadata synthetic. Actual SJ binding separately asserted by Q model.'},
'scope':['Post-existing-flush collect-only after certified cached full DATA1024 final-time commit','At most512 source samples; no seal/frameCRC/COBS/second DATA/grant/new static memory','Original prepared epoch/soft checked before and after ownership transfer','Error-only matching guarded recovery; Stop/HELLO/accepted prefix preserved'],
'limitations':['Clock/epoch/USB/actor/DWT and legacy setup are synthetic native seams; only the stated core and extracted helper bodies execute.','Preceding flush/full runtime/grant equality is source proof, not simulated USB completion.','New collection increases cached-final latency; unchanged3413us deadline and6/<500us IRQ bound require physical qualification.','28bytes SRAM beyond8192 reserve remain; no additional buffer/state added.','No continuous150k, analogue accuracy, physical loss bound or Flash approval claimed.'],'independent_review':'PENDING exact review; author does not assign acceptance score','hardware_executed':False,'flash_approved':False}
p=root/'build/v6q-freeze.json'
assert not p.exists(),'Do not replace an existing freeze'
p.write_text(json.dumps(freeze,indent=2,ensure_ascii=False)+'\n',encoding='utf8',newline='\n')
print(json.dumps(pin('build/v6q-freeze.json')))
