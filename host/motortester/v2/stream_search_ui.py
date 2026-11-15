"""Host search: connector voltage is translated once to canonical raw codes."""
from PySide6 import QtCore, QtWidgets

from .analog_profile import quantize_thresholds
from .input import UNKNOWN_PROFILE
from .stream_search import make_config, describe
from .widgets import Knob, SafeSpinBox


class StreamSearchControls(QtWidgets.QWidget):
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self._key = None
        self._loading = False
        self._unit = None
        self._factor = 1
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
        self.edge_label = QtWidgets.QLabel("Направление кода")
        edges.addWidget(self.edge_label)
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
        if hasattr(dialog, "input_changed"):
            dialog.input_changed.connect(self.refresh)
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
        profile = self.input_profile
        hysteresis = abs(config.threshold_code - config.release_code)
        if profile.configured:
            hysteresis *= abs(profile.a)
        self._presentation(bits, hysteresis)
        self.threshold.set_value(profile.voltage(config.threshold_code) if profile.configured
                                 else config.threshold_code)
        self.holdoff.set_value(config.holdoff_samples / fs)
        voltage_rising = config.polarity == 'above'
        if profile.configured and profile.a < 0:
            voltage_rising = not voltage_rising
        self.rising.setChecked(voltage_rising)
        self.falling.setChecked(not voltage_rising)
        self.window.setValue(config.max_event_samples * 1000 / fs)
        self.post.setValue(config.post_samples * 1000 / fs)
        self.pre.setValue(round(100 * config.pre_samples / config.max_event_samples))
        self.pre_label.setText(f"Предыстория · {self.pre.value()} %")
        self._loading = False
        self.dirty = False

    @property
    def input_profile(self):
        return getattr(self.dialog, "active_input_profile", UNKNOWN_PROFILE)

    def _presentation(self, bits, hysteresis):
        """Unit switches affect editors only, never raw codes or coefficients."""
        profile = self.input_profile
        high, step = (4092, 4) if bits == 10 else (4095, 1)
        self._unit = getattr(self.dialog, "voltage_unit", "В") if profile.configured else "код"
        self._factor = 1000 if self._unit == "мВ" else 1
        with QtCore.QSignalBlocker(self.hysteresis):
            if profile.configured:
                low_v, high_v = sorted((profile.voltage(0), profile.voltage(high)))
                self.threshold.step = abs(profile.a) * step
                self.threshold.set_bounds(low_v, high_v)
                self.hysteresis.setDecimals(6)
                self.hysteresis.setRange(0, (high_v - low_v) * self._factor)
                self.hysteresis.setSingleStep(abs(profile.a) * step * self._factor)
                self.threshold.setToolTip(
                    "Порог напряжения на CH1 по выбранной шкале. После округления показывается "
                    "принятый код. Границы шкалы АЦП не являются допустимым напряжением входа.")
                self.edge_label.setText("Направление напряжения CH1")
                self.rising.setToolTip("Нарастание напряжения CH1")
                self.falling.setToolTip("Спад напряжения CH1")
            else:
                self.threshold.step = step
                self.threshold.set_bounds(0, high)
                self.hysteresis.setDecimals(0)
                self.hysteresis.setRange(1, high)
                self.hysteresis.setSingleStep(step)
                self.threshold.setToolTip("Порог по исходным кодам ADC12. Шкала CH1 не настроена.")
                self.edge_label.setText("Направление кода")
                self.rising.setToolTip("Нарастание кода")
                self.falling.setToolTip("Спад кода")
            self.threshold.set_display(self._factor, self._unit)
            self.hysteresis.setSuffix(" " + self._unit)
            self.hysteresis.setValue(hysteresis * self._factor)

    def _edited(self, *_):
        if self._loading:
            return
        self.dirty = True
        self.pre_label.setText(f"Предыстория · {self.pre.value()} %")
        self.refresh()

    def candidate(self):
        fs, bits = self.dialog.search_basis()
        threshold, hysteresis, falling = (self.threshold.value,
                                         self.hysteresis.value() / self._factor,
                                         self.falling.isChecked())
        if self.input_profile.configured:
            quantized = quantize_thresholds(self.input_profile, threshold, hysteresis,
                                           "below" if falling else "above", bits)
            threshold = quantized.trigger_code
            hysteresis = abs(quantized.trigger_code - quantized.release_code)
            falling = quantized.code_polarity == "below"
        return make_config(fs=fs, retained_bits=bits, threshold=threshold,
                           hysteresis=hysteresis, falling=falling,
                           holdoff_ms=self.holdoff.value * 1000, window_ms=self.window.value(),
                           pre_percent=self.pre.value(), post_ms=self.post.value())

    def refresh(self):
        dlg = self.dialog
        # Only a source/rate/committed setting change replaces drafts. Periodic
        # status signals must not undo an edit while the user types.
        key = (id(dlg.archive), dlg._opening, dlg.search_basis(), dlg.search_config(), self.input_profile)
        if key != self._key:
            self._key = key
            self.load(dlg.search_config())
        elif self.input_profile.configured and self._unit != getattr(dlg, "voltage_unit", "В"):
            self._loading = True
            self._presentation(dlg.search_basis()[1], self.hysteresis.value() / self._factor)
            self._loading = False
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
        if not error and self.input_profile.configured:
            profile = self.input_profile
            fmt = lambda value: f"{value * self._factor:.6g} {self._unit}".replace(".", ",")
            threshold_v, release_v = profile.voltage(config.threshold_code), profile.voltage(config.release_code)
            accepted_label = "После округления" if self.dirty else "Применено"
            summary = (f"{accepted_label}: порог {fmt(threshold_v)} / возврат {fmt(release_v)}; "
                       f"гистерезис {fmt(abs(threshold_v - release_v))}.\n"
                       f"Коды: {config.threshold_code} / {config.release_code}.")
            if self.dirty:
                summary = (f"Запрошено: {fmt(self.threshold.value)}, "
                           f"гистерезис {fmt(self.hysteresis.value() / self._factor)}.\n" + summary)
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
