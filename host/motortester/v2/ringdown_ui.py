"""Explicit, read-only analysis of a held raw tail in the existing plot.

The region and peaks use absolute sample indices. Only projection into the
current plot subtracts its local origin and applies the saved CH1 profile.
No acquisition command, automatic spark boundary, or diagnosis is produced.
"""
import math
from statistics import median

from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg

from .measurement_ui import MeasurementRunner
from .ringdown import MAX_RINGDOWN_SAMPLES, read_ringdown, suggest_ringdown


def _time_text(seconds):
    """Compact estimates; extra cursor precision would imply unsupported accuracy."""
    magnitude = abs(seconds)
    factor, unit = ((1e6, 'мкс') if magnitude < .001 else
                    (1e3, 'мс') if magnitude < 1 else (1, 'с'))
    return f'{seconds * factor:.4g} {unit}'.replace('.', ',')


class RingdownControls(QtWidgets.QWidget):
    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self._closed = self._moving = self._binding = False
        self._reader = self._scope = self._indices = self._event = None
        self._operation = None
        self._revision = 0
        self.result = self.suggestion = None
        self.series = {}
        self._message = 'Выделите колебания после основного импульса и нажмите «Рассчитать».'
        self.runner = MeasurementRunner(self)
        self.runner.ready.connect(self._completed)
        self.runner.failed.connect(self._failed)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.toggle = QtWidgets.QToolButton()
        self.toggle.setText('Затухающие колебания')
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.toggle.setToolTip('Удержать показанный участок для отдельного анализа; приём и запись продолжаются.')
        layout.addWidget(self.toggle, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        self.body = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)
        buttons = QtWidgets.QHBoxLayout()
        self.propose_button = QtWidgets.QPushButton('Предложить участок')
        self.calculate_button = QtWidgets.QPushButton('Рассчитать')
        self.add_button = QtWidgets.QPushButton('Добавить в серию')
        self.propose_button.setToolTip('Найти расчётного кандидата внутри видимого участка. Осмотрите его перед расчётом.')
        self.add_button.setToolTip('До 20 пригодных выбранных событий этого источника; повтор заменяет результат события.')
        for button in (self.propose_button, self.calculate_button, self.add_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        body.addLayout(buttons)
        self.readout = QtWidgets.QLabel()
        self.readout.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.readout.setWordWrap(True)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.readout.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)
        body.addWidget(self.readout)
        layout.addWidget(self.body)
        self.body.hide()
        self.region = pg.LinearRegionItem((0, 1), movable=True,
            brush=pg.mkBrush(70, 185, 120, 35), pen=pg.mkPen('#8ce2a8', width=1.2),
            hoverBrush=pg.mkBrush(70, 185, 120, 55),
            hoverPen=pg.mkPen('#ffffff', width=1.5))
        self.region.setZValue(8)
        self.peaks_item = pg.ScatterPlotItem(size=8, symbol='o', pen=pg.mkPen('#d6ffe1'),
                                             brush=pg.mkBrush('#59b982'))
        self.peaks_item.setZValue(18)
        viewer.plot.addItem(self.region, ignoreBounds=True)
        viewer.plot.addItem(self.peaks_item, ignoreBounds=True)
        self.region.hide()
        self.peaks_item.hide()
        self.region.sigRegionChanged.connect(self._region_moved)
        self.toggle.toggled.connect(self._toggle)
        self.propose_button.clicked.connect(self.propose)
        self.calculate_button.clicked.connect(self.calculate)
        self.add_button.clicked.connect(self.add_to_series)
        viewer.inspection_reset.connect(self.reset)
        viewer.source_reset.connect(self.source_reset)
        viewer.plot_drawn.connect(self.refresh_display)
        self.refresh_display()

    def _token(self):
        viewer = self.viewer
        if viewer._recording is not None:
            return viewer._source, 'file', id(viewer._recording)
        if viewer._held_live is not None:
            return viewer._source, 'held', id(viewer._held_live)
        return None

    def _available(self):
        p = self.viewer
        return (not self._closed and not p._closed and not p._source_failure and
                p.selection is not None and
                (p._recording is not None or p._drawn_live is not None and
                 p._drawn_live.raw_u16le is not None))

    def _valid_bound(self):
        selection = self.viewer.selection
        in_frame = (self._indices is None or selection is not None and
                    selection.start <= self._indices[0] < self._indices[1] <= selection.stop)
        return (self.toggle.isChecked() and self._available() and self._reader is not None
                and self._scope == self._token() and in_frame)

    def _bind_reader(self):
        if self._valid_bound():
            return True
        if self._reader is not None:
            self.reset()
        if not self._available():
            self._message = 'Исходные отсчёты недоступны. Дождитесь графика или откройте запись.'
            self._show_result()
            return False
        # hold_current_view may clear the viewer's event selection. Preserve
        # its original association only for the explicit series action below.
        event = self.viewer._event
        self._binding = True
        try:
            self.viewer.hold_current_view()
            reader = self.viewer.inspection_reader()
        finally:
            self._binding = False
        if reader is None:
            self._message = 'Полный исходный участок недоступен. Дождитесь графика.'
            self._show_result()
            return False
        self._reader, self._scope, self._event = reader, self._token(), event
        return True

    def _toggle(self, enabled):
        self.toggle.setArrowType(QtCore.Qt.ArrowType.DownArrow if enabled else QtCore.Qt.ArrowType.RightArrow)
        self.body.setVisible(enabled)
        if not enabled:
            self.reset()
        elif self._bind_reader():
            selection = self.viewer.selection
            if self._reader.first_sample_index <= selection.start < selection.stop <= self._reader.end_sample_index:
                self.set_indices(selection.start, selection.stop)
        self.refresh_display()

    def reset(self):
        """Forget this inspection, while keeping accepted events of this source."""
        if self._binding:
            return
        self.runner.cancel()
        self._revision += 1
        self._reader = self._scope = self._indices = self._event = self._operation = None
        self.result = self.suggestion = None
        self.region.hide()
        self.peaks_item.hide()
        self.peaks_item.clear()
        self._message = 'Выберите событие или участок. «Предложить участок» не определяет конец искры.'
        self._show_result()
        self.calculate_button.setEnabled(False)
        self.add_button.setEnabled(False)

    def source_reset(self):
        self.series.clear()
        self.reset()

    def set_indices(self, start, stop):
        """Set the explicit half-open original interval; no sample is edited."""
        if not self._valid_bound():
            raise ValueError('Сначала удержите участок кнопкой «Затухающие колебания».')
        if (type(start) is not int or type(stop) is not int or
                not self._reader.first_sample_index <= start < stop <= self._reader.end_sample_index):
            raise ValueError('Границы участка должны находиться внутри доступных исходных отсчётов.')
        self.runner.cancel()
        self._revision += 1
        self._operation = None
        self._indices = start, stop
        self.result = self.suggestion = None
        self.peaks_item.clear()
        self.peaks_item.hide()
        self._message = ('Осмотрите выделенный участок; перетащите границы и нажмите «Рассчитать».'
                         if stop-start <= MAX_RINGDOWN_SAMPLES else
                         f'Сузьте выделенный участок до {MAX_RINGDOWN_SAMPLES:,} отсчётов.'.replace(',', ' '))
        self.refresh_display()

    def _region_moved(self, *_):
        if self._moving or not self._valid_bound():
            return
        left, right = self.region.getRegion()
        fs = self._reader.identity.nominal_fs_hz
        if not all(math.isfinite(value) for value in (left, right, left*fs, right*fs)):
            return
        origin = self.viewer._display_origin
        first, end = self._reader.first_sample_index, self._reader.end_sample_index
        start = max(first, min(end-1, origin + math.floor(left*fs + .5)))
        stop = max(start+1, min(end, origin + math.floor(right*fs + .5)))
        if (start, stop) != self._indices:
            self.set_indices(start, stop)

    def propose(self):
        if not self.toggle.isChecked() or not self._bind_reader():
            return False
        selection = self.viewer.selection
        return self._submit('suggest', selection.start, selection.stop)

    def calculate(self):
        if not self._valid_bound() or self._indices is None:
            return False
        return self._submit('calculate', *self._indices)

    def _submit(self, kind, start, stop):
        self.runner.cancel()
        self._revision += 1
        self._operation = kind
        self.result = self.suggestion = None
        self.peaks_item.clear()
        self.peaks_item.hide()
        reader = self._reader
        operation = suggest_ringdown if kind == 'suggest' else read_ringdown
        key = self._scope, self._revision, kind, start, stop
        self.runner.submit(key, lambda: operation(reader, start, stop))
        self._message = ('Поиск возможного участка колебаний…' if kind == 'suggest' else
                         'Расчёт по исходным отсчётам…')
        self._show_result()
        self.add_button.setEnabled(False)
        return True

    def _completed(self, result):
        if not self._valid_bound():
            self.reset()
            return
        operation, self._operation = self._operation, None
        if operation == 'suggest':
            if result.available:
                self.set_indices(result.start_index, result.stop_index)
                self.suggestion = result
                self._message = 'Предложен участок: проверьте границы и нажмите «Рассчитать». Это не конец искры.'
            else:
                self._message = 'Участок не предложен: ' + (result.reason or 'нет подходящих колебаний.')
        elif operation == 'calculate':
            self.result = result
            self._message = '' if result.available else 'Расчёт недоступен: ' + (result.reason or 'участок не подходит.')
        self.refresh_display()

    def _failed(self, message):
        if not self._valid_bound():
            self.reset()
            return
        reader = self._reader
        self._operation = None
        self.result = self.suggestion = None
        if reader is self.viewer._recording:
            self.viewer._latch_source_failure('Ошибка чтения участка колебаний: ' + message)
        self._message = 'Исходные данные не прочитаны: ' + message
        self.refresh_display()

    def _series_event_key(self):
        if not self._valid_bound() or self._event is None or self._indices is None:
            return None
        event = self._event
        if not event.start_index <= self._indices[0] < self._indices[1] <= event.end_index:
            return None
        return self.viewer._source, event.trigger_index

    def add_to_series(self):
        key = self._series_event_key()
        if key is None or self.result is None or not self.result.available:
            return False
        self.series.pop(key, None)
        self.series[key] = self.result
        while len(self.series) > 20:
            self.series.pop(next(iter(self.series)))
        self._show_result()
        return True

    def _show_result(self):
        number = lambda value: f'{value:.4g}'.replace('.', ',')
        result = self.result
        if result is not None and result.available:
            line = (f'Колебания: f ≈ {number(result.frequency_hz)} Гц · τ ≈ {_time_text(result.tau_s)}'
                    f' · Aслед/Aпред ≈ {number(result.amplitude_ratio_per_cycle)}'
                    f' · различимых циклов {result.cycle_count} за {_time_text(result.duration_s)}')
            note = result.warning or 'Время номинальное. Это параметры выделенных колебаний, не диагноз.'
        else:
            line, note = self._message, ''
        if self.series:
            values = tuple(self.series.values())
            frequencies = tuple(v.frequency_hz for v in values)
            taus = tuple(v.tau_s for v in values)
            summary = (f'Серия {len(values)}/20: f {number(median(frequencies))}'
                       f' [{number(min(frequencies))}…{number(max(frequencies))}] Гц'
                       f' · τ {_time_text(median(taus))}'
                       f' [{_time_text(min(taus))}…{_time_text(max(taus))}]')
            note = summary + (' · ' + result.warning if result is not None and result.warning else '')
        elif result is not None and result.available and self._series_event_key() is None:
            note += ' Ручной участок без выбранного события в серию не добавляется.'
        self.readout.setText(line + ('\n' + note if note else ''))
        interval = '' if self._indices is None else f'Исходный полуинтервал {self._indices}. '
        self.readout.setToolTip(interval +
            'τ — время уменьшения амплитуды в e≈2,72 раза; Aслед/Aпред — отношение амплитуд '
            'последовательных пиков одной полярности. Не длительность искры. '
            'Серия содержит только вручную добавленные пригодные события этого источника; '
            'показаны медианы и [минимум…максимум], повтор того же события заменяется. '
            'Внутренняя оценка фонового уровня не меняет исходный DC или шкалу CH1. '
            'Исходные коды не меняются.')

    def refresh_display(self, *_):
        available = self._available()
        self.toggle.setEnabled(available or self.toggle.isChecked())
        if self._reader is not None and not self._valid_bound():
            self.reset()
        bound = self._valid_bound()
        self.propose_button.setEnabled(available and self.toggle.isChecked())
        self.calculate_button.setEnabled(bound and self._indices is not None)
        self.add_button.setEnabled(bound and self.result is not None and self.result.available
                                   and self._series_event_key() is not None)
        if bound and self._indices is not None:
            p, reader = self.viewer, self._reader
            fs, origin = reader.identity.nominal_fs_hz, p._display_origin
            self._moving = True
            try:
                self.region.setBounds(((reader.first_sample_index-origin)/fs,
                                       (reader.end_sample_index-origin)/fs))
                self.region.setRegion(tuple((index-origin)/fs for index in self._indices))
                self.region.show()
            finally:
                self._moving = False
            if self.result is not None and self.result.available:
                profile = getattr(p, 'input_profile', None)
                volts = profile is not None and profile.configured and not p.raw_display
                xs, ys = [], []
                for relative, code in self.result.peaks:
                    index = self._indices[0] + relative
                    if p.selection.start <= index < p.selection.stop:
                        xs.append((index-origin)/fs)
                        # Plot ordinates stay in volts even when its axis says mV.
                        ys.append(profile.a*code+profile.b if volts else code)
                self.peaks_item.setData(xs, ys)
                self.peaks_item.setVisible(bool(xs))
        self._show_result()

    def shutdown(self):
        self._closed = True
        self.series.clear()
        self.reset()
        self.runner.shutdown()
        self.toggle.setEnabled(False)
        self.propose_button.setEnabled(False)
