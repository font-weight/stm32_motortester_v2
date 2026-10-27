"""One compact progress lifecycle/hook witness and exact SF equivalence; no hardware."""
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


def remove_hooks(source):
    source = re.sub(r'^.*N_PROGRESS_INCLUDE.*\n', '', source, flags=re.M)
    return re.sub(r'^#if CFG_MT_PROGRESS_TRACE /\* N_PROGRESS \*/\n.*?^#endif\n',
                  '', source, flags=re.M | re.S)


def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize,
         'Run python -I -B')
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('image', 'baseline', 'zig', 'output'):
        ap.add_argument('--' + name, required=True, type=Path)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[2]
    image, baseline, zig, out = (args.image.resolve(), args.baseline.resolve(),
                                 args.zig.resolve(strict=True), args.output.resolve())
    need(out.is_relative_to(root / 'build') and not out.exists(), 'Use a new build directory')
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
        completed = subprocess.run(row['argv'], cwd=out, env=env, capture_output=True, timeout=180)
        row['exit_code'] = completed.returncode
        (out / (label + '.stdout')).write_bytes(completed.stdout)
        (out / (label + '.stderr')).write_bytes(completed.stderr)
        need(completed.returncode == 0, label + ' failed; evidence retained')
        return completed.stdout.decode('utf8')

    try:
        read(Path(__file__).resolve())
        inputs[str(zig)] = sha(zig)
        current, previous = json.loads(read(image / 'receipt.json')), json.loads(read(baseline / 'receipt.json'))
        need(current['status'] == previous['status'] == 'BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE', 'Incomplete image')
        need(current['config']['firmware_build'] == 0x56325347 and
             previous['config']['firmware_build'] == 0x56325346, 'Wrong SG/SF basis')
        expected = json.loads(json.dumps(previous['config']))
        expected['firmware_build'] = 0x56325347
        expected['usb']['product'] = 'Motortester V2 Progress SG'
        need(current['config'] == expected, 'Configuration drift beyond build/product')
        helper = Path(__file__).with_name('check_usb_gate.py')
        read(helper)
        spec = importlib.util.spec_from_file_location('extract_progress', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = module.function
        changed = {'v2/app/mt_live_runtime.c', 'v2/protocol/mt_live_device.c', 'v2/platform/adc_timer_dma.c'}
        proof, unchanged = [], []
        for path in sorted((baseline / 'patched').rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(baseline / 'patched')
            target = image / 'patched' / relative
            old, new = read(path), read(target)
            if relative.as_posix() in changed:
                need(tokens(remove_hooks(new)) == tokens(old), 'Working operations changed: ' + str(relative))
                proof.append({'path': relative.as_posix(), 'method': 'Token-identical after removing explicit N-only #if blocks/includes'})
            else:
                need(path.read_bytes() == target.read_bytes(), 'Preserved SF input changed: ' + str(relative))
                unchanged.append({'path': relative.as_posix(), 'sha256': sha(target)})
        for name in ('mt_timebase.c', 'mt_timebase.h', 'mt_stream_diag.c'):
            need(read(image / 'source/firmware/platform' / name) ==
                 read(baseline / 'source/firmware/platform' / name), 'Legacy source changed: ' + name)
        core = read(image / 'patched/v2/protocol/mt_live_device.c')
        driver = read(image / 'patched/v2/platform/adc_timer_dma.c')
        runtime = read(image / 'patched/v2/app/mt_live_runtime.c')
        offer, fail = function(core, 'mt_live_device_offer'), function(driver, 'fail')
        need(offer.index('mt_sample_queue_push_quantized') < offer.index('mt_progress_close') < offer.index('terminate('), 'Queue first-close ordering')
        need(fail.index('invalidate_history') < fail.index('mt_progress_close') < fail.index('quiesce('), 'ADC first-close ordering')
        start = function(core, 'accept_frame')
        at = start.index('started=d->io.start')
        need(at < start.index('mt_progress_begin', at) < start.index('if(!now', at), 'Successful start trace boundary')
        tx = function(core, 'step_tx')
        need(tx.index('mt_progress_write_begin') < tx.index('accepted=d->io.write') <
             tx.index('mt_progress_write_end') < tx.index('if(!now(d,&after)'), 'Acceptance observation precedes final guards')
        write = function(runtime, 'live_write')
        need(write.index('tud_cdc_n_write_available(0)<length') < write.index('mt_progress_zero_space') < write.index('r->writer_active=1'), 'Space-zero classification scope')
        need(function(core, 'recover').index('mt_progress_close') < function(core, 'recover').index('local_cause'), 'Recovery cause boundary')
        source_fault = function(core, 'mt_live_device_fault')
        need(source_fault.index('cause(d,reason)') < source_fault.index('mt_progress_close') < source_fault.index('if(!now'), 'Source first-cause before clock')
        source_proof = {'status': 'PASS', 'changed_sources': proof, 'unchanged_SF_patched': unchanged,
                        'working_order_preserved_except_diagnostic_observation': True,
                        'new_hooks_execute_before_cleanup_or_postwrite_checks': True,
                        'legacy136_source_and_ABI_unchanged': True,
                        'not_a_performance_or_whole_runtime_proof': True}
        (out / 'source-equivalence.json').write_text(json.dumps(source_proof, indent=2) + '\n', encoding='utf8')

        for area, names in {'platform': ['mt_stream_progress.c', 'mt_stream_progress.h', 'mt_stream_diag.h',
                                        'mt_usb_ctr.h', 'adc_timer_dma.h'],
                            'protocol': ['mt_live_device.h', 'mt_batch1024.h', 'mt_wire.h'],
                            'acquisition': ['mt_sample_queue.h', 'mt_acquisition_profile.h']}.items():
            for name in names:
                path = image / 'patched/v2' / area / name
                if not path.exists():
                    path = image / 'source/firmware' / area / name
                need(current['inputs_before'].get(str(path)) == sha(path), 'Image source pin drift: ' + str(path))
                copy(path, area + '/' + name)
        bridge = read(image / 'patched/v2/transport/mt_usb_bridge.h')
        need('typedef struct { uint32_t previous; unsigned entered; } mt_usb_scope;' in bridge, 'Native scope seam ABI drift')
        (out / 'transport').mkdir()
        (out / 'transport/mt_usb_bridge.h').write_text('#include <stdint.h>\n'
            'typedef struct { uint32_t previous; unsigned entered; } mt_usb_scope;\n'
            'uint32_t mt_usb_bridge_lock(void);\nvoid mt_usb_bridge_unlock(uint32_t);\n'
            'int mt_usb_bridge_app_enter(mt_usb_scope*);\nvoid mt_usb_bridge_leave(mt_usb_scope*);\n', encoding='utf8')
        (out / 'tusb.h').write_text('#include <stdbool.h>\n#include <stdint.h>\n'
            'uint32_t tud_cdc_n_write_available(uint8_t);\nbool tud_task_event_ready(void);\n', encoding='utf8')
        model = read(Path(__file__).with_name('stream_progress_model.c'))
        need(model.count('/* ACTUAL_OFFER */') == model.count('/* ACTUAL_ADC_FAIL */') == 1, 'Native actual hook placeholders')
        model = model.replace('/* ACTUAL_OFFER */', offer).replace('/* ACTUAL_ADC_FAIL */', fail)
        (out / 'model.c').write_text(model, encoding='utf8', newline='\n')
        (out / 'temp').mkdir()
        env = dict(os.environ, ZIG_LOCAL_CACHE_DIR=str(out / 'zig-cache'), ZIG_GLOBAL_CACHE_DIR=str(out / 'zig-global'),
                   TMP=str(out / 'temp'), TEMP=str(out / 'temp'))
        version = run('version', [zig, 'version']).strip()
        run('compile', [zig, 'cc', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-DCFG_MT_STREAM_DIAGNOSTICS=1', '-DCFG_MT_PROGRESS_TRACE=1', '-DMT_PROGRESS_NATIVE=1',
                        '-I.', '-Iplatform', '-Iprotocol', '-Iacquisition', 'model.c',
                        'platform/mt_stream_progress.c', '-o', 'model.exe'])
        stdout = run('model', [out / 'model.exe', out / 'actual-progress.bin'])
        fixture = out / 'actual-progress.bin'
        need(fixture.stat().st_size == 64, 'Actual C fixture size')
        result.update(status='PASS', compiler_version=version, stdout=stdout,
                      C_fixture_sha256=sha(fixture), source_equivalence_sha256=sha(out / 'source-equivalence.json'),
                      image_bin_sha256=current['artifacts']['MotortesterV2-stream-candidate.bin'],
                      native_scope='Actual trace module, actual extracted offer/driver-fail functions with explicit logical boundary stubs',
                      seams=['Synthetic DWT, USB FIFO/actor/IRQ/legacy136 values',
                             'Queue and terminate/quiesce boundaries are stubs that assert first-close before cleanup',
                             'Source equivalence separately proves diagnostic-only insertions and remaining hook order'],
                      not_verified=['Observer timing overhead or CPU shares', 'Physical throughput or ADC loss', 'Flash admission'])
    except BaseException as error:
        result.update(status='FAILED', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        drift = [path for path, expected in inputs.items() if not Path(path).is_file() or sha(Path(path)) != expected]
        result['input_drift'] = drift
        if drift:
            result['status'] = 'FAILED_INPUT_DRIFT'
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8', newline='\n')
    print(json.dumps({'status': result['status'], 'result': str(out / 'result.json')}))


if __name__ == '__main__':
    main()
