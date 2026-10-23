"""Offline S7 post-stop SRAM layout via the same ARM compiler; no hardware I/O."""
from pathlib import Path
import hashlib,importlib.util,json,re,struct,subprocess
root=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent
image=root/'build/v6d-fw-01';board=root/'build/v6d-board-01'
receipt=json.loads((image/'receipt.json').read_text('utf8'))
vendor=image/'source/firmware/third_party/usb/vendor/tinyusb/src'
cdc=(vendor/'class/cdc/cdc_device.c').read_text('utf8')
dcd=(image/'patched/dcd_stm32_fsdev.c').read_text('utf8')
cdc_typedef=re.search(r'typedef struct \{.*?\} cdcd_interface_t;',cdc,re.S)[0]
xfer_typedef=re.search(r'typedef struct \{.*?\} xfer_ctl_t;',dcd,re.S)[0]
fields={
 'mt_live_runtime':['adc','device','acquisition','clock64','epoch','pending','open','in_step','clock_fault'],
 'mt_adc_dma_t':['io','start_before_us','start_after_us','last_poll_us','last_progress_us','first_sample_index','last_remaining','state','fault','next_half','owns_peripherals','stream_history_valid','stop_dma_known','stop_count','stop_offset','stop_first_index','stop_dma_end','first_fault'],
 'mt_live_device':['queue','state','last_time','nonce','generation','hardware_off','local_error','first_reason','prefix_end','tx_length','tx_offset','tx_type','tx_first_index','tx_count','tx_sequence','last_write_accepted','last_write_known'],
 'mt_sample_queue':['head_index','next_index','head','used','sealed','first_fault'],
 'cdcd_interface_t':['line_state','tx_stream','tx_ff_buf'],
 'tu_edpt_stream_t':['ep_addr','mps','xfer_len','ep_buf','ff'],
 'tu_fifo_t':['buffer','depth','overwritable','wr_idx','rd_idx'],
 'xfer_ctl_t':['buffer','ff','total_len','queued_len','max_packet_size','ep_idx'],
}
lines=['#include <stddef.h>','#include "mt_live_runtime.h"','#include "tusb.h"','#include "common/tusb_private.h"',cdc_typedef,xfer_typedef]
for typ,names in fields.items():
 lines.append(f'const unsigned size__{typ}=sizeof({typ});')
 for name in names:lines.append(f'const unsigned off__{typ}__{name}=offsetof({typ},{name});')
(out/'layout.c').write_text('\n'.join(lines)+'\n',encoding='ascii')
cmd=next(c['argv'] for c in receipt['commands'] if c['label']=='compile-21-mt_live_runtime')
cut=cmd.index('-MD');cmd=cmd[:cut]+['-c','../v6d-analysis/layout.c','-o','../v6d-analysis/layout.o']
r=subprocess.run(cmd,cwd=image,capture_output=True)
(out/'layout.stdout').write_bytes(r.stdout);(out/'layout.stderr').write_bytes(r.stderr)
if r.returncode:raise RuntimeError('Layout compilation failed')
helper=image/'source/tests/boot-link/tools/run_boot_link_tests.py'
spec=importlib.util.spec_from_file_location('elf_layout',helper);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
obj=mod.ELF(out/'layout.o');layout={}
for name,sym in obj.symbols.items():
 if name.startswith(('off__','size__')):
  section=obj.sections[sym['ndx']]
  layout[name]=struct.unpack_from('<I',obj.raw,section['offset']+sym['value'])[0]
(out/'layout.json').write_text(json.dumps(layout,indent=2)+'\n',encoding='utf8')
elf=mod.ELF(image/'MotortesterV2-stream-candidate.elf')
sram=(board/'sram-20k.bin').read_bytes()
def read(addr,fmt='<I'):return struct.unpack_from(fmt,sram,addr-0x20000000)[0]
def off(typ,name):return layout['off__'+typ+'__'+name]
def decode(typ,base,formats=None):
 return {name:read(base+off(typ,name),(formats or {}).get(name,'<I')) for name in fields[typ]}
runtime=elf.value('runtime');adc=runtime+off('mt_live_runtime','adc');device=runtime+off('mt_live_runtime','device')
queue=device+off('mt_live_device','queue');cdcd=elf.value('_cdcd_itf');stream=cdcd+off('cdcd_interface_t','tx_stream');fifo=stream+off('tu_edpt_stream_t','ff')
report={'schema':'v2s7-offline-sram-1','scope':'Post-stop snapshot only; not a historical trace or throughput qualification.',
 'addresses':{'runtime':hex(runtime),'adc':hex(adc),'device':hex(device),'queue':hex(queue),'cdcd':hex(cdcd),'tx_stream':hex(stream),'tx_fifo':hex(fifo)},
 'runtime':decode('mt_live_runtime',runtime),
 'adc':decode('mt_adc_dma_t',adc,{'first_sample_index':'<Q','next_half':'<B','owns_peripherals':'<B','stream_history_valid':'<B','stop_dma_known':'<B','stop_first_index':'<Q','stop_dma_end':'<Q'}),
 'device':decode('mt_live_device',device,{'last_time':'<Q','nonce':'<Q','first_reason':'<H','prefix_end':'<Q','tx_type':'<B','tx_first_index':'<Q','tx_count':'<H'}),
 'queue':decode('mt_sample_queue',queue,{'head_index':'<Q','next_index':'<Q'}),
 'tx_stream':decode('tu_edpt_stream_t',stream,{'ep_addr':'<B','mps':'<H','xfer_len':'<H'}),
 'tx_fifo':decode('tu_fifo_t',fifo,{'depth':'<H','overwritable':'<B','wr_idx':'<H','rd_idx':'<H'}),
 'xfers':{},'burst_state':{},'inputs':{},'layout_compile':cmd,
 'limits':['RAM was saved after source stop; former FIFO peaks and IRQ hold causes are not recorded.','Live non-diagnostic fields can change between SWD reads.','Layout uses exact ARM headers/config/compiler; synthetic constants do not execute firmware.']}
for ep in range(3):
 for direction in range(2):
  addr=elf.value('xfer_status')+(ep*2+direction)*layout['size__xfer_ctl_t']
  report['xfers'][f'{ep}_{direction}']=decode('xfer_ctl_t',addr,{'total_len':'<H','queued_len':'<H','max_packet_size':'<H','ep_idx':'<B'})
for name in ('mt_tx_burst_counter','mt_tx_burst_left','mt_irq_held','mt_ctr_deferred'):
 report['burst_state'][name]=read(elf.value(name),'<H' if name=='mt_tx_burst_counter' else '<B' if name in ('mt_irq_held','mt_ctr_deferred') else '<I')
for group,names in {'runtime':['adc','device','acquisition','clock64'],'adc':['io'],'device':['queue'],'tx_stream':['ff']}.items():
 for name in names:report[group].pop(name,None)
report['interpretation']={
 'stop_dma_completed_end':report['adc']['stop_dma_end'],
 'stream_delivered_prefix_end':report['device']['prefix_end'],
 'known_completed_DMA_transfers_after_retained_prefix':report['adc']['stop_dma_end']-report['device']['prefix_end'],
 'produced_ADC_end':'unknown; stopped DMA counter is not produced_end',
 'snapshot_limit':'Post-stop/current state does not identify historical transfer sizes, IRQ hold causes, or exact onset cycles.'}
for p in (image/'MotortesterV2-stream-candidate.elf',board/'sram-20k.bin',out/'layout.c',out/'layout.o'):
 report['inputs'][str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
(out/'sram-analysis.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:report[k] for k in ('addresses','adc','device','queue','tx_stream','tx_fifo','xfers','burst_state','interpretation')},indent=2))
