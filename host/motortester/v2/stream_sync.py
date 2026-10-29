"""Event-aligned display only; original timestamps and acquisition stay intact."""
from PySide6 import QtCore
import pyqtgraph as pg
import struct

from ..gui_stream import StreamViewerPanel, DETAIL_SAMPLES


def aligned_event(snapshot, width, after=-1):
    """Newest indexed crossing with a complete, contiguous raw display window.

    Width is in samples, independent of variable event duration. Never clamp
    a frame at buffer boundaries: that would move the crossing on the screen.
    The odd-width centre is rounded down to the nearest original sample.
    """
    index = snapshot.event_index
    if index is None or snapshot.raw_u16le is None:
        return None
    for event in reversed(index.events):
        if event.ordinal <= after:
            break
        # A slow edge can legitimately carry baseline_unsettled. Confirm the
        # crossing from adjacent source codes instead of rejecting that flag.
        offset = event.trigger_index - snapshot.raw_available_start
        if offset < 1 or offset >= len(snapshot.raw_u16le) // 2:
            continue
        before, current = struct.unpack_from('<HH', snapshot.raw_u16le, (offset - 1) * 2)
        if index.config.high(before) or not index.config.high(current):
            continue
        start = event.trigger_index - width // 2
        if snapshot.raw_available_start <= start and start + width <= snapshot.end_sample_index:
            return event, start, start + width
    return None


class SynchronizedStreamViewer(StreamViewerPanel):
    sync_changed = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs):
        self.event_sync = False
        self._sync_width = 0
        self._sync_ordinal = -1
        self._aligning = False
        self._sync_waiting = False
        super().__init__(*args, **kwargs)
        self.trigger_marker = pg.InfiniteLine(angle=90, movable=False,
                                             pen=pg.mkPen('#00d9e3', style=QtCore.Qt.PenStyle.DashLine),
                                             label='Порог', labelOpts={'position': .93})
        self.plot.addItem(self.trigger_marker)
        self.trigger_marker.hide()

    def set_event_sync(self, enabled):
        enabled = bool(enabled)
        if enabled and (self._closed or self._recording is not None or
                        self.selection is None or self._last_live is None):
            return False
        if enabled == self.event_sync:
            return True
        self.event_sync = enabled
        self._sync_ordinal = -1
        self._sync_waiting = False
        self.trigger_marker.hide()
        if enabled:
            self.inspection_reset.emit()
            self._sync_width = min(self.selection.width, DETAIL_SAMPLES)
            self.follow_tail = False
            self._held_live = None
            self._event = None
            self._revision += 1
            self._pending = None
            self.curve.setData([], [])
            self._consume_live_view(self._last_live)
        else:
            self.view_mode_label.setText('Просмотр удержанного фрагмента · «К хвосту» вернёт свежие данные')
        self.sync_changed.emit(enabled)
        return True

    def set_sync_width(self, width):
        if not self.event_sync:
            return False
        self._sync_width = max(1, min(int(width), DETAIL_SAMPLES))
        self._sync_ordinal = -1
        self._sync_waiting = False
        self._revision += 1
        self._pending = None
        self.curve.setData([], [])
        self.trigger_marker.hide()
        self._consume_live_view(self._last_live)
        return True

    def _consume_live_view(self, snapshot):
        if not self.event_sync:
            return False
        # Finish the single in-flight frame before scheduling another. The
        # base poll consumes new snapshots before a completed worker result;
        # replacing that result each tick would starve actual screen updates.
        if self._sync_waiting:
            return True
        found = aligned_event(snapshot, self._sync_width, self._sync_ordinal)
        if found is None:
            suffix = (' · показан предыдущий кадр' if self._sync_ordinal >= 0 else '')
            self.view_mode_label.setText('Синхронизация: ожидание нового события и полного кадра' + suffix)
            return True
        event, start, stop = found
        self.inspection_reset.emit()
        self._held_live = snapshot
        self._event_notice = None
        self._sync_waiting = True
        self._aligning = True
        try:
            self.select_range(start, stop, hold_live=False)
        finally:
            self._aligning = False
        self._event = event
        self._sync_ordinal = event.ordinal
        self.view_mode_label.setText('Синхронизация по событию · порог в центре · ожидание следующего кадра')
        self._actions()
        return True

    def _draw(self, payload):
        if payload.selection != self.selection:
            return
        self._sync_waiting = False
        if self.event_sync and self._event is not None:
            self.trigger_marker.setValue((self._event.trigger_index - self.selection.start) / self._identity[3])
            self.trigger_marker.show()
        super()._draw(payload)

    def _set_status(self, text):
        if self.event_sync and text.startswith('Ошибка held:'):
            self.set_event_sync(False)
            self.view_mode_label.setText('Синхронизация остановлена: ошибка подготовки кадра')
        super()._set_status(text)

    def select_range(self, *args, **kwargs):
        if self.event_sync and not self._aligning:
            self.set_event_sync(False)
        return super().select_range(*args, **kwargs)

    def _select_event(self, event):
        self.set_event_sync(False)
        return super()._select_event(event)

    def follow(self):
        self.set_event_sync(False)
        return super().follow()

    def _reset_source(self):
        self.set_event_sync(False)
        return super()._reset_source()

    def shutdown(self):
        self.set_event_sync(False)
        super().shutdown()
