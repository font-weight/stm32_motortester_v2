"""Narrow exact-source 100 kS/s DMA/whole-fit/core model; no hardware timing claim."""
import argparse, hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('Run python -I -B')
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('image','zig','output'): p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args(); root=Path(__file__).resolve().parents[2]
    image=a.image.resolve(); out=a.output.resolve(); zig=a.zig.resolve(strict=True)
    if out.exists() or not out.is_relative_to(root/'build'): raise ValueError('Use a new build output')
    out.mkdir(); inputs={str(Path(__file__).resolve()):sha(Path(__file__)),str(zig):sha(zig)}
    def read(path):
        inputs[str(path)]=sha(path); return path.read_text('utf8')
    receipt=json.loads(read(image/'receipt.json'))
    if receipt['status']!='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE': raise ValueError('Unfinished image')
    helper_path=Path(__file__).with_name('check_usb_gate.py'); read(helper_path)
    spec=importlib.util.spec_from_file_location('extract_rate',helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    runtime=read(image/'patched/v2/app/mt_live_runtime.c')
    bodies='\n'.join(helper.function(runtime,n) for n in ('adc_read','adc_write','commit_allowed','commit_timed','commit_timer'))
    base=read(Path(__file__).with_name('cen_transaction_model.c')).replace('/* BODIES */',bodies)
    base=base.replace('int main(void)', 'int cen_regression_main(void)')
    model=base+'\n'+read(Path(__file__).with_name('rate_100k_model.c'))
    (out/'model.c').write_text(model,encoding='utf8',newline='\n')
    sources=[]
    text=read(Path(__file__).with_name('whole_fit_write_model.c')).replace('/* LIVE_WRITE */',helper.function(runtime,'live_write'))
    (out/'whole_fit_write_model.c').write_text(text,encoding='utf8',newline='\n')
    sources.append('whole_fit_write_model.c')
    for area,names in {
      'platform':['adc_timer_dma.c','adc_timer_dma.h','mt_timebase.c','mt_timebase.h','mt_stream_diag.h'],
      'app':['mt_live_adc.c','mt_live_adc.h'],
      'protocol':['mt_live_device.c','mt_live_device.h','mt_wire.c','mt_wire.h','mt_v2_crc32.h'],
      'acquisition':['mt_sample_queue.c','mt_sample_queue.h']}.items():
        (out/area).mkdir()
        for name in names:
            source=image/'patched/v2'/area/name
            if not source.exists(): source=image/'source/firmware'/area/name
            text=read(source)
            if receipt['inputs_before'].get(str(source))!=sha(source): raise ValueError('Image source drift')
            (out/area/name).write_text(text,encoding='utf8',newline='\n')
            if name.endswith('.c'): sources.append(area+'/'+name)
    (out/'temp').mkdir()
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
    commands=[]
    def run(name,argv):
        r=subprocess.run([str(x) for x in argv],cwd=out,env=env,capture_output=True,timeout=180)
        (out/(name+'.stdout')).write_bytes(r.stdout);(out/(name+'.stderr')).write_bytes(r.stderr)
        commands.append(dict(name=name,argv=[str(x) for x in argv],exit_code=r.returncode))
        if r.returncode: raise ValueError(name+' failed; evidence retained')
        return r.stdout.decode()
    version=run('version',[zig,'version']).strip()
    flags=['-DMT_TEST_FIRMWARE_BUILD='+str(receipt['config']['firmware_build'])]
    run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter',*flags,
        '-I.','-Iplatform','-Iapp','-Iprotocol','-Iacquisition','model.c',*sources,'-o','model.exe'])
    stdout=run('model',[out/'model.exe'])
    for path,digest in inputs.items():
        if sha(Path(path))!=digest: raise ValueError('Input drift')
        if Path(path).is_relative_to(image) and Path(path)!=image/'receipt.json':
            if receipt['inputs_before'].get(path)!=digest: raise ValueError('Receipt source mismatch')
    result=dict(status='PASS',scope=__doc__,image_bin_sha256=receipt['artifacts']['MotortesterV2-stream-candidate.bin'],
        inputs=inputs,commands=commands,compiler_version=version,stdout=stdout,
        not_verified=['ARM execution time','USB PHY/host throughput','Physical sample fidelity','ADC settling or analogue input','Flash approval'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status='PASS',stdout=stdout,result=str(out/'result.json'))))

if __name__=='__main__':main()
