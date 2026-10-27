"""One SF/SE serializer differential and actual-core witness; no hardware or host rerun."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(ok, message):
    if not ok:
        raise ValueError(message)


def tokens(source):
    return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S',
                      re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S))


def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,
         'Run python -I -B')
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('image', 'baseline', 'zig', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    image, baseline = args.image.resolve(), args.baseline.resolve()
    zig, out = args.zig.resolve(strict=True), args.output.resolve()
    need(out.is_relative_to(root / 'build') and not out.exists(), 'Use a new build output')
    out.mkdir()
    inputs, commands = {}, []
    result = {'status': 'RUNNING', 'scope': __doc__, 'inputs': inputs, 'commands': commands}

    def read(path):
        inputs[str(path)] = sha(path)
        return path.read_text('utf8')

    def copy(path, relative):
        read(path)
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())

    def run(label, argv):
        row = {'label': label, 'argv': [str(item) for item in argv]}
        commands.append(row)
        process = subprocess.run(row['argv'], cwd=out, env=env, capture_output=True, timeout=180)
        row['exit_code'] = process.returncode
        (out / (label + '.stdout')).write_bytes(process.stdout)
        (out / (label + '.stderr')).write_bytes(process.stderr)
        need(process.returncode == 0, label + ' failed; evidence retained')
        return process.stdout.decode('utf8')

    try:
        read(Path(__file__).resolve())
        inputs[str(zig)] = sha(zig)
        current = json.loads(read(image / 'receipt.json'))
        old = json.loads(read(baseline / 'receipt.json'))
        need(current['status'] == old['status'] == 'BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE',
             'Unfinished ARM image')
        need(current['config']['firmware_build'] == 0x56325346 and
             old['config']['firmware_build'] == 0x56325345, 'Wrong SF/SE basis')
        previous_config = json.loads(json.dumps(old['config']))
        previous_config['firmware_build'] = 0x56325346
        previous_config['usb']['product'] = 'Motortester V2 Batch1024 SF'
        need(previous_config == current['config'], 'Configuration changed beyond build/product identity')

        helper = Path(__file__).with_name('check_usb_gate.py')
        read(helper)
        spec = importlib.util.spec_from_file_location('extract_sf', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = module.function
        shared = root / 'firmware/v2-stream/batch1024'
        old_c = read(baseline / 'patched/v2/protocol/mt_batch1024.c')
        new_c = read(image / 'patched/v2/protocol/mt_batch1024.c')
        need(old_c == read(shared / 'mt_batch1024.c'), 'Frozen prototype/SE C changed')
        need(new_c == read(shared / 'production/mt_batch1024.c'), 'Production recipe chose a different C')
        names = ('begin', 'collect', 'seal', 'step', 'piece', 'accepted', 'commit', 'abort')
        for name in names:
            if name != 'step':
                need(function(old_c, 'mt_batch1024_' + name) ==
                     function(new_c, 'mt_batch1024_' + name), 'Unchanged serializer body drift: ' + name)
        need(tokens(read(image / 'patched/v2/protocol/mt_batch1024.h')) ==
             tokens(read(baseline / 'patched/v2/protocol/mt_batch1024.h')), 'Serializer ABI changed')
        need('restrict' not in new_c, 'Unreviewed restrict contract')

        unchanged = []
        for path in sorted((baseline / 'patched').rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(baseline / 'patched')
            if relative.as_posix() in ('v2/protocol/mt_batch1024.c', 'v2/protocol/mt_batch1024.h'):
                continue
            target = image / 'patched' / relative
            read(path)
            read(target)
            need(path.read_bytes() == target.read_bytes(), 'Preserved SE source changed: ' + str(relative))
            unchanged.append({'path': relative.as_posix(), 'sha256': sha(target)})
        for name in ('mt_timebase.c', 'mt_timebase.h'):
            need(read(baseline / 'source/firmware/platform' / name) ==
                 read(image / 'source/firmware/platform' / name), 'Original TIME drift')
        need(current['firmware_tree'] == old['firmware_tree'], 'Upstream source tree changed')
        proof = {'status': 'PASS', 'unchanged_SE_patched_sources': unchanged,
                 'serializer_changed_function': 'mt_batch1024_step',
                 'other_seven_serializer_functions_exact_equal': True,
                 'serializer_API_token_identical': True,
                 'core_runtime_TIME_ADC_DMA_DCD_USB_queue_byte_identical': True,
                 'build_config_delta_only_build_and_product': True,
                 'no_performance_or_hardware_claim': True}
        (out / 'source-equivalence.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf8')

        copy(baseline / 'patched/v2/protocol/mt_batch1024.c', 'se.c')
        copy(image / 'patched/v2/protocol/mt_batch1024.c', 'sf.c')
        copy(image / 'patched/v2/protocol/mt_batch1024.h', 'mt_batch1024.h')
        for name in ('mt_wire.c', 'mt_wire.h', 'mt_v2_crc32.h'):
            path = image / 'patched/v2/protocol' / name
            if not path.exists():
                path = image / 'source/firmware/protocol' / name
            copy(path, name)
        copy(Path(__file__).with_name('batch1024_local_model.c'), 'local-model.c')
        (out / 'temp').mkdir()
        env = dict(os.environ, ZIG_LOCAL_CACHE_DIR=str(out / 'zig-cache'),
                   ZIG_GLOBAL_CACHE_DIR=str(out / 'zig-global'), TMP=str(out / 'temp'), TEMP=str(out / 'temp'))
        version = run('version', [zig, 'version']).strip()
        common = [zig, 'cc', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-I.']
        for prefix in ('se', 'sf'):
            aliases = ['-Dmt_batch1024_' + name + '=' + prefix + '_' + name for name in names]
            run('compile-' + prefix, [*common, *aliases, '-c', prefix + '.c', '-o', prefix + '.o'])
        run('compile-differential', [*common, 'local-model.c', 'se.o', 'sf.o', 'mt_wire.c', '-o', 'differential.exe'])
        differential_stdout = run('differential', [out / 'differential.exe'])

        sources = []
        for area, filenames in {
            'protocol': ['mt_live_device.c', 'mt_live_device.h', 'mt_wire.c', 'mt_wire.h',
                         'mt_v2_crc32.h', 'mt_batch1024.c', 'mt_batch1024.h'],
            'acquisition': ['mt_sample_queue.c', 'mt_sample_queue.h',
                            'mt_acquisition_profile.c', 'mt_acquisition_profile.h'],
        }.items():
            for name in filenames:
                path = image / 'patched/v2' / area / name
                if not path.exists():
                    path = image / 'source/firmware' / area / name
                need(current['inputs_before'].get(str(path)) == sha(path), 'Exact image source drift: ' + str(path))
                copy(path, area + '/' + name)
                if name.endswith('.c'):
                    sources.append(area + '/' + name)
        runtime = read(image / 'patched/v2/app/mt_live_runtime.c')
        model = read(Path(__file__).with_name('batch1024_core_model.c'))
        need(model.count('/* PREPARED_TX_HELPER */') == 1, 'Actual runtime helper seam changed')
        (out / 'core-model.c').write_text(model.replace('/* PREPARED_TX_HELPER */',
                                                     function(runtime, 'prepared_tx_step')),
                                        encoding='utf8', newline='\n')
        run('compile-core', [*common, '-Iprotocol', '-Iacquisition', 'core-model.c',
                             *sources, '-o', 'core-model.exe'])
        core_stdout = run('core', [out / 'core-model.exe', out / 'core1153-transcript.bin'])
        prior_native = root / 'build/v6l-core-native-01'
        native_record = json.loads(read(prior_native / 'result.json'))
        previous_fixture = prior_native / 'core1153-transcript.bin'
        inputs[str(previous_fixture)] = sha(previous_fixture)
        need(native_record['status'] == 'PASS' and native_record['C_fixture_sha256'] == sha(previous_fixture),
             'SE actual-core fixture pin changed')
        need((out / 'core1153-transcript.bin').read_bytes() == previous_fixture.read_bytes(),
             'Actual-core wire fixture differs from frozen SE')
        result.update(status='PASS', compiler_version=version, differential_stdout=differential_stdout,
                      actual_core_stdout=core_stdout, source_equivalence_sha256=sha(out / 'source-equivalence.json'),
                      image_bin_sha256=current['artifacts']['MotortesterV2-stream-candidate.bin'],
                      C_fixture_sha256=sha(out / 'core1153-transcript.bin'), fixture_byte_identical_SE=True,
                      native_io_build_id='0x56325345 in unchanged model for exact SE fixture comparison; SF image identity is ARM config0x56325346',
                      seams=['Actual serializer APIs with disjoint buffers and constructed bounded states',
                             'Unchanged actual-core model plus exact extracted prepared runtime helper; logical clock/IO/Stop seams',
                             'Not execution of entire runtime/physical peripherals; synthetic CRC/COBS lifecycle reconstruction'],
                      not_verified=['Physical150k throughput or ADC service WCET', 'Analog accuracy', 'Flash approval'])
    except BaseException as error:
        result.update(status='FAILED', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        drift = [path for path, expected in inputs.items()
                 if not Path(path).is_file() or sha(Path(path)) != expected]
        result['input_drift'] = drift
        if drift:
            result['status'] = 'FAILED_INPUT_DRIFT'
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8', newline='\n')
    print(json.dumps({'status': result['status'], 'result': str(out / 'result.json')}))


if __name__ == '__main__':
    main()
