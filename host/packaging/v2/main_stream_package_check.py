"""Bind the embedded-main-window witness to the relocated Windows package."""
from pathlib import Path
import platform


def verify_main_stream_package(*, output, gui_exe, relocated, foreign_cwd,
                               frozen_env, run, portable, portable_hash,
                               expected_tree, source_archive, revision,
                               exe_hashes, log, file_tree, png_info, read_json,
                               sha256, write_json):
    folder = output / "frozen-main-stream"
    run(gui_exe, "--verify-main-stream", folder, cwd=foreign_cwd,
        environment=frozen_env, timeout=60)
    smoke = read_json(folder / "result.json")
    if (smoke.get("status") != "PASS" or smoke.get("frozen") is not True or
            smoke.get("platform") != "win32" or smoke.get("qt_platform") != "windows" or
            Path(smoke.get("executable", "")).resolve() != gui_exe.resolve() or
            smoke.get("callback_errors") != [] or smoke.get("error") or
            smoke.get("cleanup_error") or smoke.get("failures") != [] or
            smoke.get("execution_kind") != "DEMO + injected serial handshake" or
            smoke.get("physical_stream_verified") is not False or
            smoke.get("owners_closed") is not True or
            type(smoke.get("real_serial_open_calls")) is not int or
            smoke["real_serial_open_calls"] != 0):
        raise RuntimeError("Frozen embedded-main-window witness failed")
    required = (
        "embedded_widget", "capture_controls_hidden", "main_time_scale", "main_y_scale",
        "source_cursor_readback", "recording_continued_during_navigation",
        "saved_recording_reopened_in_main_window", "raw_checkbox_restored",
        "empty_autoscale_handled", "stream_can_reopen", "return_restores_main_controls",
        "source_selector_routes_stream", "cancel_preserves_source", "primary_button_routes_stream",
        "legacy_explicit", "connect_150k_without_start", "connection_owners_closed",
        "live_event_navigation_retained", "file_event_navigation_retained",
        "service_menu_retains_hidden_tools", "unavailable_event_explained",
        "search_math_and_limits", "search_controls_before_start", "search_locked_during_acquisition",
        "search_snapshot_and_legacy", "search_reindex_preserves_raw", "search_mode_change_resets_draft",
        "live_sync_center_and_recording", "live_sync_wait_and_manual_hold",
        "single_capture_live_and_boundaries", "single_capture_save_open",
        "reconnect_file_to_live", "reconnect_stop_search", "reconnect_ownership_fences", "reconnect_close_priority")
    if any(smoke.get("checks", {}).get(key) is not True for key in required):
        raise RuntimeError("Embedded main-window evidence incomplete")
    reconnect = read_json(folder / 'result-reconnect.json')
    if (reconnect.get('status') != 'PASS' or reconnect.get('real_serial_open_calls') != 0 or
            any(reconnect.get(key) is not True for key in (
                'old_owners_joined', 'stale_callbacks_ignored', 'close_failure_fenced',
                'metadata_failure_fenced', 'dirty_capture_cancelled', 'same_page', 'ready_without_start')) or
            (reconnect.get('saved_threshold'), reconnect.get('file_threshold'),
             reconnect.get('next_live_threshold')) != (2600, 2800, 2500)):
        raise RuntimeError('Same-page reconnect evidence incomplete')
    for name, digest in reconnect.get('archive_sha256', {}).items():
        if Path(name).name != name or sha256(folder / name) != digest:
            raise RuntimeError('Reconnect changed a saved file')
    frames = smoke.get("sync_frames", [])
    for width, minimum in ((1000, 3), (500, 2)):
        selected = [frame for frame in frames if frame.get("width_samples") == width]
        if len({frame["trigger_index"] for frame in selected}) < minimum:
            raise RuntimeError("Not enough distinct synchronized frames")
        for frame in selected:
            if (abs(frame["crossing_x_s"] - frame["centre_x_s"]) > 0.5 / 50_000 + 1e-10 or
                    abs(frame["marker_x_s"] - frame["crossing_x_s"]) > 1e-10):
                raise RuntimeError("Synchronized threshold moved away from frame centre")
    if (smoke.get("demo_rate_hz") != 50_000 or
            smoke.get("initial_window_samples") != 1_000 or
            smoke.get("sweep_knob_samples") != 2_000 or
            type(smoke.get("saved_file_bytes")) is not int or
            smoke["saved_file_bytes"] <= 0 or
            smoke.get("saved_file_sha256") is None):
        raise RuntimeError("Embedded stream values or recording receipt mismatch")
    recording_name = smoke.get("saved_recording_artifact")
    if (not isinstance(recording_name, str) or Path(recording_name).name != recording_name or
            not (folder / recording_name).is_file() or
            (folder / recording_name).stat().st_size != smoke["saved_file_bytes"] or
            sha256(folder / recording_name) != smoke["saved_file_sha256"]):
        raise RuntimeError("Embedded stream saved-recording evidence is missing or changed")
    screenshot = folder / "result.png"
    capture = smoke.get('single_capture', {})
    artifact = capture.get('artifact', '')
    if (not artifact or Path(artifact).name != artifact or not (folder / artifact).is_file() or
            sha256(folder / artifact) != capture.get('sha256') or
            capture.get('captured_ordinal') != capture.get('expected_ordinal') or
            capture.get('trigger_index', -1) < capture.get('arm_end_index', 0)):
        raise RuntimeError('Single-capture evidence missing or changed')
    if not screenshot.is_file() or smoke.get("screenshot_sha256") != sha256(screenshot):
        raise RuntimeError("Embedded main-window screenshot missing or changed")
    if file_tree(relocated) != expected_tree or sha256(portable) != portable_hash:
        raise RuntimeError("Frozen witness changed the sealed package")
    report = dict(
        status="PASS", verification_scope="embedded-main-stream",
        scope="Frozen Windows same-page serial reconnection after file/Stop, next-live search draft and owner retirement/failure/close fences; existing capture and stream checks; injected serial and DEMO, no COM or physical input qualification",
        source_commit=revision, portable_zip=portable.name,
        portable_sha256=portable_hash, source_sha256=sha256(source_archive),
        executable_sha256=exe_hashes, extracted_bundle=str(relocated),
        working_directory=str(foreign_cwd), isolated_path=frozen_env["PATH"],
        frozen_smoke=smoke, png_files={name: png_info(folder / name) for name in
                                    ("result.png", "result-entry.png", "result-connected.png",
                                     "result-live-event.png", "result-file-event.png", "result-service-menu.png",
                                     "result-search.png", "result-search-file.png", "result-sync.png",
                                     "result-capture.png", "result-capture-open.png", "result-reconnect.png")},
        smoke_files=file_tree(folder), windows_host=platform.platform(),
        physical_device_verified=False, public_release_approved=False)
    write_json(output / "build-report.json", report)
    artifacts = [portable, source_archive, output / "build-report.json", log, screenshot,
                 folder / "result.json"]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output).as_posix()}\n"
                for path in artifacts), encoding="utf-8")
    print(f"Embedded stream package verified: {portable}")
    return 0
