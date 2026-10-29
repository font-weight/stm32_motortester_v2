"""Two raw cursor samples, independent of the decimated curve and receiver.

Coordinates are absolute integer indices; only small differences become float.
One separate worker/result and one replaceable request keep file I/O off Qt
without displacing the plot worker's pending repaint. No acquisition commands.
"""
from dataclasses import dataclass
import math
import struct

from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg

from ..gui_stream import _Mailbox, _Request, identity_key
from ..stream_model import uint


@dataclass(frozen=True, slots=True)
class CursorValues:
    a: int
    b: int
    code_a: int
    code_b: int
    delta_s: float


def read_cursor_pair(reader, a, b):
    """Read exactly two u16 samples, not an overview bin or their intervening span.

    A recovered file exposes only its verified prefix. Missing/changed bytes
    fail instead of filling a gap or returning a previous point's value.
    """
    uint(a); uint(b)
    key = identity_key(reader.identity)
    codes = []
    for index in (a, b):
        if not reader.first_sample_index <= index < reader.end_sample_index:
            raise ValueError("У курсора нет исходного отсчёта")
        blocks = iter(reader.iter_raw(index, index + 1, chunk_samples=1))
        block = next(blocks, None)
        if (block is None or identity_key(block.identity) != key or
                block.first_sample_index != index or len(block.raw_u16le) != 2 or
                next(blocks, None) is not None):
            raise ValueError("Отсчёт курсора отсутствует или не соответствует источнику")
        codes.append(struct.unpack('<H', block.raw_u16le)[0])
    return CursorValues(a, b, *codes, (b - a) / reader.identity.nominal_fs_hz)


def time_text(seconds):
    magnitude = abs(seconds)
    factor, unit = ((1e6, 'мкс') if magnitude < .001 else
                    (1e3, 'мс') if magnitude < 1 else (1, 'с'))
    return f'{seconds * factor:.9g} {unit}'.replace('.', ',')


class StreamCursorTool(QtWidgets.QWidget):
    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self._mailbox = _Mailbox()
        self._pending = None
        self._revision = 0
        self._reader = None
        self._indices = None
        self._moving = False
        self._closed = False
        self.values = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.enabled = QtWidgets.QCheckBox('Курсоры A–B')
        self.enabled.setToolTip('Перетащите A и B. В живом потоке показанный фрагмент удерживается; запись продолжается.')
        self.center_button = QtWidgets.QPushButton('В видимую область')
        row.addWidget(self.enabled)
        row.addWidget(self.center_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.readout = QtWidgets.QLabel('Включите курсоры для измерения двух исходных точек.')
        self.readout.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.readout.setWordWrap(True)
        layout.addWidget(self.readout)
        self.lines = []
        for name in ('A', 'B'):
            line = pg.InfiniteLine(angle=90, movable=True, label=name,
                pen=pg.mkPen('#00d8e5', width=1.5, style=QtCore.Qt.PenStyle.DashLine),
                hoverPen=pg.mkPen('#ffffff', width=2),
                labelOpts={'position': .93, 'color': '#00e7ef', 'fill': '#102a35'})
            line.setZValue(20)
            viewer.plot.addItem(line, ignoreBounds=True)
            line.hide()
            line.sigPositionChanged.connect(self._line_moved)
            self.lines.append(line)
        self.enabled.toggled.connect(self._toggle)
        self.center_button.clicked.connect(self.center)
        viewer.plot_drawn.connect(self._drawn)
        viewer.inspection_reset.connect(self.reset)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        mailbox = self._mailbox
        self.destroyed.connect(lambda: mailbox.close())
        self._drawn()

    @property
    def busy(self):
        with self._mailbox.lock:
            return bool(self._mailbox.running or self._mailbox.result or self._pending)

    def reset(self):
        self._revision += 1
        self._pending = self._reader = self._indices = self.values = None
        self.enabled.blockSignals(True)
        self.enabled.setChecked(False)
        self.enabled.blockSignals(False)
        for line in self.lines:
            line.hide()
        self.center_button.setEnabled(False)
        self.readout.setText('Включите курсоры для измерения двух исходных точек.')

    def _toggle(self, checked):
        if not checked:
            self.reset()
            return
        self.viewer.hold_current_view()
        self._reader = self.viewer.inspection_reader()
        if self._reader is None:
            self.reset()
            self.readout.setText('Исходные отсчёты пока недоступны. Дождитесь графика.')
            return
        self.center_button.setEnabled(True)
        self.center()

    def center(self):
        selection, reader = self.viewer.selection, self._reader
        if not self.enabled.isChecked() or selection is None or reader is None:
            return
        first = max(reader.first_sample_index, selection.start)
        last = min(reader.end_sample_index, selection.stop) - 1
        if last < first:
            return
        width = last - first
        self.set_indices(first + width // 3, first + 2 * width // 3)

    def set_indices(self, a, b):
        """Exact sample indices, also useful to make reproducible measurements."""
        uint(a); uint(b)
        if not self.enabled.isChecked() or self._reader is None:
            raise ValueError('Курсоры выключены')
        if not all(self._reader.first_sample_index <= i < self._reader.end_sample_index for i in (a, b)):
            raise ValueError('Курсор вне доступных исходных отсчётов')
        self._indices = a, b
        self._revision += 1
        self.values = None
        self.readout.setText('Чтение исходных значений A–B…')
        reader = self._reader
        self._pending = _Request(self.viewer._source, self._revision, 'cursor', reader,
                                lambda: read_cursor_pair(reader, a, b))
        self._place_lines()

    def _line_moved(self, line):
        if self._moving or self._indices is None:
            return
        value = line.value()
        if not math.isfinite(value):
            return
        # Subtract/restore the integer origin before any float coordinate use.
        index = self.viewer._display_origin + math.floor(value * self._reader.identity.nominal_fs_hz + .5)
        index = max(self._reader.first_sample_index, min(index, self._reader.end_sample_index - 1))
        pair = list(self._indices)
        pair[self.lines.index(line)] = index
        self.set_indices(*pair)

    def _place_lines(self):
        if self._indices is None:
            return
        self._moving = True
        try:
            selection = self.viewer.selection
            fs = self._reader.identity.nominal_fs_hz
            for line, index in zip(self.lines, self._indices):
                line.setValue((index - self.viewer._display_origin) / fs)
                line.setVisible(selection.start <= index < selection.stop)
        finally:
            self._moving = False

    def _drawn(self):
        p = self.viewer
        available = (not self._closed and not p._closed and not p._source_failure and
                     p.selection is not None and
                     (p._recording is not None or p._drawn_live is not None and
                      p._drawn_live.raw_u16le is not None))
        self.enabled.setEnabled(available)
        self.center_button.setEnabled(available and self.enabled.isChecked())
        self._place_lines()
        if self.values is not None:
            self._show_values()

    def _show_values(self):
        v, p = self.values, self.viewer
        fs = self._reader.identity.nominal_fs_hz
        base = self._reader.first_sample_index if p._recording is not None else p._first
        def point(name, index, code):
            outside = ' · вне экрана' if not p.selection.start <= index < p.selection.stop else ''
            return f'{name}: {time_text((index-base)/fs)} · {code} код{outside}'
        time_base = 'начала записи' if p._recording is not None else 'начала потока'
        bits = ('10 старших бит, шаг 4 кода на шкале ADC12.' if self._reader.identity.retained_bits == 10
                else 'Исходные коды АЦП.')
        self.readout.setText(
            f'{point("A", v.a, v.code_a)}    |    {point("B", v.b, v.code_b)}\n'
            f'B−A: Δt = {time_text(v.delta_s)} · Δкод = {v.code_b-v.code_a:+d}\n'
            f'Время от {time_base}, номинальное. {bits} Шкала В/мВ не настроена.')

    def _poll(self):
        if self._closed:
            return
        with self._mailbox.lock:
            completed, self._mailbox.result = self._mailbox.result, None
            idle = not self._mailbox.running
        if completed is not None:
            request, result, error = completed
            current_source = request.source == self.viewer._source
            # A stale pair must not suppress integrity errors from this file.
            if current_source and error and request.recording is self.viewer._recording:
                self.viewer._latch_source_failure('Ошибка чтения курсоров: ' + error)
                self.readout.setText('Нет достоверных значений: ' + error)
                self._drawn()
            elif (current_source and request.revision == self._revision and
                  self.enabled.isChecked() and request.recording is self._reader):
                self.values = result
                if error:
                    self.readout.setText('Нет исходных значений: ' + error)
                elif result is not None:
                    self._show_values()
        if idle and self._pending is not None:
            request, self._pending = self._pending, None
            self._mailbox.start(request)

    def shutdown(self):
        self.reset()
        self._closed = True
        self._timer.stop()
        self._mailbox.close()
        self._drawn()
