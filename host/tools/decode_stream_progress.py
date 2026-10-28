"""Decode saved SG/SH/SI/SJ/SK/SL progress-v1 evidence. Never opens COM, SWD or a GUI.

The 64-byte bank measures FIFO acceptance, not delivered samples. Its identity
must match the independently decoded legacy136 and an explicitly pinned image.
"""
from pathlib import Path
import argparse
import hashlib
import json
import stat
import struct

BUILD = 0x56325347
SUPPORTED_BUILDS = (BUILD, 0x56325348, 0x56325349, 0x5632534A, 0x5632534B, 0x5632534C)
MAGIC = 0x4D544E31
CAP = 18_000_000
FIELDS = """magic flags generation nonce_low nonce_high begin_cycle end_cycle
prepare_cycles positive_bytes last_positive_cycle max_positive_gap_cycles
prepare_count positive_count zero_space_count zero_other_count tx_offset tx_length
stage_count fifo_free stage_phase queue_used snapshot_bits close_kind""".split()
LAYOUT = struct.Struct('<11I8H4B')
FLAGS = {3: 'have_positive', 4: 'saturated', 5: 'dwt_invalid',
         6: 'partial_write', 7: 'unknown_write', 8: 'partial_prepare',
         9: 'core_snapshot', 10: 'no_active_start', 11: 'cap_overshoot',
         12: 'metadata_invalid', 13: 'write_space_mark', 14: 'prepare_open',
         15: 'start_ack_pending'}
CLOSE = {1: 'queue', 2: 'source', 3: 'recovery', 4: 'stop', 5: 'cap',
         6: 'transport', 7: 'adc', 8: 'hello', 9: 'no_start', 10: 'unavailable', 11: 'time'}
PHASES = {0: 'empty', 1: 'collect', 2: 'crc', 3: 'cobs', 4: 'ready',
          5: 'done', 6: 'aborted'}
PRIMARY = {1: {1}, 2: set(range(1, 7)), 3: set(range(1, 8)), 4: {0}, 5: {0},
           6: {3}, 7: set(range(1, 9)), 8: {0}, 9: {0}, 10: {0}, 11: {2}}


def decode(first, second, legacy, nonce, generation, image_sha256, expected_build=BUILD):
    out = {'schema': 'motortester-sg-progress-v1-offline', 'errors': [],
           'warnings': [], 'accepted_frozen_record': False,
           'physical_identity_verified': False, 'timing_qualified': False,
           'raw': None, 'nominal_timing': None}
    errors, warnings = out['errors'], out['warnings']
    for label, raw in (('first', first), ('second', second)):
        out[label + '_sha256'] = hashlib.sha256(raw).hexdigest()
        if len(raw) != LAYOUT.size:
            errors.append(label + '_size_not_64')
    if errors:
        return out
    if first != second:
        errors.append('repeated_dump_mismatch')
    if expected_build not in SUPPORTED_BUILDS:
        errors.append('unsupported_expected_build')
    d = dict(zip(FIELDS, LAYOUT.unpack(first)))
    out['raw'] = d
    flags = d['flags']
    has = lambda bit: bool(flags & (1 << bit))
    actual_nonce = d['nonce_low'] | d['nonce_high'] << 32
    out['nonce_hex'] = f'{actual_nonce:016x}'
    out['raw_flag_names'] = [name for bit, name in FLAGS.items() if has(bit)]
    out['close_kind'] = CLOSE.get(d['close_kind'], 'invalid')
    out['primary_reason'] = flags >> 16
    if d['magic'] != MAGIC:
        errors.append('magic_version_mismatch')
    if flags & 7 != 4:
        errors.append('record_not_frozen')
    if actual_nonce != nonce or not nonce:
        errors.append('nonce_mismatch')
    if d['generation'] != generation or not generation:
        errors.append('generation_mismatch')
    if d['close_kind'] not in CLOSE:
        errors.append('close_kind_invalid')
    elif flags >> 16 not in PRIMARY[d['close_kind']]:
        errors.append('primary_outside_close_kind_domain')
    if len(image_sha256) != 64 or any(c not in '0123456789abcdef' for c in image_sha256):
        errors.append('expected_image_sha256_invalid')
    lr = legacy.get('raw') or {}
    pin = legacy.get('exact_candidate') or {}
    if (legacy.get('accepted_frozen_record') is not True or legacy.get('errors') != []
            or lr.get('firmware_build') != expected_build or lr.get('generation') != generation
            or lr.get('phase') != 3 or lr.get('nonce_low') != (nonce & 0xffffffff)
            or lr.get('nonce_high') != nonce >> 32
            or pin.get('image_bin_sha256') != image_sha256):
        errors.append('legacy_build_session_image_binding_invalid')
    out['expected_build'] = f'0x{expected_build:08x}'
    out['declared_image_sha256'] = image_sha256
    if has(9):
        if not (d['tx_offset'] <= d['tx_length'] <= 1335 and d['stage_count'] <= 1024
                and d['stage_phase'] in PHASES and d['queue_used'] <= 8):
            errors.append('core_snapshot_out_of_range')
        out['core_snapshot'] = {name: d[name] for name in
                                ('tx_offset', 'tx_length', 'stage_count', 'queue_used')}
        out['core_snapshot']['stage_phase'] = PHASES.get(d['stage_phase'], 'invalid')
        out['core_snapshot']['start_ack_pending'] = has(15)
    else:
        out['core_snapshot'] = None
        if any(d[name] != 65535 for name in ('tx_offset', 'tx_length', 'stage_count')) or any(
                d[name] != 255 for name in ('stage_phase', 'queue_used')):
            errors.append('unavailable_core_snapshot_not_sentinel')
    bits = d['snapshot_bits']
    if bits & ~15:
        errors.append('undefined_USB_snapshot_bits')
    if bits & 1:
        if d['fifo_free'] > 384:
            errors.append('FIFO_space_out_of_range')
        out['USB_snapshot'] = {'fifo_free_bytes': d['fifo_free'], 'held': bool(bits & 2),
                               'deferred': bool(bits & 4), 'task_ready': bool(bits & 8)}
    else:
        out['USB_snapshot'] = None
        if d['fifo_free'] != 65535 or bits:
            errors.append('unavailable_USB_snapshot_not_sentinel')
    if not has(3) and (d['positive_count'] or d['positive_bytes'] or
                       d['last_positive_cycle'] != d['begin_cycle']):
        errors.append('positive_history_without_flag')
    if has(3) and not (d['positive_count'] and d['positive_bytes']):
        errors.append('positive_flag_without_history')
    if not has(4) and not d['positive_count'] <= d['positive_bytes'] <= 384 * d['positive_count']:
        errors.append('accepted_bytes_exceed_callback_capacity')
    if not d['prepare_count'] and d['prepare_cycles']:
        errors.append('prepare_cycles_without_completed_call')
    if has(8) != has(14):
        errors.append('partial_prepare_marker_inconsistent')
    elapsed = (d['end_cycle'] - d['begin_cycle']) & 0xffffffff
    if has(10):
        warnings.append('no_active_start_no_duration')
        if any(d[name] for name in ('begin_cycle', 'end_cycle', 'prepare_cycles', 'positive_bytes',
                'last_positive_cycle', 'max_positive_gap_cycles', 'prepare_count', 'positive_count',
                'zero_space_count', 'zero_other_count')) or any(has(bit) for bit in (3, 6, 7, 8, 11, 13, 14)):
            errors.append('no_active_start_with_active_history')
    if d['close_kind'] in (9, 10) and not has(10):
        errors.append('no_start_kind_without_no_active_flag')
    if d['close_kind'] != 5 and has(11):
        errors.append('cap_overshoot_without_cap_close')
    legacy_clock_bad = bool(lr.get('flags', 0) & (1 | 16))
    timing_interpretable = not errors and not any(has(bit) for bit in (4, 5, 10, 12)) and not legacy_clock_bad
    if timing_interpretable:
        # This is modulo arithmetic, conditional on no halt/reset and <one wrap.
        tail = (d['end_cycle'] - d['last_positive_cycle']) & 0xffffffff
        if d['close_kind'] == 5 and (elapsed < CAP or has(11) != (elapsed > CAP)):
            errors.append('cap_boundary_inconsistent')
        if d['prepare_cycles'] > elapsed or d['max_positive_gap_cycles'] > elapsed or tail > d['max_positive_gap_cycles']:
            errors.append('cycle_spans_inconsistent')
        if not errors:
            out['nominal_timing'] = {
                'elapsed_cycles': elapsed, 'elapsed_ms_at_assumed_72MHz': elapsed / 72000,
                'completed_prepare_us_at_assumed_72MHz': d['prepare_cycles'] / 72,
                'max_no_positive_us_at_assumed_72MHz': d['max_positive_gap_cycles'] / 72,
                'close_tail_no_positive_cycles': tail,
                'qualification': 'Conditional modulo arithmetic: assumes uninterrupted DWT and less than one wrap. Includes IRQ and observer work; not CPU share, calibrated time or WCET.'}
    if lr.get('flags', 0) & (1 | 16):
        warnings.append('legacy_DWT_invalid')
    for bit in (4, 5, 6, 7, 8, 11, 12):
        if has(bit):
            warnings.append(FLAGS[bit])
    if has(9) and has(15):
        warnings.append('start_ack_pending_at_close')
    if d['close_kind'] == 5:
        warnings.append('checkpoint_freeze_not_acquisition_stop')
    out['accepted_frozen_record'] = not errors
    out['status'] = 'INVALID' if errors else 'VALID_WITH_LIMITS'
    out['limits'] = [
        'These are saved bytes and declared identity pins; physical image/readback and operator chronology are separate evidence.',
        'positive_bytes are known DATA FIFO acceptance before freeze, not USB delivery, complete frames or committed sample prefix.',
        'Unknown writes and unsaved partial prepare time cannot be reconstructed from zero counts.',
        'The final no-positive interval includes the tail through first close; without positives it starts at begin.',
        '250ms cap is a checkpoint for observation only; actual end and overshoot are retained.',
        'No throughput fix, losslessness, analog accuracy or calibrated sampling rate follows from a valid record.']
    return out


def saved(path, maximum):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Expected a saved regular file')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('Saved file exceeds size bound')
    return raw


def number(value):
    return int(value, 16 if value.lower().startswith('0x') else 10)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('first', type=Path)
    ap.add_argument('second', type=Path)
    ap.add_argument('--legacy', type=Path, required=True)
    ap.add_argument('--nonce', type=number, required=True)
    ap.add_argument('--generation', type=number, required=True)
    ap.add_argument('--image-sha256', required=True)
    ap.add_argument('--build-id', type=number, choices=SUPPORTED_BUILDS, default=BUILD,
                    help='Exact expected build; SG remains the default for saved evidence')
    args = ap.parse_args()
    try:
        out = decode(saved(args.first, 64), saved(args.second, 64),
                     json.loads(saved(args.legacy, 1024 * 1024)), args.nonce,
                     args.generation, args.image_sha256, args.build_id)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        out = {'status': 'INVALID', 'accepted_frozen_record': False, 'errors': [str(exc)]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out['accepted_frozen_record'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
