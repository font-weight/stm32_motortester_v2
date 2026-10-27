"""One actual SJ post-commit collect-only core/runtime-boundary model; no hardware."""
import argparse,hashlib,importlib.util,json,os,re,struct,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(x,m):
    if not x:raise ValueError(m)
def tokens(s):return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))
def once(s,a,b):
    need(s.count(a)==1,'Exact normalization: '+a[:100]);return s.replace(a,b)
def load(p,n):
    sp=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'Use a new output; failures retained');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf-8-sig')
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
        build=ri['config']['firmware_build'];need(build==0x5632534a and rb['config']['firmware_build']==0x56325349,'Wrong SJ/SI basis')
        expected=json.loads(json.dumps(rb['config']));expected['firmware_build']=build;expected['usb']['product']='Motortester V2 Prefetch SJ'
        need(ri['config']==expected,'Configuration changed beyond SJ identity/product')
        extract=Path(__file__).with_name('check_usb_gate.py');read(extract);fn=load(extract,'q_extract').function
        core=read(image/'patched/v2/protocol/mt_live_device.c');old=read(base/'patched/v2/protocol/mt_live_device.c')
        # Re-inline only the factored collector, then remove the two explicit
        # new entry points. Every other original core token must remain SI.
        cc=fn(core,'batch_collect');bp=fn(core,'batch_prepare')
        body=cc[cc.index('{')+1:];body=once(body,'unsigned blocks,i,j,room;','unsigned blocks,i,j,room,turns;')
        end='    }\n    return 1;\n}\n';need(body.endswith(end),'Collector boundary changed')
        body=body[:-len(end)]
        seal='    if(d->batch.phase==MT_BATCH1024_COLLECT) {\n';need(bp.count(seal)==1,'Prepare phase boundary')
        merged='static int batch_prepare(mt_live_device *d,unsigned *error) {'+body+bp.split(seal,1)[1]
        normalized=once(core,cc,'');normalized=once(normalized,bp,merged)
        for name in ('mt_live_device_prefetch_ready','mt_live_device_prefetch_tx'):
            normalized=once(normalized,fn(normalized,name),'')
        need(tokens(normalized)==tokens(old),'Core changed beyond factoring and two collect-only APIs')
        header=read(image/'patched/v2/protocol/mt_live_device.h');old_header=read(base/'patched/v2/protocol/mt_live_device.h')
        for decl in ('int mt_live_device_prefetch_ready(const mt_live_device *device,const mt_live_tx_ticket *ticket);',
                     'mt_live_prepare_result mt_live_device_prefetch_tx(mt_live_device *device,mt_live_tx_ticket *ticket);'):
            header=once(header,decl,'')
        need(tokens(header)==tokens(old_header),'Core public state/layout changed')
        runtime=read(image/'patched/v2/app/mt_live_runtime.c');old_runtime=read(base/'patched/v2/app/mt_live_runtime.c')
        helper=fn(runtime,'prefetch_after_tx');norm=once(runtime,helper,'')
        dispatch='''    if(tx_ok && ticket.tx_mode==5u && ticket.tx_type==152u &&
       ticket.tx_count==1024u && ticket.tx_offset && !r->device.tx_length &&
       r->device.batch.phase==MT_BATCH1024_EMPTY)
        return prefetch_after_tx(r,&ticket,prepared_epoch,prepared_soft_serial);
'''
        norm=once(norm,dispatch,'');need(tokens(norm)==tokens(old_runtime),'Runtime changed beyond explicit post-flush helper/dispatch')
        step=fn(runtime,'step');need(step.index(dispatch)>step.index('tud_cdc_n_write_flush(0)'),'Prefetch precedes existing flush')
        before=step[:step.index(dispatch)];need(before.rfind('live_time(r)')>before.index('tud_cdc_n_write_flush(0)') and before.rfind('synchronize_loss(r)')>before.index('tud_cdc_n_write_flush(0)'),'Missing post-flush TIME/loss')
        need('mt_live_device_prefetch_tx(&r->device,ticket)' in helper and 'if(result!=MT_LIVE_TX_ERROR)return' in helper,'Collect/error-only boundary changed')
        unchanged=[];changed={'v2/protocol/mt_live_device.c','v2/protocol/mt_live_device.h','v2/app/mt_live_runtime.c'}
        for p in sorted((base/'patched').rglob('*')):
            if not p.is_file() or p.relative_to(base/'patched').as_posix() in changed:continue
            q=image/'patched'/p.relative_to(base/'patched');read(p);read(q)
            need(p.read_bytes()==q.read_bytes(),'Unrelated SI source changed '+str(p));unchanged.append({'path':q.relative_to(image).as_posix(),'sha256':sha(q)})
        for rel in ('firmware/platform/mt_timebase.c','firmware/third_party/usb/vendor/tinyusb/src/tusb.c','firmware/third_party/usb/vendor/tinyusb/src/class/cdc/cdc_device.c'):
            need(read(image/'source'/rel)==read(base/'source'/rel),'TIME/USB source changed '+rel)
        hp=image/'generated/mt_firmware_build.h';h=read(hp)
        need(re.findall(r'#define MT_FIRMWARE_BUILD UINT32_C\((0x[0-9a-f]+)\)',h)==[f'0x{build:08x}'],'Wrong generated observer identity')
        for rel in ('objects/board.d','objects/29-mt_stream_progress.d'):
            need('generated/mt_firmware_build.h' in read(image/rel),'Shared header dependency absent '+rel)
        need(ri['inputs_before'].get(str(hp))==sha(hp),'Generated identity missing input pin')
        coretool=image/'source/tests/boot-link/tools/run_boot_link_tests.py';read(coretool);elfmod=load(coretool,'q_elf')
        elf=elfmod.ELF(image/'MotortesterV2-stream-candidate.elf');need(elf.word(elf.value('mt_board')+12)==build,'Linked board id mismatch')
        aobj=elfmod.ELF(base/'objects/29-mt_stream_progress.o');bobj=elfmod.ELF(image/'objects/29-mt_stream_progress.o')
        ab=aobj.bytes(aobj.by_name['.text.bind']);bb=bobj.bytes(bobj.by_name['.text.bind'])
        need(ab.count(struct.pack('<I',0x56325349))==1 and bb==ab.replace(struct.pack('<I',0x56325349),struct.pack('<I',build)),'Observer binding machine code changed beyond config identity')
        stable_objects=[]
        for p in sorted((base/'objects').glob('*.o')):
            if p.name in ('board.o','21-mt_live_runtime.o','24-mt_live_device.o','29-mt_stream_progress.o'):continue
            q=image/'objects'/p.name;need(sha(p)==sha(q),'Unrelated compiled object changed '+p.name);stable_objects.append({'path':q.relative_to(image).as_posix(),'sha256':sha(q)})
        proof={'status':'PASS','original_core':'All SI tokens after exact reinlining of shared collect and removal of two new APIs','runtime':'All SI tokens after removal of exact post-flush helper/dispatch','core_state_and_layout_unchanged':True,'static_collector_only':cc,'new_helper':helper,'post_flush_dispatch':dispatch,'shared_generated_build_id':f'0x{build:08x}','observer_bind_machine_code':'SI identical except single config-derived id literal','unchanged_SI_patched_sources':unchanged,'unchanged_nonfunctional_objects':stable_objects,'ADC_TIME_USB_DCD_queue_wire_serializer_unchanged':True,'not_a_timing_or_physical_proof':True}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        for p in (image/'patched/v2').rglob('*.h'):copy(p,p.relative_to(image/'patched/v2'))
        for rel in ('platform/mt_timebase.h','platform/mt_stream_diag.h','transport/mt_usb_epoch.h'):
            copy(image/'source/firmware'/rel,rel)
        copy(hp,'generated/mt_firmware_build.h')
        sources=[]
        for area,names in {'protocol':['mt_live_device.c','mt_wire.c','mt_batch1024.c','mt_v2_crc32.h'],
            'acquisition':['mt_sample_queue.c','mt_acquisition_profile.c'],'platform':['mt_stream_progress.c']}.items():
            for name in names:
                p=image/'patched/v2'/area/name
                if not p.exists():p=image/'source/firmware'/area/name
                need(ri['inputs_before'].get(str(p))==sha(p),'Actual source compiler pin drift '+str(p));copy(p,area+'/'+name)
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
        model=read(Path(__file__).with_name('prefetch_model.c'));need(model.count('/* RUNTIME_BODIES */')==1,'Model seam')
        (out/'model.c').write_text(model.replace('/* RUNTIME_BODIES */',fn(runtime,'prepared_tx_step')+'\n'+helper),encoding='utf8',newline='\n')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).strip()
        run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-I.','-Igenerated','-Iplatform','-Iprotocol','-Iacquisition','-Iapp','-Itransport','-DCFG_MT_STREAM_DIAGNOSTICS=1','-DCFG_MT_PROGRESS_TRACE=1','-DMT_PROGRESS_NATIVE=1','model.c',*sources,'-o','model.exe'])
        stdout=run('model',[out/'model.exe'])
        result.update(status='PASS',compiler_version=version,stdout=stdout,image_bin_sha256=ri['artifacts']['MotortesterV2-stream-candidate.bin'],source_equivalence_sha256=sha(out/'source-equivalence.json'),limitations=['Actual core/queue/serializer/wire/observer plus exact extracted runtime helpers execute.','Clock, epoch, actor/USB and preceding flush are explicit logical seams; ISR injection occurs at synthetic DWT span reads.','Observer uses exact ARM-generated SJ identity; legacy136 setup is synthetic, not execution of legacy module.','No target time/WCET, full runtime/MMIO/USB/DMA, continuous150k or Flash admission.'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,v in inputs.items() if not Path(p).is_file() or sha(Path(p))!=v];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
