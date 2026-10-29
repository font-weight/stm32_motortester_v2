"""Bind the focused cursor witness to the sealed and relocated Windows package."""
from pathlib import Path
import platform


def verify_cursors_package(*, output, gui_exe, relocated, foreign_cwd,
                           frozen_env, run, portable, portable_hash,
                           expected_tree, source_archive, revision,
                           exe_hashes, log, file_tree, png_info, read_json,
                           sha256, write_json):
    folder = output / 'frozen-cursors'
    run(gui_exe, '--verify-cursors', folder, cwd=foreign_cwd, environment=frozen_env, timeout=60)
    smoke = read_json(folder / 'result.json')
    if (smoke.get('status') != 'PASS' or smoke.get('frozen') is not True or
            smoke.get('platform') != 'win32' or smoke.get('qt_platform') != 'windows' or
            Path(smoke.get('executable', '')).resolve() != gui_exe.resolve() or
            smoke.get('callback_errors') != [] or smoke.get('error') or smoke.get('cleanup_error') or
            smoke.get('execution_kind') != 'DEMO' or smoke.get('physical_stream_verified') is not False or
            smoke.get('owners_closed') is not True or type(smoke.get('real_serial_open_calls')) is not int or
            smoke['real_serial_open_calls'] != 0):
        raise RuntimeError('Frozen cursor witness failed')
    required = ('held_values_survive_eviction', 'mouse_drag_reads_raw',
                'zoom_preserves_indices_and_graph', 'pause_cursors_recording_continues',
                'follow_clears_cursors', 'overview_raw_values_signed_delta',
                'file_unchanged', 'raw_visibility_clears_values')
    if any(smoke.get('checks', {}).get(key) is not True for key in required):
        raise RuntimeError('Cursor evidence incomplete')
    live = smoke['live']
    if (not 0 < live['held_bytes'] <= 131072 or
            live['held_bytes'] != 2 * (live['held_end'] - live['held_first']) or
            live['received_after'] <= max(live['received_before'], live['held_end'] + 65536)):
        raise RuntimeError('Held window or continued reception mismatch')
    pngs = {}
    for name, item in smoke.get('files', {}).items():
        path = folder / name
        if (Path(name).name != name or not path.is_file() or
                item.get('sha256') != sha256(path) or item.get('bytes') != path.stat().st_size):
            raise RuntimeError('Cursor artifact drift')
        if path.suffix == '.png':
            pngs[name] = png_info(path)
    if set(pngs) != {'cursors-live.png', 'cursors-pause.png', 'cursors-file.png'}:
        raise RuntimeError('Missing cursor screenshots')
    record = smoke['recording']
    if (record['samples'] <= 65536 or record['sha256'] != sha256(folder / 'cursors.mtstream') or
            record['delta_s'] != (record['b'] - record['a']) / 50000 or record['delta_s'] >= 0):
        raise RuntimeError('Cursor record or signed interval mismatch')
    if file_tree(relocated) != expected_tree or sha256(portable) != portable_hash:
        raise RuntimeError('Frozen witness changed the sealed package')
    report = dict(status='PASS', verification_scope='stream-cursors',
        scope='Frozen Windows DEMO cursor gestures, continued recording and opened-file raw values; no COM or full-suite qualification',
        source_commit=revision, portable_zip=portable.name, portable_sha256=portable_hash,
        source_sha256=sha256(source_archive), executable_sha256=exe_hashes,
        extracted_bundle=str(relocated), working_directory=str(foreign_cwd),
        isolated_path=frozen_env['PATH'], frozen_smoke=smoke, png_files=pngs,
        smoke_files=file_tree(folder), windows_host=platform.platform(),
        physical_device_verified=False, public_release_approved=False)
    write_json(output / 'build-report.json', report)
    artifacts = [portable, source_archive, output / 'build-report.json', log] + sorted(p for p in folder.iterdir() if p.is_file())
    (output / 'SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.relative_to(output).as_posix()}\n' for p in artifacts), encoding='utf-8')
    print(f'Cursor package verified: {portable}')
    return 0
