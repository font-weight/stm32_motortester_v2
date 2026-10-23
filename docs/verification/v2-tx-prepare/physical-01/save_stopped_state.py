"""Decode only the already saved post-close register files; no hardware access."""
import json, struct, hashlib
from pathlib import Path
p=Path(__file__).resolve().parent
def words(name,n):
    data=(p/(name+'.bin')).read_bytes()
    assert len(data)==4*n
    return struct.unpack('<'+'I'*n,data)
t=words('tim3',12); a=words('adc',3); d=words('dma',4); r=words('rcc',5)
registers=dict(TIM3_CR1=t[0],TIM3_PSC=t[10],TIM3_ARR=t[11],ADC_CR2=a[0],ADC_SMPR1=a[1],ADC_SMPR2=a[2],DMA_CCR=d[0],RCC_APB2RSTR=r[0],RCC_APB1RSTR=r[1],RCC_AHBENR=r[2],RCC_APB2ENR=r[3],RCC_APB1ENR=r[4])
checks=dict(TIM3_CEN_off=not bool(t[0]&1),TIM3_rate_registers=t[10:12]==(71,9),ADC_off=a[0]==0,ADC_sample_PA0=(a[2]&7)==4,DMA_off=not bool(d[0]&1),DMA_clock=bool(r[2]&1),ADC_GPIOA_clocks=(r[3]&516)==516,TIM3_clock=bool(r[4]&2),ADC_reset_released=not bool(r[0]&512),TIM3_reset_released=not bool(r[1]&2))
result=dict(scope='Post-owner-close stopped state only, not active sampling accuracy',registers=registers,checks=checks,all_checks=all(checks.values()))
(p/'registers-decoded.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
trial=json.loads((p/'run/result.json').read_text('utf-8'))
invocation=json.loads((p/'trial-invocation.json').read_text('utf-8-sig'))
assert trial['cleanup_finished'] and trial['final_state']['phase']=='closed'
assert result['all_checks']
diag=(p/'diagnostics-first.bin').read_bytes()
assert len(diag)==136 and diag==(p/'diagnostics-second.bin').read_bytes()
facts=dict(source='Root executed procedure and explicit user reply; not inferred solely from equal files',program_readback_bytes=37132,user_confirmed_candidate_replug=True,starts=1,trial_command_wall_seconds=invocation['wall_seconds'],SWD_or_debug_halt_during_active=False,SWD_only_after_cleanup_finished_and_phase_closed=True,legacy_dump_independent_calls=2,separate_512byte_profile_read=False,ADC_DR_read=False,rollback_performed=False,retained_image='V2SA/0x56325341',reason_for_retention='Exact build/CAPS answered, owner closed and stopped TIM3/ADC/DMA confirmed; user requested no unnecessary rollback',user_stop_instruction='If another error occurs, finish today and continue tomorrow',additional_START_after_failure=False)
(p/'hardware-procedure-facts.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'stopped_checks':checks,'diag_sha256':hashlib.sha256(diag).hexdigest(),'board':'V2SA retained; no rollback'},indent=2))
