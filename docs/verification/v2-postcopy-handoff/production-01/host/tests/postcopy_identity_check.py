"""One SK/SL identity check using saved actual-C24/64/136 fixtures.

Only build/image/session binding changes are exercised. The old structural
decoder suite and native producer are not rerun. Fixtures and legacy setup
are synthetic evidence, never hardware authentication or performance data.
"""
from pathlib import Path
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import struct
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / 'host/tools/decode_usb_gate.py'
PROGRESS = ROOT / 'host/tools/decode_stream_progress.py'
SK, SL, SM = 0x5632534B, 0x5632534C, 0x5632534D
ARCHIVED_SK = ROOT / 'docs/verification/v2-usb-gate/production-01/build/v6r-native-01'
spec = importlib.util.spec_from_file_location('postcopy_gate_decoder', GATE)
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,
         'Use Python -I -B without optimization')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sl-fixtures', type=Path, required=True)
    ap.add_argument('--sk-image-sha256', required=True)
    ap.add_argument('--sl-image-sha256', required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    need(output.parent == ROOT / 'build' and output.name.startswith('v6s-host-')
         and not output.exists(), 'Use a new build/v6s-host-* output directory')
    output.mkdir()
    inputs = {}
    report = {'schema': 'v2-06s-offline-identity-check-1', 'status': 'RUNNING',
              'argv': sys.argv, 'python': sys.version, 'inputs': inputs, 'checks': [],
              'hardware_executed': False, 'native_producer_rerun': False,
              'legacy_binding_is_synthetic': True, 'physical_throughput_claim': False,
              'limits': ['Repeated fixture bytes are API inputs, not two independent RAM reads.',
                         'Gate24 has no embedded build/session; paired evidence and declared pins are not authentication.',
                         'N_CLOSING/history/CAP/skew restrictions remain those of the R decoder.']}

    def read(path, bound=1024 * 1024):
        path = path.resolve()
        raw = decoder.progress_decoder.saved(path, bound)
        inputs[str(path)] = {'bytes': len(raw), 'sha256': sha(raw)}
        return raw

    def load_fixture(label, folder, build, image):
        raw = {name: read(folder / name, size) for name, size in
               (('actual-gate.bin', 24), ('actual-progress.bin', 64), ('actual-legacy.bin', 136))}
        producer_bytes, companion_bytes = read(folder / 'result.json'), read(folder / 'companion.json')
        producer = json.loads(producer_bytes.decode('utf-8-sig'))
        companion = json.loads(companion_bytes.decode('utf-8-sig'))
        need(producer.get('status') == 'PASS' and producer.get('image_bin_sha256') == image,
             label + ' producer/image pin mismatch')
        need(companion.get('origin') == 'SYNTHETIC_NATIVE_C_SETUP_NOT_PHYSICAL'
             and companion.get('legacy_module_not_executed') is True
             and companion.get('firmware_build') == f'0x{build:08x}'
             and companion.get('image_bin_sha256') == image, label + ' companion binding')
        header_pin = companion.get('generated_header_sha256')
        header_inputs = [value for path, value in producer.get('inputs', {}).items()
                         if path.replace('\\', '/').endswith('/generated/mt_firmware_build.h')]
        need(isinstance(header_pin, str) and len(header_pin) == 64 and header_pin in header_inputs,
             label + ' generated common build header pin missing from producer')
        nonce, generation = int(companion['nonce_hex'], 16), companion['generation']
        need(nonce != 0 and isinstance(generation, int) and 0 < generation <= 0xffffffff,
             label + ' invalid fixture session')
        for name, data in raw.items():
            need(companion.get('fixtures', {}).get(name) == sha(data)
                 and producer.get('fixtures', {}).get(name) == sha(data), label + ' fixture SHA: ' + name)
        words = struct.unpack('<34I', raw['actual-legacy.bin'])
        need(words[:3] == (0x4d544447, 1, 136) and words[3] == build and words[4] == 3
             and words[6] == generation and (words[32] | words[33] << 32) == nonce,
             label + ' actual C legacy identity mismatch')
        legacy = {'accepted_frozen_record': True, 'errors': [],
                  'raw': dict(firmware_build=words[3], phase=words[4], flags=words[5],
                              generation=words[6], nonce_low=words[32], nonce_high=words[33]),
                  'exact_candidate': {'image_bin_sha256': image},
                  'origin': 'Actual native-C legacy136 with synthetic setup, not a physical readback'}
        copied = output / label
        copied.mkdir()
        for name, data in dict(raw, **{'producer-result.json': producer_bytes,
                                      'companion.json': companion_bytes}).items():
            (copied / name).write_bytes(data)
            need((copied / name).read_bytes() == data, label + ' evidence copy mismatch')
        write_json(copied / 'legacy-binding.json', legacy)
        report[label] = {'firmware_build': f'0x{build:08x}', 'nonce_hex': f'{nonce:016x}',
                         'generation': generation, 'image_sha256': image,
                         'generated_header_sha256': header_pin, 'fixture_sha256': companion['fixtures']}
        return dict(raw=raw, legacy=legacy, nonce=nonce, generation=generation, image=image, build=build)

    def decode(fixture, **changes):
        data = dict(fixture, **changes)
        raw = data['raw']
        return decoder.decode(raw['actual-gate.bin'], raw['actual-gate.bin'],
                              raw['actual-progress.bin'], raw['actual-progress.bin'],
                              data['legacy'], data['nonce'], data['generation'], data['image'], data['build'])

    def rejected(label, value, error=None):
        need(not value['accepted_frozen_record'] and value['errors'], (label, value))
        if error:
            need(error in value['errors'], (label, value))
        report['checks'].append({'case': label, 'kind': 'reject', 'errors': value['errors']})

    try:
        for source in (Path(__file__), GATE, PROGRESS,
                       ROOT / 'host/tests/usb_gate_decoder_check.py',
                       ROOT / 'host/tests/stream_progress_decoder_check.py',
                       ROOT / 'docs/streaming-postcopy-handoff.md', ROOT / 'docs/streaming-usb-gate.md'):
            read(source)
        need(decoder.BUILD == SK and decoder.SUPPORTED_BUILDS == (SK, SL), 'Gate build defaults/allowlist')
        progress = decoder.progress_decoder
        need(progress.BUILD == 0x56325347 and progress.decode.__defaults__ == (0x56325347,),
             'Progress implicit build must remain SG')
        need(progress.SUPPORTED_BUILDS == tuple(range(0x56325347, SL + 1)), 'Progress historical builds')
        sk = load_fixture('sk', ARCHIVED_SK, SK, args.sk_image_sha256)
        sl = load_fixture('sl', args.sl_fixtures.resolve(), SL, args.sl_image_sha256)
        for label, fixture in (('SK', sk), ('SL', sl)):
            value = decode(fixture)
            need(value['accepted_frozen_record'] and not value['errors'], (label, value))
            need(value['expected_build'] == f"0x{fixture['build']:08x}"
                 and value['physical_identity_verified'] is False
                 and value['timing_qualified'] is False
                 and value['same_episode_as_later64_proven'] is False
                 and value['current64_causal_attribution_available'] is False, label + ' limits changed')
            write_json(output / label.lower() / 'decoded.json', value)
            report['checks'].append({'case': label + '_actual_C_explicit', 'kind': 'valid_with_limits'})
            rejected(label + '_crossed_build', decode(fixture, build=SL if label == 'SK' else SK))
        rejected('SL_foreign_image', decode(sl, image='0' * 64))
        rejected('SL_foreign_nonce', decode(sl, nonce=sl['nonce'] ^ 1))
        rejected('SL_foreign_generation', decode(sl, generation=sl['generation'] + 1))
        rejected('SM_gate_unsupported', decode(sl, build=SM), 'unsupported_expected_gate_build')
        nraw = sl['raw']['actual-progress.bin']
        value = progress.decode(nraw, nraw, sl['legacy'], sl['nonce'], sl['generation'], sl['image'], SM)
        rejected('SM_progress_unsupported', value, 'unsupported_expected_build')
        value = progress.decode(nraw, nraw, sl['legacy'], sl['nonce'], sl['generation'], sl['image'])
        rejected('SL_requires_explicit_progress_build', value, 'legacy_build_session_image_binding_invalid')
        need(value['expected_build'] == '0x56325347', 'Progress default silently changed')

        # Exercise the unchanged required CLI option without reaching any file read.
        cli = [str(GATE), 'first', 'second', '--progress-first', 'p1', '--progress-second', 'p2',
               '--legacy', 'legacy', '--nonce', '1', '--generation', '1', '--image-sha256', '0' * 64]
        stderr = io.StringIO()
        with patch.object(sys, 'argv', cli), contextlib.redirect_stderr(stderr):
            try:
                decoder.main()
            except SystemExit as exc:
                need(exc.code == 2 and '--build-id' in stderr.getvalue(), 'Gate CLI no longer requires build')
            else:
                raise AssertionError('Gate CLI accepted missing --build-id')
        report['checks'].append({'case': 'gate_CLI_requires_explicit_build', 'kind': 'reject_before_file_read'})
        report['status'] = 'PASS'
    except BaseException as exc:
        report['status'] = 'FAILED'
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        report['input_drift'] = [path for path, pin in inputs.items()
                                 if sha(Path(path).read_bytes()) != pin['sha256']]
        if report['input_drift']:
            report['status'] = 'FAILED_INPUT_DRIFT'
        report['outputs'] = {str(path.relative_to(output)): {'bytes': path.stat().st_size,
                              'sha256': sha(path.read_bytes())} for path in output.rglob('*') if path.is_file()}
        write_json(output / 'result.json', report)
    need(report['status'] == 'PASS', report['status'])
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'result': str(output / 'result.json')}))


if __name__ == '__main__':
    main()
