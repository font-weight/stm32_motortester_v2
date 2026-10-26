"""One actual SE core/ownership/lifecycle model with immutable SD guard proof; no hardware."""
import argparse,hashlib,importlib.util,json,os,re,subprocess,sys
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,message):
    if not ok:raise ValueError(message)
def tokens(s):return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))
def once(s,a,b):need(s.count(a)==1,'Normalization count: '+a[:80]);return s.replace(a,b)
def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('image','baseline','zig','output'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(out.is_relative_to(root/'build') and not out.exists(),'Use a new build output');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf8')
    def run(label,argv):
        row={'label':label,'argv':[str(x) for x in argv]};commands.append(row)
        q=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180);row['exit_code']=q.returncode
        (out/(label+'.stdout')).write_bytes(q.stdout);(out/(label+'.stderr')).write_bytes(q.stderr)
        need(q.returncode==0,label+' failed; evidence retained');return q.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        ri,rb=json.loads(read(image/'receipt.json')),json.loads(read(base/'receipt.json'))
        need(ri['status']==rb['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Unfinished image')
        need(ri['config']['firmware_build']==0x56325345 and rb['config']['firmware_build']==0x56325344,'Wrong SE/SD basis')
        need(ri['config']['acquisition_modes']==[1,2,3,4,5] and not ri['config']['active_profile_enabled'],'Wrong modes/observer')
        helper=Path(__file__).with_name('check_usb_gate.py');read(helper)
        spec=importlib.util.spec_from_file_location('extract_se',helper);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);fn=mod.function
        changed={'protocol/mt_live_device.c','protocol/mt_live_device.h','acquisition/mt_sample_queue.c',
                 'acquisition/mt_sample_queue.h','acquisition/mt_acquisition_profile.c'}
        unchanged=[]
        for p in sorted((base/'patched').rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(base/'patched');q=image/'patched'/rel
            if rel.as_posix().removeprefix('v2/') in changed:continue
            need(p.read_bytes()==q.read_bytes(),'Preserved SD source changed: '+str(rel));read(p);read(q)
            unchanged.append({'path':rel.as_posix(),'sha256':sha(q)})
        for name in ('mt_timebase.c','mt_timebase.h'):
            p=base/'source/firmware/platform'/name;q=image/'source/firmware/platform'/name
            need(read(p)==read(q),'Original TIME source changed')
        core,old=read(image/'patched/v2/protocol/mt_live_device.c'),read(base/'patched/v2/protocol/mt_live_device.c');proofs=[]
        for name in ('now','expire','deadline','recover','raw_barrier','flags','quiesce_before_start','snapshot_valid',
                     'terminate','accept_frame','mt_live_device_receive','mt_live_device_offer','mt_live_device_fault',
                     'mt_live_device_transport_lost','stage_data','completed_data','completed','tx_intents'):
            need(tokens(fn(core,name))==tokens(fn(old,name)),'Preserved core body changed: '+name)
            proofs.append({'function':name,'method':'token-identical SD; new owned cleanup in abandon_tx separately reviewed'})
        for name in ('abandon_tx','commit_hello'):
            current=fn(core,name).replace('batch_discard(d);','')
            need(tokens(current)==tokens(fn(old,name)),'Unexpected cleanup delta '+name)
        current=once(fn(core,'begin_hello'),'    if(!d->tx_offset) { d->tx_length=0;batch_discard(d); }','    if(!d->tx_offset)d->tx_length=0;')
        need(tokens(current)==tokens(fn(old,'begin_hello')),'HELLO guards changed beyond accepted0 stage discard')
        current=fn(core,'step_tx')
        current=once(current,'    mt_live_batch_completion pending;unsigned batch_pending=0;\n','')
        current=once(current,'''            if(d->tx_type==DATA && d->tx_mode==5u) {
                if(!batch_completion_prepare(d,&pending)) { recover(d,MT_LIVE_ERR_CALLBACK);return 0; }
                batch_pending=1;
            } else completed(d);''','            completed(d);')
        current=once(current,'    if(batch_pending)batch_completion_publish(d,&pending);\n','')
        need(tokens(current)==tokens(fn(old,'step_tx')),'Original write/TIME guard changed beyond mode5 deferred completion')
        step=fn(core,'step_tx');need(step.index('if(batch_pending)')>step.index('if(bound!=UINT64_MAX && after>=bound)'),'Deferred stores precede last TIME/bound')
        pub=fn(core,'batch_completion_publish');need(not re.search(r'\b(?!if\b)[A-Za-z_]\w*\s*\(',pub[pub.index('{')+1:]),'Publication calls a function')
        completion=fn(core,'batch_completion_prepare')
        for text in ('d->batch.length!=d->tx_length','d->batch.count!=d->tx_count'):
            need(text in completion,'Missing exact completion metadata '+text)
        queue,oq=read(image/'patched/v2/acquisition/mt_sample_queue.c'),read(base/'patched/v2/acquisition/mt_sample_queue.c')
        for name in ('mt_sample_queue_init','mt_sample_queue_push_quantized','mt_sample_queue_push','mt_sample_queue_seal',
                     'mt_sample_queue_peek','mt_sample_queue_peek_offset','mt_sample_queue_pop_span','mt_sample_queue_pop'):
            need(tokens(fn(queue,name))==tokens(fn(oq,name)),'Old queue API changed '+name)
        pack,op=read(image/'patched/v2/acquisition/mt_acquisition_profile.c'),read(base/'patched/v2/acquisition/mt_acquisition_profile.c')
        need(tokens(fn(pack,'mt_acquisition_pack'))==tokens(fn(op,'mt_acquisition_pack')),'Old packer changed')
        prototype=root/'firmware/v2-stream/batch1024'
        need(read(image/'patched/v2/protocol/mt_batch1024.c')==read(prototype/'mt_batch1024.c'),'Frozen serializer body changed')
        need(tokens(read(image/'patched/v2/protocol/mt_batch1024.h'))==tokens(read(prototype/'mt_batch1024.h')),'Serializer header changed beyond comment')
        proof={'status':'PASS','unchanged_SD_patched_sources':unchanged,'core_guard_proofs':proofs,
               'original_step_tx_guards':'token-identical after explicit mode5 deferred completion insertion',
               'deferred_publish_after_last_now_bound':True,'publish_no_function_calls':True,
               'runtime_TIME_ADC_DMA_DCD_FIFO_USB_byte_identical':True,'old_queue_APIs_token_identical':True,
               'not_a_hardware_or_scheduler_proof':True}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        sources=[]
        for area,names in {'protocol':['mt_live_device.c','mt_live_device.h','mt_wire.c','mt_wire.h','mt_v2_crc32.h','mt_batch1024.c','mt_batch1024.h'],
            'acquisition':['mt_sample_queue.c','mt_sample_queue.h','mt_acquisition_profile.c','mt_acquisition_profile.h']}.items():
            (out/area).mkdir()
            for name in names:
                p=image/'patched/v2'/area/name
                if not p.exists():p=image/'source/firmware'/area/name
                text=read(p);need(ri['inputs_before'].get(str(p))==sha(p),'Image source pin drift '+str(p))
                (out/area/name).write_text(text,encoding='utf8',newline='\n')
                if name.endswith('.c'):sources.append(area+'/'+name)
        runtime=read(image/'patched/v2/app/mt_live_runtime.c');model=read(Path(__file__).with_name('batch1024_core_model.c'))
        need(model.count('/* PREPARED_TX_HELPER */')==1,'Wrong actual runtime helper seam')
        (out/'model.c').write_text(model.replace('/* PREPARED_TX_HELPER */',fn(runtime,'prepared_tx_step')),encoding='utf8',newline='\n')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).strip()
        run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-I.','-Iprotocol','-Iacquisition','model.c',*sources,'-o','model.exe'])
        stdout=run('model',[out/'model.exe',out/'core1153-transcript.bin'])
        result.update(status='PASS',compiler_version=version,stdout=stdout,
            image_bin_sha256=ri['artifacts']['MotortesterV2-stream-candidate.bin'],
            source_equivalence_sha256=sha(out/'source-equivalence.json'),C_fixture_sha256=sha(out/'core1153-transcript.bin'),
            fixture={'scope':'Actual production core prepare->step_prepared; no hardware','nonce':503,'generation':3,'mode':5,
                     'bareCOBS':['DATA1024 seq4 index0','DATA129 seq5 index1024','END seq6 prefix1153']},
            seams=['Logical IO/clock/Stop callbacks, not physical peripherals','Actual extracted runtime submit helper plus explicit actual-core cleanup call, not entire runtime/USB execution',
                   'CRC/COBS Stop states reconstructed by real serializer API; scheduler currently encodes in one nonreentrant FG prepare'],
            not_verified=['Physical150k throughput/ADC deadlines','Analog accuracy','Flash approval'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,v in inputs.items() if not Path(p).is_file() or sha(Path(p))!=v];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
