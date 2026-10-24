"""One exact-runtime early-grant order model; unchanged ADC/core/USB are source-pinned."""
import argparse,hashlib,importlib.util,json,os,re,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(x,m):
    if not x:raise ValueError(m)
def tokens(s):return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))
def once(s,a,b):need(s.count(a)==1,'Pinned normalization: '+a[:80]);return s.replace(a,b)

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2];image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'Use a new build output');out.mkdir();inputs={};commands=[];result={'status':'RUNNING','inputs':inputs,'commands':commands,'scope':__doc__}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf-8-sig')
    def run(label,argv):
        row={'label':label,'argv':[str(x) for x in argv]};commands.append(row)
        q=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180);row['exit_code']=q.returncode
        (out/(label+'.stdout')).write_bytes(q.stdout);(out/(label+'.stderr')).write_bytes(q.stderr);need(q.returncode==0,label+' failed; retained');return q.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        ri=json.loads(read(image/'receipt.json'));rb=json.loads(read(base/'receipt.json'))
        need(ri['status']==rb['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Unfinished image')
        need(ri['config']['firmware_build']==0x56325342 and rb['config']['firmware_build']==0x56325341,'Wrong SB/SA basis')
        need(not ri['config']['active_profile_enabled'],'Unexpected active observer')
        ext=Path(__file__).with_name('check_usb_gate.py');read(ext);sp=importlib.util.spec_from_file_location('early_extract',ext);mod=importlib.util.module_from_spec(sp);sp.loader.exec_module(mod);fn=mod.function
        path=Path('patched/v2/app/mt_live_runtime.c');s=read(image/path);old=read(base/path)
        ow=fn(old,'mt_live_runtime_step');a0=ow.index('    if(!r->clock_fault && mt_timebase_healthy(r->clock)) {');a1=ow.index('#if CFG_MT_STREAM_DIAGNOSTICS',a0);old_grant=ow[a0:a1]
        expected='static void grant_irq(mt_live_runtime *r) {\n    uint32_t key;\n'+old_grant+'}\n'
        need(tokens(fn(s,'grant_irq'))==tokens(expected),'Grant helper changes previous gating')
        normalized=once(s,fn(s,'grant_irq'),'')
        normalized=once(normalized,'static mt_live_runtime_result step(mt_live_runtime *r,unsigned *grant_attempted)','static mt_live_runtime_result step(mt_live_runtime *r)')
        n0=normalized.index('    /* A task completion can already have armed');n1=normalized.index('    if(r->carry_offset==r->carry_used)',n0);early=normalized[n0:n1]
        need(early.index('*grant_attempted=1u')<early.index('grant_irq(r)')<early.index('live_time(r)')<early.index('if(!stable(r))'),'New boundary guard order')
        normalized=normalized[:n0]+normalized[n1:]
        normalized=once(normalized,'    mt_live_runtime_result result; unsigned grant_attempted=0u;','    mt_live_runtime_result result; uint32_t key;')
        normalized=once(normalized,'result=step(r,&grant_attempted);','result=step(r);')
        normalized=once(normalized,'    if(!grant_attempted)grant_irq(r);\n',old_grant)
        need(tokens(normalized)==tokens(old),'Original runtime operations/checks changed beyond grant relocation and new boundary')
        unchanged=[]
        for p in sorted((base/'patched').rglob('*')):
            if not p.is_file() or p.relative_to(base)==path:continue
            q=image/p.relative_to(base);need(read(q)==read(p),'Changed SA patched source '+str(p));unchanged.append({'path':p.relative_to(base).as_posix(),'sha256':sha(q)})
        need(read(image/'source/firmware/platform/mt_timebase.c')==read(base/'source/firmware/platform/mt_timebase.c'),'TIME backend changed')
        for folder,rec in ((image,ri),(base,rb)):
            for p,v in list(inputs.items()):
                if Path(p).is_relative_to(folder) and p in rec['inputs_before']:need(rec['inputs_before'][p]==v,'Receipt source pin differs')
        proof={'status':'PASS','method':'Whole runtime token equivalence after exact grant relocation and explicit post-IRQ guards; all other patched files byte-identical to SA','early_boundary':early,'old_grant_body':old_grant,'unchanged_SA_patched_sources':unchanged,'TIME_source_unchanged':True,'DCD_budget_unchanged':True,'no_physical_timing_claim':True}
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
        model=read(Path(__file__).with_name('usb_turnover_model.c'));need(model.count('/* BODIES */')==1,'Model seam missing')
        names=('stable','usable','quiescent','loss_result','synchronize_loss','time_fault','live_write','prepared_tx_step','grant_irq','step','mt_live_runtime_step')
        (out/'model.c').write_text(model.replace('/* BODIES */','\n'.join(fn(s,n) for n in names)),encoding='utf8',newline='\n')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).strip()
        run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-I.','-Itransport','-DCFG_MT_STREAM_DIAGNOSTICS=0','model.c','transport/mt_usb_epoch.c','-o','model.exe'])
        stdout=run('model',[out/'model.exe'])
        result.update(status='PASS',image_bin_sha256=ri['artifacts']['MotortesterV2-stream-candidate.bin'],baseline_bin_sha256=rb['artifacts']['MotortesterV2-stream-candidate.bin'],compiler_version=version,stdout=stdout,source_equivalence_sha256=sha(out/'source-equivalence.json'),limitations=['Actual runtime bodies and epoch functions execute; ADC/core/USB/MMIO/clock are logical boundary seams.','No target CPU/IRQ timing, physical USB/DMA, losslessness or100k qualification.','Unchanged SA core/DCD/TIME models not rerun; preserved source pins and negative physical evidence remain.'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,v in inputs.items() if not Path(p).is_file() or sha(Path(p))!=v];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
