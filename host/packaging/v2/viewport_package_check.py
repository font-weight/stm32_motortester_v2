"""Verify the changed viewport flow from the sealed, relocated Windows ZIP."""
from pathlib import Path
import platform


def verify_viewport_package(*, output, gui_exe, relocated, foreign_cwd,
                            frozen_env, run, portable, portable_hash,
                            expected_tree, source_archive, revision,
                            exe_hashes, log, file_tree, png_info, read_json,
                            sha256, write_json):
    folder=output/'frozen-viewport'
    run(gui_exe,'--verify-viewport',folder,cwd=foreign_cwd,environment=frozen_env,timeout=60)
    smoke=read_json(folder/'result.json')
    if (smoke.get('status')!='PASS' or smoke.get('frozen') is not True or
            smoke.get('platform')!='win32' or smoke.get('qt_platform')!='windows' or
            Path(smoke.get('executable','')).resolve()!=gui_exe.resolve() or
            smoke.get('callback_errors')!=[] or smoke.get('error') or smoke.get('cleanup_error') or
            smoke.get('execution_kind')!='DEMO' or smoke.get('physical_stream_verified') is not False or
            smoke.get('owners_closed') is not True or type(smoke.get('real_serial_open_calls')) is not int or
            smoke['real_serial_open_calls']!=0):
        raise RuntimeError('Frozen viewport witness failed')
    required=('held_after_ring_eviction','one_wheel_repaints_live_edges','drag_repaints_held',
              'paused_zoom_repaints_while_recording','resume_returns_fresh_tail',
              'one_wheel_repaints_file_edges','file_detail_to_overview_edges',
              'source_swap_clears_held_raw','recording_unchanged')
    if any(smoke.get('checks',{}).get(name) is not True for name in required):
        raise RuntimeError('Viewport evidence incomplete')
    live=smoke.get('live',{})
    if (not 0<live.get('held_bytes',0)<=131072 or
            live['held_bytes']!=2*(live['held_end']-live['held_first']) or
            live['received_after']<=live['received_before'] or
            live['received_after']<=live['held_end']+65536):
        raise RuntimeError('Held-window budget or continued reception not established')
    pngs={}
    for name,item in smoke.get('files',{}).items():
        path=folder/name
        if Path(name).name!=name or not path.is_file() or item.get('sha256')!=sha256(path) or item.get('bytes')!=path.stat().st_size:
            raise RuntimeError('Viewport artifact drift')
        if path.suffix=='.png':
            pngs[name]=png_info(path)
    if set(pngs)!={'viewport-held.png','viewport-paused.png','viewport-tail.png','viewport-file.png'}:
        raise RuntimeError('Missing viewport screenshots')
    if (smoke.get('recording',{}).get('samples',0)<=0 or
            smoke['recording']['sha256']!=sha256(folder/'viewport.mtstream')):
        raise RuntimeError('Recorded file mismatch')
    if file_tree(relocated)!=expected_tree or sha256(portable)!=portable_hash:
        raise RuntimeError('Frozen witness changed the sealed package')
    report={'status':'PASS','verification_scope':'stream-viewport',
        'scope':'Frozen Windows DEMO recording, manual/pause/file viewport; no COM, analog or unchanged full-suite qualification',
        'source_commit':revision,'portable_zip':portable.name,'portable_sha256':portable_hash,
        'source_sha256':sha256(source_archive),'executable_sha256':exe_hashes,
        'extracted_bundle':str(relocated),'working_directory':str(foreign_cwd),
        'isolated_path':frozen_env['PATH'],'frozen_smoke':smoke,'png_files':pngs,
        'smoke_files':file_tree(folder),'windows_host':platform.platform(),
        'physical_device_verified':False,'public_release_approved':False}
    write_json(output/'build-report.json',report)
    artifacts=[portable,source_archive,output/'build-report.json',log]+sorted(p for p in folder.iterdir() if p.is_file())
    (output/'SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.relative_to(output).as_posix()}\n' for p in artifacts),encoding='utf-8')
    print(f'Viewport package verified: {portable}')
    return 0
