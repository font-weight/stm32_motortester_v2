"""One focused check of the offline decoder against the native C64 fixture.

The companion is synthetic metadata or an explicitly supplied native-C bank;
neither originates from hardware or authenticates a physical build.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import struct

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('progress_decoder', ROOT/'host/tools/decode_stream_progress.py')
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixture', type=Path, required=True)
    ap.add_argument('--image-sha256', required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--build-id', type=lambda value: int(value, 0), default=decoder.BUILD,
                    choices=decoder.SUPPORTED_BUILDS)
    ap.add_argument('--legacy-bin', type=Path,
                    help='Native-C legacy136 fixture; never a physical qualification')
    ap.add_argument('--fixture-profile', choices=('fault-markers', 'clean'), default='fault-markers')
    args = ap.parse_args()
    args.output.mkdir(exist_ok=False)
    raw = args.fixture.read_bytes()
    nonce, gen = 0x0123456789abcdef, 7
    legacy = {'accepted_frozen_record': True, 'errors': [],
              'raw': {'firmware_build': args.build_id, 'generation': gen, 'phase': 3,
                      'nonce_low': nonce & 0xffffffff, 'nonce_high': nonce >> 32, 'flags': 4},
              'exact_candidate': {'image_bin_sha256': args.image_sha256},
              'origin': 'synthetic decoder binding fixture, not physical legacy dump'}
    if args.legacy_bin:
        legacy_bytes = args.legacy_bin.read_bytes()
        words = struct.unpack('<34I', legacy_bytes)
        assert words[:3] == (0x4d544447, 1, 136), words[:3]
        assert words[3] == args.build_id and words[4] == 3 and words[6] == gen
        assert (words[32] | words[33] << 32) == nonce
        legacy['raw'] = dict(firmware_build=words[3], phase=words[4], flags=words[5],
                             generation=words[6], nonce_low=words[32], nonce_high=words[33])
        legacy['origin'] = 'actual native-C legacy136 bank with synthetic setup; not physical'
    def decode(first=raw, second=None, **kwargs):
        return decoder.decode(first, first if second is None else second, kwargs.get('legacy', legacy),
                              kwargs.get('nonce', nonce), kwargs.get('generation', gen),
                              kwargs.get('image_sha256', args.image_sha256),
                              kwargs.get('expected_build', args.build_id))
    def change(**fields):
        values = dict(zip(decoder.FIELDS, decoder.LAYOUT.unpack(raw)))
        values.update(fields)
        return decoder.LAYOUT.pack(*(values[name] for name in decoder.FIELDS))
    result = decode()
    assert result['accepted_frozen_record'] and not result['errors'], result
    d = result['raw']
    expected = {'begin_cycle': 1000, 'end_cycle': 5000, 'prepare_cycles': 400,
                'prepare_count': 1, 'positive_bytes': 401, 'positive_count': 2,
                'last_positive_cycle': 2400, 'max_positive_gap_cycles': 2600,
                'zero_space_count': 1, 'zero_other_count': 1,
                'tx_offset': 384, 'tx_length': 1335, 'stage_count': 1024,
                'stage_phase': 4, 'queue_used': 8, 'fifo_free': 128, 'snapshot_bits': 15,
                'close_kind': 1}
    assert all(d[k] == v for k, v in expected.items()), d
    assert result['primary_reason'] == 1 and result['nominal_timing']['elapsed_cycles'] == 4000
    if args.fixture_profile == 'fault-markers':
        assert set(('partial_write', 'unknown_write', 'partial_prepare')).issubset(result['warnings'])
    else:
        assert not result['warnings'], result['warnings']
    assert result['core_snapshot']['start_ack_pending'] is False
    checks = []
    def reject(name, value):
        assert not value['accepted_frozen_record'] and value['errors'], (name, value)
        assert value['nominal_timing'] is None, (name, value)
        checks.append({'case': name, 'errors': value['errors']})
    reject('wrong_size', decode(raw[:-1]))
    reject('unequal_pair', decode(second=bytes([raw[0] ^ 1])+raw[1:]))
    reject('not_frozen', decode(change(flags=(d['flags'] & ~7) | 2)))
    reject('foreign_nonce', decode(nonce=nonce ^ 1))
    reject('foreign_generation', decode(generation=gen+1))
    reject('wrong_image_binding', decode(image_sha256='0'*64))
    reject('wrong_typed_primary', decode(change(close_kind=11)))
    reject('noactive_with_history', decode(change(flags=d['flags'] | (1 << 10))))
    reject('short_cap', decode(change(close_kind=5, flags=d['flags'] & 0xffff)))
    reject('prepare_without_count', decode(change(prepare_count=0)))
    reject('impossible_positive_count', decode(change(positive_count=500)))
    reject('unavailable_FIFO_not_sentinel', decode(change(snapshot_bits=0)))
    reject('missing_close_tail', decode(change(max_positive_gap_cycles=2599)))
    sh_legacy = dict(legacy, raw=dict(legacy['raw'], firmware_build=0x56325348))
    sh_result = decode(legacy=sh_legacy, expected_build=0x56325348)
    assert sh_result['accepted_frozen_record'] and sh_result['expected_build'] == '0x56325348'
    reject('SH_requires_explicit_build', decode(legacy=sh_legacy, expected_build=decoder.BUILD))
    sg_legacy = dict(legacy, raw=dict(legacy['raw'], firmware_build=decoder.BUILD))
    reject('SG_not_SH', decode(legacy=sg_legacy, expected_build=0x56325348))
    si_legacy = dict(legacy, raw=dict(legacy['raw'], firmware_build=0x56325349))
    assert decode(legacy=si_legacy, expected_build=0x56325349)['accepted_frozen_record']
    reject('SI_requires_explicit_build', decode(legacy=si_legacy, expected_build=decoder.BUILD))
    reject('SH_not_SI', decode(legacy=sh_legacy, expected_build=0x56325349))
    sj_legacy = dict(legacy, raw=dict(legacy['raw'], firmware_build=0x5632534a))
    assert decode(legacy=sj_legacy, expected_build=0x5632534a)['accepted_frozen_record']
    reject('SI_not_SJ', decode(legacy=si_legacy, expected_build=0x5632534a))
    reject('unsupported_build', decode(expected_build=0x5632534b))
    reject('empty_observer_bank', decode(bytes(64)))
    # Legal unavailable snapshot stays unknown; it must never be rendered as0.
    unavailable = decode(change(snapshot_bits=0, fifo_free=65535))
    assert unavailable['accepted_frozen_record'] and unavailable['USB_snapshot'] is None
    time_close = decode(change(close_kind=11, flags=(d['flags'] & 0xffff) | (2 << 16)))
    assert time_close['accepted_frozen_record'] and time_close['close_kind'] == 'time'
    report = {'status': 'PASS', 'scope': 'One native-C-fixture decode plus bounded malformed-evidence group',
              'fixture_sha256': hashlib.sha256(raw).hexdigest(),
              'decoder_sha256': hashlib.sha256((ROOT/'host/tools/decode_stream_progress.py').read_bytes()).hexdigest(),
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'known_fixture_fields': expected, 'negative_checks': checks,
              'unknown_FIFO_preserved': True, 'typed_TIME_supported': True,
              'legacy_binding_is_synthetic': True, 'hardware_executed': False,
              'native_legacy136_used': args.legacy_bin is not None,
              'native_legacy136_sha256': hashlib.sha256(legacy_bytes).hexdigest() if args.legacy_bin else None,
              'expected_build': hex(args.build_id),
              'fixture_profile': args.fixture_profile,
              'SG_default_and_explicit_SH_SI_SJ_checked': True,
              'physical_throughput_claim': False}
    (args.output/'fixture-decoded.json').write_text(json.dumps(result, indent=2)+'\n',encoding='utf-8')
    (args.output/'result.json').write_text(json.dumps(report, indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status': report['status'], 'negative_cases': len(checks), 'fixture_sha256': report['fixture_sha256']}))


if __name__ == '__main__':
    main()
