#!/usr/bin/env python3
"""V2SD offline ABI-v1 decoder for two 136-byte saved diagnostic dumps. No device access."""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
import struct

FIELDS = '''magic version bytes firmware_build phase flags generation
step_count step_body_max_cycles step_gap_max_cycles tx_count tx_max_cycles
poll_count driver_observed_poll_gap_us poll_gap_max_cycles copy_count copy_max_us
queue_high_water first_runtime_result first_local_error first_acquisition_reason
first_adc_fault first_epoch final_runtime_result final_core_state final_epoch
final_adc_state final_adc_owned final_hardware_off start_cycle last_cycle freeze_cycle
nonce_low nonce_high'''.split()
PROFILES = {50000: (1, 10240, 71, 19, 12),
            100000: (2, 5120, 71, 9, 12),
            150000: (4, 3413, 47, 9, 10)}
PLAN = json.loads((Path(__file__).resolve().parent / 'plan.json').read_text('utf-8'))
FLAGS = {1: 'dwt_unusable', 2: 'count_saturated', 4: 'first_fault',
         8: 'replacement_hello_partial_step', 16: 'invalid_cycle_source'}


def integer(bits, nonzero=False):
    def parse(value):
        try:
            n = int(value, 16 if value.lower().startswith('0x') else 10)
        except ValueError as exc:
            raise argparse.ArgumentTypeError('expected decimal or 0x integer') from exc
        if n < int(nonzero) or n >= 1 << bits:
            raise argparse.ArgumentTypeError('integer outside allowed range')
        return n
    return parse


def decode(first, second, build, generation, nonce, sample_rate):
    result = {'schema': 'stream-diag-v1-offline', 'accepted_frozen_record': False,
              'physical_identity_verified': False, 'timing_qualified': False,
              'errors': [], 'warnings': [], 'raw': None}
    if build != 0x56325344:
        result['errors'].append('expected_build_not_v2sd')
    if sample_rate not in PROFILES:
        result['errors'].append('unsupported_expected_sample_rate')
    if result['errors']:
        return result
    mode, deadline_us, timer_psc, timer_arr, retained_bits = PROFILES[sample_rate]
    for label, data in (('first', first), ('second', second)):
        result[label + '_sha256'] = hashlib.sha256(data).hexdigest() if len(data) == 136 else None
        if len(data) != 136:
            result['errors'].append(label + '_size_not_136')
    if result['errors']:
        return result
    d = dict(zip(FIELDS, struct.unpack('<34I', first)))
    result['raw'] = d
    result['exact_candidate'] = {
        'image_bin_sha256': PLAN['candidate_sha256'],
        'elf_sha256': PLAN['candidate_elf_sha256'],
        'record_address': PLAN['diagnostic_address'], 'record_bytes': 136,
        'image_nm_sha256': PLAN['candidate_nm_sha256'],
        'firmware_build_expected': 0x56325344,
        'runtime_grant_order': 'One ordinary opportunity after ADC/TIME/stable before RX/prepare, with a fresh TIME/stable barrier; the former wrapper opportunity is only an early-return fallback. No second opportunity per runtime step.',
        'active_profile_enabled': False, 'separate_512byte_profile_present': False,
        'queue_slots': 8, 'dma_ring_samples': 1024, 'dma_half_samples': 512,
        'nominal_sample_rate_hz': sample_rate, 'service_deadline_us_exclusive': deadline_us,
        'acquisition_mode_expected': mode, 'retained_bits_expected': retained_bits,
        'adc_bits': 12, 'timer_psc_expected': timer_psc, 'timer_arr_expected': timer_arr,
        'sample_rate_expectation_origin': 'Explicit caller argument, not stored in this136-byte ABI. Check CAPS/session and separate TIM3 register evidence.',
        'sample_rate_authenticated_by_dump': False,
        'warning': 'These constants describe the reviewed image, not authenticated physical identity.'}
    result['field_offsets_bytes'] = {name: i*4 for i, name in enumerate(FIELDS)}
    result['decoded_states'] = {
        'phase': {0:'empty',1:'armed',2:'active',3:'frozen',4:'unavailable'}.get(d['phase'],'unknown'),
        'first_adc_fault': {0:'none',1:'clock',2:'calibration',3:'timebase',4:'transfer',5:'deadline',6:'stop',7:'sequence_limit',8:'admission'}.get(d['first_adc_fault'],'unknown'),
        'first_local_error': {0:'none',1:'protocol',2:'clock',3:'transport',4:'deadline',5:'argument',6:'callback',7:'incompatible'}.get(d['first_local_error'],'unknown'),
        'final_core_state': {0:'no_session',1:'hello_pending',2:'stopped',3:'starting',4:'streaming',5:'draining',6:'terminal',7:'needs_hello',8:'fault'}.get(d['final_core_state'],'unknown'),
        'final_adc_state': {0:'stopped',1:'running',2:'faulted'}.get(d['final_adc_state'],'unknown')}
    result['metric_meaning'] = {
        'driver_observed_poll_gap_us': 'Maximum observed driver stamp minus previous service timestamp; not the latest timestamp or a WCET bound.',
        'copy_max_us': 'Maximum observed read/copy validation interval; not an ADC conversion or only memcpy duration.',
        'poll_gap_max_cycles': 'Maximum interval between DWT poll instrumentation points; can include TX preparation and differs from TIM2 service timestamps.',
        'step_body_max_cycles': 'Runtime step bracket still includes prepare/encode; not a measured CPU-only or IRQ-off duration.',
        'step_gap_max_cycles': 'Maximum begin-step stamp spacing; includes prepare/encode, inter-step work and interrupts, not only step body.',
        'tx_max_cycles': 'V2SD bracket starts AFTER prepare/encode and covers guarded submit through unlock. Preparation is excluded; do not directly compare against S8/S9 TX maxima. This is not an exact IRQ-off duration or qualified transaction bound.',
        'queue_high_water': 'Maximum observed queue128 slot use (DATA256 consumes two slots) out of 8; no proof of zero ADC loss.',
        'start_cycle_last_cycle_freeze_cycle': 'Raw DWT modulo2^32 values; cannot directly subtract for sessions longer than one cycle-counter wrap.',
        'first_runtime_result_0xffffffff': 'Sentinel: cause observed before a runtime return; see first fault fields.'}
    result['nominal_cycles_to_us'] = {
        key.removesuffix('_cycles')+'_us_at_assumed_72MHz': d[key]/72
        for key in ('step_body_max_cycles','step_gap_max_cycles','tx_max_cycles','poll_gap_max_cycles')}
    result['nominal_cycles_to_us']['qualification'] = 'Arithmetic only; assumes72MHz, uninterrupted DWT and intervals shorter than one2^32-cycle wrap (~59.65s).'
    result['observed_service_headroom_arithmetic_us'] = deadline_us-d['driver_observed_poll_gap_us'] if d['poll_count'] else None
    result['observed_deadline_comparison'] = {
        'deadline_us_exclusive': deadline_us,
        'poll_gap_below_deadline': d['driver_observed_poll_gap_us'] < deadline_us if d['poll_count'] else None,
        'copy_validation_below_deadline': d['copy_max_us'] < deadline_us if d['copy_count'] else None,
        'qualification': 'Only observed maxima versus nominal selected-profile budget, not WCET or a sample-loss proof.'}
    result['minimal_stopped_register_checks'] = {
        'TIM3_CR1_0x40000400': 'CEN bit0 must be0; driver normally writes whole register0.',
        'TIM3_PSC_0x40000428': f'Expected {timer_psc} for caller-selected mode{mode}; read separately after closed COM.',
        'TIM3_ARR_0x4000042c': f'Expected {timer_arr} for caller-selected mode{mode}; read separately after closed COM.',
        'ADC1_SMPR2_0x40012410': 'SMP0 low3bits expected4 (41.5cycles); physical ADC remains12bits in every mode.',
        'ADC1_CR2_0x40012408': 'Whole register must be0.',
        'DMA1_CH1_CCR_0x40020008': 'EN bit0 must be0; remaining configuration normally0x25a0.',
        'RCC_AHBENR_0x40021014': 'DMA1 enable bit0 must remain1 for meaningful readback.',
        'RCC_APB2ENR_0x40021018': 'GPIOA bit2 and ADC1 bit9 must remain1.',
        'RCC_APB1ENR_0x4002101c': 'TIM3 bit1 must remain1.',
        'RCC_APB2RSTR_0x4002100c': 'ADC1 reset bit9 must be0.',
        'RCC_APB1RSTR_0x40021010': 'TIM3 reset bit1 must be0.'}

    if first != second:
        result['errors'].append('repeated_dump_mismatch')
    expected = {'magic': 0x4d544447, 'version': 1, 'bytes': 136, 'phase': 3,
                'firmware_build': build, 'generation': generation}
    for key, value in expected.items():
        if d[key] != value:
            result['errors'].append(key + '_mismatch')
    actual_nonce = d['nonce_low'] | d['nonce_high'] << 32
    result['nonce_hex'] = f'{actual_nonce:016x}'
    if actual_nonce != nonce:
        result['errors'].append('nonce_mismatch')
    if d['flags'] & ~31:
        result['errors'].append('undefined_flags')
    if d['final_adc_owned'] != 0 or d['final_hardware_off'] != 1 or d['final_adc_state'] != 0:
        result['errors'].append('frozen_without_quiescence')
    if d['freeze_cycle'] != d['last_cycle']:
        result['errors'].append('freeze_cycle_mismatch')
    if d['queue_high_water'] > 8:
        result['errors'].append('queue_high_water_out_of_range')
    for key, maximum in (('first_local_error', 7), ('first_acquisition_reason', 6),
                         ('first_adc_fault', 8)):
        if d[key] > maximum:
            result['errors'].append(key + '_out_of_range')
    if d['first_runtime_result'] not in (*range(6), 0xffffffff):
        result['errors'].append('first_runtime_result_out_of_range')
    if d['flags'] & 8:
        if d['final_core_state'] not in (1, 2) or d['final_runtime_result'] != 0xffffffff:
            result['errors'].append('replacement_terminal_mismatch')
    elif d['final_core_state'] not in (7, 8) or d['final_runtime_result'] not in range(6):
        result['errors'].append('ordinary_terminal_mismatch')
    first_fields = ('first_runtime_result', 'first_local_error',
                    'first_acquisition_reason', 'first_adc_fault', 'first_epoch')
    if not d['flags'] & 4:
        if any(d[key] for key in first_fields):
            result['errors'].append('cause_fields_without_fault_flag')
    elif not (d['first_local_error'] or d['first_acquisition_reason'] or d['first_adc_fault']
              or d['first_runtime_result'] in (3, 4, 5)):
        result['errors'].append('fault_flag_without_cause')
    if not d['flags'] & 8 and d['step_count'] == 0:
        result['errors'].append('ordinary_freeze_without_step')
    if d['final_runtime_result'] in (3, 4, 5) and not d['flags'] & 4:
        result['errors'].append('final_fault_without_first_fault')
    if d['flags'] & 1:
        result['errors'].append('unavailable_dwt_cannot_freeze')
    counts = ('step_count', 'tx_count', 'poll_count', 'copy_count')
    if d['flags'] & 2 and not any(d[key] == 0xffffffff for key in counts):
        result['errors'].append('saturation_without_saturated_counter')
    if d['flags'] == 0 and d['final_runtime_result'] == 0 and d['final_core_state'] == 7 and d['tx_count'] == 0:
        result['errors'].append('normal_stop_without_tx_observation')
    result['warnings'] = [label for bit, label in FLAGS.items() if d['flags'] & bit]
    result['observed_metrics'] = {
        'step_body_cycles': d['step_body_max_cycles'] if d['step_count'] else None,
        'step_stamp_gap_cycles': d['step_gap_max_cycles'] if d['step_count'] >= 2 else None,
        'tx_bracket_cycles': d['tx_max_cycles'] if d['tx_count'] else None,
        'driver_poll_gap_us': d['driver_observed_poll_gap_us'] if d['poll_count'] else None,
        'poll_gap_cycles': d['poll_gap_max_cycles'] if d['poll_count'] >= 2 else None,
        'copy_validation_us': d['copy_max_us'] if d['copy_count'] else None}
    result['accepted_frozen_record'] = not result['errors']
    result['normal_stop_record_shape'] = (not result['errors'] and d['flags'] == 0
        and d['final_runtime_result'] == 0 and d['final_core_state'] == 7)
    result['limits'] = ['Local dumps and expected values do not prove flashed image identity.',
        'HOST END/STOP_ACK and actual USB delivery require separate evidence.',
        'Expected Fs/mode is supplied by caller; this136-byte record has no profile field. Match wire CAPS, nonce/generation and stopped PSC/ARR separately.',
        'Mode150k retains10MSB of ADC12; the low2bits are discarded. This decoder does not inspect raw samples or their quantization.',
        'All timing values/budgets are nominal; no calibrated physical sample-rate inference.',
        'No hardware/register access is performed. ADC_DR is never read; register items are expectations for separate saved evidence only.',
        'Cycles are modulo uint32; no elapsed-time or calibrated clock inference.',
        'Debugger halt and intervals below one cycle-counter wrap are external assumptions.',
        'TX bracket excludes prepare/encode in V2SD; its boundary differs from S8/S9. Runtime step and poll spacing still include preparation. It is not the qualified transaction or exact IRQ-off duration.',
        'The separate S9 512-byte active-phase profile is disabled in this image; this decoder reads only legacy136.',
        'V2SD preserves the V2SB early grant. This ABI does not timestamp final-IN to task/publication or prove throughput for the selected mode.',
        'A record with warnings remains evidence of a failed or limited observation.']
    return result


def read_dump(path):
    # Local regular files only. No FIFO/device access; no symlink final component.
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError('dump must be a regular file, not a link or special file')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError('dump changed or is not a regular file')
        data = stream.read(137)
        after = os.fstat(stream.fileno())
        if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError('dump changed while reading')
        return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('first', type=Path)
    ap.add_argument('second', type=Path)
    ap.add_argument('--build', type=integer(32), default=0x56325344, choices=(0x56325344,))
    ap.add_argument('--sample-rate', type=integer(32, True), choices=(50000, 100000, 150000), required=True, help='Expected nominal acquisition Fs; not inferred/authenticated from this dump.')
    ap.add_argument('--generation', type=integer(32, True), required=True)
    ap.add_argument('--nonce', type=integer(64, True), required=True)
    a = ap.parse_args()
    try:
        # Read at most one extra byte to reject oversized files without allocating them.
        first = read_dump(a.first)
        second = read_dump(a.second)
    except OSError as exc:
        ap.error(str(exc))
    result = decode(first, second, a.build, a.generation, a.nonce, a.sample_rate)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['accepted_frozen_record'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
