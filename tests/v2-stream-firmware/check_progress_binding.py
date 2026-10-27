"""One actual observer binding/freeze model with exact candidate-generated build identity."""
import argparse,hashlib,importlib.util,json,os,re,struct,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(x,m):
    if not x:raise ValueError(m)
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'Use a new build output');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf-8-sig')
    def copy(p,rel):
        q=out/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(read(p),encoding='utf8',newline='\n')
    def run(label,argv,negative=False):
        row={'label':label,'argv':[str(x) for x in argv],'expected_nonzero':negative};commands.append(row)
        q=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180);row['exit_code']=q.returncode
        (out/(label+'.stdout')).write_bytes(q.stdout);(out/(label+'.stderr')).write_bytes(q.stderr)
        need((q.returncode!=0) if negative else (q.returncode==0),label+' unexpected result; retained')
        return q
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        current=json.loads(read(image/'receipt.json'));previous=json.loads(read(base/'receipt.json'))
        need(current['status']==previous['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Incomplete image')
        build=current['config']['firmware_build'];need(build==0x56325349 and previous['config']['firmware_build']==0x56325348,'Wrong SI/SH basis')
        expected=json.loads(json.dumps(previous['config']));expected['firmware_build']=build;expected['usb']['product']='Motortester V2 Build Binding SI'
        need(current['config']==expected,'Configuration drift beyond build/product')
        header_path=image/'generated/mt_firmware_build.h';header=read(header_path)
        need(re.findall(r'#define MT_FIRMWARE_BUILD UINT32_C\((0x[0-9a-f]+)\)',header)==[f'0x{build:08x}'],'Generated build differs from validated config')
        need(current['inputs_before'].get(str(header_path))==sha(header_path),'Generated identity missing compiler input pin')
        board=read(image/'generated/board.c')
        need('#include "mt_firmware_build.h"' in board and '.firmware_build = MT_FIRMWARE_BUILD' in board,'Board does not consume shared identity')
        need('generated/mt_firmware_build.h' in read(image/'objects/board.d'),'Board dependency missing shared identity')
        need('generated/mt_firmware_build.h' in read(image/'objects/29-mt_stream_progress.d'),'Observer dependency missing shared identity')
        changed=Path('v2/platform/mt_stream_progress.h');unchanged=[]
        old_header=read(base/'patched'/changed);new_header=read(image/'patched'/changed)
        old_gate='#define MT_N_BUILD UINT32_C(0x56325347)'
        new_gate='''#if CFG_MT_PROGRESS_TRACE
#include "mt_firmware_build.h"
#ifndef MT_FIRMWARE_BUILD
#error "Progress trace requires generated target build identity"
#endif
#define MT_N_BUILD MT_FIRMWARE_BUILD /* Same config-derived identity as mt_board. */
#endif'''
        need(old_header.count(old_gate)==1 and new_header.count(new_gate)==1,'Exact observer gate changed unexpectedly')
        normalized=new_header.replace(new_gate,old_gate).replace('matching nonce/generation/generated target build and an independently pinned image.','matching nonce/generation/buildSG and an independently pinned image.')
        need(normalized==old_header,'Observer header changed beyond shared build admission/comment')
        for p in sorted((base/'patched').rglob('*')):
            if not p.is_file() or p.relative_to(base/'patched')==changed:continue
            q=image/'patched'/p.relative_to(base/'patched');read(q);read(p)
            need(q.read_bytes()==p.read_bytes(),'Functional SH source changed: '+str(p))
            unchanged.append({'path':p.relative_to(base).as_posix(),'sha256':sha(q)})
        for rel in ('platform/mt_timebase.c','platform/mt_stream_diag.c'):
            need(read(image/'source/firmware'/rel)==read(base/'source/firmware'/rel),'Canonical TIME/legacy changed')
        elf_module_path=image/'source/tests/boot-link/tools/run_boot_link_tests.py';read(elf_module_path)
        core=load(elf_module_path,'binding_elf');old_obj=core.ELF(base/'objects/29-mt_stream_progress.o');new_obj=core.ELF(image/'objects/29-mt_stream_progress.o')
        old_bytes=old_obj.bytes(old_obj.by_name['.text.bind']);new_bytes=new_obj.bytes(new_obj.by_name['.text.bind'])
        need(old_bytes.count(struct.pack('<I',0x56325347))==1,'Unexpected prior bind literal')
        need(new_bytes==old_bytes.replace(struct.pack('<I',0x56325347),struct.pack('<I',build)),'Compiled bind changed beyond candidate id')
        object_sections=[]
        for old_section in old_obj.sections:
            if not old_section['flags']&2:continue
            new_section=new_obj.by_name[old_section['name']]
            need((new_section['size'],new_section['flags'],new_section['align'])==(old_section['size'],old_section['flags'],old_section['align']),'Observer section geometry changed')
            if old_section['name']!='.text.bind' and old_section['type']!=8:
                need(old_obj.bytes(old_section)==new_obj.bytes(new_section),'Observer machine section changed '+old_section['name'])
            object_sections.append(old_section['name'])
        elf=core.ELF(image/'MotortesterV2-stream-candidate.elf')
        need(elf.word(elf.value('mt_board')+12)==build,'Linked board id differs')
        unchanged_objects=[]
        for p in sorted((base/'objects').glob('*.o')):
            if p.name in ('board.o','29-mt_stream_progress.o'):continue
            q=image/'objects'/p.name;need(sha(p)==sha(q),'Non-binding object changed '+p.name);unchanged_objects.append({'path':q.relative_to(image).as_posix(),'sha256':sha(q)})
        proof={'status':'PASS','shared_generated_header':{'path':'generated/mt_firmware_build.h','sha256':sha(header_path),'value':f'0x{build:08x}','board_and_observer_dependencies_pinned':True},'observer_C_body_unchanged':True,'observer_bind_machine_bytes':'Byte-identical SH except single SG literal replaced by exact SI config id','observer_alloc_sections_same_geometry':object_sections,'unchanged_SH_patched_sources':unchanged,'unchanged_nonbinding_objects':unchanged_objects,'late_grant_ADC_USB_wire_queue_TIME_unchanged':True,'no_target_timing_claim':True}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        for area,names in {'platform':['mt_stream_progress.c','mt_stream_progress.h','mt_stream_diag.h','mt_usb_ctr.h'], 'protocol':['mt_live_device.h','mt_batch1024.h','mt_wire.h'],'acquisition':['mt_sample_queue.h','mt_acquisition_profile.h']}.items():
            for name in names:
                p=image/'patched/v2'/area/name
                if not p.exists():p=image/'source/firmware'/area/name
                need(current['inputs_before'].get(str(p))==sha(p),'Candidate source pin drift '+str(p));copy(p,area+'/'+name)
        copy(header_path,'generated/mt_firmware_build.h')
        bridge=read(image/'patched/v2/transport/mt_usb_bridge.h')
        need('typedef struct { uint32_t previous; unsigned entered; } mt_usb_scope;' in bridge,'Scope ABI drift')
        (out/'transport').mkdir();(out/'transport/mt_usb_bridge.h').write_text('#include <stdint.h>\ntypedef struct {uint32_t previous;unsigned entered;} mt_usb_scope;\nuint32_t mt_usb_bridge_lock(void);\nvoid mt_usb_bridge_unlock(uint32_t);\nint mt_usb_bridge_app_enter(mt_usb_scope*);\nvoid mt_usb_bridge_leave(mt_usb_scope*);\n',encoding='ascii')
        (out/'tusb.h').write_text('#include <stdbool.h>\n#include <stdint.h>\nuint32_t tud_cdc_n_write_available(uint8_t);\nbool tud_task_event_ready(void);\n',encoding='ascii')
        copy(Path(__file__).with_name('progress_binding_model.c'),'model.c')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).stdout.decode().strip()
        flags=['-std=c11','-O1','-Wall','-Wextra','-Werror','-DCFG_MT_STREAM_DIAGNOSTICS=1','-DCFG_MT_PROGRESS_TRACE=1','-DMT_PROGRESS_NATIVE=1','-I.','-Iplatform','-Iprotocol','-Iacquisition']
        run('compile',[zig,'cc',*flags,'-Igenerated','model.c','platform/mt_stream_progress.c','-o','model.exe'])
        stdout=run('model',[out/'model.exe',out/'actual-progress.bin',out/'actual-legacy.bin']).stdout.decode('utf8')
        need((out/'actual-progress.bin').stat().st_size==64 and (out/'actual-legacy.bin').stat().st_size==136,'C fixture sizes')
        legacy=struct.unpack('<34I',(out/'actual-legacy.bin').read_bytes())
        need(legacy[:5]==(0x4d544447,1,136,build,3) and legacy[6]==7 and legacy[32:]==(0x89abcdef,0x01234567),'Actual C companion identity')
        companion={'schema':'motortester-native-progress-companion-1','origin':'SYNTHETIC_NATIVE_C_SETUP_NOT_PHYSICAL','firmware_build':f'0x{build:08x}','generation':7,'nonce_hex':'0123456789abcdef','progress_file':'actual-progress.bin','progress_sha256':sha(out/'actual-progress.bin'),'legacy136_file':'actual-legacy.bin','legacy136_sha256':sha(out/'actual-legacy.bin'),'generated_header_sha256':sha(header_path),'candidate_bin_sha256':current['artifacts']['MotortesterV2-stream-candidate.bin'],'nominal_clock_hz':72000000,'cycles_are_synthetic':True,'not_actual_legacy_module_execution':True}
        (out/'companion.json').write_text(json.dumps(companion,indent=2)+'\n',encoding='utf8')
        (out/'missing-id').mkdir();(out/'missing-id/mt_firmware_build.h').write_text('/* Deliberately no macro: required compile-time rejection. */\n',encoding='ascii')
        rejection=run('compile-missing-build-negative',[zig,'cc',*flags,'-Imissing-id','-c','platform/mt_stream_progress.c','-o','missing-id.o'],negative=True)
        need(b'Progress trace requires generated target build identity' in rejection.stderr,'Negative compile failed for wrong reason')
        result.update(status='PASS',compiler_version=version,stdout=stdout,source_equivalence_sha256=sha(out/'source-equivalence.json'),C_fixture_sha256=sha(out/'actual-progress.bin'),C_legacy_companion_sha256=sha(out/'actual-legacy.bin'),companion_sha256=sha(out/'companion.json'),image_bin_sha256=current['artifacts']['MotortesterV2-stream-candidate.bin'],expected_negative_compile='Missing generated build macro rejected; no fallback',limitations=['Actual observer C executes with exact ARM-generated shared identity header.','DWT/USB/legacy are synthetic seams; no full core/runtime or physical session.','Negative missing-macro compilation is intentional and retained, not a failed candidate build.','No throughput, physical identity, calibrated timing or Flash admission.'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,h in inputs.items() if not Path(p).is_file() or sha(Path(p))!=h];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
