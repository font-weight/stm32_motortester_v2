"""One SK actual gate/progress transition, extracted-DCD and read-order check; no hardware."""
import argparse,hashlib,importlib.util,json,os,re,struct,subprocess,sys
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(x,m):
    if not x:raise ValueError(m)
def tokens(s):return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))
def once(s,a,b):need(s.count(a)==1,'Exact normalization '+a[:90]);return s.replace(a,b)
def load(p,n):
    sp=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,'Run python -I -B')
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('image','baseline','zig','output'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args();root=Path(__file__).resolve().parents[2]
    image,base,zig,out=a.image.resolve(),a.baseline.resolve(),a.zig.resolve(strict=True),a.output.resolve()
    need(not out.exists() and out.is_relative_to(root/'build'),'New output only; failures retained');out.mkdir()
    inputs={};commands=[];result={'status':'RUNNING','scope':__doc__,'inputs':inputs,'commands':commands}
    def read(p):inputs[str(p)]=sha(p);return p.read_text('utf8')
    def copy(p,rel):
        q=out/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(read(p),encoding='utf8',newline='\n')
    def run(label,argv):
        row={'label':label,'argv':[str(x) for x in argv]};commands.append(row)
        q=subprocess.run(row['argv'],cwd=out,env=env,capture_output=True,timeout=180);row['exit_code']=q.returncode
        (out/(label+'.stdout')).write_bytes(q.stdout);(out/(label+'.stderr')).write_bytes(q.stderr)
        need(q.returncode==0,label+' failed; retained');return q.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve());inputs[str(zig)]=sha(zig)
        ri=json.loads(read(image/'receipt.json'));rb=json.loads(read(base/'receipt.json'))
        need(ri['status']==rb['status']=='BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE','Unfinished image')
        build=ri['config']['firmware_build'];need(build==0x5632534b and rb['config']['firmware_build']==0x5632534a,'Wrong SK/SJ')
        expected=json.loads(json.dumps(rb['config']));expected['firmware_build']=build;expected['usb']['product']='Motortester V2 USB Gate SK'
        need(ri['config']==expected,'Unexpected config change')
        ext=Path(__file__).with_name('check_usb_gate.py');read(ext);fn=load(ext,'r_extract').function
        s=read(image/'patched/dcd_stm32_fsdev.c');old=read(base/'patched/dcd_stm32_fsdev.c');norm=s
        for name in ('mt_gate_time','mt_gate_continue'):norm=once(norm,fn(norm,name),'')
        norm=once(norm,fn(norm,'mt_tx_burst_time_ok'),fn(old,'mt_tx_burst_time_ok'))
        for line in ('#include "mt_usb_gate.h" /* R_GATE_INCLUDE */\n','bool mt_usb_fsdev_lifecycle_pending(void); /* R_GATE_PROTO */\n',
            '  mt_gate_invalidate(0u); /* R_GATE_GRANT: old reason becomes historical. */\n',
            '  mt_gate_invalidate(0u); /* R_GATE_ISR_ENTRY */\n',
            '  if(int_status&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP))\n    mt_gate_invalidate(1u); /* R_GATE_LIFECYCLE */\n',
            '  bool gate_seen=false,gate_meta=false;\n  unsigned gate_total=UINT16_MAX,gate_queued=UINT16_MAX;\n  unsigned gate_initial=MT_G_HOLD_OTHER,gate_decision=0u,gate_age=UINT32_MAX;\n',
            '      gate_decision=MT_G_RESUMED; /* R_GATE_RESUME */\n',
            '    if(gate_seen)mt_gate_note(gate_decision,gate_total,gate_queued,\n        mt_tx_burst_left,gate_age,gate_meta); /* R_GATE_NOTE */\n'):
            norm=once(norm,line,'')
        norm=once(norm,'''  if (FSDEV_REG->CNTR & (U_CNTR_FRES | U_CNTR_PDWN)) {
    mt_gate_invalidate(1u); /* R_GATE_FRES */
    return false;
  }''','  if (FSDEV_REG->CNTR & (U_CNTR_FRES | U_CNTR_PDWN)) return false;')
        blocks=re.findall(r'      /\* R_GATE_BEGIN:.*?/\* R_GATE_END \*/\n',norm,re.S)
        need(len(blocks)==2,'Metadata blocks count')
        for block in blocks:norm=once(norm,block,'')
        old_expr='''mt_continue_tx && mt_tx_burst_left &&
        !(int_status&(U_ISTR_RESET|U_ISTR_PMAOVR|U_ISTR_SUSP|U_ISTR_WKUP|U_ISTR_ERR)) &&
        !(FSDEV_REG->ISTR&(U_ISTR_DIR|U_ISTR_ERR)) &&
        !mt_usb_fsdev_lifecycle_pending() && mt_tx_burst_time_ok() &&
        !(FSDEV_REG->CNTR&(U_CNTR_FRES|U_CNTR_PDWN|U_CNTR_FSUSP)) &&
        (FSDEV_REG->DADDR&U_DADDR_EF)'''
        need(old.count(old_expr)==1,'Frozen SJ condition differs')
        norm=once(norm,'mt_gate_continue(&gate_decision,&gate_age,gate_initial,\n                        mt_continue_tx,mt_tx_burst_left,int_status)',old_expr)
        line='  if(ep_addr==0x82u)mt_gate_invalidate(1u); /* R_GATE_CANCEL */\n';need(norm.count(line)==2,'Endpoint cancel count');norm=norm.replace(line,'')
        norm=once(norm,'  mt_gate_invalidate(1u); /* R_GATE_CANCEL */\n','')
        line='  mt_gate_submit_begin(ep_addr); /* R_GATE_SUBMIT_BEGIN */\n';need(norm.count(line)==2,'Submit begin count');norm=norm.replace(line,'')
        tail='''  const bool gate_ok=edpt_xfer(rhport, ep_num, dir);
  mt_gate_submit_done(ep_addr,gate_ok,total_bytes,xfer->queued_len,
      xfer->max_packet_size,(xfer->buffer?1u:0u)|(xfer->ff?2u:0u),is_isr);
  return gate_ok; /* R_GATE_SUBMIT_DONE */'''
        need(norm.count(tail)==2,'Submit done count');norm=norm.replace(tail,'  return edpt_xfer(rhport, ep_num, dir);')
        need(tokens(norm)==tokens(old),'Working DCD changed beyond stated observer/timer exposure')
        # Exact field/order expression independently strips only annotation wrappers.
        expr=fn(s,'mt_gate_continue').split('return ',1)[1].rsplit(';',1)[0]
        def strip(expr):
            while 'mt_gate_condition(' in expr:
                start=expr.index('mt_gate_condition(');pos=start+len('mt_gate_condition(');depth=1;args=[];last=pos
                while depth:
                    c=expr[pos]
                    if c=='(':depth+=1
                    if c==')':depth-=1
                    if c==',' and depth==1:args.append(expr[last:pos]);last=pos+1
                    pos+=1
                args.append(expr[last:pos-1]);need(len(args)==3,'Annotation args')
                expr=expr[:start]+args[2]+expr[pos:]
            return expr
        expr=strip(expr).replace('mt_gate_time(decision,age)','mt_tx_burst_time_ok()')
        expr=re.sub(r'\bcan\b','mt_continue_tx',expr);expr=re.sub(r'\bleft\b','mt_tx_burst_left',expr);expr=expr.replace('!=0u','')
        need(tokens(expr)==tokens(old_expr),'Working continuation read/field/order expression differs')
        ready=fn(s,'mt_tx_timer_ready');need(tokens(ready)==tokens(fn(old,'mt_tx_timer_ready')),'Timer-ready reads changed')
        timer=fn(s,'mt_tx_burst_time_ok')
        need('if(!mt_tx_timer_ready())return false;' in timer and timer.index('mt_tx_timer_ready()')<timer.index('mt_tx_timer_read(0x40000024u)')<timer.index('return *age<500u'),'CNT exposure/order changed')
        n=read(image/'patched/v2/platform/mt_stream_progress.c');on=read(base/'patched/v2/platform/mt_stream_progress.c')
        nn=n
        for line in ('#include "mt_usb_gate.h" /* R_GATE_INCLUDE */\n','    mt_gate_begin(); /* R_GATE_INIT: before N ACTIVE, ISR hooks still forbidden. */\n','    mt_gate_freeze(); /* R_GATE_FREEZE: even if app_enter below refuses. */\n'):nn=once(nn,line,'')
        need(tokens(nn)==tokens(on),'N64 changed beyond init/freeze hooks')
        need(fn(n,'mt_progress_begin').index('mt_gate_begin()')<fn(n,'mt_progress_begin').index('state(MT_N_ACTIVE)'),'Gate initialized after ACTIVE')
        snap=fn(n,'snapshot');need(snap.index('mt_usb_bridge_lock()')<snap.index('mt_gate_freeze()')<snap.index('mt_usb_bridge_app_enter'),'Freeze not under outer lock/outside scope')
        unchanged=[]
        for p in sorted((base/'patched').rglob('*')):
            rel=p.relative_to(base/'patched')
            if not p.is_file() or rel.as_posix() in ('dcd_stm32_fsdev.c','v2/platform/mt_stream_progress.c'):continue
            q=image/'patched'/rel;read(q);read(p);need(p.read_bytes()==q.read_bytes(),'Unrelated SJ source changed '+str(rel));unchanged.append({'path':rel.as_posix(),'sha256':sha(q)})
        coretool=image/'source/tests/boot-link/tools/run_boot_link_tests.py';read(coretool);E=load(coretool,'gate_elf').ELF
        elf=E(image/'MotortesterV2-stream-candidate.elf');be=E(base/'MotortesterV2-stream-candidate.elf')
        need(elf.by_name['.data']['size']==be.by_name['.data']['size'] and elf.by_name['.bss']['size']==be.by_name['.bss']['size']+24,'Whole static growth not24')
        need(elf.word(elf.value('mt_board')+12)==build,'Linked SK id mismatch')
        hp=image/'generated/mt_firmware_build.h';read(hp)
        need(f'UINT32_C(0x{build:08x})' in hp.read_text(),'Wrong shared header')
        for dep in ('objects/board.d','objects/29-mt_stream_progress.d','objects/30-mt_usb_gate.d'):
            need('generated/mt_firmware_build.h' in read(image/dep),'Missing common identity '+dep)
        gobj=E(image/'objects/30-mt_usb_gate.o');allocated=[x for x in gobj.sections if x['flags']&2 and x['type']==8]
        need(sum(x['size'] for x in allocated)==24,'Hidden gate BSS/private storage')
        stable=[]
        for p in sorted((base/'objects').glob('*.o')):
            if p.name in ('13-dcd_stm32_fsdev.o','29-mt_stream_progress.o','board.o'):continue
            q=image/'objects'/p.name;need(sha(p)==sha(q),'Unrelated compiled object changed '+p.name);stable.append({'path':q.relative_to(image).as_posix(),'sha256':sha(q)})
        static=json.loads(read(image/'static-bound.json'));f={x['address']:x['name'] for x in static['functions']};seen={a for a,nm in f.items() if nm in ('Reset_Handler','USB_HP_CAN1_TX_IRQHandler','USB_LP_CAN1_RX0_IRQHandler')};todo=list(seen)
        while todo:
            at=todo.pop()
            for edge in static['call_edges']:
                if edge[0]==at and edge[1] not in seen:seen.add(edge[1]);todo.append(edge[1])
        for nm in ('tusb_deinit','tud_deinit','tud_disconnect','dcd_deinit','dcd_disconnect'):need(not any(at in seen for at,name in f.items() if name==nm),'Unguarded disconnect/deinit reachable '+nm)
        proof={'status':'PASS','DCD':'All SJ tokens after exact removal of observer-only boundaries and restoration of exposed timer/continuation','working_MMIO_field_order':'Exact same continuation expression after stripping bool annotations; ready chain identical and same gated single CNT read','metadata_pre_post_source_blocks':blocks,'N64':'All SJ tokens after removing only include/init/freeze; layouts/header unchanged','unchanged_SJ_sources':unchanged,'unchanged_compiled_objects':stable,'static_growth_bytes':24,'gate_only_BSS_bytes':24,'unreachable_unguarded_disconnect_deinit':True,'native_USB_journal_limit':'Native records common USB base access, not individual fields; exact fields/order proven by source expression','not_a_WCET_or_hardware_proof':True}
        (out/'source-equivalence.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
        for p in (image/'patched/v2').rglob('*.h'):copy(p,p.relative_to(image/'patched/v2'))
        for rel in ('platform/mt_stream_diag.h','transport/mt_usb_epoch.h'):copy(image/'source/firmware'/rel,rel)
        for name in ('mt_stream_progress.c','mt_usb_gate.c'):copy(image/'patched/v2/platform'/name,'platform/'+name)
        copy(hp,'generated/mt_firmware_build.h')
        (out/'device').mkdir();(out/'device/dcd.h').write_text('#include "tusb.h"\n',encoding='ascii')
        (out/'tusb.h').write_text('''#ifndef MODEL_TUSB_H
#define MODEL_TUSB_H
#include <stdbool.h>
#include <stdint.h>
typedef struct {unsigned ignored;} dcd_event_t;
typedef struct {unsigned ignored;} tu_fifo_t;
typedef struct {unsigned ignored;} tusb_desc_endpoint_t;
typedef struct {unsigned ignored;} tusb_control_request_t;
uint32_t tud_cdc_n_write_available(uint8_t);
bool tud_task_event_ready(void);
#endif
''',encoding='ascii')
        model=read(Path(__file__).with_name('usb_gate_trace_model.c'))
        names=('mt_tx_timer_ready','mt_tx_burst_time_ok','mt_gate_time','mt_gate_continue','mt_usb_fsdev_irq_grant','dcd_edpt_xfer','dcd_edpt_xfer_fifo')
        model=once(model,'/* DCD_BODIES */','\n'.join(fn(s,name) for name in names))
        legacy=fn(old,'mt_tx_timer_ready')+'\n'+fn(old,'mt_tx_burst_time_ok')
        legacy=legacy.replace('mt_tx_timer_ready','se_timer_ready').replace('mt_tx_burst_time_ok','se_time_ok')
        legacy+='\nstatic bool se_continue(bool mt_continue_tx,unsigned mt_tx_burst_left,uint32_t int_status) {\nreturn '+old_expr.replace('mt_tx_burst_time_ok()','se_time_ok()')+';\n}\n'
        model=once(model,'/* OLD_CONTINUATION */',legacy)
        for placeholder,block in zip(('/* ACTUAL_METADATA_PRE */','/* ACTUAL_METADATA_POST */'),blocks):model=once(model,placeholder,block)
        (out/'model.c').write_text(model,encoding='utf8',newline='\n')
        (out/'temp').mkdir();env=dict(os.environ,ZIG_LOCAL_CACHE_DIR=str(out/'zig-cache'),ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
        version=run('version',[zig,'version']).strip()
        run('compile',[zig,'cc','-std=c11','-O1','-Wall','-Wextra','-Werror','-I.','-Igenerated','-Iplatform','-Iprotocol','-Iacquisition','-Itransport','-DCFG_MT_PROGRESS_TRACE=1','-DCFG_MT_STREAM_DIAGNOSTICS=1','-DMT_PROGRESS_NATIVE=1','model.c','platform/mt_stream_progress.c','platform/mt_usb_gate.c','-o','model.exe'])
        stdout=run('model',[out/'model.exe',out/'actual-gate.bin',out/'actual-progress.bin',out/'actual-legacy.bin'])
        need([(out/p).stat().st_size for p in ('actual-gate.bin','actual-progress.bin','actual-legacy.bin')]==[24,64,136],'Fixture sizes')
        companion={'origin':'SYNTHETIC_NATIVE_C_SETUP_NOT_PHYSICAL','firmware_build':f'0x{build:08x}','generation':7,'nonce_hex':'0123456789abcdef','image_bin_sha256':ri['artifacts']['MotortesterV2-stream-candidate.bin'],'generated_header_sha256':sha(hp),'fixtures':{p:sha(out/p) for p in ('actual-gate.bin','actual-progress.bin','actual-legacy.bin')},'legacy_module_not_executed':True}
        (out/'companion.json').write_text(json.dumps(companion,indent=2)+'\n',encoding='utf8')
        result.update(status='PASS',compiler_version=version,stdout=stdout,image_bin_sha256=ri['artifacts']['MotortesterV2-stream-candidate.bin'],source_equivalence_sha256=sha(out/'source-equivalence.json'),companion_sha256=sha(out/'companion.json'),fixtures=companion['fixtures'],limitations=['Actual gate/N64 modules and extracted DCD publisher/grant/timer/continuation/metadata source blocks execute.','MMIO storage, PMA submit, DWT and legacy136 setup are synthetic; not full USB/DMA/runtime execution.','USB read journal uses a common base; source equivalence separately verifies exact field/read order.','Pre-CLOSING episode is historical; matching late HELD64 does not prove same episode.','No throughput/timing/WCET/ADC/analogue/Flash qualification.'])
    except BaseException as e:result.update(status='FAILED',error=type(e).__name__+': '+str(e));raise
    finally:
        drift=[p for p,h in inputs.items() if not Path(p).is_file() or sha(Path(p))!=h];result['input_drift']=drift
        if drift:result['status']='FAILED_INPUT_DRIFT'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'result':str(out/'result.json')}))
if __name__=='__main__':main()
