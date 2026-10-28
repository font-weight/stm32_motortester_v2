"""One SL/SN offline identity check; SN records are explicitly synthetic.

Reuse archived actual-C SL24/64/136, changing only the legacy build word for
the SN derivation. This does not execute SN observers, reproduce an SN fault,
authenticate a board, or rerun the old structural/native checks.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / 'host/tools/decode_usb_gate.py'
PROGRESS = ROOT / 'host/tools/decode_stream_progress.py'
ARCHIVED_SL = ROOT / 'docs/verification/v2-postcopy-handoff/production-01/build/v6s-native-01'
SL, SM, SN, SO = 0x5632534C, 0x5632534D, 0x5632534E, 0x5632534F
ORIGIN = 'SYNTHETIC_DERIVATION_OF_ACTUAL_SL_FIXTURE_NOT_ACTUAL_SN_EXECUTION'
spec = importlib.util.spec_from_file_location('collect_gate_decoder', GATE)
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,
         'Use Python -I -B without optimization')
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sn-build', type=Path, required=True)
    ap.add_argument('--sn-image-sha256', required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    need(output.parent == ROOT / 'build' and output.name.startswith('v6u-host-')
         and not output.exists(), 'Use a new build/v6u-host-* directory')
    output.mkdir()
    inputs = {}
    report = {'schema': 'v2-06u-offline-identity-check-1', 'status': 'RUNNING',
              'argv': sys.argv, 'python': sys.version, 'inputs': inputs, 'checks': [],
              'sn_fixture_origin': ORIGIN, 'sn_observer_executed': False,
              'hardware_executed': False, 'native_producer_rerun': False,
              'physical_throughput_claim': False,
              'limits': ['Paired bytes are repeated fixture inputs, not independent RAM reads.',
                         'Gate24 has no embedded build/session; declared pins are not authentication.',
                         'N_CLOSING/history/CAP/skew restrictions are unchanged.',
                         'SN ARM header/image binding does not make the derived fixture an SN execution.']}

    def read(path, bound=1024 * 1024):
        path = path.resolve()
        raw = decoder.progress_decoder.saved(path, bound)
        inputs[str(path)] = {'bytes': len(raw), 'sha256': sha(raw)}
        return raw

    def copied(folder, name, raw):
        (folder / name).write_bytes(raw)
        need((folder / name).read_bytes() == raw, 'Evidence copy mismatch: ' + name)

    def reject(label, value, error=None):
        need(not value['accepted_frozen_record'] and value['errors'], (label, value))
        need(error is None or error in value['errors'], (label, value))
        report['checks'].append({'case': label, 'errors': value['errors']})

    try:
        for source in (Path(__file__), GATE, PROGRESS):
            read(source)
        progress = decoder.progress_decoder
        need(decoder.BUILD == 0x5632534B and decoder.SUPPORTED_BUILDS == (0x5632534B, SL, SN),
             'Gate default or historical build allowlist changed')
        need(progress.BUILD == 0x56325347 and progress.decode.__defaults__ == (0x56325347,)
             and progress.SUPPORTED_BUILDS == tuple(range(0x56325347, SL + 1)) + (SN,),
             'Progress default or historical build allowlist changed')

        raw = {name: read(ARCHIVED_SL / ('actual-' + name + '.bin'), size)
               for name, size in (('gate', 24), ('progress', 64), ('legacy', 136))}
        producer_raw, companion_raw = read(ARCHIVED_SL / 'result.json'), read(ARCHIVED_SL / 'companion.json')
        producer, companion = json.loads(producer_raw), json.loads(companion_raw)
        sl_image = companion['image_bin_sha256']
        need(producer['status'] == 'PASS' and producer['image_bin_sha256'] == sl_image
             and companion['firmware_build'] == f'0x{SL:08x}'
             and companion['origin'] == 'SYNTHETIC_NATIVE_C_SETUP_NOT_PHYSICAL'
             and companion['legacy_module_not_executed'] is True, 'Archived SL producer binding')
        header_pins = [pin for path, pin in producer['inputs'].items()
                       if path.replace('\\', '/').endswith('/generated/mt_firmware_build.h')]
        need(companion['generated_header_sha256'] in header_pins, 'Archived SL header binding')
        for name, data in raw.items():
            key = 'actual-' + name + '.bin'
            need(companion['fixtures'][key] == sha(data) == producer['fixtures'][key], 'Archived SL fixture pin')
        nonce, generation = int(companion['nonce_hex'], 16), companion['generation']
        words = struct.unpack('<34I', raw['legacy'])
        need(words[:3] == (0x4D544447, 1, 136) and words[3:5] == (SL, 3)
             and words[6] == generation and (words[32] | words[33] << 32) == nonce,
             'Archived SL legacy identity')
        sl_folder, sn_folder = output / 'sl-actual-C', output / 'sn-synthetic-derived'
        sl_folder.mkdir(); sn_folder.mkdir()
        for name, data in raw.items():
            copied(sl_folder, 'actual-' + name + '.bin', data)
        copied(sl_folder, 'producer-result.json', producer_raw)
        copied(sl_folder, 'companion.json', companion_raw)

        build = args.sn_build.resolve()
        receipt_raw, header_raw = read(build / 'receipt.json'), read(build / 'generated/mt_firmware_build.h')
        image_raw = read(build / 'MotortesterV2-stream-candidate.bin', 65536)
        receipt = json.loads(receipt_raw)
        need(receipt['status'] == 'BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE'
             and receipt['config']['firmware_build'] == SN and receipt['input_drift'] == []
             and receipt['artifacts']['MotortesterV2-stream-candidate.bin'] == sha(image_raw) == args.sn_image_sha256,
             'Exact SN ARM receipt/image binding')
        macros = re.findall(rb'^#define MT_FIRMWARE_BUILD UINT32_C\((0x[0-9a-fA-F]+)\)\r?$', header_raw, re.M)
        need(len(macros) == 1 and int(macros[0], 16) == SN, 'SN generated common build header')
        copied(sn_folder, 'arm-receipt.json', receipt_raw)
        copied(sn_folder, 'mt_firmware_build.h', header_raw)
        derived = raw['legacy'][:12] + struct.pack('<I', SN) + raw['legacy'][16:]
        need(derived[:12] == raw['legacy'][:12] and derived[16:] == raw['legacy'][16:], 'Derivation changed non-build fields')
        for name, data in dict(raw, legacy=derived).items():
            copied(sn_folder, 'synthetic-' + name + '.bin', data)
        report['derivation'] = {'origin': ORIGIN, 'changed_field': 'legacy136 firmware_build',
                                'offset': 12, 'bytes': 4, 'from': f'0x{SL:08x}', 'to': f'0x{SN:08x}',
                                'source_legacy_sha256': sha(raw['legacy']), 'derived_legacy_sha256': sha(derived),
                                'gate24_unchanged': True, 'progress64_unchanged': True}
        write_json(sn_folder / 'derivation.json', report['derivation'])
        report['identity'] = {'nonce_hex': f'{nonce:016x}', 'generation': generation,
                              'sl_image_sha256': sl_image, 'sn_image_sha256': sha(image_raw),
                              'sn_generated_header_sha256': sha(header_raw)}

        def binding(legacy_bytes, image):
            fields = struct.unpack('<34I', legacy_bytes)
            build_id = fields[3]
            return {'accepted_frozen_record': True, 'errors': [],
                    'origin': ORIGIN if build_id == SN else 'Archived actual-C SL synthetic legacy setup',
                    'raw': dict(firmware_build=build_id, phase=fields[4], flags=fields[5],
                                generation=fields[6], nonce_low=fields[32], nonce_high=fields[33]),
                    'exact_candidate': {'image_bin_sha256': image}}

        def decode(legacy, expected, image):
            return decoder.decode(raw['gate'], raw['gate'], raw['progress'], raw['progress'],
                                  legacy, nonce, generation, image, expected)

        sl, sn = binding(raw['legacy'], sl_image), binding(derived, sha(image_raw))
        for label, folder, legacy, expected, image in (
                ('SL_actual_C', sl_folder, sl, SL, sl_image),
                ('SN_synthetic_derived', sn_folder, sn, SN, sha(image_raw))):
            value = decode(legacy, expected, image)
            need(value['accepted_frozen_record'] and value['errors'] == [] and
                 all(value[field] is False for field in ('physical_identity_verified', 'timing_qualified',
                     'same_episode_as_later64_proven', 'current64_causal_attribution_available')), (label, value))
            write_json(folder / 'legacy-binding.json', legacy)
            write_json(folder / 'decoded.json', value)
            report['checks'].append({'case': label, 'kind': 'valid_with_limits'})
        reject('SL_not_SN', decode(sl, SN, sl_image))
        reject('SN_not_SL', decode(sn, SL, sha(image_raw)))
        reject('SN_foreign_image', decode(sn, SN, '0' * 64))
        for unsupported in (SM, SO):
            reject(f'gate_unsupported_{unsupported:08x}', decode(sn, unsupported, sha(image_raw)), 'unsupported_expected_gate_build')
            value = progress.decode(raw['progress'], raw['progress'], sn, nonce, generation, sha(image_raw), unsupported)
            reject(f'progress_unsupported_{unsupported:08x}', value, 'unsupported_expected_build')
        value = progress.decode(raw['progress'], raw['progress'], sn, nonce, generation, sha(image_raw))
        reject('SN_requires_explicit_build_default_remains_SG', value, 'legacy_build_session_image_binding_invalid')
        report['status'] = 'PASS'
    except BaseException as exc:
        report['status'] = 'FAILED'
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        report['input_drift'] = [path for path, pin in inputs.items() if sha(Path(path).read_bytes()) != pin['sha256']]
        if report['input_drift']:
            report['status'] = 'FAILED_INPUT_DRIFT'
        report['outputs'] = {str(path.relative_to(output)): {'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes())}
                             for path in output.rglob('*') if path.is_file()}
        write_json(output / 'result.json', report)
    need(report['status'] == 'PASS', report['status'])
    print(json.dumps({'status': report['status'], 'checks': len(report['checks']), 'result': str(output / 'result.json')}))


if __name__ == '__main__':
    main()
