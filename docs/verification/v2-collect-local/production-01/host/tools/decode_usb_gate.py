"""Strict offline SK/SL/SN USB-gate-v1 decoder; no COM, SWD, UI or live reads.

Contract: docs/streaming-usb-gate.md. Gate24 stops at N CLOSING, whereas the
USB fields in progress64 are sampled later. Even equal HELD booleans do not
identify the same episode. Declared image/session pins are not authentication.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import struct

_spec = importlib.util.spec_from_file_location(
    'usb_gate_progress_decoder', Path(__file__).with_name('decode_stream_progress.py'))
progress_decoder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(progress_decoder)

BUILD = 0x5632534B
SUPPORTED_BUILDS = (BUILD, 0x5632534C, 0x5632534E)
MAGIC = 0x4D544731
LAYOUT = struct.Struct('<4I3H2B')
FIELDS = ('magic', 'flags', 'publication_serial', 'event_cycle', 'total_len',
          'queued_len', 'evaluated_age_us', 'remaining_budget', 'decision')
FLAGS = {2: 'has_publication', 3: 'transfer_active', 4: 'decision_applicable_to_held',
         5: 'age_valid', 6: 'serial_saturated', 7: 'metadata_invalid',
         8: 'lifecycle_invalid', 9: 'unobserved_initial_transfer',
         10: 'no_active_start', 11: 'observation_cap', 12: 'zlp'}
DECISIONS = {0: 'unknown', 1: 'published', 2: 'resumed', 3: 'hold_final',
             4: 'hold_other', 5: 'hold_budget', 6: 'hold_time',
             7: 'hold_timer_unavailable', 8: 'hold_lifecycle', 9: 'hold_status'}


def decode(first, second, progress_first, progress_second, legacy, nonce,
           generation, image_sha256, expected_build):
    out = {'schema': 'motortester-sk-usb-gate-v1-offline', 'status': 'INVALID',
           'accepted_frozen_record': False, 'errors': [], 'warnings': [],
           'physical_identity_verified': False, 'timing_qualified': False,
           'raw': None, 'history': None, 'nominal_event_timing': None,
           'pre_closing_episode_applicable': False,
           'current64_causal_attribution_available': False,
           'same_episode_as_later64_proven': False}
    errors, warnings = out['errors'], out['warnings']
    for label, raw in (('first', first), ('second', second)):
        out[label + '_sha256'] = hashlib.sha256(raw).hexdigest()
        if len(raw) != LAYOUT.size:
            errors.append(label + '_size_not_24')
    if errors:
        return out
    if first != second:
        errors.append('repeated_gate_dump_mismatch')
    if expected_build not in SUPPORTED_BUILDS:
        errors.append('unsupported_expected_gate_build')
    if not isinstance(legacy, dict):
        errors.append('legacy_report_not_object')
        return out
    try:
        progress = progress_decoder.decode(progress_first, progress_second, legacy,
            nonce, generation, image_sha256, expected_build)
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        errors.append('paired_progress_invalid: ' + str(exc))
        return out
    out['paired_progress'] = progress
    if progress.get('accepted_frozen_record') is not True or progress.get('errors') != []:
        errors.append('paired_progress_session_image_binding_invalid')
    out['expected_build'] = f'0x{expected_build:08x}'
    out['declared_image_sha256'] = image_sha256
    out['nonce_hex'] = f'{nonce:016x}'
    out['generation'] = generation
    d = dict(zip(FIELDS, LAYOUT.unpack(first)))
    out['raw'] = d
    flags = d['flags']
    has = lambda bit: bool(flags & (1 << bit))
    out['raw_flag_names'] = [name for bit, name in FLAGS.items() if has(bit)]
    decision = d['decision']
    out['decision'] = DECISIONS.get(decision, 'invalid')
    unknown = (d['total_len'] == d['queued_len'] == d['evaluated_age_us'] == 65535
               and d['remaining_budget'] == 255 and not has(5))
    if d['magic'] != MAGIC:
        errors.append('gate_magic_version_mismatch')
    if flags & 3 != 3:
        errors.append('gate_not_frozen')
    if flags & ~0x1fff:
        errors.append('undefined_gate_flags')
    if decision not in DECISIONS:
        errors.append('gate_decision_invalid')
    if not has(5) and d['evaluated_age_us'] != 65535:
        errors.append('unknown_age_not_sentinel')
    if has(4) and decision not in range(3, 10):
        errors.append('applicability_without_hold_decision')
    if any(has(bit) for bit in (6, 7, 8)) and (has(3) or has(4)):
        errors.append('sticky_invalid_with_active_association')
    if has(6) and (d['publication_serial'] != 0xffffffff or not has(2)):
        errors.append('serial_saturation_inconsistent')
    pd = progress.get('raw') or {}
    pf = pd.get('flags', 0)
    if has(10) != bool(pf & (1 << 10)):
        errors.append('no_active_marker_disagrees_with_progress')
    if has(11) != (pd.get('close_kind') == 5):
        errors.append('cap_marker_disagrees_with_progress')
    if not has(2):
        if (d['publication_serial'] or d['event_cycle'] or decision != 0 or not unknown
                or not has(9) or any(has(bit) for bit in (3, 4, 5, 6, 12))):
            errors.append('unobserved_initial_history_inconsistent')
    else:
        if not d['publication_serial'] or decision == 0 or has(9) or has(10):
            errors.append('publication_identity_inconsistent')
    if has(10) and flags != (3 | (1 << 9) | (1 << 10)):
        errors.append('no_active_record_has_history_flags')

    # Metadata invalidation deliberately replaces the tuple with U. Lifecycle
    # and saturation retain the last-good historical row instead. A failed
    # submit can clear ACTIVE/APPLICABLE without sticky flags; do not reject
    # that legitimate historical PUBLISHED/RESUMED/intermediate row.
    if has(7) and has(2):
        if decision != 4 or not unknown or has(12):
            errors.append('metadata_invalid_tuple_not_unknown_other')
    elif has(2) and decision in DECISIONS:
        total, queued = d['total_len'], d['queued_len']
        age, budget = d['evaluated_age_us'], d['remaining_budget']
        if not 0 <= queued <= total <= 384:
            errors.append('transfer_tuple_out_of_range')
        if has(12) != (total == queued == 0):
            errors.append('zlp_marker_tuple_mismatch')
        if decision == 1:
            if queued != min(total, 64) or has(4) or has(5) or budget != 255:
                errors.append('published_row_inconsistent')
        else:
            if not 0 <= budget <= 5:
                errors.append('evaluated_budget_out_of_range')
            if not (total == queued == 0 or
                    (total > 0 and queued > 0 and (queued == total or queued % 64 == 0))):
                errors.append('evaluated_PRE_tuple_not_PMA_packet_boundary')
            if decision in (2, 5, 6, 7, 8, 9):
                if not (0 < queued < total <= 384 and queued % 64 == 0):
                    errors.append('intermediate_tuple_invalid')
                if has(4) and not has(3):
                    errors.append('applicable_intermediate_without_active_transfer')
            if decision == 2 and (has(4) or not has(5) or age >= 500 or not 1 <= budget <= 5):
                errors.append('resumed_row_inconsistent')
            if decision == 3 and (queued != total or has(3) or has(5)):
                errors.append('final_row_inconsistent')
            if decision == 4 and has(5):
                errors.append('other_row_has_skipped_age')
            if decision == 4 and queued == total and has(3):
                errors.append('completed_other_transfer_still_active')
            if decision == 5 and (has(5) or budget != 0):
                errors.append('budget_row_inconsistent')
            if decision == 6 and (not has(5) or age < 500 or not 1 <= budget <= 5):
                errors.append('time_row_inconsistent')
            if decision == 7 and (has(5) or not 1 <= budget <= 5):
                errors.append('timer_unavailable_row_inconsistent')
            if decision in (8, 9) and (not 1 <= budget <= 5 or (has(5) and age >= 500)):
                errors.append('status_lifecycle_row_inconsistent')
            if decision == 8 and not has(8):
                errors.append('lifecycle_decision_without_sticky_marker')

    later = progress.get('USB_snapshot')
    out['later_USB64_snapshot'] = later
    out['later_snapshot_relation'] = ('skew_visible_held_false' if has(4) and later and not later['held']
        else 'USB64_unavailable' if later is None
        else 'held_compatible_but_same_episode_unproven' if has(4)
        else 'historical_decision_not_applicable_to_held')
    if has(4) and later and not later['held']:
        warnings.append('N_CLOSING_to_snapshot_skew_not_structural_error')
    if later is None:
        warnings.append('later_USB64_snapshot_unavailable')
    for bit in (6, 7, 8, 9, 10, 11):
        if has(bit):
            warnings.append(FLAGS[bit])
    if has(2) and not has(4):
        warnings.append('last_decision_is_historical_not_applicable_to_held')

    timing = progress.get('nominal_timing')
    if has(2) and not timing:
        warnings.append('paired_progress_window_not_interpretable')
    if not errors and has(2) and timing and not any(has(bit) for bit in (6, 7, 8, 10)):
        offset = (d['event_cycle'] - pd['begin_cycle']) & 0xffffffff
        if offset > timing['elapsed_cycles']:
            errors.append('gate_event_outside_paired_active_window')
        else:
            tail = (pd['end_cycle'] - d['event_cycle']) & 0xffffffff
            out['nominal_event_timing'] = {
                'event_from_begin_cycles': offset, 'event_to_N_close_cycles': tail,
                'event_to_N_close_us_at_assumed_72MHz': tail / 72,
                'qualification': 'Conditional no-halt, no-reset, less-than-one-DWT-wrap arithmetic. Event stamp follows publication/decision; not IRQ duration, calibrated time or atomic bank sampling.'}
    if not errors and has(2):
        out['history'] = {'publication_serial': d['publication_serial'],
            'decision': DECISIONS[decision], 'transfer_association_active_before_N_CLOSING': has(3),
            'total_len': None if d['total_len'] == 65535 else d['total_len'],
            'queued_len_before_IN_handler_or_after_publication': None if d['queued_len'] == 65535 else d['queued_len'],
            'evaluated_TIM2_age_us': d['evaluated_age_us'] if has(5) else None,
            'remaining_budget': None if d['remaining_budget'] == 255 else d['remaining_budget'],
            'zlp': has(12), 'metadata_valid': not has(7)}
    out['pre_closing_episode_applicable'] = bool(not errors and has(4) and
        not any(has(bit) for bit in (6, 7, 8, 9, 10, 11)) and out['nominal_event_timing'])
    out['accepted_frozen_record'] = not errors
    out['status'] = 'INVALID' if errors else 'VALID_WITH_LIMITS'
    if errors:
        out['nominal_event_timing'] = None
    out['limits'] = [
        'Gate24 has no embedded session/image identity: saved64/136, declared pins, exact source/readback and single-boot chronology are separate evidence.',
        'The publication serial is an EP0x82 transfer cookie, not DATA sequence, sample count or USB packet count; queued bytes are staged in PMA, not host delivery.',
        'APPLICABLE names the last episode before N CLOSING only. USB64 is later: HELD0 exposes skew, HELD1 never proves the same episode. Current64 attribution is always unavailable.',
        'Grant, other ISR, failed submit, lifecycle and sticky-invalid history cannot be treated as the current held cause. Unknown fields stay unknown.',
        'CAP is an observation checkpoint, not acquisition stop; this bank cannot explain a later failure.',
        'Evaluated age is the existing modulo TIM2 decision operand, not a fresh freeze-time measurement or a 500us WCET guarantee.',
        'No stable sampling/USB throughput, losslessness or analog accuracy follows from a valid diagnostic record.']
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('first', type=Path)
    ap.add_argument('second', type=Path)
    ap.add_argument('--progress-first', type=Path, required=True)
    ap.add_argument('--progress-second', type=Path, required=True)
    ap.add_argument('--legacy', type=Path, required=True)
    ap.add_argument('--nonce', type=progress_decoder.number, required=True)
    ap.add_argument('--generation', type=progress_decoder.number, required=True)
    ap.add_argument('--image-sha256', required=True)
    ap.add_argument('--build-id', type=progress_decoder.number, choices=SUPPORTED_BUILDS, required=True)
    args = ap.parse_args()
    try:
        legacy_raw = progress_decoder.saved(args.legacy, 1024 * 1024)
        out = decode(progress_decoder.saved(args.first, 24), progress_decoder.saved(args.second, 24),
            progress_decoder.saved(args.progress_first, 64), progress_decoder.saved(args.progress_second, 64),
            json.loads(legacy_raw), args.nonce, args.generation, args.image_sha256, args.build_id)
        out['legacy_report_sha256'] = hashlib.sha256(legacy_raw).hexdigest()
    except (OSError, ValueError, TypeError, AttributeError, OverflowError) as exc:
        out = {'status': 'INVALID', 'accepted_frozen_record': False, 'errors': [str(exc)]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out['accepted_frozen_record'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
