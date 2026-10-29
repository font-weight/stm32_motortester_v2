"""Necessary display-mode checks within the existing Windows witness."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import time
import json
import struct

from .stream_sync import aligned_event


def check_sync(app, window, panel, output, wait):
    viewer = panel.viewer
    assert viewer.event_sync and panel.sync_button.isChecked(), 'Preview→Record отключил синхронизацию'
    before = panel.bridge.state.validated_samples
    config = panel.bridge.state.config
    window.sweep.set_value(.002, emit=True)
    frames = []
    evidence = []

    def drawn():
        if viewer.event_sync and viewer._event is not None:
            bounds = viewer.plot.getViewBox().viewRange()[0]
            centre = (bounds[0] + bounds[1]) / 2
            fs = viewer._identity[3]
            actual = (viewer._event.trigger_index - viewer._display_origin) / fs
            assert abs(actual - centre) <= .5 / fs + 1e-10, 'Пересечение уехало от центра'
            assert abs(viewer.trigger_marker.value() - actual) < 1e-10
            frames.append((viewer._event.trigger_index, viewer.selection.width))
            if len(evidence) < 32:
                evidence.append(dict(trigger_index=viewer._event.trigger_index,
                                     width_samples=viewer.selection.width, crossing_x_s=actual,
                                     centre_x_s=centre, marker_x_s=viewer.trigger_marker.value()))

    viewer.plot_drawn.connect(drawn)
    try:
        if not wait(app, lambda: len(set(t for t, _ in frames)) >= 3):
            diagnostic = dict(frames=frames, enabled=viewer.event_sync, waiting=viewer._sync_waiting,
                              ordinal=viewer._sync_ordinal, width=viewer._sync_width,
                              status=viewer.status_label.text(), mode=viewer.view_mode_label.text(),
                              selection=repr(viewer.selection), revision=viewer._revision,
                              pending=None if viewer._pending is None else viewer._pending.kind,
                              running=viewer._mailbox.running,
                              events=[repr(e) for e in viewer._events[-5:]],
                              callback_errors='see native log', phase=panel.bridge.state.phase)
            Path(output).with_name(Path(output).stem + '-sync-failure.json').write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
            raise AssertionError('Нет новых выровненных кадров; состояние сохранено')
        assert all(width == 1000 for _, width in frames)
        frames.clear()
        window.sweep.set_value(.001, emit=True)
        assert viewer.event_sync
        assert wait(app, lambda: len(set(t for t, w in frames if w == 500)) >= 2)
        assert panel.bridge.state.validated_samples > before and panel.bridge.state.phase == 'recording'
        assert panel.bridge.state.config == config
        original_y = window.yscale.value
        window.yscale.set_value(512, emit=True)
        assert window.grab().save(str(Path(output).with_name(Path(output).stem + '-sync.png')))
        window.yscale.set_value(original_y, emit=True)

        # No-event/buffer boundary decisions use original indices, not a clamped frame.
        event = NS(ordinal=1, trigger_index=50, flags=())
        fake = NS(event_index=NS(events=(event,), config=NS(high=lambda c: c >= 50)),
                  raw_u16le=struct.pack('<100H', *([40] * 50 + [60] * 50)),
                  raw_available_start=0, end_sample_index=100)
        assert aligned_event(fake, 20)[1:] == (40, 60)
        assert aligned_event(fake, 101) is None  # Full centred frame not yet received.
        fake.raw_available_start = 41
        fake.raw_u16le = fake.raw_u16le[82:]
        assert aligned_event(fake, 20) is None  # Required prehistory already evicted.
        fake.event_index.events = ()
        assert aligned_event(fake, 20) is None

        assert wait(app, lambda: not viewer._sync_waiting)
        held = viewer.selection
        with patch('motortester.v2.stream_sync.aligned_event', return_value=None):
            until = time.monotonic() + .15
            wait(app, lambda: time.monotonic() >= until)
            assert viewer.selection == held and 'предыдущий кадр' in viewer.view_mode_label.text()
        panel.cursors.enabled.setChecked(True)
        assert not viewer.event_sync and not panel.sync_button.isChecked()
        assert wait(app, lambda: panel.cursors.values is not None)
        held = viewer.selection
        until = time.monotonic() + .1
        wait(app, lambda: time.monotonic() >= until)
        assert viewer.selection == held
        panel.sync_button.click()
        assert viewer.event_sync and not panel.cursors.enabled.isChecked()
        window.xposition.set_value(window.xposition.value + .001, emit=True)
        assert not viewer.event_sync and viewer.holding_live
        panel.sync_button.click()
        viewer.previous_button.click()
        assert not viewer.event_sync and viewer._event is not None
        panel.sync_button.click()
        panel.pause_button.click()
        assert panel._paused and not viewer.event_sync and not panel.sync_button.isEnabled()
        viewer.follow_button.click()
        assert not panel._paused and viewer.follow_tail and not viewer.event_sync
        assert wait(app, lambda: panel.sync_button.isEnabled())
        panel.sync_button.click()
        assert viewer.event_sync
        viewer.plot.setXRange(.001, .005, padding=0)
        viewer.plot.getViewBox().sigRangeChangedManually.emit([True, False])
        assert not viewer.event_sync and viewer.holding_live
        panel.sync_button.click()
        assert viewer.event_sync
    finally:
        viewer.plot_drawn.disconnect(drawn)
    return evidence
