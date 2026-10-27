"""One exact-runtime deferred-grant order model; other SG algorithms are source-pinned."""
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(x,m):
    if not x:raise ValueError(m)
def tokens(s):return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))
def once(s,a,b):
    need(s.count(a)==1,'Exact normalization: '+a[:100]);return s.replace(a,b)

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'Use a new build output');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf-8-sig')
    def run(label,argv):
        row={'label':label,'argv':[str(x) for x in argv]};commands.append(row)
        q=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180)
        row['exit_code']=q.returncode;(out/(label+'.stdout')).write_bytes(q.stdout);(out/(label+'.stderr')).write_bytes(q.stderr)
        need(q.returncode==0,label+' failed; retained');return q.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        ri=json.loads(read(image/'receipt.json'));rb=json.loads(read(base/'receipt.json'))
        need(ri['status']==rb['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Unfinished image')
        need(ri['config']['firmware_build']==0x56325348 and rb['config']['firmware_build']==0x56325347,'Wrong SH/SG basis')
        need(not ri['config']['active_profile_enabled'],'Unexpected512B observer')
        ext=Path(__file__).with_name('check_usb_gate.py');read(ext)
        sp=importlib.util.spec_from_file_location('late_extract',ext);mod=importlib.util.module_from_spec(sp);sp.loader.exec_module(mod);fn=mod.function
        path=Path('patched/v2/app/mt_live_runtime.c');s=read(image/path);old=read(base/path)
        normalized=s
        for name in ('defer_data_grant','new_data_ticket'):normalized=once(normalized,fn(normalized,name),'')
        normalized=once(normalized,'    mt_live_tx_ticket ticket; unsigned deferred_grant;','    mt_live_tx_ticket ticket;')
        choice='    deferred_grant=(unsigned)defer_data_grant(r);\n    if(!deferred_grant) { *grant_attempted=1u; grant_irq(r); }'
        normalized=once(normalized,choice,'    *grant_attempted=1u; grant_irq(r);')
        start=normalized.index('    if(deferred_grant) {\n');end=normalized.index('    MT_DIAG_STAMP(diag_tx);',start)
        late=normalized[start:end];normalized=normalized[:start]+normalized[end:]
        need(tokens(normalized)==tokens(old),'Working SG runtime changed beyond explicit selector/deferred boundary')
        need(late.index('*grant_attempted=1u')<late.index('live_time(r)')<late.index('synchronize_loss(r)')<late.index('if(!usable(r))')<late.index('mt_usb_bridge_app_enter(&scope)')<late.index('grant_irq(r)'),'Pre-grant actual admission order')
        after=late[late.index('grant_irq(r);')+len('grant_irq(r);'):]
        need(after.index('live_time(r)')<after.index('if(!stable(r))')<after.index('new_data_ticket(&ticket)'),'Post-grant validation order')
        need(tokens(fn(s,'grant_irq'))==tokens(fn(old,'grant_irq')),'Grant budget/gating changed')
        need(tokens(fn(s,'prepared_tx_step'))==tokens(fn(old,'prepared_tx_step')),'Guarded epoch/ticket submit changed')
        unchanged=[]
        for p in sorted((base/'patched').rglob('*')):
            if not p.is_file() or p.relative_to(base)==path:continue
            q=image/p.relative_to(base);need(read(q)==read(p),'Changed SG source '+str(p))
            unchanged.append({'path':p.relative_to(base).as_posix(),'sha256':sha(q)})
        for rel in ('firmware/platform/mt_timebase.c','firmware/third_party/usb/vendor/tinyusb/src/tusb.c','firmware/third_party/usb/vendor/tinyusb/src/class/cdc/cdc_device.c'):
            need(read(image/'source'/rel)==read(base/'source'/rel),'Changed canonical TIME/USB '+rel)
        proof={'status':'PASS','method':'Whole runtime token equivalence after removing two pure predicates and exactly delimited deferred boundary/selector; all other patched files byte-identical SG','deferred_boundary':late,'selector':choice,'unchanged_SG_patched_sources':unchanged,'grant_and_prepared_submit_unchanged':True,'N64_ABI_unchanged':True,'TIME_ADC_DCD_wire_queue_algorithms_unchanged':True,'no_physical_timing_claim':True}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        for p in (image/'patched/v2').rglob('*.h'):
            q=out/p.relative_to(image/'patched/v2');q.parent.mkdir(parents=True,exist_ok=True);q.write_text(read(p),encoding='utf8',newline='\n')
        for rel in ('platform/mt_timebase.h','platform/mt_stream_diag.h','transport/mt_usb_epoch.h','transport/mt_usb_epoch.c'):
            p=image/'source/firmware'/rel;q=out/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(read(p),encoding='utf8',newline='\n')
        (out/'device').mkdir();(out/'device/dcd.h').write_text('#include "tusb.h"\n',encoding='ascii')
        (out/'tusb.h').write_text('''#ifndef MODEL_TUSB_H
#define MODEL_TUSB_H
#include <stdint.h>
#include <stdbool.h>
typedef struct {unsigned ignored;} dcd_event_t;
typedef struct {unsigned ignored;} tu_fifo_t;
typedef struct {unsigned ignored;} tusb_desc_endpoint_t;
typedef struct {unsigned ignored;} tusb_control_request_t;
#endif
''',encoding='ascii')
        model=read(Path(__file__).with_name('deferred_grant_model.c'));need(model.count('/* BODIES */')==1,'Model seam missing')
        names=('stable','usable','quiescent','loss_result','synchronize_loss','time_fault','live_write','prepared_tx_step','grant_irq','defer_data_grant','new_data_ticket','step','mt_live_runtime_step')
        (out/'model.c').write_text(model.replace('/* BODIES */','\n'.join(fn(s,n) for n in names)),encoding='utf8',newline='\n')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).strip()
        run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-I.','-Itransport','-DCFG_MT_STREAM_DIAGNOSTICS=0','-DCFG_MT_PROGRESS_TRACE=0','model.c','transport/mt_usb_epoch.c','-o','model.exe'])
        stdout=run('model',[out/'model.exe'])
        result.update(status='PASS',image_bin_sha256=ri['artifacts']['MotortesterV2-stream-candidate.bin'],baseline_bin_sha256=rb['artifacts']['MotortesterV2-stream-candidate.bin'],compiler_version=version,stdout=stdout,source_equivalence_sha256=sha(out/'source-equivalence.json'),limitations=['Actual runtime bodies and epoch functions execute; ADC/core/USB/MMIO/clock are logical boundary seams.','N64 observer is unchanged and source-pinned; disabled only in this logical order harness.','No target CPU/IRQ timing, full USB/DMA/lossless throughput or150k physical qualification.'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,v in inputs.items() if not Path(p).is_file() or sha(Path(p))!=v];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
