"""One actual-core TX prepare/commit native comparison; no hardware timing claim."""
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,msg):
    if not ok: raise ValueError(msg)
def tokens(s):
    s=re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S)
    return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',s)
def replace_once(s,a,b):
    need(s.count(a)==1,'Pinned normalization input: '+a[:90]);return s.replace(a,b)

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode,'Run python -I -B')
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):parser.add_argument('--'+n,type=Path,required=True)
    a=parser.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'Use a new build output')
    out.mkdir();inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf-8-sig')
    def run(label,argv,cwd):
        row={'label':label,'argv':[str(x) for x in argv],'cwd':str(cwd)};commands.append(row)
        proc=subprocess.run(row['argv'],cwd=cwd,env=env,capture_output=True,timeout=180)
        row['exit_code']=proc.returncode;(out/(label+'.stdout')).write_bytes(proc.stdout);(out/(label+'.stderr')).write_bytes(proc.stderr)
        need(proc.returncode==0,label+' failed; evidence retained')
        return proc.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        receipts={folder:json.loads(read(folder/'receipt.json')) for folder in (image,base)}
        for folder,receipt in receipts.items():need(receipt['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Unfinished image')
        need(receipts[image]['config']['firmware_build']==0x56325341 and receipts[image]['config']['active_profile_enabled'] is False,'Wrong candidate/profile')
        need(receipts[base]['config']['firmware_build']==0x56325338,'Expected exact S8 baseline')
        helper_path=Path(__file__).with_name('check_usb_gate.py');read(helper_path)
        spec=importlib.util.spec_from_file_location('prepare_extract',helper_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        fn=helper.function
        core=read(image/'patched/v2/protocol/mt_live_device.c');old=read(base/'patched/v2/protocol/mt_live_device.c')
        # Verify the entire unchanged core remainder, including completed()/CRC,
        # receive/offer/Stop/recovery callbacks, separately from changed bodies.
        old_rest=old
        for name in ('build_tx','mt_live_device_step'):old_rest=replace_once(old_rest,fn(old,name),'')
        new_rest=core
        for name in ('build_tx','tx_intents','ticket_capture','ticket_matches','mt_live_device_prepare_tx','step_tx','mt_live_device_step','mt_live_device_step_prepared'):
            new_rest=replace_once(new_rest,fn(core,name),'')
        new_rest=re.sub(r'_Static_assert\(sizeof\(mt_live_tx_ticket\)<=224u,"bounded foreground TX ticket"\);','',new_rest)
        need(tokens(new_rest)==tokens(old_rest),'Unchanged core code differs')
        built=fn(core,'build_tx')
        built=replace_once(built,'build_tx(mt_live_device *d,unsigned *error)','build_tx(mt_live_device *d)')
        built=replace_once(built,'    *error=MT_LIVE_ERR_NONE;\n','')
        built=replace_once(built,'*error=MT_LIVE_ERR_PROTOCOL; return 0;','recover(d,MT_LIVE_ERR_PROTOCOL); return 0;')
        built=replace_once(built,'*error=MT_LIVE_ERR_ARGUMENT; return 0;','recover(d,MT_LIVE_ERR_ARGUMENT); return 0;')
        need(tokens(built)==tokens(fn(old,'build_tx')),'Build logic other than deferred errors differs')
        step=fn(core,'step_tx')
        step=replace_once(step,'static int step_tx(mt_live_device *d,const mt_live_tx_ticket *ticket)','int mt_live_device_step(mt_live_device *d)')
        step=replace_once(step,'unsigned first,hello_complete=0,error;','unsigned first,hello_complete=0;')
        start=step.index('    if(!now(d,&n) || !expire(d,n))return d->state!=MT_LIVE_FAULT;')
        end=step.index('    if(!now(d,&n) || !expire(d,n))return 0;',start)
        block=step[start:end]
        # The additional branch is retained in the proof receipt for manual review.
        need('if(!ticket_matches(d,ticket))' in block and block.index('ticket_matches')<block.index('recover(d,ticket->error)'),'Error precedes current ticket')
        step=step[:start]+'    if(!now(d,&n) || !expire(d,n) || !build_tx(d))return d->state!=MT_LIVE_FAULT;\n'+step[end:]
        step=replace_once(step,'    if(ticket && !ticket_matches(d,ticket))return d->state!=MT_LIVE_FAULT;\n','')
        need(tokens(step)==tokens(fn(old,'mt_live_device_step')),'Original TX/TIME/deadline/commit body differs')
        runtime=read(image/'patched/v2/app/mt_live_runtime.c');old_runtime=read(base/'patched/v2/app/mt_live_runtime.c')
        normalized=replace_once(runtime,fn(runtime,'prepared_tx_step'),'')
        normalized=replace_once(normalized,'    mt_usb_scope scope; uint32_t key,prepared_epoch,prepared_soft_serial; int serviced,tx_ok;\n    mt_live_tx_ticket ticket;','    mt_usb_scope scope; uint32_t key; int serviced,tx_ok;')
        a0=normalized.index('    /* Pure staging runs');a1=normalized.index('    MT_DIAG_TX_END(diag_tx);',a0)
        prepare_runtime=normalized[a0:a1]
        need(prepare_runtime.index('prepare_tx')<prepare_runtime.index('key=mt_usb_bridge_lock()')<prepare_runtime.index('prepared_tx_step')<prepare_runtime.index('mt_usb_bridge_unlock'),'Prepare/guard order')
        normalized=normalized[:a0]+'    MT_DIAG_STAMP(diag_tx);\n    key=mt_usb_bridge_lock(); tx_ok=mt_live_device_step(&r->device); mt_usb_bridge_unlock(key);\n'+normalized[a1:]
        need(tokens(normalized)==tokens(old_runtime),'Unchanged runtime ADC/TIME/loss/grant order differs')
        header=read(image/'patched/v2/protocol/mt_live_device.h');old_header=read(base/'patched/v2/protocol/mt_live_device.h')
        h0=header.index('/* Foreground-only staging transaction.');h1=header.index('/* All operations are single-owner foreground calls',h0)
        need(tokens(header[:h0]+header[h1:])==tokens(old_header),'Existing core API/storage differs')
        unchanged=[]
        for rel in ('dcd_stm32_fsdev.c','usbd.c','fsdev_stm32.h','v2/app/mt_live_adc.c','v2/platform/adc_timer_dma.c','v2/platform/adc_timer_dma.h','v2/app/mt_live_adc.h','v2/acquisition/mt_sample_queue.c','v2/protocol/mt_wire.c','v2/transport/mt_usb_bridge.c','v2/boot/tusb_config.h'):
            need(read(image/'patched'/rel)==read(base/'patched'/rel),'Unchanged ADC/USB source differs: '+rel);unchanged.append(rel)
        need(read(image/'source/firmware/platform/mt_timebase.c')==read(base/'source/firmware/platform/mt_timebase.c'),'TIME source differs')
        proof={'status':'PASS','method':'whole unchanged core/runtime token comparison plus exact changed-body normalization and byte-pinned ADC/USB sources','unchanged_files':unchanged,'original_step_calls_and_checks_restored_by_normalization':True,'pure_build_only_error_deferral':True,'completed_rolling_CRC_unchanged':True,'runtime_submit_helper':fn(runtime,'prepared_tx_step'),'new_ticket_error_branch':block,'prepare_runtime_block':prepare_runtime,'scope_limit':'Source proof is distinct from native API execution; no target WCET or physical USB claim.'}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        result['source_equivalence_sha256']=sha(out/'source-equivalence.json')
        model_path=Path(__file__).with_name('tx_prepare_model.c');model=read(model_path)
        need(model.count('/* PREPARED_TX_HELPER */')==1,'Model helper seam absent')
        model=model.replace('/* PREPARED_TX_HELPER */',fn(runtime,'prepared_tx_step'))
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        run('version',[zig,'version'],out)
        for label,folder in (('baseline',base),('candidate',image)):
            dest=out/label;dest.mkdir();(dest/'model.c').write_text(model,encoding='utf8',newline='\n');sources=[]
            for area,names in {'protocol':['mt_live_device.c','mt_live_device.h','mt_wire.c','mt_wire.h','mt_v2_crc32.h'],'acquisition':['mt_sample_queue.c','mt_sample_queue.h']}.items():
                (dest/area).mkdir()
                for name in names:
                    src=folder/'patched/v2'/area/name;text=read(src);need(receipts[folder]['inputs_before'].get(str(src))==sha(src),'Image dependency drift')
                    (dest/area/name).write_text(text,encoding='utf8',newline='\n')
                    if name.endswith('.c'):sources.append(area+'/'+name)
            flags=['-DMT_TEST_BASELINE='+('1' if label=='baseline' else '0')]
            run('compile-'+label,[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter',*flags,'-I.','-Iprotocol','-Iacquisition','model.c',*sources,'-o','model.exe'],dest)
            run('model-'+label,[dest/'model.exe',dest/'transcript.bin'],dest)
        b=(out/'baseline/transcript.bin').read_bytes();c=(out/'candidate/transcript.bin').read_bytes();need(b==c,'Deterministic wire transcript differs from S8')
        result.update(status='PASS',image_bin_sha256=receipts[image]['artifacts']['MotortesterV2-stream-candidate.bin'],baseline_bin_sha256=receipts[base]['artifacts']['MotortesterV2-stream-candidate.bin'],transcript_bytes=len(c),transcript_sha256=hashlib.sha256(c).hexdigest(),not_verified=['ARM duration/IRQ-off bound','DMA/USB physical throughput','Physical rate/fidelity or losslessness','Flash approval'])
    except BaseException as e:
        result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[x for x,v in inputs.items() if not Path(x).is_file() or sha(Path(x))!=v]
        result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
