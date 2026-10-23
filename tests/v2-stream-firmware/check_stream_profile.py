"""Narrow actual S9 profiler and transparent S8 guard/source equivalence; no hardware."""
import argparse,hashlib,importlib.util,json,os,re,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def unwrap_guards(text):
    needle='mt_profile_guard('
    while needle in text:
        start=text.index(needle);pos=start+len(needle);level=1;comma=None
        while level:
            c=text[pos]
            if c=='(':level+=1
            elif c==')':level-=1
            elif c==',' and level==1:comma=pos
            pos+=1
        if comma is None:raise ValueError('Guard call geometry')
        term=text[comma+1:pos-1]
        if term=='mt_tx_burst_left!=0u':term='mt_tx_burst_left'
        text=text[:start]+term+text[pos:]
    return text
def normalized(text):
    text=re.sub(r'(?ms)^[ \t]*/\* MT_PROFILE_BEGIN \*/\n.*?^[ \t]*/\* MT_PROFILE_END \*/\n','',text)
    for new,old in {
        'mt_profiled_live_start_body':'live_start','mt_profiled_live_write_body':'live_write',
        'mt_profiled_runtime_init_body':'mt_live_runtime_init','mt_profiled_runtime_step_body':'mt_live_runtime_step',
        'mt_profiled_timebase_update_body':'mt_timebase_update','mt_profiled_dcd_int_handler_body':'dcd_int_handler',
        'mt_profiled_edpt_xfer_fifo_body':'dcd_edpt_xfer_fifo'}.items():text=text.replace(new,old)
    return unwrap_guards(text)
def tokens(text):
    pattern=r'''//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_]\w*|[0-9][A-Za-z0-9_.]*|<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|->|[^\s]'''
    return [t for t in re.findall(pattern,text,re.S) if not t.startswith(('//','/*'))]

def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.flags.optimize:raise ValueError('Run -I -B')
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):parser.add_argument('--'+n,type=Path,required=True)
    a=parser.parse_args();root=Path(__file__).resolve().parents[2];out=a.output.resolve()
    image=a.image.resolve();base=a.baseline.resolve();zig=a.zig.resolve(strict=True)
    if out.exists() or not out.is_relative_to(root/'build'):raise ValueError('New build output required')
    out.mkdir();inputs={};commands=[]
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf8')
    read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
    receipt=json.loads(read(image/'receipt.json'));previous=json.loads(read(base/'receipt.json'))
    if receipt['status']!='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' or receipt['config']['firmware_build']!=0x56325339:
        raise ValueError('Expected completed S9')
    if receipt['archive_sha256']!=previous['archive_sha256']:raise ValueError('Changed upstream archive')
    proof=[]
    pairs=[('patched/v2/app/mt_live_runtime.c','patched/v2/app/mt_live_runtime.c'),
           ('patched/v2/protocol/mt_live_device.c','patched/v2/protocol/mt_live_device.c'),
           ('patched/v2/platform/adc_timer_dma.c','patched/v2/platform/adc_timer_dma.c'),
           ('source/firmware/platform/mt_timebase.c','patched/v2/platform/mt_timebase.c'),
           ('patched/dcd_stm32_fsdev.c','patched/dcd_stm32_fsdev.c')]
    for old,new in pairs:
        before=read(base/old);after=read(image/new);clean=normalized(after)
        (out/(Path(new).name+'.normalized')).write_text(clean,encoding='utf8',newline='\n')
        if tokens(before)!=tokens(clean):raise ValueError('Working source/guard drift '+new)
        proof.append(dict(baseline=old,candidate=new,baseline_sha256=sha(base/old),candidate_sha256=sha(image/new),
                          normalized_C_tokens_sha256=hashlib.sha256(json.dumps(tokens(clean)).encode()).hexdigest()))
    oldcfg=previous['config'];newcfg=receipt['config']
    for key in oldcfg:
        if key=='firmware_build':continue
        if key=='usb':
            if {k:v for k,v in oldcfg[key].items() if k!='product'}!={k:v for k,v in newcfg[key].items() if k!='product'}:
                raise ValueError('Changed USB setup')
        elif oldcfg[key]!=newcfg[key]:raise ValueError('Changed config '+key)
    helper_path=Path(__file__).with_name('check_usb_gate.py');read(helper_path)
    spec=importlib.util.spec_from_file_location('extract_profile',helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    runtime=(image/'patched/v2/app/mt_live_runtime.c').read_text('utf8')
    core=(image/'patched/v2/protocol/mt_live_device.c').read_text('utf8')
    driver=(image/'patched/v2/platform/adc_timer_dma.c').read_text('utf8')
    def ordered(source,name,needles):
        body=helper.function(source,name);positions=[body.index(n) for n in needles]
        if positions!=sorted(positions) or len(set(positions))!=len(positions):raise ValueError('Wrong close order '+name)
        return dict(function=name,ordered=needles)
    close_order=[
        ordered(driver,'fail',['invalidate_history','mt_profile_close(MT_P_CLOSE_ADC','quiesce(d)']),
        ordered(core,'mt_live_device_offer',['mt_sample_queue_push','mt_profile_close(MT_P_CLOSE_FAULT','terminate(d']),
        ordered(core,'mt_live_device_fault',['if(!d || reason==0u','cause(d,reason)','mt_profile_close(MT_P_CLOSE_FAULT','if(!now(d']),
        ordered(core,'mt_live_device_transport_lost',['if(!d)return','mt_profile_close(MT_P_CLOSE_TRANSPORT','raw_barrier(d)']),
        ordered(core,'terminate',['mt_profile_close','cause(d,reason)','d->io.quiesce']),
        ordered(core,'recover',['mt_profile_close','local_cause','raw_barrier']),
        ordered(runtime,'live_start',['mt_profiled_live_start_body','mt_profile_attempt','mt_profile_begin']),
        ordered(runtime,'time_fault',['mt_profile_close','r->clock_fault=1','mt_live_device_transport_lost'])]
    unchanged=[];changed={Path(p[1]) for p in pairs}
    for p in sorted((base/'patched').rglob('*')):
        if not p.is_file() or p.relative_to(base) in changed:continue
        target=image/p.relative_to(base);read(p);read(target)
        if sha(p)!=sha(target):raise ValueError('Unchanged source drift '+str(target))
        unchanged.append(dict(path=p.relative_to(base).as_posix(),sha256=sha(target)))
    result=dict(status='SOURCE_EQUIVALENT_PENDING_NATIVE',source_equivalence=proof,close_order=close_order,
                unchanged_S8_patched_sources=unchanged,
                boolean_coercion='Only USB burst-left argument is explicitly !=0u before condition observer; truth preserved.',
                limit='Observer instructions necessarily alter execution time; token equivalence does not prove physical behavior/timing.')
    (out/'source-equivalence.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    for area in ('platform','protocol','acquisition'):(out/area).mkdir()
    for area,names in {'platform':['mt_stream_profile.c','mt_stream_profile.h','adc_timer_dma.h'],
                       'protocol':['mt_live_device.h','mt_wire.h'],
                       'acquisition':['mt_sample_queue.h']}.items():
        for name in names:
            path=image/'patched/v2'/area/name
            if not path.exists():path=image/'source/firmware'/area/name
            text=read(path)
            if receipt['inputs_before'].get(str(path))!=sha(path):raise ValueError('Unpinned profiler dependency '+name)
            (out/area/name).write_text(text,encoding='utf8',newline='\n')
    model=Path(__file__).with_name('stream_profile_model.c')
    (out/'model.c').write_text(read(model),encoding='utf8',newline='\n')
    (out/'temp').mkdir()
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
    def run(name,argv):
        p=subprocess.run([str(v) for v in argv],cwd=out,env=env,capture_output=True,timeout=180)
        (out/(name+'.stdout')).write_bytes(p.stdout);(out/(name+'.stderr')).write_bytes(p.stderr)
        commands.append(dict(name=name,argv=[str(v) for v in argv],exit_code=p.returncode))
        if p.returncode:raise ValueError(name+' failed; evidence retained')
        return p.stdout.decode('utf8')
    version=run('version',[zig,'version']).strip()
    run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-DMT_PROFILE_NATIVE=1',
          '-Iplatform','-Iprotocol','-Iacquisition','model.c','platform/mt_stream_profile.c','-o','model.exe'])
    stdout=run('model',[out/'model.exe'])
    for p,digest in inputs.items():
        if sha(Path(p))!=digest:raise ValueError('Input drift '+p)
    result.update(status='PASS',scope=__doc__,image_bin_sha256=receipt['artifacts']['MotortesterV2-stream-candidate.bin'],
                  compiler_version=version,stdout=stdout,inputs=inputs,commands=commands,
                  not_verified=['Physical ADC/USB timing/throughput','Analogue accuracy','Overhead upper bound','Flash admission'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status='PASS',stdout=stdout,result=str(out/'result.json'))))
if __name__=='__main__':main()
