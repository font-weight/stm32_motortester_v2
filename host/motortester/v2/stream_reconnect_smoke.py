"""Focused persistent-page lifecycle witness, using injected serial only."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from .stream_device import ContextFailure, companion_path, open_verified_context


def check_reconnect(app, window, panel, factory, output, wait):
    output = Path(output)
    path = output.with_name(output.stem + '-reconnect.mtstream')
    old = panel.bridge
    viewer, editor = panel.viewer, window.stream_search_controls
    old_displays = []
    old.live_ready.connect(old_displays.append)
    window.raw_view.setChecked(True)
    panel.live_button.click()
    assert wait(app, lambda: old.state.phase == 'preview' and old.state.validated_samples > 3000)
    assert not editor.fields.isEnabled() and not panel.connect_button.isEnabled()
    assert not panel.connect_device()  # Running acquisition must not be replaced.
    assert panel.record_path(path)
    assert wait(app, lambda: old.state.phase == 'recording' and old.state.validated_samples > 12000)
    assert wait(app, panel.capture.arm_button.isEnabled)
    panel.capture.arm_button.click()
    assert wait(app, lambda: panel.capture.shot is not None)
    shot = panel.capture.shot
    panel.stop_button.click()
    assert wait(app, lambda: old.state.can_open and not old.metadata_pending
                and panel.connect_button.isEnabled() and editor.fields.isEnabled())
    backend = factory.backends[-1]
    original = old.state.config
    editor.threshold.set_value(2500, emit=True)
    editor.apply_button.click()
    next_config = old.search_config
    assert next_config.threshold_code == 2500 and old.state.config == original
    assert open_verified_context(path).event_search.config == original
    # Cancel must keep the same owner and dirty capture; no reconnect command.
    count = len(factory.backends)
    panel.connect_button.click()
    assert panel.capture.prompt is not None and panel.bridge is old
    window.close()  # A close request must supersede the existing reconnect prompt.
    assert window._stream_close_pending
    panel.capture.prompt.reject()
    assert wait(app, lambda: panel.capture.prompt is None)
    assert panel.capture.shot is shot and panel.capture.dirty and not panel._reconnecting
    assert not window._stream_close_pending and not panel._closing
    shot_path = output.with_name(output.stem + '-reconnect.mtshot')
    assert panel.capture.save_path(shot_path)
    assert wait(app, lambda: not panel.busy and not panel.capture.dirty)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, companion_path(path), shot_path)}
    assert panel.open_path(path)
    assert wait(app, lambda: panel.archive is not None and not panel.busy)
    editor.threshold.set_value(2800, emit=True)
    editor.apply_button.click()
    assert panel.search_config().threshold_code == 2800 and old.search_config == next_config
    # A companion error still belongs to the old attempt, even in file view.
    old._metadata_error = ContextFailure(str(path), panel.context, shot.identity, 'injected metadata error')
    panel._state(old.state)
    assert not panel.connect_button.isEnabled() and not panel.connect_device()
    assert panel.bridge is old and len(factory.backends) == count
    old._metadata_error = None
    panel._state(old.state)
    # Delayed close cannot release the lease or create a competing COM owner.
    backend.fail_close = True
    with patch.object(old, 'deleteLater'):
        panel.connect_button.click()
        assert wait(app, lambda: old.state.can_retry_close)
        assert panel.bridge is old and panel._reconnecting and len(factory.backends) == count
        assert window._serial_owner is panel and not panel.closed and not viewer._closed
        backend.fail_close = False
        panel.disconnect_button.click()  # Cleanup-only retry while old handle is retained.
        assert wait(app, lambda: panel.bridge is not old and panel.bridge.state.ready
                    and not panel._opening and not panel._return_to_device)
        current = panel.bridge
        assert old._closed and old.controller.join(0) and not backend.is_open
        assert window.stream_dialog is panel and panel.viewer is viewer and window._serial_owner is panel
        assert panel.archive is None and editor.fields.isEnabled() and panel.search_config() == next_config
        assert current.state.validated_samples == 0 and factory.backends[-1].commands == [1, 1, 2]
        assert panel.capture.shot is shot and panel.capture.save_button.isEnabled()
        assert old_displays
        state_text, error_text = panel.state_label.text(), panel.error_label.text()
        previous_path = panel.saved_path
        old.state_changed.emit(old.state)
        old.live_ready.emit(old_displays[-1])
        old.error.emit('STALE OWNER')
        old.recording_ready.emit('STALE FILE')
        old.finished.emit()
        assert panel.bridge is current and not panel.closed and not viewer._closed
        assert panel.state_label.text() == state_text and panel.error_label.text() == error_text
        assert panel.saved_path == previous_path and panel.viewer._identity is None
    old.deleteLater()
    assert window.grab().save(str(output.with_name(output.stem + '-reconnect.png')))
    panel.live_button.click()
    assert wait(app, lambda: current.state.phase == 'preview' and current.state.validated_samples > 3000)
    assert current.state.config == next_config and not editor.fields.isEnabled()
    panel.stop_button.click()
    assert wait(app, lambda: current.state.can_open and panel.connect_button.isEnabled())
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == before[p.name]
               for p in (path, companion_path(path), shot_path))
    receipt = dict(status='PASS', source='injected serial only', real_serial_open_calls=0,
        old_owners_joined=True, stale_callbacks_ignored=True, close_failure_fenced=True,
        metadata_failure_fenced=True, dirty_capture_cancelled=True, same_page=True,
        ready_without_start=True, file_threshold=2800, next_live_threshold=2500,
        saved_threshold=original.threshold_code, archive_sha256=before,
        first_backend_count=count, final_backend_count=len(factory.backends))
    output.with_name(output.stem + '-reconnect.json').write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'reconnect_file_to_live': True, 'reconnect_stop_search': True,
            'reconnect_ownership_fences': True}


def close_during_reconnect(app, window, panel, factory, wait):
    before, bridge = len(factory.backends), panel.bridge
    panel.connect_button.click()
    assert panel._reconnecting and panel.bridge is bridge
    panel.close_panel_button.click()
    assert wait(app, lambda: panel.closed and not window._stream_page_active)
    assert len(factory.backends) == before and bridge._closed and bridge.controller.join(0)
    assert window._serial_owner is None and panel.viewer._closed and panel.cursors._closed

