"""Bind one focused analog GUI scenario to the immutable relocated bundle."""
from pathlib import Path
import platform


def verify_analog_package(*, output, gui_exe, relocated, foreign_cwd,
                         frozen_env, run, portable, portable_hash,
                         expected_tree, source_archive, revision,
                         exe_hashes, log, file_tree, png_info, read_json,
                         sha256, write_json):
    folder = output / 'frozen-analog'
    run(gui_exe, '--verify-analog', folder, cwd=foreign_cwd,
        environment=frozen_env, timeout=60)
    receipt = read_json(folder / 'result.json')
    if (receipt.get('status') != 'PASS' or receipt.get('frozen') is not True
            or receipt.get('qt_platform') != 'windows'
            or receipt.get('errors') != [] or receipt.get('callback_errors') != []
            or receipt.get('owners_closed') is not True
            or receipt.get('checks', {}).get('no_real_com') is not True
            or receipt.get('physical_measurement') is not False
            or receipt.get('real_serial_open_calls') != 0
            or Path(receipt.get('executable', '')).resolve() != gui_exe.resolve()):
        raise RuntimeError('Frozen analog scenario failed or evidence is incomplete')
    required = ('unknown_until_manual_selection', 'all_three_modes_manual_no_start_ui_profile_unchanged',
        'threshold_quantized_once_to_4_codes', 'config_locked_during_reception', 'volts_curve_matches_raw',
        'cursors_match_two_original_samples', 'millivolts_preserve_codes',
        'metrics_share_scale', 'unit_change_keeps_recording',
        'recording_and_capture_keep_profile_snapshot', 'reopened_files_use_saved_profile',
        'reconnect_resets_unknown', 'reconnect_does_not_start', 'saved_files_unchanged')
    if any(receipt.get('checks', {}).get(key) is not True for key in required):
        raise RuntimeError('Missing changed-flow analog evidence')
    for name, digest in receipt.get('files', {}).items():
        if Path(name).name != name or sha256(folder / name) != digest:
            raise RuntimeError('Analog raw/snapshot file changed')
    if file_tree(relocated) != expected_tree or sha256(portable) != portable_hash:
        raise RuntimeError('Frozen scenario changed the sealed package')
    write_json(output / 'build-report.json', dict(
        status='PASS', verification_scope='analog-nominal-stream',
        source_commit=revision, portable_zip=portable.name, portable_sha256=portable_hash,
        source_sha256=sha256(source_archive), executable_sha256=exe_hashes,
        extracted_bundle=str(relocated), working_directory=str(foreign_cwd),
        isolated_path=frozen_env['PATH'], windows_host=platform.platform(),
        frozen_smoke=receipt, smoke_files=file_tree(folder),
        png_files={p.name: png_info(p) for p in folder.glob('*.png')},
        physical_device_verified=False, physical_analog_verified=False,
        public_release_approved=False))
    artifacts = (portable, source_archive, output / 'build-report.json', log, folder / 'result.json')
    (output / 'SHA256SUMS.txt').write_text(''.join(
        f'{sha256(p)}  {p.relative_to(output).as_posix()}\n' for p in artifacts), encoding='utf-8')
    print(f'Analog package verified: {portable}')
    return 0
