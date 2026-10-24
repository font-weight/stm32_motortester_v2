"""One exact-image selectable-profile model; no hardware/throughput certificate."""
import argparse,hashlib,importlib.util,json,os,re,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(x,m):
    if not x:raise ValueError(m)
def once(s,a,b):need(s.count(a)==1,'Normalization count: '+a[:90]);return s.replace(a,b)
def tokens(s):return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'Use a new build output');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','inputs':inputs,'commands':commands,'scope':__doc__}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf8')
    def run(label,argv):
        row={'label':label,'argv':[str(x) for x in argv]};commands.append(row)
        q=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180);row['exit_code']=q.returncode
        (out/(label+'.stdout')).write_bytes(q.stdout);(out/(label+'.stderr')).write_bytes(q.stderr)
        need(q.returncode==0,label+' failed; retained');return q.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        ri=json.loads(read(image/'receipt.json'));rb=json.loads(read(base/'receipt.json'))
        need(ri['status']==rb['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Unfinished image')
        need(ri['config']['firmware_build']==0x56325343 and rb['config']['firmware_build']==0x56325342,'Wrong SC/SB basis')
        need(ri['config']['acquisition_modes']==[1,2,3] and not ri['config']['active_profile_enabled'],'Profile/observer recipe differs')
        helper=Path(__file__).with_name('check_usb_gate.py');read(helper)
        sp=importlib.util.spec_from_file_location('profile_extract',helper);mod=importlib.util.module_from_spec(sp);sp.loader.exec_module(mod);fn=mod.function
        changed={'protocol/mt_live_device.c','protocol/mt_live_device.h','protocol/mt_wire.c','protocol/mt_wire.h',
                 'platform/adc_timer_dma.c','platform/adc_timer_dma.h','app/mt_live_adc.c',
                 'acquisition/mt_sample_queue.c','acquisition/mt_sample_queue.h'}
        unchanged=[]
        for p in sorted((base/'patched').rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(base/'patched');q=image/'patched'/rel
            if rel.as_posix().removeprefix('v2/') in changed:continue
            need(read(q)==read(p),'Changed preserved SB source '+str(rel));unchanged.append({'path':rel.as_posix(),'sha256':sha(q)})
        need(read(image/'source/firmware/platform/mt_timebase.c')==read(base/'source/firmware/platform/mt_timebase.c'),'TIME changed')
        core=read(image/'patched/v2/protocol/mt_live_device.c');old=read(base/'patched/v2/protocol/mt_live_device.c')
        proofs=[]
        for n in ('now','expire','deadline','recover','raw_barrier','flags','quiesce_before_start','snapshot_valid','tx_intents'):
            need(tokens(fn(core,n))==tokens(fn(old,n)),'Changed core guard '+n);proofs.append({'function':n,'method':'token-identical'})
        text=fn(core,'step_tx')
        text=once(text,'                            d->tx_revision==d->pending_revision && d->tx_mode==d->pending_mode &&\n','')
        need(tokens(text)==tokens(fn(old,'step_tx')),'Write/TIME/commit guard changed beyond HELLO identity pins')
        proofs.append({'function':'step_tx','method':'token-identical after exact added HELLO revision/mode checks'})
        text=fn(core,'terminate')
        text=once(text,'mt_sample_queue_push_quantized(&d->queue,s.tail[b].first_index,\n                    s.tail[b].codes,s.tail[b].count,b+1u==s.tail_count,d->mode==3u?2u:0u)',
                       'mt_sample_queue_push(&d->queue,s.tail[b].first_index,\n                    s.tail[b].codes,s.tail[b].count,b+1u==s.tail_count)')
        need(tokens(text)==tokens(fn(old,'terminate')),'Stop guards changed beyond canonical queue ingress')
        text=fn(core,'completed')
        text=once(text,'(d->tx_nonce!=d->pending_nonce || d->tx_revision!=d->pending_revision || d->tx_mode!=d->pending_mode)','d->tx_nonce!=d->pending_nonce')
        need(tokens(text)==tokens(fn(old,'completed')),'Completed CRC/pop guards changed beyond HELLO identity')
        adc=read(image/'patched/v2/platform/adc_timer_dma.c');oa=read(base/'patched/v2/platform/adc_timer_dma.c')
        for n in ('start','mt_adc_dma_read_block'):
            text=fn(adc,n).replace('d->profile->block_deadline_us','MT_ADC_DMA_BLOCK_US').replace('d->profile->start_bracket_max_us','MT_ADC_DMA_SAMPLE_US')
            text=text.replace('d->profile->rate_hz','MT_ADC_DMA_RATE_HZ')
            text=text.replace('d->profile->period_num_us,d->profile->period_den','MT_ADC_DMA_SAMPLE_US')
            need(tokens(text)==tokens(fn(oa,n)),'ADC ownership/TIME guard changed beyond profile constants '+n)
            proofs.append({'function':n,'method':'token-identical after selected descriptor constants/rational metadata'})
        proof={'status':'PASS','unchanged_SB_patched_sources':unchanged,'core_ADC_guard_proofs':proofs,
               'runtime_H_turnover_byte_identical':True,'TIME_backend_byte_identical':True,
               'DCD_FIFO_USB_byte_identical':True,'no_WCET_or_hardware_claim':True}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        sources=[]
        for area,names in {
            'platform':['adc_timer_dma.c','adc_timer_dma.h','mt_timebase.c','mt_timebase.h','mt_stream_diag.h'],
            'protocol':['mt_live_device.c','mt_live_device.h','mt_wire.c','mt_wire.h','mt_v2_crc32.h'],
            'acquisition':['mt_sample_queue.c','mt_sample_queue.h','mt_acquisition_profile.c','mt_acquisition_profile.h']}.items():
            (out/area).mkdir()
            for name in names:
                p=image/'patched/v2'/area/name
                if not p.exists():p=image/'source/firmware'/area/name
                text=read(p);need(ri['inputs_before'].get(str(p))==sha(p),'Image source pin differs')
                (out/area/name).write_text(text,encoding='utf8',newline='\n')
                if name.endswith('.c'):sources.append(area+'/'+name)
        runtime=read(image/'patched/v2/app/mt_live_runtime.c')
        bodies='\n'.join(fn(runtime,n) for n in ('adc_read','adc_write','commit_allowed','commit_timed','commit_timer'))
        scaffold=read(Path(__file__).with_name('cen_transaction_model.c'))
        scaffold=scaffold[:scaffold.index('int main(void)')].replace('/* BODIES */',bodies)
        model=read(Path(__file__).with_name('selectable_profiles_model.c'))
        (out/'model.c').write_text(scaffold+'\n'+model,encoding='utf8',newline='\n')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).strip()
        run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter',
            '-I.','-Iplatform','-Iprotocol','-Iacquisition','model.c',*sources,'-o','model.exe'])
        stdout=run('model',[out/'model.exe',out/'packed-tail-transcript.bin'])
        result.update(status='PASS',compiler_version=version,stdout=stdout,
            image_bin_sha256=ri['artifacts']['MotortesterV2-stream-candidate.bin'],
            source_equivalence_sha256=sha(out/'source-equivalence.json'),
            synthetic_packed_tail_wire_sha256=sha(out/'packed-tail-transcript.bin'),
            not_verified=['Target CPU/IRQ timing','Physical150k stream/ADC/DMA/USB','Analog input/settling','Flash approval'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,v in inputs.items() if not Path(p).is_file() or sha(Path(p))!=v];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
