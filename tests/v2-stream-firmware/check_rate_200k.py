"""Narrow exact-source 200 kS/s DMA/adapter/core model; no hardware timing claim."""
import argparse, hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('Run python -I -B')
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('image','zig','output'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--bulk',action='store_true',help='Also check V2S6 bulk offer and exact live_write wrapper')
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
    model=base+'\n'+read(Path(__file__).with_name('rate_200k_model.c'))
    (out/'model.c').write_text(model,encoding='utf8',newline='\n')
    sources=[]
    if a.bulk:
        text=read(Path(__file__).with_name('bulk_write_model.c')).replace('/* LIVE_WRITE */',helper.function(runtime,'live_write'))
        (out/'bulk_write_model.c').write_text(text,encoding='utf8',newline='\n')
        sources.append('bulk_write_model.c')
        vendor=image/'source/firmware/third_party/usb/vendor/tinyusb/src'
        stream=read(vendor/'tusb.c')
        bodies='\n'.join(helper.function(stream,n) for n in ('tu_edpt_stream_write_zlp_if_needed','tu_edpt_stream_write_xfer','tu_edpt_stream_write'))
        text=read(Path(__file__).with_name('usb_fifo_model.c')).replace('/* STREAM_WRITE */',bodies)
        (out/'usb_fifo_model.c').write_text(text,encoding='utf8',newline='\n');sources.append('usb_fifo_model.c')
        for area in ('common','osal'):
            (out/area).mkdir()
            for path in (vendor/area).glob('*.h'):
                (out/area/path.name).write_text(read(path),encoding='utf8',newline='\n')
        for relative in ('tusb_option.h','common/tusb_fifo.c'):
            (out/relative).write_text(read(vendor/relative),encoding='utf8',newline='\n')
        sources.append('common/tusb_fifo.c')
        (out/'tusb_config.h').write_text('#define CFG_TUSB_MCU OPT_MCU_NONE\n#define CFG_TUSB_OS OPT_OS_NONE\n#define CFG_TUD_ENABLED 0\n#define CFG_TUH_ENABLED 0\n#define CFG_TUSB_DEBUG 0\n',encoding='ascii')
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
    flags=['-DMT_TEST_BULK_OFFER=1','-DMT_TEST_FIRMWARE_BUILD='+str(receipt['config']['firmware_build'])] if a.bulk else []
    run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter',*flags,
        '-I.','-Iplatform','-Iapp','-Iprotocol','-Iacquisition','model.c',*sources,'-o','model.exe'])
    stdout=run('model',[out/'model.exe'])
    if any(sha(Path(path))!=digest for path,digest in inputs.items()): raise ValueError('Input drift')
    result=dict(status='PASS',scope=__doc__,image_bin_sha256=receipt['artifacts']['MotortesterV2-stream-candidate.bin'],
        inputs=inputs,commands=commands,compiler_version=version,stdout=stdout,
        not_verified=['ARM execution time','USB PHY/host throughput','Physical sample fidelity','ADC settling or analogue input','Flash approval'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status='PASS',stdout=stdout,result=str(out/'result.json'))))

if __name__=='__main__':main()
