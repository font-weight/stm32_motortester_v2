"""Read-only embedded view of the original MTV2/MTCAP recording model.

These files may contain gaps, non-integral Fs or non-stream trigger metadata.
They remain Recording objects: no fabricated stream start/end or event index.
"""
from pathlib import Path
import math

import numpy as np
from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg

from .analog_view import ConnectorAxis
from .data import Recording
from .measurement_ui import MeasurementRunner, format_segment_measurements
from .segment_measurements import MAX_MEASUREMENT_SAMPLES, SegmentMeasurements, analyze_samples
from .storage import load, export_csv


def measure_legacy_interval(recording, start, stop):
    """Measure the entire requested half-open raw interval, never its envelope.

    MTV2/MTCAP use the original ADC12 domain and may have fractional Fs or
    an unknown-duration boundary between adjacent blocks. Such boundaries
    invalidate an interval crossing them, but not a later complete interval.
    """
    count = max(0, stop - start)

    def unavailable(reason):
        return SegmentMeasurements(count, None, None, None, None, None, reason, reason, False)

    if count > MAX_MEASUREMENT_SAMPLES:
        return unavailable('Сузьте видимый участок: предел — 262 144 исходных отсчёта.')
    if count == 0:
        return unavailable('В видимом участке нет исходных отсчётов.')
    if start < recording.start_index or stop > recording.end_index:
        return unavailable('Участок выходит за границы исходных данных. Сузьте видимую область.')
    codes, expected = [], start
    for block in recording.blocks:
        left, right = max(start, block.start_index), min(stop, block.end_index)
        if left >= right:
            continue
        if left != expected or (left > start and left == block.start_index and block.gap_before):
            return unavailable('В видимом участке есть разрыв исходных данных.')
        codes.extend(block.samples[left - block.start_index:right - block.start_index])
        expected = right
    if expected != stop:
        return unavailable('В видимом участке есть разрыв исходных данных.')
    return analyze_samples(codes, recording.sample_rate_hz, code_step=1)


def _index_boundary(local_s, sample_rate_hz):
    """Ceil in local time, snapping only arithmetic ULPs at sample boundaries."""
    position = local_s * sample_rate_hz
    nearest = round(position)
    if abs(position - nearest) <= 4 * math.ulp(position):
        position = nearest
    return math.ceil(position)


class LegacyRecordingView(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.recording = None
        self.path = None
        self.voltage_unit = 'В'
        self.raw = False
        self._x = self._codes = np.array([], dtype=float)
        self._origin_s = 0.
        self._cursor_updating = False
        self.measurement_result = None
        self._measurement_interval = None
        self._measurement_error = None
        self.measurement_runner = MeasurementRunner(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.info = self._label('Откройте прежнюю запись .mtv2 или .mtcap.')
        self.profile_note = self._label('')
        self.quality = self._label('')
        for widget in (self.info, self.profile_note, self.quality):
            layout.addWidget(widget)
        self.axis = ConnectorAxis(orientation='left')
        self.plot = pg.PlotWidget(background='#091720', axisItems={'left': self.axis})
        self.plot.setObjectName('legacyRecordingPlot')
        self.plot.setMinimumHeight(220)
        self.plot.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=.2)
        self.plot.disableAutoRange()
        self.plot.setLabel('bottom', 'Время от начала сохранённой записи, с')
        self.plot.getAxis('bottom').enableAutoSIPrefix(False)
        self.curve = self.plot.plot([], [], pen=pg.mkPen('#ffe800', width=1.5))
        layout.addWidget(self.plot, 1)
        self.measurement_label = self._label('Измерения видимого участка появятся после открытия записи.')
        self.measurement_label.setObjectName('legacySegmentMeasurements')
        layout.addWidget(self.measurement_label)
        row = QtWidgets.QHBoxLayout()
        self.cursor_toggle = QtWidgets.QCheckBox('Курсоры A–B')
        self.cursor_center = QtWidgets.QPushButton('В видимую область')
        self.export_button = QtWidgets.QPushButton('Экспорт записи CSV + JSON…')
        row.addWidget(self.cursor_toggle)
        row.addWidget(self.cursor_center)
        row.addStretch(1)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        self.cursor_readout = self._label('Курсоры показывают исходные отсчёты, включая отсутствие данных в разрывах.')
        self.message = self._label('')
        layout.addWidget(self.cursor_readout)
        layout.addWidget(self.message)
        self.cursor_lines = []
        for name in ('A', 'B'):
            line = pg.InfiniteLine(angle=90, movable=True, label=name,
                pen=pg.mkPen('#00d8e5', width=1.4, style=QtCore.Qt.PenStyle.DashLine),
                labelOpts={'position': .93, 'color': '#00d8e5'})
            self.plot.addItem(line, ignoreBounds=True)
            line.hide()
            line.sigPositionChanged.connect(self._read_cursors)
            self.cursor_lines.append(line)
        self.cursor_toggle.toggled.connect(self._toggle_cursors)
        self.cursor_center.clicked.connect(self.center_cursors)
        self.export_button.clicked.connect(self.export_dialog)
        self.plot.getViewBox().sigRangeChangedManually.connect(lambda *_: self.changed.emit())
        self.plot.getViewBox().sigXRangeChanged.connect(self._schedule_measurements)
        self.measurement_runner.ready.connect(self._measurement_ready)
        self.measurement_runner.failed.connect(self._measurement_failed)
        self.cursor_toggle.setEnabled(False)
        self.cursor_center.setEnabled(False)
        self.export_button.setEnabled(False)

    @staticmethod
    def _label(text):
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        return label

    @property
    def voltage_display(self):
        return self.recording is not None and self.recording.input_profile.configured and not self.raw

    def load_path(self, path):
        recording = load(path)  # Strict size/hash/model checks before replacing the visible file.
        self.load_recording(recording, path=path)
        return recording

    def load_recording(self, recording, *, path=None):
        if type(recording) is not Recording:
            raise ValueError('Нужна исходная запись .mtv2 / .mtcap')
        self.measurement_runner.cancel()
        self.measurement_result = None
        self._measurement_interval = None
        self._measurement_error = None
        self.recording, self.path = recording, None if path is None else Path(path)
        self._origin_s = recording.start_index / recording.sample_rate_hz
        xs, codes, previous = [], [], None
        for block in recording.blocks:
            if previous is not None and (block.start_index != previous or block.gap_before):
                xs.append(np.array([np.nan])); codes.append(np.array([np.nan]))
            # Subtract integer indices before conversion to local floating time.
            xs.append((np.arange(len(block.samples), dtype=float) + (block.start_index - recording.start_index))
                      / block.sample_rate_hz)
            codes.append(np.asarray(block.samples, dtype=float))
            previous = block.end_index
        self._x, self._codes = np.concatenate(xs), np.concatenate(codes)
        self.cursor_toggle.setChecked(False)
        self.cursor_toggle.setEnabled(True)
        self.export_button.setEnabled(True)
        source = 'синтетические данные' if recording.source == 'demo' else 'источник DEVICE заявлен в файле'
        basis = {'synthetic_exact': 'синтетическая временная основа',
                 'nominal_unverified': 'частота номинальная, не проверена',
                 'measured': 'временная основа указана как измеренная в файле'}[recording.time_basis]
        name = self.path.name if self.path is not None else 'запись'
        self.info.setText(f'{name} · CH1 · {recording.channel_name}\n{source} · '
                          f'{recording.sample_rate_hz:g} отсчётов/с · {basis}')
        self.info.setToolTip(f'Исходный индекс начала: {recording.start_index}; '
                             f'время нуля графика: {self._origin_s:.17g} с в системе исходной записи. '
                             f'time_basis: {recording.time_basis}; сеанс: {recording.session_id}')
        p = recording.input_profile
        state = {'unconfigured': 'шкала В/мВ не настроена', 'nominal': 'расчётная шкала',
                 'calibrated': 'калибровка заявлена в файле'}[p.state]
        note = f'Сохранённый профиль: {p.profile_id} · {state}'
        if p.configured:
            note += f' · U_CH1 = {p.a:g} × код + {p.b:g} В'
            note += f'\nОснование: {p.coefficient_source}'
        if p.coupling == 'AC':
            note += ' · постоянная составляющая не измеряется'
        self.profile_note.setText(note)
        quality = f'Исходных отсчётов: {recording.sample_count:,} · разрывов: {len(recording.gaps)}'
        if 'window_local_time' in recording.quality_flags or recording.legacy_format == 'mtcap-v1':
            quality += ' · отдельное окно; промежутки между окнами неизвестны'
        if recording.quality_flags:
            quality += '\nОтметки файла: ' + ', '.join(recording.quality_flags)
        self.quality.setText(quality)
        self.quality.setToolTip('\n'.join(f'[{g.start_index}, {g.end_index}): {g.reason}' for g in recording.gaps))
        self.message.clear()
        self._render()
        self.full_signal()
        self.auto_scale()
        self._schedule_measurements()
        self.changed.emit()

    def _render(self):
        if self.recording is None:
            return
        p = self.recording.input_profile
        values = self._codes * p.a + p.b if self.voltage_display else self._codes
        self.axis.factor = 1000 if self.voltage_display and self.voltage_unit == 'мВ' else 1
        self.axis.picture = None
        self.axis.update()
        self.plot.setLabel('left', ('CH1 · AC' if p.coupling == 'AC' else 'CH1') + ', ' + self.voltage_unit
                           if self.voltage_display else 'Код АЦП')
        self.curve.setData(self._x, values, connect='finite', autoDownsample=True, downsampleMethod='peak')
        self._read_cursors()
        self._show_measurements()

    def _schedule_measurements(self, *_):
        if self.recording is None:
            return
        left, right = self.plot.getViewBox().viewRange()[0]
        recording = self.recording
        if not all(math.isfinite(value) for value in
                   (left, right, left * recording.sample_rate_hz, right * recording.sample_rate_hz)):
            self.measurement_runner.cancel()
            self.measurement_result = None
            self._measurement_interval = None
            self.measurement_label.setText('Измерения: — · недопустимый временной интервал.')
            return
        start = recording.start_index + _index_boundary(left, recording.sample_rate_hz)
        stop = recording.start_index + _index_boundary(right, recording.sample_rate_hz)
        key = (id(recording), start, stop)
        self._measurement_interval = (start, stop)
        if self.measurement_runner.submit(key, lambda: measure_legacy_interval(recording, start, stop)):
            self.measurement_result = None
            self._measurement_error = None
            self._show_measurements()

    def _measurement_ready(self, result):
        self.measurement_result = result
        self._measurement_error = None
        self._show_measurements()

    def _measurement_failed(self, message):
        self.measurement_result = None
        self._measurement_error = message
        self._show_measurements()

    def _show_measurements(self):
        if self.recording is None or self._measurement_interval is None:
            return
        recording = self.recording
        start, stop = self._measurement_interval
        left = (start - recording.start_index) / recording.sample_rate_hz
        right = (stop - recording.start_index) / recording.sample_rate_hz
        basis = {'synthetic_exact': 'синтетическое время',
                 'nominal_unverified': 'Fs номинальная, не проверена',
                 'measured': 'временная основа заявлена измеренной в файле'}[recording.time_basis]
        header = (f'Измерения видимого участка: {left:.6g}…{right:.6g} с · '
                  f'Fs {recording.sample_rate_hz:g} отсчётов/с · {basis}')
        text = ('Измерения: — · ' + self._measurement_error if self._measurement_error else
                'Расчёт по исходным отсчётам…' if self.measurement_result is None else
                format_segment_measurements(self.measurement_result, recording.input_profile,
                                            raw=self.raw, unit=self.voltage_unit))
        self.measurement_label.setText(header + '\n' + text)
        self.measurement_label.setToolTip(f'Исходный полуинтервал [{start}, {stop}); '
            'выбраны отсчёты с временем внутри видимого полуинтервала. '
            'Расчёт не использует прорежённые точки графика или расстояние между курсорами.')

    def closeEvent(self, event):
        self.measurement_runner.shutdown()
        super().closeEvent(event)

    def set_voltage_unit(self, unit):
        if unit not in ('В', 'мВ'):
            raise ValueError('Неизвестная единица напряжения')
        self.voltage_unit = unit
        self._render()
        self.changed.emit()

    def set_raw(self, raw):
        old_voltage = self.voltage_display
        self.raw = bool(raw)
        if self.recording is not None and old_voltage != self.voltage_display:
            low, high = self.plot.getViewBox().viewRange()[1]
            p = self.recording.input_profile
            bounds = [(v - p.b) / p.a for v in (low, high)] if old_voltage else [p.a*v+p.b for v in (low, high)]
            self.plot.setYRange(*sorted(bounds), padding=0)
        self._render()
        self.changed.emit()

    def apply_scope_view(self, *, seconds_per_div, x_start_s, y_center, codes_per_div, **kwargs):
        if self.recording is None:
            return False
        if not all(math.isfinite(v) for v in (seconds_per_div, x_start_s, y_center, codes_per_div)):
            return False
        if seconds_per_div <= 0 or codes_per_div <= 0:
            return False
        self.plot.setYRange(y_center - codes_per_div * 4, y_center + codes_per_div * 4, padding=0)
        if kwargs.get('change_time', True):
            self.plot.setXRange(x_start_s, x_start_s + seconds_per_div * 10, padding=0)
        self.changed.emit()
        return True

    def full_signal(self):
        if self.recording is not None:
            self.plot.setXRange(0, self.recording.duration_s, padding=0)
            self.changed.emit()

    def auto_scale(self):
        if self.recording is None:
            return
        low, high = float(np.nanmin(self._codes)), float(np.nanmax(self._codes))
        if self.voltage_display:
            p = self.recording.input_profile
            low, high = sorted((p.a*low+p.b, p.a*high+p.b))
        minimum_span = abs(self.recording.input_profile.a) if self.voltage_display else 1.
        margin = max((high-low)*.1, minimum_span)
        self.plot.setYRange(low-margin, high+margin, padding=0)
        self.changed.emit()

    def _toggle_cursors(self, checked):
        checked = checked and self.recording is not None
        self.cursor_center.setEnabled(checked)
        for line in self.cursor_lines:
            line.setVisible(checked)
        if checked:
            self.center_cursors()
        else:
            self.cursor_readout.setText('Курсоры показывают исходные отсчёты, включая отсутствие данных в разрывах.')

    def center_cursors(self):
        if self.recording is None or not self.cursor_toggle.isChecked():
            return
        left, right = self.plot.getViewBox().viewRange()[0]
        self._cursor_updating = True
        for line, fraction in zip(self.cursor_lines, (1/3, 2/3)):
            line.setValue(left + (right-left)*fraction)
        self._cursor_updating = False
        self._read_cursors()

    def _read_cursors(self, *_):
        if self._cursor_updating or self.recording is None or not self.cursor_toggle.isChecked():
            return
        points, texts = [], []
        factor = 1000 if self.voltage_unit == 'мВ' else 1
        for name, line in zip(('A', 'B'), self.cursor_lines):
            point = self.recording.sample_at_time(self._origin_s + line.value())
            points.append(point)
            if point is None:
                texts.append(f'{name}: нет исходного отсчёта')
            else:
                time, code, voltage = point
                value = f'{voltage*factor:.6g} {self.voltage_unit}' if self.voltage_display else f'{code} код'
                texts.append(f'{name}: {time-self._origin_s:.9g} с · {value}')
        if all(point is not None for point in points):
            texts.append(f'Δt: {points[1][0]-points[0][0]:.9g} с')
            if self.voltage_display:
                texts.append(f'ΔU: {(points[1][2]-points[0][2])*factor:.6g} {self.voltage_unit}')
        self.cursor_readout.setText('   |   '.join(texts))

    def export_path(self, path):
        if self.recording is None:
            return False
        result = export_csv(path, self.recording)
        self.message.setText('Экспорт сохранён: ' + str(result[0]))
        return result

    def export_dialog(self):
        if self.recording is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Экспорт прежней записи', '', 'CSV (*.csv)')
        if path:
            try:
                self.export_path(path)
            except (OSError, ValueError) as exc:
                self.message.setText('Не удалось экспортировать: ' + str(exc))
