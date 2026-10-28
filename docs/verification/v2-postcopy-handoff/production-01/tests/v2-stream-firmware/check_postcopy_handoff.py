"""One SL actual adapter/runtime/core post-copy ownership model; no hardware."""
import argparse,hashlib,importlib.util,json,os,re,struct,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(x,m):
    if not x:raise ValueError(m)
def tokens(s):return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))
def once(s,a,b):need(s.count(a)==1,'Exact normalization '+a[:100]);return s.replace(a,b)
def load(p,n):
    sp=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'New output only; failures retained');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf8')
    def copy(p,rel):
        q=out/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(read(p),encoding='utf8',newline='\n')
    def run(label,argv):
        row={'label':label,'argv':[str(x) for x in argv]};commands.append(row)
        q=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180);row['exit_code']=q.returncode
        (out/(label+'.stdout')).write_bytes(q.stdout);(out/(label+'.stderr')).write_bytes(q.stderr)
        need(q.returncode==0,label+' failed; evidence retained');return q.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        ri=json.loads(read(image/'receipt.json'));rb=json.loads(read(base/'receipt.json'))
        need(ri['status']==rb['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Unfinished image')
        build=ri['config']['firmware_build'];need(build==0x5632534c and rb['config']['firmware_build']==0x5632534b,'Wrong SL/SK basis')
        expected=json.loads(json.dumps(rb['config']));expected['firmware_build']=build;expected['usb']['product']='Motortester V2 Postcopy SL'
        need(ri['config']==expected,'Unexpected acquisition/transport/resource config change')
        extractor=Path(__file__).with_name('check_usb_gate.py');read(extractor);fn=load(extractor,'s_extract').function
        adapter=read(image/'patched/v2/app/mt_live_adc.c');old_adapter=read(base/'patched/v2/app/mt_live_adc.c')
        adapter_names=('split_source_fault','split_source_matches','split_elapsed','mt_live_adc_acquire','mt_live_adc_publish_next')
        normalized=adapter
        for name in adapter_names:normalized=once(normalized,fn(normalized,name),'')
        need(tokens(normalized)==tokens(old_adapter),'Original adapter/service/start/Stop changed')
        header=read(image/'patched/v2/app/mt_live_adc.h');old_header=read(base/'patched/v2/app/mt_live_adc.h')
        start=header.index('/* One stack-only borrowed private half.')
        need(tokens(header[:start]+header[header.rindex('#endif'):])==tokens(old_header),'Persistent adapter/header state changed')
        runtime=read(image/'patched/v2/app/mt_live_runtime.c');old=read(base/'patched/v2/app/mt_live_runtime.c')
        new_names=('postcopy_hint','postcopy_identity','postcopy_abort','postcopy_publish','postcopy_ticket','postcopy_handoff')
        normalized=runtime
        for name in new_names:normalized=once(normalized,fn(normalized,name),'')
        normalized=once(normalized,'    mt_live_tx_ticket ticket; unsigned deferred_grant,handoff_consumed=0u;',
            '    mt_live_tx_ticket ticket; unsigned deferred_grant;')
        dispatch='''    if(postcopy_hint(r)) {
        mt_live_runtime_result handoff=postcopy_handoff(r,&ticket,grant_attempted,&handoff_consumed,&serviced);
        if(handoff!=MT_LIVE_RUNTIME_OK) { mt_usb_bridge_leave(&scope); return handoff; }
    } else serviced=mt_live_adc_service(&r->acquisition);'''
        normalized=once(normalized,dispatch,'    serviced=mt_live_adc_service(&r->acquisition);')
        normalized=once(normalized,'''    deferred_grant=handoff_consumed?0u:(unsigned)defer_data_grant(r);
    if(!handoff_consumed && !deferred_grant) { *grant_attempted=1u; grant_irq(r); }''',
            '''    deferred_grant=(unsigned)defer_data_grant(r);
    if(!deferred_grant) { *grant_attempted=1u; grant_irq(r); }''')
        normalized=once(normalized,'    if(handoff_consumed)return MT_LIVE_RUNTIME_OK;\n','')
        need(tokens(normalized)==tokens(old),'Runtime changed outside explicit handoff selector/consumed exit')
        retained=('live_write','prepared_tx_step','grant_irq','prefetch_after_tx','defer_data_grant','new_data_ticket',
            'stable','usable','synchronize_loss','time_fault','mt_live_runtime_step')
        for name in retained:need(tokens(fn(runtime,name))==tokens(fn(old,name)),'Old runtime helper changed '+name)
        publish=fn(runtime,'postcopy_publish');handoff=fn(runtime,'postcopy_handoff')
        need('mt_live_device_receive' not in publish+handoff and 'tud_cdc_n_read(' not in publish+handoff and 'tud_task_ext' not in publish+handoff,'RX/task inside pending ownership')
        need(handoff.count('mt_live_adc_acquire(')==1 and handoff.count('grant_irq(r);')==1 and handoff.count('prepared_tx_step(')==1,'Unbounded read/grant/DATA attempts')
        need(handoff.index('*handoff_consumed=1u;*grant_attempted=1u;')<handoff.index('grant_irq(r);'),'Attempt markers too late')
        need(handoff.index('tud_cdc_n_write_flush(0)')<handoff.index('prefetch_after_tx(')<handoff.rindex('postcopy_publish('),'Handoff flush/Q/publish order')
        need('for(unsigned chunk=0u;chunk<4u;++chunk)' in publish and publish.count('mt_live_adc_publish_next(')==1,'Publisher not fixed4')
        unchanged=[]
        changed={'v2/app/mt_live_adc.c','v2/app/mt_live_adc.h','v2/app/mt_live_runtime.c'}
        for p in sorted((base/'patched').rglob('*')):
            if not p.is_file() or p.relative_to(base/'patched').as_posix() in changed:continue
            q=image/'patched'/p.relative_to(base/'patched');read(p);read(q)
            need(p.read_bytes()==q.read_bytes(),'Unrelated SK source changed '+str(p));unchanged.append({'path':q.relative_to(image).as_posix(),'sha256':sha(q)})
        for rel in ('firmware/platform/mt_timebase.c','firmware/third_party/usb/vendor/tinyusb/src/tusb.c','firmware/third_party/usb/vendor/tinyusb/src/class/cdc/cdc_device.c'):
            need(read(image/'source'/rel)==read(base/'source'/rel),'Canonical TIME/USB changed '+rel)
        hp=image/'generated/mt_firmware_build.h';h=read(hp)
        need(re.findall(r'#define MT_FIRMWARE_BUILD UINT32_C\((0x[0-9a-f]+)\)',h)==[f'0x{build:08x}'],'Wrong generated common identity')
        for rel in ('objects/board.d','objects/29-mt_stream_progress.d','objects/30-mt_usb_gate.d'):
            need('generated/mt_firmware_build.h' in read(image/rel),'Missing common-header dependency '+rel)
        coretool=image/'source/tests/boot-link/tools/run_boot_link_tests.py';read(coretool);E=load(coretool,'s_elf').ELF
        elf=E(image/'MotortesterV2-stream-candidate.elf');be=E(base/'MotortesterV2-stream-candidate.elf')
        need(elf.word(elf.value('mt_board')+12)==build,'Linked board id mismatch')
        need(elf.by_name['.data']['size']==be.by_name['.data']['size'] and elf.by_name['.bss']['size']==be.by_name['.bss']['size'],'New hidden static storage')
        stable_objects=[]
        for p in sorted((base/'objects').glob('*.o')):
            if p.name in ('board.o','21-mt_live_runtime.o','22-mt_live_adc.o','29-mt_stream_progress.o'):continue
            q=image/'objects'/p.name;need(sha(p)==sha(q),'Unrelated compiled object changed '+p.name);stable_objects.append({'path':q.relative_to(image).as_posix(),'sha256':sha(q)})
        old_bind=E(base/'objects/29-mt_stream_progress.o');new_bind=E(image/'objects/29-mt_stream_progress.o')
        ab=old_bind.bytes(old_bind.by_name['.text.bind']);bb=new_bind.bytes(new_bind.by_name['.text.bind'])
        need(ab.count(struct.pack('<I',0x5632534b))==1 and bb==ab.replace(struct.pack('<I',0x5632534b),struct.pack('<I',build)),'Observer binding differs beyond generated identity')
        proof={'status':'PASS','original_adapter_functions_exact':True,'original_runtime_after_exact_new_block_removal':True,
            'retained_runtime_helpers':retained,'unchanged_SK_sources':unchanged,'unchanged_compiled_objects':stable_objects,
            'static_growth_bytes':0,'observer_bind_machine_code':'SK exact except config-derived build literal',
            'ADC_driver_DCD_TIME_core_queue_serializer_wire_bridge_algorithms_unchanged':True,
            'limitations':['Source order and exact bodies are not target WCET/throughput proof.','Observed loss is quarantined; no claim of atomic absence of queue stores after arbitrary asynchronous hardware flag.']}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        for p in (image/'patched/v2').rglob('*.h'):copy(p,p.relative_to(image/'patched/v2'))
        for rel in ('platform/mt_timebase.h','platform/mt_stream_diag.h','transport/mt_usb_epoch.h'):copy(image/'source/firmware'/rel,rel)
        copy(hp,'generated/mt_firmware_build.h')
        sources=[]
        for area,names in {'app':['mt_live_adc.c'],'platform':['adc_timer_dma.c','mt_stream_progress.c','mt_usb_gate.c'],
            'protocol':['mt_live_device.c','mt_wire.c','mt_batch1024.c','mt_v2_crc32.h'],
            'acquisition':['mt_sample_queue.c','mt_acquisition_profile.c'],
            'transport':['mt_usb_epoch.c']}.items():
            for name in names:
                p=image/'patched/v2'/area/name
                if not p.exists():p=image/'source/firmware'/area/name
                need(ri['inputs_before'].get(str(p))==sha(p),'Actual compiler input pin missing '+str(p));copy(p,area+'/'+name)
                if name.endswith('.c'):sources.append(area+'/'+name)
        (out/'device').mkdir();(out/'device/dcd.h').write_text('#include "tusb.h"\n',encoding='ascii')
        (out/'tusb.h').write_text('''#ifndef MODEL_TUSB_H
#define MODEL_TUSB_H
#include <stdbool.h>
#include <stdint.h>
typedef struct {unsigned ignored;} dcd_event_t;
typedef struct {unsigned ignored;} tu_fifo_t;
typedef struct {unsigned ignored;} tusb_desc_endpoint_t;
typedef struct {unsigned ignored;} tusb_control_request_t;
uint32_t tud_cdc_n_write_available(uint8_t);
bool tud_task_event_ready(void);
#endif
''',encoding='ascii')
        model=read(Path(__file__).with_name('postcopy_handoff_model.c'));need(model.count('/* RUNTIME_BODIES */')==1,'Model actual runtime seam')
        names=('stable','usable','quiescent','loss_result','synchronize_loss','time_fault','live_write','prepared_tx_step','grant_irq',
            'prefetch_after_tx','defer_data_grant','new_data_ticket',*new_names,'step','mt_live_runtime_step')
        (out/'model.c').write_text(model.replace('/* RUNTIME_BODIES */','\n'.join(fn(runtime,n) for n in names)),encoding='utf8',newline='\n')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).strip()
        run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-I.','-Igenerated','-Iplatform','-Iapp','-Iprotocol','-Iacquisition','-Itransport',
            '-DCFG_MT_USB_BRIDGE=1','-DCFG_MT_USB_CTR_FAIRNESS=1','-DCFG_TUD_CDC=1','-DCFG_TUD_CDC_TX_OVERWRITABLE_IF_NOT_CONNECTED=0',
            '-DCFG_TUD_CDC_RX_PERSISTENT=0','-DCFG_TUD_CDC_TX_PERSISTENT=0','-DCFG_MT_STREAM_DIAGNOSTICS=1','-DCFG_MT_PROGRESS_TRACE=1','-DMT_PROGRESS_NATIVE=1',
            'model.c',*sources,'-o','model.exe'])
        stdout=run('model',[out/'model.exe',out/'actual-gate.bin',out/'actual-progress.bin',out/'actual-legacy.bin'])
        fixtures={n:sha(out/n) for n in ('actual-gate.bin','actual-progress.bin','actual-legacy.bin')}
        need([len((out/n).read_bytes()) for n in fixtures]==[24,64,136],'Fixture lengths')
        legacy=struct.unpack('<34I',(out/'actual-legacy.bin').read_bytes())
        need(legacy[:3]==(0x4d544447,1,136) and legacy[3]==build and legacy[4]==3,'Actual C legacy fixture identity')
        companion={'origin':'SYNTHETIC_NATIVE_C_SETUP_NOT_PHYSICAL','legacy_module_not_executed':True,'firmware_build':f'0x{build:08x}',
            'generation':legacy[6],'nonce_hex':f'{legacy[33]:08x}{legacy[32]:08x}','image_bin_sha256':ri['artifacts']['MotortesterV2-stream-candidate.bin'],
            'generated_header_sha256':sha(hp),'fixtures':fixtures}
        (out/'companion.json').write_text(json.dumps(companion,indent=2)+'\n',encoding='utf8')
        result.update(status='PASS',compiler_version=version,stdout=stdout,image_bin_sha256=companion['image_bin_sha256'],fixtures=fixtures,
            companion_sha256=sha(out/'companion.json'),source_equivalence_sha256=sha(out/'source-equivalence.json'),
            limitations=['Actual adapter/driver/core/queue/serializer/wire/progress/gate and extracted modified runtime boundaries execute.',
                'Driver initialized state, MMIO/TIME/USB/actor/IRQ/FIFO are synthetic controlled stimuli, not target latency or DMA/USB PHY.',
                'Legacy136 setup and diagnostic function seams are synthetic; actual legacy diagnostic module is not executed.',
                'No physical throughput, target WCET/settling, Flash admission or lossless150k qualification.'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,v in inputs.items() if not Path(p).is_file() or sha(Path(p))!=v];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
