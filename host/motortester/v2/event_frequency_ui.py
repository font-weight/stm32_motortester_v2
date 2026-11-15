"""Live threshold-event readout, independent of the held/zoomed graph."""
import time

from PySide6 import QtCore, QtWidgets

from .event_frequency import estimate_event_frequency, format_event_frequency


class EventFrequencyReadout(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.setToolTip(
            'Частота найденных пороговых событий по последним 2–8 интервалам. '
            'Время рассчитано по номинальной частоте приёма. Масштаб, курсоры и '
            'пауза просмотра не меняют эту живую оценку. Порог, гистерезис и '
            'пауза запуска влияют на поиск. Событие не подтверждает отдельную искру; '
            'обороты двигателя здесь не вычисляются.')
        self._active = False
        self._key = None
        self._sequence = -1
        self._end = None
        self._advanced_at = None
        self.result = None
        self.reset()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._watchdog)
        self._timer.start()

    def reset(self):
        self._key = self._end = self._advanced_at = self.result = None
        self._sequence = -1
        self.setText('Частота событий: — · появится во время живого приёма.')

    def set_active(self, active):
        active = bool(active)
        if active != self._active:
            self._active = active
            self.reset()

    def observe(self, owner, source):
        if not self._active:
            return
        key = (id(owner), source.revision, source.identity,
               source.config_revision, source.config)
        if key != self._key:
            self.reset()
            self._key = key
        if source.sequence <= self._sequence:
            return
        self._sequence = source.sequence
        if self._end is None or source.end > self._end:
            self._advanced_at = time.monotonic()
        self._end = source.end
        self.result = estimate_event_frequency(source.events, source.detector,
                                               source.identity.nominal_fs_hz)
        self.setText(format_event_frequency(self.result).replace(
            'Частота событий:', 'Частота событий (живой приём):', 1))
        self._watchdog()

    def _watchdog(self):
        # Source time detects missing events; wall time detects a frozen source.
        # Neither timeout proves zero sparks or an electrically quiet input.
        if (self._active and self._advanced_at is not None and
                time.monotonic() - self._advanced_at > 2.0):
            self.result = None
            self.setText('Частота событий: — · нет свежих данных более 2 с.')

