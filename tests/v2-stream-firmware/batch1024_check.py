"""One isolated serializer model and ARM object/stack census; no firmware image or hardware."""
import argparse,hashlib,json,os,re,subprocess,sys,zlib
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,message):
    if not ok:raise ValueError(message)

def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    root=Path(__file__).resolve().parents[2];out=a.output.resolve()
    need(out.is_relative_to(root/'build') and not out.exists(),'Use a new build output');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def pin(p):inputs[str(p)]=sha(p)
    def copy(source,target):pin(source);(out/target).write_bytes(source.read_bytes())
    def run(label,argv):
        row={'label':label,'argv':[str(x) for x in argv]};commands.append(row)
        process=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180)
        row['exit_code']=process.returncode
        (out/(label+'.stdout')).write_bytes(process.stdout);(out/(label+'.stderr')).write_bytes(process.stderr)
        need(process.returncode==0,label+' failed; original output retained')
        return process.stdout.decode('utf8')
    try:
        pin(Path(__file__).resolve())
        base=root/'build/v6k-fw-01';receipt=base/'receipt.json';pin(receipt)
        original=json.loads(receipt.read_text('utf8'))
        need(original['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE' and original['config']['firmware_build']==0x56325344,'Wrong immutable SD basis')
        production={str(p):sha(p) for p in (root/'firmware/v2-stream').rglob('*') if p.is_file() and 'batch1024' not in p.parts}
        copy(root/'firmware/v2-stream/batch1024/mt_batch1024.c','mt_batch1024.c')
        copy(root/'firmware/v2-stream/batch1024/mt_batch1024.h','mt_batch1024.h')
        copy(Path(__file__).with_name('batch1024_model.c'),'model.c')
        for name in ('mt_wire.c','mt_wire.h','mt_v2_crc32.h'):
            p=base/'patched/v2/protocol'/name
            if not p.exists():p=base/'source/firmware/protocol'/name
            need(original['inputs_before'].get(str(p))==sha(p),'SD source drift')
            copy(p,name)
        zig=root/'build/v5-native-toolchain/zig-x86_64-windows-0.15.2/zig.exe';pin(zig)
        arm=Path(next(r for r in original['commands'] if r['label']=='compile-24-mt_live_device')['argv'][0]);pin(arm)
        (out/'temp').mkdir()
        env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        run('native-compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-I.',
            'model.c','mt_batch1024.c','mt_wire.c','-o','model.exe'])
        stdout=run('native-model',[out/'model.exe',out/'batch1153-transcript.bin'])
        run('arm-object',[arm,'-std=c11','-mcpu=cortex-m3','-mthumb','-mfloat-abi=soft','-ffreestanding',
            '-fno-common','-fno-short-enums','-fstack-usage','-Os','-Wall','-Wextra','-Wpedantic',
            '-Wconversion','-Wsign-conversion','-Werror','-pedantic-errors','-fno-unwind-tables',
            '-fno-asynchronous-unwind-tables','-fno-stack-protector','-fno-lto','-I.','-c','mt_batch1024.c','-o','batch1024.o'])
        size_tool=arm.with_name('arm-none-eabi-size.exe');pin(size_tool)
        object_size=run('arm-size',[size_tool,'batch1024.o']).strip()
        usage=(out/'batch1024.su').read_text('utf8');rows=[]
        for line in usage.splitlines():
            label,amount,kind=line.rsplit('\t',2);rows.append({'function':label.rsplit(':',1)[-1],'bytes':int(amount),'kind':kind})
        need(rows and all(row['kind']=='static' for row in rows),'Unexpected dynamic stack')
        drift=[p for p,value in production.items() if sha(Path(p))!=value]
        need(not drift,'Production firmware outside prototype changed during run')
        codes=[((i*37+3)&4095)&4092 for i in range(1024)]+[(4095-i)&4092 for i in range(129)]
        raw=b''.join(n.to_bytes(2,'little') for n in codes)
        result.update(status='PASS',stdout=stdout,prototype_state_bytes=32,proposed_TX_capacity_bytes=1336,
          memory_calculation={'old_SD_static_plus_stack_reserve':19564,'TX_growth':792,'state_growth':32,
            'proposed_total_with8192reserve':20388,'capacity':20480,'spare':92,'exact_integrated_map_proved':False},
          arm_object_size_output=object_size,arm_function_stack=rows,
          arm_stack_note='Per-function isolated module object only, not a linked runtime/IRQ/callback bound.',
          arm_object_sha256=sha(out/'batch1024.o'),arm_stack_usage_sha256=sha(out/'batch1024.su'),
          native_model_exe_sha256=sha(out/'model.exe'),production_outside_prototype_drift=drift,
          fixture={'path':str(out/'batch1153-transcript.bin'),'sha256':sha(out/'batch1153-transcript.bin'),
            'format':'bareCOBS DATA1024 seq4/index0, DATA129 seq5/index1024, synthetic END seq6/prefix1153',
            'nonce':503,'generation':3,'mode':5,'config_id':5,'protocol_revision':'0.3',
            'canonical_u16le_sha256':hashlib.sha256(raw).hexdigest(),'canonical_END_crc32':zlib.crc32(raw),
            'raw_formula':'first1024=((i*37+3)&4095)&4092; final129=(4095-i)&4092',
            'producer_scope':'Actual isolated serializer + existing generic C END encoder; not production core/runtime.'},
          not_confirmed=['Runtime ownership/Stop/HELLO/epoch integration','ADC/USB schedule/deadline/throughput','Final ARM SRAM/stack/link','Flash admission'])
    except BaseException as e:
        result.update(status='FAIL',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,value in inputs.items() if not Path(p).is_file() or sha(Path(p))!=value]
        result['input_drift']=drift
        if drift:result['status']='FAIL_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))

if __name__=='__main__':main()
