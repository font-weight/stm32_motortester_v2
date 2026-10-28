"""Read saved SL/SN ARM artifacts; no compilation, ISA execution or hardware."""
from pathlib import Path
import hashlib
import json
import re
import struct

root = Path(__file__).resolve().parents[2]
old, new = root/'build/v6s-fw-02', root/'build/v6u-fw-01'
inputs = {}

def read(path):
    b=path.read_bytes();inputs[str(path.relative_to(root))]=hashlib.sha256(b).hexdigest();return b

def text(path):return read(path).decode('utf8')

def instructions(folder, start, end):
    raw=text(folder/'disassembly-28-mt_batch1024.stdout')
    a=raw.index('<mt_batch1024_collect>:');z=raw.index('Disassembly of section .text.mt_batch1024_seal',a)
    rows=[]
    for line in raw[a:z].splitlines():
        m=re.match(r'\s*([0-9a-f]+):\s+(?:(?:[0-9a-f]{4}|[0-9a-f]{8})\s+)+\s*([a-z][a-z0-9.]*)\s*(.*)',line)
        if m and start<=int(m[1],16)<=end:rows.append({'address':int(m[1],16),'mnemonic':m[2],'operand':m[3]})
    assert rows and rows[0]['address']==start and rows[-1]['address']==end
    return rows

sl=instructions(old,0xcc,0x14a)
sn=instructions(new,0x102,0x1dc)
assert len(sl)==40 and len(sn)==61
assert sum(r['mnemonic'].startswith('strb') for r in sl)==2
assert sum(r['mnemonic'].startswith('strb') for r in sn)==5
assert sum(r['mnemonic'].startswith('muls') for r in sl)==1
assert not any(r['mnemonic'].startswith('mul') for r in sn)
assert any(r['mnemonic'].startswith('ldrh') and '[r5, #8]' in r['operand'] for r in sl)
assert not any('[r6,' in r['operand'] for r in sn)  # SN state lives in r6; not reloaded inside fast path.
orow=json.loads(text(old/'receipt.json'));nrow=json.loads(text(new/'receipt.json'))
assert orow['config']['firmware_build']==0x5632534c and nrow['config']['firmware_build']==0x5632534e
ocmd=next(c for c in orow['commands'] if c['label']=='compile-28-mt_batch1024')
ncmd=next(c for c in nrow['commands'] if c['label']=='compile-28-mt_batch1024')
assert ocmd['argv']==ncmd['argv'] and '-Os' in ncmd['argv']
bound=json.loads(text(new/'static-bound.json'))
size=re.search(r'\n\s*(\d+)\s+(\d+)\s+(\d+)\s+',text(new/'size.stdout'))
flash_text,data,bss=map(int,size.groups())
assert (data,bss)==(128,12156) and data+bss+8192==20476 and bound['upper_bound_bytes']==6348
nm=text(new/'image.nm')
def symbol(name):
    row=re.search(r'^([0-9a-f]+)\s+([0-9a-f]+)\s+\w\s+'+re.escape(name)+r'$',nm,re.M)
    assert row,name
    return int(row[1],16),int(row[2],16)
board_addr,board_size=symbol('mt_board');assert board_size==48
binary=read(new/'MotortesterV2-stream-candidate.bin')
board_build=struct.unpack_from('<I',binary,board_addr-0x08000000+12)[0]
assert board_build==0x5632534e
header=text(new/'generated/mt_firmware_build.h')
assert '#define MT_FIRMWARE_BUILD UINT32_C(0x5632534e)' in header
for name in ('board','29-mt_stream_progress'):
    assert 'generated/mt_firmware_build.h' in text(new/'objects'/(name+'.d')).replace('\\','/')
old_observer=read(old/'objects/29-mt_stream_progress.o');new_observer=read(new/'objects/29-mt_stream_progress.o')
slid=struct.pack('<I',0x5632534c);snid=struct.pack('<I',0x5632534e)
assert old_observer.count(slid)==new_observer.count(snid)==1 and old_observer.replace(slid,snid)==new_observer
for folder,expect in ((old,36),(new,48)):
    assert re.search(r':mt_batch1024_collect\t'+str(expect)+r'\tstatic',text(folder/'objects/28-mt_batch1024.su'))
native=json.loads(text(root/'build/v6u-native-01/result.json'))
proof=json.loads(text(root/'build/v6u-native-01/source-equivalence.json'))
assert native['status']=='PASS' and not native['input_drift']
rows=proof['compiled_SL_objects']
result={
    'status':'PASS_MATERIAL_COMPILED_WORK_REDUCTION_NOT_WCET',
    'scope':'Saved ARM artifact analysis, no native replay/ISA execution/timing estimate',
    'firmware_build':'0x5632534e','baseline_build':'0x5632534c',
    'inputs':inputs,
    'hot_path':{'SL_body_inclusive':['0x000000cc','0x0000014a'],'SN_aligned4_body_inclusive':['0x00000102','0x000001dc'],
        'SL_listing_slots_per_sample':40,'SN_listing_slots_per_four_samples':61,
        'SL_listing_slots_for_four_iterations':160,
        'listing_limit':'Static listed instruction slots include IT/predicated slots and branch tests; not retired instructions, cycles or WCET. Entry validation/prologue/epilogue and scalar tails excluded.',
        'packed_byte_stores_per_four_samples':{'SL':8,'SN':5},
        'count_state_loads_per_four_samples':{'SL':4,'SN':0},
        'count_to_bit_multiply_per_four_samples':{'SL':4,'SN':0},
        'SL_owned_byte_RMW_loads_for_shifts_2_4_6':3,'SN_aligned_group_owned_byte_RMW_loads':0,
        'canonical_crc_table_loads_per_four_samples':{'SL':8,'SN':8},
        'CRC_was_already_local':True,'ARM_compile_argv_exactly_unchanged':True,'optimization':'-Os',
        'SL_rows':sl,'SN_rows':sn},
    'resources':{'BIN_bytes':len(binary),'BIN_sha256':hashlib.sha256(binary).hexdigest(),
        'ELF_sha256':nrow['artifacts']['MotortesterV2-stream-candidate.elf'],
        'text_bytes':flash_text,'data_bytes':data,'bss_bytes':bss,'all_extra_static_bytes':0,
        'stack_reserve_bytes':8192,'RAM_bytes':20480,'static_plus_stack_reserve':20476,'spare_bytes':4,
        'SL_collect_frame_bytes':36,'SN_collect_frame_bytes':48,'collect_stack_delta_bytes':12,
        'conditional_stack_upper_bytes':bound['upper_bound_bytes'],'conditional_aligned_bytes':bound['aligned_minimum_bytes']},
    'common_identity':{'board_address':f'0x{board_addr:08x}','build_member_offset':12,'BIN_word':f'0x{board_build:08x}',
        'board_and_observer_depend_on_same_generated_header':True,'observer_object_only_one_common_literal_changed':True},
    'observer_addresses':{name:{'address':f'0x{symbol(name)[0]:08x}','bytes':symbol(name)[1]}
        for name in ('mt_stream_diagnostics','mt_stream_progress','mt_usb_gate')},
    'unchanged_compiled_objects_exact_bytes':sum(r['verdict']=='EXACT_BYTES' for r in rows),
    'unchanged_patched_sources':len(proof['unchanged_patched_sources']),
    'limits':['No measured CPU share, SRAM watermark, IRQ/ADC WCET or sustainable150k claim.',
        'Prepare58ms/147ms from S2 is inclusive wall time and does not rank CPU versus USB latency.',
        'Raw/wire/runtime/source identity unchanged except common SN build/product; physical evidence remains SL failure.',
        'Four spare SRAM bytes are arithmetic after the8192 reserve, not permission to add state.']}
target=Path(__file__).with_name('arm-audit.json')
target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps({'status':result['status'],'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
