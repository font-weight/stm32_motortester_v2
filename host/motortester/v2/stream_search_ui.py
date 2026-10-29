"""Main-window editor for host event search, separate from voltage/DEMO knobs."""
from PySide6 import QtCore, QtWidgets

from .stream_search import make_config, describe
from .widgets import Knob, SafeSpinBox


class StreamSearchControls(QtWidgets.QWidget):
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self._key = None
        self._loading = False
        self.dirty = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fields = QtWidgets.QWidget()
        fields = QtWidgets.QVBoxLayout(self.fields)
        fields.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        fields.setContentsMargins(0, 0, 0, 0)
        knobs = QtWidgets.QHBoxLayout()
        self.threshold = Knob("Уровень запуска", 0, 4095, 2600, 1, "код")
        self.holdoff = Knob("Пауза запуска", 0, 1, .002, .001, "мс")
        self.holdoff.set_display(1000, "мс")
        self.threshold.setToolTip("Порог поиска по исходным кодам ADC12. Входное напряжение пока неизвестно.")
        self.holdoff.setToolTip("Минимум времени между началами событий. Приём и запись не останавливает.")
        for knob in (self.threshold, self.holdoff):
            knobs.addWidget(knob)
            knob.changed.connect(self._edited)
        fields.addLayout(knobs)
        edges = QtWidgets.QHBoxLayout()
        edges.addWidget(QtWidgets.QLabel("Направление кода"))
        self.rising, self.falling = QtWidgets.QPushButton("↗"), QtWidgets.QPushButton("↘")
        self.edges = QtWidgets.QButtonGroup(self)
        for button, tip in ((self.rising, "Нарастание кода"), (self.falling, "Спад кода")):
            button.setCheckable(True)
            button.setToolTip(tip)
            self.edges.addButton(button)
            edges.addWidget(button)
            button.clicked.connect(self._edited)
        self.rising.setChecked(True)
        fields.addLayout(edges)
        self.advanced_button = QtWidgets.QPushButton("Дополнительно: гистерезис и контекст ▾")
        self.advanced_button.setCheckable(True)
        fields.addWidget(self.advanced_button)
        self.advanced = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout()
        self.advanced.setLayout(form)
        form.setContentsMargins(0, 0, 0, 0)
        self.hysteresis = self._spin(1, 4095, 400, " код", decimals=0)
        self.window = self._spin(.1, 200, 10, " мс")
        self.post = self._spin(0, 200, 3, " мс")
        self.pre = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.pre.setRange(1, 90)
        self.pre.setValue(10)
        self.pre.valueChanged.connect(self._edited)
        self.pre_label = QtWidgets.QLabel("Предыстория · 10 %")
        form.addRow("Гистерезис", self.hysteresis)
        form.addRow("Предел события", self.window)
        form.addRow("Хвост после возврата", self.post)
        fields.addWidget(self.advanced)
        self.advanced.hide()
        self.advanced_button.toggled.connect(self.advanced.setVisible)
        fields.addWidget(self.pre_label)
        fields.addWidget(self.pre)
        self.window.setToolTip("Максимальная длина контекста события, включая предысторию. Не масштаб графика.")
        self.post.setToolTip("Хвост после устойчивого возврата за уровень гистерезиса, не после начала импульса.")
        layout.addWidget(self.fields)
        self.apply_button = QtWidgets.QPushButton("Применить поиск")
        self.apply_button.clicked.connect(self.apply_pending)
        self.restore_button = QtWidgets.QPushButton("Вернуть параметры файла")
        self.restore_button.clicked.connect(self.restore_file)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.restore_button)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.note.setStyleSheet("color: #a1bccb")
        layout.addWidget(self.note)
        dialog.prepare_search = self.apply_pending
        dialog.search_changed.connect(self.refresh)
        self.refresh()

    def _spin(self, low, high, value, suffix, decimals=3):
        spin = SafeSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(self._edited)
        return spin

    def load(self, config):
        self._loading = True
        fs, bits = self.dialog.search_basis()
        self.threshold.set_bounds(0, 4092 if bits == 10 else 4095)
        self.threshold.set_value(config.threshold_code)
        self.holdoff.set_value(config.holdoff_samples / fs)
        self.rising.setChecked(config.polarity == 'above')
        self.falling.setChecked(config.polarity == 'below')
        self.hysteresis.setValue(abs(config.threshold_code - config.release_code))
        self.window.setValue(config.max_event_samples * 1000 / fs)
        self.post.setValue(config.post_samples * 1000 / fs)
        self.pre.setValue(round(100 * config.pre_samples / config.max_event_samples))
        self.pre_label.setText(f"Предыстория · {self.pre.value()} %")
        self._loading = False
        self.dirty = False

    def _edited(self, *_):
        if self._loading:
            return
        self.dirty = True
        self.pre_label.setText(f"Предыстория · {self.pre.value()} %")
        self.refresh()

    def candidate(self):
        fs, bits = self.dialog.search_basis()
        return make_config(fs=fs, retained_bits=bits, threshold=self.threshold.value,
                           hysteresis=self.hysteresis.value(), falling=self.falling.isChecked(),
                           holdoff_ms=self.holdoff.value * 1000, window_ms=self.window.value(),
                           pre_percent=self.pre.value(), post_ms=self.post.value())

    def refresh(self):
        dlg = self.dialog
        # Only a source/rate/committed setting change replaces drafts. Periodic
        # status signals must not undo an edit while the user types.
        key = (id(dlg.archive), dlg._opening, dlg.search_basis(), dlg.search_config())
        if key != self._key:
            self._key = key
            self.load(dlg.search_config())
        editable = dlg.search_editable()
        self.fields.setEnabled(editable)
        self.restore_button.setVisible(dlg.archive is not None)
        self.restore_button.setEnabled(editable)
        self.apply_button.setEnabled(editable)
        error = ""
        try:
            config = self.candidate() if self.dirty else dlg.search_config()
            details = describe(config, dlg.search_basis()[0])
        except ValueError as exc:
            error, details = str(exc), ""
            self.apply_button.setEnabled(False)
        summary = (f"Порог {config.threshold_code} / возврат {config.release_code} код."
                   if not error else error)
        self.note.setToolTip(details)
        self.note.setText(("Не применено: " if self.dirty else "") + summary +
                          "\n" + dlg.search_origin_note())

    def apply_pending(self):
        dlg = self.dialog
        if not dlg.search_editable():
            return False
        try:
            # Preserve exact stored sample counts on load/restore. UI rounding
            # of percentages is presentation only until the operator edits.
            config = self.candidate() if self.dirty else dlg.search_config()
            if not dlg.apply_search(config):
                return False
            self.dirty = False
            self._key = None
            self.refresh()
            return True
        except ValueError as exc:
            self.note.setText(str(exc) + "\nПараметры не применены.")
            return False

    def restore_file(self):
        if self.dialog.search_editable() and self.dialog.archive is not None:
            self.dialog.apply_search(self.dialog.original_file_search())
            self.dialog._file_search_revision = 0
            self._key = None
            self.refresh()
