"""One SD actual-core/queue batching model; no hardware or throughput claim."""
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok, message):
    if not ok: raise ValueError(message)
def tokens(text):
    return re.findall(r'[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+|\S', re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S))


def main():
    need(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize, 'Run python -I -B')
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('image', 'baseline', 'zig', 'output'): ap.add_argument('--' + name, type=Path, required=True)
    a = ap.parse_args(); root = Path(__file__).resolve().parents[2]
    image, base, zig, out = a.image.resolve(), a.baseline.resolve(), a.zig.resolve(strict=True), a.output.resolve()
    need(not out.exists() and out.is_relative_to(root / 'build'), 'Use a new build output'); out.mkdir()
    inputs, commands = {}, []
    result = {'status': 'RUNNING', 'scope': __doc__, 'inputs': inputs, 'commands': commands}
    def read(p):
        inputs[str(p)] = sha(p)
        return p.read_text('utf8')
    def run(label, argv):
        row = {'label': label, 'argv': [str(x) for x in argv]}; commands.append(row)
        q = subprocess.run(row['argv'], cwd=out, env=env, capture_output=True, timeout=180)
        row['exit_code'] = q.returncode
        (out / (label + '.stdout')).write_bytes(q.stdout); (out / (label + '.stderr')).write_bytes(q.stderr)
        need(q.returncode == 0, label + ' failed; evidence retained')
        return q.stdout.decode('utf8')
    try:
        read(Path(__file__).resolve()); inputs[str(zig)] = sha(zig)
        ri, rb = json.loads(read(image / 'receipt.json')), json.loads(read(base / 'receipt.json'))
        need(ri['status'] == rb['status'] == 'BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE', 'Unfinished image')
        need(ri['config']['firmware_build'] == 0x56325344 and rb['config']['firmware_build'] == 0x56325343, 'Wrong SD/SC image')
        need(ri['config']['acquisition_modes'] == [1, 2, 3, 4] and not ri['config']['active_profile_enabled'], 'Wrong modes/observer')
        helper = Path(__file__).with_name('check_usb_gate.py'); read(helper)
        spec = importlib.util.spec_from_file_location('batch_extract', helper)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); fn = module.function
        changed = {'protocol/mt_live_device.c', 'protocol/mt_live_device.h',
                   'acquisition/mt_sample_queue.c', 'acquisition/mt_sample_queue.h',
                   'acquisition/mt_acquisition_profile.c', 'acquisition/mt_acquisition_profile.h'}
        unchanged = []
        for p in sorted((base / 'patched').rglob('*')):
            if not p.is_file(): continue
            rel = p.relative_to(base / 'patched'); q = image / 'patched' / rel
            if rel.as_posix().removeprefix('v2/') in changed: continue
            need(p.read_bytes() == q.read_bytes(), 'Preserved SC source changed: ' + str(rel))
            read(p); read(q); unchanged.append({'path': rel.as_posix(), 'sha256': sha(q)})
        for area in ('platform/mt_timebase.c', 'platform/mt_timebase.h'):
            p, q = base / 'source/firmware' / area, image / 'source/firmware' / area
            need(read(p) == read(q), 'TIME source changed')
        core, old = read(image / 'patched/v2/protocol/mt_live_device.c'), read(base / 'patched/v2/protocol/mt_live_device.c')
        proofs = []
        for name in ('now', 'expire', 'deadline', 'recover', 'raw_barrier', 'flags', 'quiesce_before_start',
                     'snapshot_valid', 'begin_hello', 'accept_frame', 'commit_hello', 'mt_live_device_receive', 'tx_intents', 'step_tx'):
            need(tokens(fn(core, name)) == tokens(fn(old, name)), 'Preserved core guard changed: ' + name)
            proofs.append({'function': name, 'method': 'token-identical to SC'})
        for name in ('terminate', 'mt_live_device_offer'):
            current = fn(core, name).replace('discarded_lsb(d)', 'd->mode==3u?2u:0u')
            need(tokens(current) == tokens(fn(old, name)), 'Ingress change beyond descriptor quantization: ' + name)
            proofs.append({'function': name, 'method': 'token-identical after descriptor retention expression'})
        queue = read(image / 'patched/v2/acquisition/mt_sample_queue.c')
        old_queue = read(base / 'patched/v2/acquisition/mt_sample_queue.c')
        for name in ('mt_sample_queue_init', 'mt_sample_queue_push_quantized', 'mt_sample_queue_push',
                     'mt_sample_queue_seal', 'mt_sample_queue_peek', 'mt_sample_queue_pop'):
            need(tokens(fn(queue, name)) == tokens(fn(old_queue, name)), 'Old queue API changed: ' + name)
            proofs.append({'function': name, 'method': 'token-identical to SC'})
        pack = read(image / 'patched/v2/acquisition/mt_acquisition_profile.c')
        old_pack = read(base / 'patched/v2/acquisition/mt_acquisition_profile.c')
        need(tokens(fn(pack, 'mt_acquisition_pack')) == tokens(fn(old_pack, 'mt_acquisition_pack')), '128-code packer changed')
        proofs.append({'function': 'mt_acquisition_pack', 'method': 'token-identical; invoked twice at byte-aligned 128-code boundary'})
        proof = {'status': 'PASS', 'unchanged_SC_patched_sources': unchanged, 'guard_proofs': proofs,
                 'runtime_H_early_grant_byte_identical': True, 'TIME_backend_byte_identical': True,
                 'ADC_DMA_DCD_FIFO_USB_byte_identical': True,
                 'scope': 'Actual core/queue logic below is executed; unchanged MMIO/USB paths are pinned, not simulated as physical proof.'}
        (out / 'source-equivalence.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf8')
        sources = []
        for area, names in {
            'protocol': ['mt_live_device.c', 'mt_live_device.h', 'mt_wire.c', 'mt_wire.h', 'mt_v2_crc32.h'],
            'acquisition': ['mt_sample_queue.c', 'mt_sample_queue.h', 'mt_acquisition_profile.c', 'mt_acquisition_profile.h']}.items():
            (out / area).mkdir()
            for name in names:
                p = image / 'patched/v2' / area / name
                if not p.exists(): p = image / 'source/firmware' / area / name
                text = read(p); need(ri['inputs_before'].get(str(p)) == sha(p), 'Image source pin differs: ' + str(p))
                (out / area / name).write_text(text, encoding='utf8', newline='\n')
                if name.endswith('.c'): sources.append(area + '/' + name)
        runtime = read(image / 'patched/v2/app/mt_live_runtime.c')
        fit = read(Path(__file__).with_name('whole_fit_write_model.c'))
        need(fit.count('/* LIVE_WRITE */') == 1, 'Whole-fit source seam differs')
        (out / 'whole-fit.c').write_text(fit.replace('/* LIVE_WRITE */', fn(runtime, 'live_write')), encoding='utf8', newline='\n')
        (out / 'model.c').write_text(read(Path(__file__).with_name('batch256_model.c')), encoding='utf8', newline='\n')
        (out / 'temp').mkdir()
        env = dict(os.environ, ZIG_LOCAL_CACHE_DIR=str(out / 'zig-cache'), ZIG_GLOBAL_CACHE_DIR=str(out / 'zig-global'),
                   TMP=str(out / 'temp'), TEMP=str(out / 'temp'))
        version = run('version', [zig, 'version']).strip()
        run('compile', [zig, 'cc', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-I.', '-Iprotocol', '-Iacquisition', 'model.c', 'whole-fit.c', *sources, '-o', 'model.exe'])
        stdout = run('model', [out / 'model.exe', out / 'batch385-transcript.bin'])
        result.update(status='PASS', compiler_version=version, stdout=stdout,
                      image_bin_sha256=ri['artifacts']['MotortesterV2-stream-candidate.bin'],
                      source_equivalence_sha256=sha(out / 'source-equivalence.json'),
                      synthetic_C_fixture_sha256=sha(out / 'batch385-transcript.bin'),
                      fixture={'format': 'bare COBS frames with delimiter', 'nonce': 503, 'generation': 3, 'mode': 4,
                               'frames': ['DATA sequence4 index0 count256', 'DATA sequence5 index256 count129', 'END sequence6 prefix385'],
                               'raw_formula': 'first256: ((i*37+3)&4095)&4092; final129: (4095-i)&4092',
                               'physical': False},
                      not_verified=['Target CPU/IRQ timing', 'Physical150k stream/ADC/DMA/USB', 'Analog input/settling', 'Flash approval'])
    except BaseException as e:
        result.update(status='FAILED', error=type(e).__name__ + ': ' + str(e)); raise
    finally:
        drift = [p for p, value in inputs.items() if not Path(p).is_file() or sha(Path(p)) != value]
        result['input_drift'] = drift
        if drift: result['status'] = 'FAILED_INPUT_DRIFT'
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'status': result['status'], 'result': str(out / 'result.json')}))


if __name__ == '__main__': main()
