"""Exact S4 runtime schedule plus pinned S7 guards; narrow logical native order."""
import argparse, hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode or sys.flags.optimize:
        raise ValueError('Run python -I -B without optimization')
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('image','baseline','previous','zig','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    image=args.image.resolve();previous=args.previous.resolve();baseline=args.baseline.resolve()
    out=args.output.resolve();zig=args.zig.resolve(strict=True)
    if out.exists() or not out.is_relative_to(root/'build'):raise ValueError('Use a new build output')
    out.mkdir();inputs={};commands=[]
    def read(path):inputs[str(path)]=sha(path);return path.read_text('utf8')
    self_path=Path(__file__).resolve();read(self_path);inputs[str(zig)]=sha(zig)
    receipts={name:json.loads(read(folder/'receipt.json')) for name,folder in
              [('candidate',image),('previous',previous),('baseline',baseline)]}
    for receipt in receipts.values():
        if receipt['status']!='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE':raise ValueError('Unfinished image')
    if receipts['candidate']['config']['firmware_build']!=0x56325338:raise ValueError('Expected S8')
    if receipts['candidate']['archive_sha256']!=receipts['previous']['archive_sha256']:
        raise ValueError('Changed upstream archive')
    helper_path=self_path.with_name('check_usb_gate.py');read(helper_path)
    spec=importlib.util.spec_from_file_location('extract_schedule',helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    runtime_path=Path('patched/v2/app/mt_live_runtime.c')
    current=read(image/runtime_path);old=read(previous/runtime_path);s4=read(baseline/runtime_path)
    if 'adc_checkpoint' in current:raise ValueError('Additional ADC opportunity remains')
    if helper.function(current,'step')!=helper.function(s4,'step'):raise ValueError('Step differs from exact S4')
    names=('adc_read','adc_write','adc_time','live_time','stable','usable','commit_enter','commit_leave',
           'commit_allowed','commit_timed','commit_timer','live_start','live_stop','live_isolate',
           'prepare_adc','mt_live_runtime_init','quiescent','loss_result','synchronize_loss',
           'time_fault','mt_live_runtime_step')
    equivalence=[]
    for name in names:
        body=helper.function(current,name)
        if body!=helper.function(old,name) or body!=helper.function(s4,name):raise ValueError('Changed guard '+name)
        equivalence.append(dict(function=name,sha256=hashlib.sha256(body.encode()).hexdigest()))
    if helper.function(current,'live_write')!=helper.function(old,'live_write'):
        raise ValueError('Changed whole-fit admission')
    unchanged=[]
    for path in sorted((previous/'patched').rglob('*')):
        if not path.is_file() or path.relative_to(previous)==runtime_path:continue
        target=image/path.relative_to(previous);read(path);read(target)
        if sha(path)!=sha(target):raise ValueError('Changed S7 patched source '+str(path))
        unchanged.append(dict(path=path.relative_to(previous).as_posix(),sha256=sha(target)))
    for tag,folder in [('candidate',image),('previous',previous),('baseline',baseline)]:
        receipt=receipts[tag]
        for path,digest in list(inputs.items()):
            p=Path(path)
            # Unused copied legacy headers do not enter the compiler receipt;
            # their old/new equality is recorded above, not called a compiler pin.
            if p.is_relative_to(folder) and p!=folder/'receipt.json' and path in receipt['inputs_before'] and receipt['inputs_before'][path]!=digest:
                raise ValueError('Source not pinned by image receipt '+path)
    # Actual headers/types, with deliberately small USB declaration-only seams.
    for path in (image/'patched/v2').rglob('*.h'):
        target=out/path.relative_to(image/'patched/v2');target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(read(path),encoding='utf8',newline='\n')
    for relative in ('platform/mt_timebase.h','platform/mt_stream_diag.h','transport/mt_usb_epoch.h'):
        path=image/'source/firmware'/relative
        target=out/relative;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(read(path),encoding='utf8',newline='\n')
    epoch_source=image/'source/firmware/transport/mt_usb_epoch.c'
    (out/'transport/mt_usb_epoch.c').write_text(read(epoch_source),encoding='utf8',newline='\n')
    (out/'device').mkdir()
    (out/'device/dcd.h').write_text('#include "tusb.h"\n',encoding='ascii')
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
    body_names=('stable','usable','quiescent','loss_result','synchronize_loss','time_fault',
                'live_write','step','mt_live_runtime_step')
    model=read(self_path.with_name('schedule_s4_model.c'))
    (out/'model.c').write_text(model.replace('/* BODIES */','\n'.join(helper.function(current,n) for n in body_names)),encoding='utf8',newline='\n')
    (out/'temp').mkdir()
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
    def run(name,argv):
        process=subprocess.run([str(a) for a in argv],cwd=out,env=env,capture_output=True,timeout=180)
        (out/(name+'.stdout')).write_bytes(process.stdout);(out/(name+'.stderr')).write_bytes(process.stderr)
        commands.append(dict(name=name,argv=[str(a) for a in argv],exit_code=process.returncode))
        if process.returncode:raise ValueError(name+' failed; retained')
        return process.stdout.decode('utf8')
    version=run('version',[zig,'version']).strip()
    run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function',
        '-I.','-Itransport','-DCFG_MT_STREAM_DIAGNOSTICS=0','model.c','transport/mt_usb_epoch.c','-o','model.exe'])
    stdout=run('model',[out/'model.exe'])
    for path,digest in inputs.items():
        if sha(Path(path))!=digest:raise ValueError('Input drift '+path)
    result=dict(status='PASS',scope=__doc__,image_bin_sha256=receipts['candidate']['artifacts']['MotortesterV2-stream-candidate.bin'],
        exact_S4_step=True,unchanged_runtime_functions=equivalence,unchanged_S7_patched_sources=unchanged,
        unchanged_whole_fit_sha256=hashlib.sha256(helper.function(current,'live_write').encode()).hexdigest(),
        upstream_archive_sha256=receipts['candidate']['archive_sha256'],inputs=inputs,commands=commands,
        compiler_version=version,stdout=stdout,
        limitations=['ADC/USB/core callbacks are logical boundary seams; only runtime order and actual epoch metadata functions execute.',
          'No physical DMA/USB/CPU timing, frequency accuracy, throughput, Stop hardware barrier or flash admission established.',
          'Unchanged ADC/core/whole-fit/USB models are not rerun; exact source pins retain previous logical evidence and physical failures.'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(status='PASS',stdout=stdout,result=str(out/'result.json'))))

if __name__=='__main__':main()
