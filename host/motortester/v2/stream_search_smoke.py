"""Focused assertions used by the existing native/frozen main-window witness."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil

from .stream_search import make_config, validate_config, SearchSnapshot
from .stream_device import companion_path, open_verified_context


def check_math():
    base = dict(threshold=2500, hysteresis=200, falling=False, holdoff_ms=6,
                window_ms=10, pre_percent=20, post_ms=1)
    for fs, bits in ((50_000, 12), (100_000, 12), (150_000, 10)):
        cfg = make_config(fs=fs, retained_bits=bits, **base)
        assert (cfg.pre_samples, cfg.post_samples, cfg.baseline_samples,
                cfg.holdoff_samples, cfg.max_event_samples) == tuple(
                    round(fs * seconds) for seconds in (.002, .001, .0005, .006, .010))
        assert cfg.release_code == 2300 and cfg.rail_high == (4092 if bits == 10 else 4095)
        fallen = make_config(fs=fs, retained_bits=bits, **(base | {'falling': True}))
        assert fallen.release_code == 2700 and fallen.high(2496) and not fallen.high(2504)
        assert SearchSnapshot.from_dict(asdict(SearchSnapshot(cfg, 7))).config == cfg
    invalid = ({'threshold': 100}, {'threshold': 4093, 'falling': True},
               {'pre_percent': 90, 'post_ms': 5}, {'window_ms': float('nan')})
    for delta in invalid:
        try:
            make_config(fs=150_000, retained_bits=10, **(base | delta))
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid search settings accepted: {delta}")
    try:
        SearchSnapshot(cfg, True)
    except ValueError:
        pass
    else:
        raise AssertionError('Boolean revision accepted')
    return True


def configure_editor(window):
    editor = window.stream_search_controls
    assert editor is not None and editor.fields.isEnabled()
    editor.threshold.set_value(100, emit=True)
    assert not editor.apply_button.isEnabled()
    assert not editor.apply_pending()
    editor.threshold.set_value(2400, emit=True)
    editor.hysteresis.setValue(200)
    editor.falling.click()
    editor.holdoff.set_value(.006, emit=True)
    editor.window.setValue(10)
    editor.pre.setValue(20)
    editor.post.setValue(1)
    editor.apply_button.click()
    cfg = window.stream_dialog.bridge.search_config
    assert cfg.threshold_code == 2400 and cfg.polarity == 'below'
    assert (cfg.pre_samples, cfg.post_samples, cfg.holdoff_samples) == (100, 50, 300)
    assert not editor.dirty
    return cfg


def check_file(app, window, panel, path, output, wait):
    editor = window.stream_search_controls
    raw_before = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = companion_path(path)
    context_before = sidecar.read_bytes()
    saved = open_verified_context(path).event_search
    assert saved is not None and saved.config == panel.bridge.state.config
    assert saved.config_revision == panel.bridge.state.config_revision
    assert json.loads(context_before)['format_version'] == 4
    assert panel.viewer._config == saved.config and panel._file_search_config == saved.config
    assert wait(app, lambda: panel.viewer._scan is None and panel.viewer._events)
    original_triggers = tuple(x.trigger_index for x in panel.viewer._events)
    assert editor.fields.isEnabled() and editor.falling.isChecked()
    token_before = panel.viewer._source
    panel.cursors.enabled.setChecked(True)
    editor.rising.click()
    editor.apply_button.click()
    assert not panel.cursors.enabled.isChecked() and panel.viewer._source != token_before
    assert wait(app, lambda: panel.viewer._scan is None and panel.viewer._events)
    assert panel.viewer._config.polarity == 'above'
    assert tuple(x.trigger_index for x in panel.viewer._events) != original_triggers
    assert panel._file_search_revision == 1 and 'файл не изменён' in editor.note.text()
    # Supersede one unfinished scan immediately; the old source token cannot win.
    editor.threshold.set_value(2450, emit=True)
    editor.apply_button.click()
    stale_token = panel.viewer._source
    editor.restore_button.click()
    assert panel.viewer._source != stale_token and panel._file_search_revision == 0
    assert wait(app, lambda: panel.viewer._scan is None and panel.viewer._events)
    assert panel.viewer._config == saved.config
    assert tuple(x.trigger_index for x in panel.viewer._events) == original_triggers
    assert panel.verified_context.event_search == saved
    assert panel.bridge.search_config == saved.config  # file override never becomes next-live config
    assert sidecar.read_bytes() == context_before and hashlib.sha256(path.read_bytes()).hexdigest() == raw_before

    # v3 lacks a search snapshot. It must stay readable without pretending that
    # the fallback thresholds were recorded by the source.
    legacy = path.with_name('legacy-search.mtstream')
    shutil.copyfile(path, legacy)
    value = json.loads(context_before)
    value['format_version'] = 3
    del value['event_search']
    companion_path(legacy).write_text(json.dumps(value), encoding='utf-8')
    assert open_verified_context(legacy).event_search is None
    assert panel.open_path(legacy)
    assert wait(app, lambda: panel.archive is not None and panel.viewer._recording is not None)
    assert 'Параметры поиска не сохранены' in editor.note.text()
    assert panel.open_path(path)
    assert wait(app, lambda: panel.archive is not None and panel.viewer._recording is not None)
    assert panel.viewer._config == saved.config

    # Read-time validation must not ignore a bad hash or invalid search snapshot.
    value = json.loads(context_before)
    for mutate in (lambda v: v.update(journal_sha256='0'*64),
                   lambda v: v['event_search'].update(config_revision=True)):
        broken = json.loads(context_before)
        mutate(broken)
        companion_path(legacy).write_text(json.dumps(broken), encoding='utf-8')
        try:
            open_verified_context(legacy)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid companion accepted')
    # Exact settings also survive the retry path's immutable failure receipt.
    from .stream_device import ContextFailure
    from unittest.mock import patch
    class Executor:
        def submit(self, fn, *args):
            assert args[-1] is saved
            return None
    failure = ContextFailure(str(path), panel.context, panel.archive.identity, 'fixture', None, saved)
    with patch.object(panel.bridge, '_executor', Executor()), patch.object(panel.bridge, '_metadata_error', failure):
        assert panel.bridge.retry_context(failure)
    return True
