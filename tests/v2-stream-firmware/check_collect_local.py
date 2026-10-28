"""One actual-C SL/SN collect differential; no peripheral or throughput claim."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(ok, message):
    if not ok:
        raise ValueError(message)


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
        need(sha(baseline / 'receipt.json') ==
             '8cbc2b57d83e8b610277de5bf41dfb6ff32a538905862481ed11f9b19fced5a9', 'Wrong frozen SL receipt')
        need(current['status'] == old['status'] == 'BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE',
             'Unfinished ARM image')
        need(current['config']['firmware_build'] == 0x5632534e and
             old['config']['firmware_build'] == 0x5632534c, 'Wrong SN/SL basis')
        previous_config = json.loads(json.dumps(old['config']))
        previous_config['firmware_build'] = 0x5632534e
        previous_config['usb']['product'] = 'Motortester V2 Collect Local SN'
        need(previous_config == current['config'], 'Configuration changed beyond build/product identity')
        for folder, receipt in ((image, current), (baseline, old)):
            for name, expected in receipt['artifacts'].items():
                inputs[str(folder / name)] = sha(folder / name)
                need(sha(folder / name) == expected, 'Image artifact drift: ' + str(folder / name))
        read(root / 'build/v6s-freeze.json')

        helper = Path(__file__).with_name('check_usb_gate.py')
        read(helper)
        spec = importlib.util.spec_from_file_location('extract_u', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = module.function
        old_c = read(baseline / 'patched/v2/protocol/mt_batch1024.c')
        new_c = read(image / 'patched/v2/protocol/mt_batch1024.c')
        need(new_c == read(root / 'firmware/v2-stream/batch1024/production/mt_batch1024.c'),
             'Production recipe chose a different serializer')
        names = ('begin', 'collect', 'seal', 'step', 'piece', 'accepted', 'commit', 'abort')
        old_body = function(old_c, 'mt_batch1024_collect')
        new_body = function(new_c, 'mt_batch1024_collect')
        need(old_body != new_body and new_c.replace(new_body, old_body) == old_c,
             'Serializer delta is not exactly one collect body')
        for name in names:
            if name != 'collect':
                need(function(old_c, 'mt_batch1024_' + name) ==
                     function(new_c, 'mt_batch1024_' + name), 'Preserved API body drift: ' + name)
        need('restrict' not in new_c, 'Unreviewed restrict contract')
        unchanged = []
        for path in sorted((baseline / 'patched').rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(baseline / 'patched')
            if relative.as_posix() == 'v2/protocol/mt_batch1024.c':
                continue
            target = image / 'patched' / relative
            read(path)
            read(target)
            need(path.read_bytes() == target.read_bytes(), 'Preserved SL source drift: ' + str(relative))
            unchanged.append({'path': relative.as_posix(), 'sha256': sha(target)})
        need(current['firmware_tree'] == old['firmware_tree'], 'Upstream source tree changed')

        # Exact object equality proves the preserved working code as compiled,
        # not only its C spelling. Common-ID literals are the sole observer delta.
        objects = []
        identity = {'board.o', '29-mt_stream_progress.o'}
        old_id, new_id = (0x5632534c).to_bytes(4, 'little'), (0x5632534e).to_bytes(4, 'little')
        for path in sorted((baseline / 'objects').glob('*.o')):
            target = image / 'objects' / path.name
            read_bytes = path.read_bytes()
            current_bytes = target.read_bytes()
            inputs[str(path)], inputs[str(target)] = sha(path), sha(target)
            if path.name == '28-mt_batch1024.o':
                continue
            if path.name == '29-mt_stream_progress.o':
                need(read_bytes.count(old_id) == 1 and current_bytes.count(new_id) == 1 and
                     read_bytes.replace(old_id, new_id) == current_bytes,
                     'Observer changed beyond the one common build-ID literal')
                verdict = 'EXACT_AFTER_ONE_COMMON_ID_LITERAL'
            elif path.name in identity:
                verdict = 'GENERATED_BOARD_ID_AND_PRODUCT'
            else:
                need(read_bytes == current_bytes, 'Preserved SL ARM object drift: ' + path.name)
                verdict = 'EXACT_BYTES'
            objects.append({'object': path.name, 'baseline_sha256': sha(path),
                            'candidate_sha256': sha(target), 'verdict': verdict})
        build_header = image / 'generated/mt_firmware_build.h'
        need('#define MT_FIRMWARE_BUILD UINT32_C(0x5632534e)' in read(build_header), 'Common SN ID missing')
        for name in ('board', '29-mt_stream_progress'):
            need('generated/mt_firmware_build.h' in read(image / 'objects' / (name + '.d')).replace('\\', '/'),
                 'Common build-header dependency missing: ' + name)
        for receipt in (old, current):
            batch_compile = next(row for row in receipt['commands']
                                 if row['label'] == 'compile-28-mt_batch1024')
            need('-Os' in batch_compile['argv'] and '-O2' not in batch_compile['argv'], 'ARM optimization changed')
        proof = {'status': 'PASS', 'changed_function': 'mt_batch1024_collect',
                 'other_seven_serializer_functions_and_all_other_text_exact_equal': True,
                 'unchanged_patched_sources': unchanged, 'compiled_SL_objects': objects,
                 'config_delta_only_common_ID_and_product': True,
                 'ARM_optimization_Os_unchanged': True, 'no_performance_or_hardware_claim': True}
        (out / 'source-equivalence.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf8')

        copy(baseline / 'patched/v2/protocol/mt_batch1024.c', 'sl.c')
        copy(image / 'patched/v2/protocol/mt_batch1024.c', 'sn.c')
        copy(image / 'patched/v2/protocol/mt_batch1024.h', 'mt_batch1024.h')
        for name in ('mt_wire.c', 'mt_wire.h', 'mt_v2_crc32.h'):
            path = image / 'patched/v2/protocol' / name
            if not path.exists():
                path = image / 'source/firmware/protocol' / name
            copy(path, name)
        copy(Path(__file__).with_name('collect_local_model.c'), 'model.c')
        (out / 'temp').mkdir()
        env = dict(os.environ, ZIG_LOCAL_CACHE_DIR=str(out / 'zig-cache'),
                   ZIG_GLOBAL_CACHE_DIR=str(out / 'zig-global'), TMP=str(out / 'temp'), TEMP=str(out / 'temp'))
        version = run('version', [zig, 'version']).strip()
        common = [zig, 'cc', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-I.']
        for prefix in ('sl', 'sn'):
            aliases = ['-Dmt_batch1024_' + name + '=' + prefix + '_' + name for name in names]
            run('compile-' + prefix, [*common, *aliases, '-c', prefix + '.c', '-o', prefix + '.o'])
        run('compile-model', [*common, 'model.c', 'sl.o', 'sn.o', 'mt_wire.c', '-o', 'model.exe'])
        stdout = run('model', [out / 'model.exe'])
        result.update(status='PASS', compiler_version=version, model_stdout=stdout,
                      source_equivalence_sha256=sha(out / 'source-equivalence.json'),
                      image_bin_sha256=current['artifacts']['MotortesterV2-stream-candidate.bin'],
                      model_scope='Actual SL/SN serializers with disjoint state/input/storage; return/full-bank/canary equality and independent decode oracle',
                      not_verified=['Full runtime/USB/ADC execution', 'Physical150k or WCET', 'Flash approval'])
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
