"""One actual-C24/64/136 decode plus bounded synthetic evidence mutations.

The native legacy136 record is a synthetic setup, not a physical image witness.
No device, native model rerun, GUI, old suite or transport test is performed.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
DECODER = ROOT / 'host/tools/decode_usb_gate.py'
PROGRESS = ROOT / 'host/tools/decode_stream_progress.py'
spec = importlib.util.spec_from_file_location('gate_decoder_check_target', DECODER)
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,
         'Use Python -I -B without optimization')
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('gate-fixture', 'progress-fixture', 'legacy-bin', 'producer-receipt', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--image-sha256', required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    need(output.parent == ROOT / 'build' and output.name.startswith('v6r-decoder-')
         and not output.exists(), 'Use a new build/v6r-decoder-* output')
    output.mkdir()
    companion_path = args.producer_receipt.resolve().with_name('companion.json')
    sources = [Path(__file__).resolve(), DECODER, PROGRESS, ROOT / 'docs/streaming-usb-gate.md',
               ROOT / 'host/tests/stream_progress_decoder_check.py', args.gate_fixture.resolve(),
               args.progress_fixture.resolve(), args.legacy_bin.resolve(), args.producer_receipt.resolve(),
               companion_path]
    inputs = {str(path): sha(path) for path in sources}
    report = {'status': 'RUNNING', 'scope': __doc__, 'argv': sys.argv,
              'python': sys.version, 'inputs': inputs, 'checks': [],
              'hardware_executed': False, 'physical_throughput_claim': False,
              'native_producer_rerun': False, 'legacy_binding_is_synthetic': True}
    try:
        producer = json.loads(args.producer_receipt.read_text('utf-8-sig'))
        need(producer.get('status') == 'PASS', 'Actual native producer did not PASS')
        need(producer.get('image_bin_sha256') == args.image_sha256,
             'Image pin differs from the actual-C producer receipt')
        companion = json.loads(companion_path.read_text('utf-8-sig'))
        gate = args.gate_fixture.read_bytes()
        progress = args.progress_fixture.read_bytes()
        legacy_bytes = args.legacy_bin.read_bytes()
        words = struct.unpack('<34I', legacy_bytes)
        nonce, generation = 0x0123456789abcdef, 7
        need(companion.get('origin') == 'SYNTHETIC_NATIVE_C_SETUP_NOT_PHYSICAL'
             and companion.get('legacy_module_not_executed') is True
             and companion.get('firmware_build') == '0x5632534b'
             and companion.get('generation') == generation
             and companion.get('nonce_hex') == f'{nonce:016x}'
             and companion.get('image_bin_sha256') == args.image_sha256,
             'Native companion scope/identity mismatch')
        for name, raw in (('actual-gate.bin', gate), ('actual-progress.bin', progress),
                          ('actual-legacy.bin', legacy_bytes)):
            need(companion.get('fixtures', {}).get(name) == hashlib.sha256(raw).hexdigest(),
                 'Actual-C fixture differs from native companion: ' + name)
        report['native_companion'] = companion
        need(words[:3] == (0x4d544447, 1, 136) and words[3] == decoder.BUILD
             and words[4] == 3 and words[6] == generation
             and (words[32] | words[33] << 32) == nonce, 'Native legacy fixture identity')
        legacy = {'accepted_frozen_record': True, 'errors': [],
                  'raw': dict(firmware_build=words[3], phase=words[4], flags=words[5],
                              generation=words[6], nonce_low=words[32], nonce_high=words[33]),
                  'exact_candidate': {'image_bin_sha256': args.image_sha256},
                  'origin': 'actual native-C legacy136 bytes with explicit synthetic setup; not hardware/readback'}
        (output / 'legacy-binding.json').write_text(json.dumps(legacy, indent=2) + '\n', encoding='utf-8')

        def run(raw=gate, second=None, nraw=progress, nsecond=None, **kwargs):
            return decoder.decode(raw, raw if second is None else second,
                nraw, nraw if nsecond is None else nsecond, kwargs.get('legacy', legacy),
                kwargs.get('nonce', nonce), kwargs.get('generation', generation),
                kwargs.get('image', args.image_sha256), kwargs.get('build', decoder.BUILD))

        def mutate(raw, layout, fields, changes):
            values = dict(zip(fields, layout.unpack(raw)))
            values.update(changes)
            return layout.pack(*(values[field] for field in fields))

        def change(**fields):
            return mutate(gate, decoder.LAYOUT, decoder.FIELDS, fields)

        def nchange(**fields):
            p = decoder.progress_decoder
            return mutate(progress, p.LAYOUT, p.FIELDS, fields)

        def accepted(label, result, applicable=False):
            need(result['accepted_frozen_record'] and result['errors'] == [], (label, result))
            need(result['pre_closing_episode_applicable'] is applicable, (label, result))
            need(result['current64_causal_attribution_available'] is False
                 and result['same_episode_as_later64_proven'] is False, label)
            report['checks'].append({'case': label, 'kind': 'valid_with_limits'})
            return result

        def rejected(label, result):
            need(not result['accepted_frozen_record'] and result['errors'], (label, result))
            need(result['nominal_event_timing'] is None and not result['pre_closing_episode_applicable'], label)
            report['checks'].append({'case': label, 'kind': 'reject', 'errors': result['errors']})

        actual = accepted('actual_native_C24_C64_C136', run(), True)
        expected = dict(magic=decoder.MAGIC, flags=3 | 4 | 8 | 16 | 32,
                        publication_serial=1, event_cycle=3000, total_len=384, queued_len=64,
                        evaluated_age_us=501, remaining_budget=5, decision=6)
        need(actual['raw'] == expected, actual['raw'])
        need(actual['nominal_event_timing']['event_to_N_close_cycles'] == 2000, actual)
        need(actual['later_snapshot_relation'] == 'held_compatible_but_same_episode_unproven', actual)
        (output / 'actual-fixture-decoded.json').write_text(json.dumps(actual, indent=2) + '\n', encoding='utf-8')
        report['actual_C_known_fields'] = expected
        report['synthetic_mutations_start_after_actual_fixture'] = True

        flags = expected['flags']
        rejected('truncated_gate', run(gate[:-1]))
        rejected('changed_gate_pair', run(second=bytes([gate[0] ^ 1]) + gate[1:]))
        rejected('changed_progress_pair', run(nsecond=bytes([progress[0] ^ 1]) + progress[1:]))
        rejected('foreign_session', run(nonce=nonce ^ 1))
        rejected('foreign_generation', run(generation=generation + 1))
        rejected('foreign_image', run(image='0' * 64))
        rejected('SJ_not_SK', run(build=0x5632534a))
        rejected('unsupported_future_build', run(build=0x5632534d))
        rejected('not_frozen', run(change(flags=(flags & ~3) | 1)))
        rejected('wrong_magic', run(change(magic=decoder.MAGIC ^ 1)))
        rejected('undefined_bits', run(change(flags=flags | (1 << 13))))
        rejected('unknown_decision', run(change(decision=10)))
        rejected('event_after_first_close', run(change(event_cycle=5001)))
        rejected('time_below_threshold', run(change(evaluated_age_us=499)))
        rejected('time_zero_budget', run(change(remaining_budget=0)))
        rejected('not_intermediate', run(change(queued_len=384)))
        rejected('OTHER_impossible_PRE_packet_tuple', run(change(flags=flags & ~32,
                 decision=4, queued_len=1, evaluated_age_us=65535)))
        rejected('sentinel_without_flag', run(change(flags=flags & ~(1 << 5))))
        rejected('unbound_cap', run(change(flags=flags | (1 << 11))))
        rejected('saturation_not_max', run(change(flags=(flags & ~(8 | 16)) | (1 << 6))))
        rejected('sticky_active', run(change(flags=flags | (1 << 8))))

        # Positive boundary cases are deliberately synthetic, not additional C
        # transition evidence. HELD0 is skew; HELD1 is not same-episode proof.
        skew = accepted('later64_HELD0_is_skew', run(nraw=nchange(snapshot_bits=13)), True)
        need(skew['later_snapshot_relation'] == 'skew_visible_held_false', skew)
        accepted('later64_unavailable', run(nraw=nchange(snapshot_bits=0, fifo_free=65535)), True)
        accepted('historical_after_grant', run(change(flags=flags & ~16)))
        accepted('historical_after_failed_submit', run(change(flags=flags & ~(8 | 16))))
        accepted('age65535_is_valid_with_flag', run(change(evaluated_age_us=65535)), True)
        accepted('DWT_zero_is_valid_event', run(change(event_cycle=0), nraw=nchange(begin_cycle=0)), True)
        unknown = dict(publication_serial=0, event_cycle=0, total_len=65535, queued_len=65535,
                       evaluated_age_us=65535, remaining_budget=255, decision=0)
        unobserved = accepted('unobserved_initial', run(change(flags=3 | (1 << 9), **unknown)))
        need(unobserved['history'] is None and unobserved['nominal_event_timing'] is None, unobserved)
        accepted('sticky_metadata_U', run(change(flags=3 | 4 | 128, decision=4,
                 total_len=65535, queued_len=65535, evaluated_age_us=65535, remaining_budget=255)))
        accepted('sticky_lifecycle_history', run(change(flags=(flags & ~(8 | 16)) | 256)))
        accepted('sticky_serial_saturation', run(change(flags=(flags & ~(8 | 16)) | 64,
                 publication_serial=0xffffffff)))
        accepted('ZLP_published', run(change(flags=3 | 4 | 8 | 4096, decision=1,
                 total_len=0, queued_len=0, evaluated_age_us=65535, remaining_budget=255)))
        accepted('ZLP_final', run(change(flags=3 | 4 | 16 | 4096, decision=3,
                 total_len=0, queued_len=0, evaluated_age_us=65535)), True)
        for age_valid in (False, True):
            accepted('status_' + ('after_TIME' if age_valid else 'before_TIME'),
                     run(change(flags=flags if age_valid else flags & ~32,
                                decision=9, evaluated_age_us=499 if age_valid else 65535)), True)

        pd = actual['paired_progress']['raw']
        accepted('paired_DWT_invalid_no_window_attribution', run(nraw=nchange(flags=pd['flags'] | 32)))
        cap_progress = nchange(close_kind=5, flags=pd['flags'] & 0xffff,
            end_cycle=pd['begin_cycle'] + decoder.progress_decoder.CAP,
            max_positive_gap_cycles=pd['begin_cycle'] + decoder.progress_decoder.CAP - pd['last_positive_cycle'])
        accepted('CAP_not_later_fault', run(change(flags=flags | 2048), nraw=cap_progress))
        noactive_fields = dict(flags=4 | (1 << 10), close_kind=9,
            begin_cycle=0, end_cycle=0, prepare_cycles=0, positive_bytes=0,
            last_positive_cycle=0, max_positive_gap_cycles=0, prepare_count=0,
            positive_count=0, zero_space_count=0, zero_other_count=0,
            tx_offset=65535, tx_length=65535, stage_count=65535, fifo_free=65535,
            stage_phase=255, queue_used=255, snapshot_bits=0)
        accepted('NO_ACTIVE_unknown_only', run(change(flags=3 | 512 | 1024, **unknown),
                                              nraw=nchange(**noactive_fields)))
        rejected('NO_ACTIVE_fabricated_history', run(change(flags=flags | 1024),
                                                  nraw=nchange(**noactive_fields)))
        # The progress change is an additive explicit-build allowlist only.
        for old_build in (decoder.progress_decoder.BUILD, 0x5632534a):
            old_legacy = dict(legacy, raw=dict(legacy['raw'], firmware_build=old_build))
            value = decoder.progress_decoder.decode(progress, progress, old_legacy, nonce,
                generation, args.image_sha256, old_build)
            need(value['accepted_frozen_record'], ('historical progress build', value))
        value = decoder.progress_decoder.decode(progress, progress, legacy, nonce,
                                                generation, args.image_sha256)
        need(not value['accepted_frozen_record'], 'SK must not use the legacy default')
        value = decoder.progress_decoder.decode(progress, progress, legacy, nonce,
                                                generation, args.image_sha256, 0x5632534d)
        need(not value['accepted_frozen_record'] and 'unsupported_expected_build' in value['errors'],
             'Future progress build must remain unsupported')
        report['old_progress_builds_preserved_SK_requires_explicit_build'] = True
        report['status'] = 'PASS'
    except BaseException as exc:
        report['status'] = 'FAILED'
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        report['input_drift'] = [path for path, value in inputs.items() if sha(Path(path)) != value]
        if report['input_drift']:
            report['status'] = 'FAILED_INPUT_DRIFT'
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'result': str(output),
                      'actual_C_gate_sha256': inputs[str(args.gate_fixture.resolve())]}))


if __name__ == '__main__':
    main()
