"""DC/AC calibration using files or new excerpts of an existing live stream."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import math

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .analog_profile import RawFormat
from .calibration import (CalibrationPlan, SampleWindow, fit_dc, fit_ac,
                          validate_control, save_calibration, load_calibration)
from .calibration_io import import_window
from .calibration_capture_ui import CalibrationCapturePanel
from .widgets import STYLE


def label(text):
    item = QtWidgets.QLabel(text)
    item.setWordWrap(True)
    item.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    return item


def number(value=0, minimum=-10000, maximum=10000, decimals=6):
    item = QtWidgets.QDoubleSpinBox()
    item.setRange(minimum, maximum)
    item.setDecimals(decimals)
    item.setValue(value)
    item.setKeyboardTracking(False)
    return item


def page_layout(page):
    """Keep controls reachable on 1366×768 and enlarged Windows fonts."""
    outer = QtWidgets.QVBoxLayout(page)
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    body = QtWidgets.QWidget()
    body.setObjectName("calibrationPageBody")
    body.setStyleSheet("QWidget#calibrationPageBody { background:#091720; }")
    layout = QtWidgets.QVBoxLayout(body)
    scroll.setWidget(body); outer.addWidget(scroll)
    return layout


def rate_format(rate):
    packed = rate == 150000
    return RawFormat(rate, 5 if packed else rate // 50000, 12, 10 if packed else 12,
        2 if packed else 0, "u10packed_le" if packed else "u16le",
        "left_shift_2" if packed else "identity", "truncate_lsb" if packed else "none",
        "u16le", "adc12", canonical_max=4092 if packed else 4095,
        canonical_step=4 if packed else 1)


def artificial_window(plan, role, reference):
    """DC a=.02,b=-40; AC |a|=.005 with separate zero. Not measurements."""
    if plan.origin != "synthetic":
        raise ValueError("Искусственные данные разрешены только для учебного опыта")
    count = 12000
    step = plan.raw_format.canonical_step
    indexes = np.arange(count)
    if plan.mode_id == "DC_WIDE":
        samples = (reference + 40) / .02 + .35 * np.sin(indexes * .7)
    elif role == "zero":
        samples = np.full(count, 2000.)
    else:
        peak = reference / {"Vpp": 2., "Vpk": 1., "Vrms": 1 / math.sqrt(2)}[plan.amplitude_kind]
        # Offset of sine deliberately differs from zero record: b must keep C0.
        samples = 2015 + peak / .005 * np.sin(2 * np.pi * plan.frequency_hz * indexes / plan.raw_format.sample_rate_hz)
    codes = tuple(int(x) for x in (np.rint(samples / step) * step))
    source = hashlib.sha256((plan.created_at_utc + role + str(reference)).encode()).hexdigest()
    return SampleWindow(codes, source, plan.raw_format, plan.mode_id,
                        plan.hardware_instance_id, origin="synthetic")


class ImportWindowDialog(QtWidgets.QDialog):
    """One bounded file worker; close waits for it instead of orphaning work."""
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan, self.window = plan, None
        self.future = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.setWindowTitle("Устойчивый участок исходной записи")
        self.resize(740, 530)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(label("Выберите короткую .mtstream-запись со штатным Stop и соседним .v2.json. "
            "В ней должны быть указаны этот экземпляр, режим и частота. Время ниже — от начала записи."))
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit()
        self.pick_button = QtWidgets.QPushButton("Выбрать…")
        self.pick_button.clicked.connect(self.pick)
        row.addWidget(self.path); row.addWidget(self.pick_button); layout.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.offset = number(0, 0, 1000000, 3)
        self.count = QtWidgets.QSpinBox(); self.count.setRange(128, 16384); self.count.setValue(12000)
        form.addRow("Начало участка, мс", self.offset)
        form.addRow("Число отсчётов", self.count)
        layout.addLayout(form)
        self.read = QtWidgets.QPushButton("Показать исходный участок")
        self.read.clicked.connect(self.load); layout.addWidget(self.read)
        self.plot = pg.PlotWidget(background="#0b202a")
        self.plot.setLabel("left", "Код АЦП"); self.plot.setLabel("bottom", "Время участка", "s")
        layout.addWidget(self.plot, 1)
        self.notice = label(""); layout.addWidget(self.notice)
        self.settled = QtWidgets.QCheckBox("Участок установился, переходных процессов и ограничения не видно")
        layout.addWidget(self.settled)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok); self.ok.setText("Использовать участок")
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.ok.setEnabled(False); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(30); self.timer.timeout.connect(self.poll)
        for signal in (self.path.textChanged, self.offset.valueChanged, self.count.valueChanged):
            signal.connect(self.invalidate)
        self.settled.toggled.connect(lambda: self.ok.setEnabled(self.window is not None and self.settled.isChecked()))

    def invalidate(self, *_):
        self.window = None; self.ok.setEnabled(False); self.settled.setChecked(False)

    def pick(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Исходная запись", "", "Мотортестер (*.mtstream)")
        if path: self.path.setText(path)

    def load(self):
        if self.future is not None: return
        self.invalidate()
        offset = round(self.offset.value() * self.plan.raw_format.sample_rate_hz / 1000)
        self.future = self.pool.submit(import_window, self.path.text(), self.plan, offset, self.count.value())
        for widget in (self.read, self.path, self.offset, self.count, self.pick_button, self.settled): widget.setEnabled(False)
        self.notice.setText("Чтение и проверка исходной записи…"); self.timer.start()

    def poll(self):
        if self.future is None or not self.future.done(): return
        future, self.future = self.future, None; self.timer.stop()
        for widget in (self.read, self.path, self.offset, self.count, self.pick_button, self.settled): widget.setEnabled(True)
        self.settled.setChecked(False)
        try:
            self.window = future.result()
            self.plot.clear()
            self.plot.plot(np.arange(len(self.window.codes)) / self.plan.raw_format.sample_rate_hz,
                           self.window.codes, pen="#ffe523")
            self.notice.setText(f"{len(self.window.codes)} исходных отсчётов. Проверьте участок и подтвердите установление.")
        except (ValueError, OSError) as exc:
            self.notice.setText(str(exc))

    def accept(self):
        if self.window is not None and self.settled.isChecked():
            self.pool.shutdown(wait=False); super().accept()

    def reject(self):
        if self.future is not None:
            self.notice.setText("Дождитесь окончания чтения файла."); return
        self.pool.shutdown(wait=False); super().reject()


class PlanPage(QtWidgets.QWizardPage):
    def __init__(self):
        super().__init__(); self.setTitle("1. Режим и условия опыта")
        layout = page_layout(self)
        layout.addWidget(label("Для STM32 сначала запустите «Живой поток» в главном окне. Мастер не открывает COM и не запускает АЦП. "
            "DC: два уровня и независимый третий. AC: отдельный ноль, синусоида и другая амплитуда. "
            "Пределы ниже — условия проверки, а не допустимое напряжение входа."))
        form = QtWidgets.QFormLayout()
        self.mode = QtWidgets.QComboBox()
        for mode in ("DC_WIDE", "AC_WIDE", "AC_SENSITIVE"): self.mode.addItem(mode.replace("_", " + "), mode)
        self.origin = QtWidgets.QComboBox(); self.origin.addItem("Учебный опыт · искусственные данные", "synthetic"); self.origin.addItem("Мои сохранённые записи STM32", "device")
        self.origin.addItem("Живой поток STM32", "live")
        self.origin.addItem("Учебный поток · без платы", "synthetic_live")
        self.rate = QtWidgets.QComboBox()
        for rate, bits in ((50000, 12), (100000, 12), (150000, 10)): self.rate.addItem(f"{rate} отсчётов/с · {bits} сохранённых бит", rate)
        self.hardware = QtWidgets.QLineEdit(); self.hardware.setMaxLength(80); self.hardware.setPlaceholderText("То же имя, что в настройке аналогового входа")
        self.instrument = QtWidgets.QLineEdit(); self.instrument.setMaxLength(256)
        self.conditions = QtWidgets.QLineEdit(); self.conditions.setMaxLength(256); self.conditions.setPlaceholderText("Питание, ОУ, температура, схема земли, прибор и его диапазон")
        self.uncertainty = number(0, 0, 10000); self.tolerance = number(0, 0, 10000)
        self.frequency = number(1000, .1, 50000, 3)
        self.kind = QtWidgets.QComboBox(); self.kind.addItems(["Vpp", "Vpk", "Vrms"])
        self.sign = QtWidgets.QComboBox(); self.sign.addItem("Положительный", 1); self.sign.addItem("Отрицательный", -1)
        self.sign_basis = QtWidgets.QLineEdit(); self.sign_basis.setMaxLength(256)
        for title, widget in (("Источник данных", self.origin), ("Физический режим", self.mode),
            ("Частота АЦП", self.rate), ("Экземпляр платы", self.hardware), ("Контрольный прибор", self.instrument),
            ("Условия", self.conditions), ("Погрешность каждого опорного измерения, В", self.uncertainty),
            ("Допустимая ошибка с учётом погрешностей, В", self.tolerance),
            ("Частота синусоиды AC, Гц", self.frequency), ("Амплитуда AC", self.kind),
            ("Знак передачи AC", self.sign), ("Как проверен знак AC", self.sign_basis)):
            form.addRow(title, widget)
        layout.addLayout(form)
        layout.addWidget(label("Vpp — размах, Vpk — пиковая амплитуда, Vrms — действующее значение синусоиды. "
            "Для AC погрешность и предел задаются в том же виде амплитуды. Модель учитывает опорные точки и разброс кодов. "
            "По умолчанию нет универсального допуска. Изменение условий после расчёта требует нового опыта."))
        self.error = label(""); self.error.setStyleSheet("color:#ffcb66"); layout.addWidget(self.error)
        load = QtWidgets.QPushButton("Открыть сохранённый подбор или результат…")
        load.clicked.connect(self.open_saved); layout.addWidget(load)
        self.origin.currentIndexChanged.connect(self.origin_changed)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.origin_changed(); self.mode_changed()

    def open_saved(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Сохранённая калибровка", "", "Калибровка (*.mtcal.json *.json)")
        if not path: return
        try:
            record = load_calibration(path)
            CalibrationWizard(self, resume_record=record, live_current=self.wizard().live_current).exec()
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))

    def origin_changed(self):
        synthetic = self.origin.currentData() in ("synthetic", "synthetic_live")
        self.hardware.setText("Учебный пример" if synthetic else "")
        self.instrument.setText("Искусственный источник" if synthetic else "")
        self.conditions.setText("Проверка программы; физических измерений нет" if synthetic else "")
        self.uncertainty.setValue(.002 if synthetic else 0)
        self.tolerance.setValue(.08 if synthetic else 0)
        self.sign_basis.setText("Знак задан моделью" if synthetic else "")
        if self.origin.currentData() == "live" and self.wizard() is not None:
            try:
                context = self.wizard().live_provider.context()
                if context.origin != "device":
                    raise ValueError("Текущий источник искусственный. Выберите «Учебный поток · без платы».")
                self.mode.setCurrentIndex(self.mode.findData(context.mode_id))
                self.rate.setCurrentIndex(self.rate.findData(context.raw_format.sample_rate_hz))
                self.hardware.setText(context.hardware_instance_id)
                self.error.clear()
            except (ValueError, RuntimeError) as exc:
                self.error.setText(str(exc))

    def mode_changed(self):
        ac = self.mode.currentData() != "DC_WIDE"
        for widget in (self.frequency, self.kind, self.sign, self.sign_basis): widget.setEnabled(ac)

    def validatePage(self):
        try:
            ac = self.mode.currentData() != "DC_WIDE"
            method = self.origin.currentData()
            fmt = rate_format(self.rate.currentData())
            if method == "live":
                current = self.wizard().live_provider.context()
                if (current.origin != "device" or current.mode_id != self.mode.currentData() or
                        current.hardware_instance_id != self.hardware.text().strip() or
                        current.raw_format.sample_rate_hz != self.rate.currentData()):
                    raise ValueError("Параметры должны совпадать с текущим потоком STM32. Проверьте режим, имя платы и частоту.")
                fmt = current.raw_format
            plan = CalibrationPlan(self.mode.currentData(), fmt,
                self.hardware.text().strip(), "synthetic" if method in ("synthetic", "synthetic_live") else "device", self.instrument.text().strip(),
                self.conditions.text().strip(), self.uncertainty.value(), self.tolerance.value(),
                frequency_hz=self.frequency.value() if ac else None,
                amplitude_kind=self.kind.currentText(), polarity=self.sign.currentData(),
                polarity_basis=self.sign_basis.text().strip())
            if not self.wizard().allow_discard(): return False
            self.wizard().cancel_capture()
            self.wizard().method = method
            self.wizard().plan = plan; self.wizard().draft = self.wizard().record = None
            self.error.clear(); return True
        except ValueError as exc:
            self.error.setText(str(exc)); return False


class WindowRow(QtWidgets.QGroupBox):
    def __init__(self, title, role, page):
        super().__init__(title); self.role, self.page, self.window = role, page, None
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout(); row.addWidget(label("Измерено на CH1, В:"))
        self.reference = number(1); row.addWidget(self.reference)
        self.button = QtWidgets.QPushButton("Выбрать отсчёты…"); self.button.clicked.connect(self.acquire); row.addWidget(self.button)
        layout.addLayout(row); self.status = label("Отсчёты ещё не выбраны"); layout.addWidget(self.status)
        self.measured = QtWidgets.QCheckBox("Значение выше измерено на CH1; для нуля CH1 соединён с AGND")
        layout.addWidget(self.measured)
        self.reference.valueChanged.connect(self.invalidate)
        self.measured.toggled.connect(self.measurement_confirmed)

    def measurement_confirmed(self, checked):
        if not checked:
            self.invalidate()

    def invalidate(self, *_):
        capture = getattr(self.page, "capture", None)
        if capture is not None and capture.row is self:
            capture.cancel()
        self.window = None; self.status.setText("Отсчёты ещё не выбраны")
        self.measured.setChecked(False)

    def reset(self, value, zero=False):
        synthetic = self.page.wizard().plan.origin == "synthetic"
        self.reference.setValue(value if synthetic else 0); self.reference.setEnabled(not zero)
        self.invalidate()
        self.measured.setVisible(not synthetic)
        self.button.setText("Создать учебные отсчёты" if synthetic else "Выбрать участок записи…")
        if self.page.wizard().method in ("live", "synthetic_live"):
            self.button.setText("Получить учебный участок" if synthetic else "Получить участок из потока")

    def acquire(self):
        plan = self.page.wizard().plan
        try:
            if self.page.wizard().method in ("live", "synthetic_live"):
                if plan.origin != "synthetic" and not self.measured.isChecked():
                    raise ValueError("Сначала введите и подтвердите измеренное значение CH1")
                self.invalidate()
                self.measured.setChecked(True)
                self.page.capture.begin(self)
            elif plan.origin == "synthetic":
                self.set_window(artificial_window(plan, self.role, self.reference.value()))
            else:
                if not self.measured.isChecked(): raise ValueError("Сначала введите и подтвердите измеренное значение CH1")
                dialog = ImportWindowDialog(plan, self)
                if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted: self.set_window(dialog.window)
        except ValueError as exc:
            self.status.setText(str(exc))

    def set_window(self, window):
        self.window = window
        values = np.asarray(window.codes)
        self.status.setText(f"{len(values)} отсчётов · среднее {values.mean():.3f} · σ {values.std():.3f} код. "
            + ("Искусственный пример" if window.origin == "synthetic" else "Исходная запись STM32"))


class FitPage(QtWidgets.QWizardPage):
    def __init__(self):
        super().__init__(); self.setTitle("2. Две исходные точки")
        layout = page_layout(self); self.explanation = label(""); layout.addWidget(self.explanation)
        self.first = WindowRow("Точка 1", "first", self); self.second = WindowRow("Точка 2", "second", self)
        layout.addWidget(self.first); layout.addWidget(self.second)
        self.capture = CalibrationCapturePanel(self); layout.addWidget(self.capture)
        self.error = label(""); self.error.setStyleSheet("color:#ffcb66"); layout.addWidget(self.error)
        layout.addStretch()

    def initializePage(self):
        self.capture.cancel(); self.capture.hide()
        ac = self.wizard().plan.mode_id != "DC_WIDE"
        self.first.role = "zero" if ac else "first"
        self.first.setTitle("Ноль · CH1 соединён с AGND" if ac else "Первый постоянный уровень")
        self.second.setTitle("Известная синусоида" if ac else "Второй постоянный уровень")
        self.first.reset(0 if ac else 1, ac); self.second.reset(4 if ac else 5)
        self.explanation.setText("AC: сначала отдельная запись установившегося нуля. Затем синусоида известной частоты и амплитуды. "
            "Среднее синусоиды не заменяет нулевой опыт." if ac else
            "DC WIDE: выберите устойчивые участки двух разных измеренных напряжений. "
            "Контрольный третий уровень далее должен лежать между ними. Числа учебного опыта не являются указанием подать их на вашу плату.")
        self.error.clear()

    def validatePage(self):
        try:
            if self.capture.pending or self.capture.window is not None:
                raise ValueError("Сначала примите или отмените показанный участок")
            if self.first.window is None or self.second.window is None: raise ValueError("Выберите оба исходных участка")
            w = self.wizard()
            if w.plan.origin == "device" and not (self.first.measured.isChecked() and self.second.measured.isChecked()):
                raise ValueError("Подтвердите измеренные значения обоих уровней")
            draft = (fit_dc(w.plan, self.first.window, self.first.reference.value(), self.second.window, self.second.reference.value())
                       if w.plan.mode_id == "DC_WIDE" else fit_ac(w.plan, self.first.window, self.second.window, self.second.reference.value()))
            if not w.allow_discard(): return False
            w.draft, w.record = draft, None
            self.error.clear(); return True
        except ValueError as exc:
            self.error.setText(str(exc)); return False


class ControlPage(QtWidgets.QWizardPage):
    def __init__(self):
        super().__init__(); self.setTitle("3. Независимая проверка")
        layout = page_layout(self); self.summary = label(""); layout.addWidget(self.summary)
        layout.addWidget(label("Это новый опыт: не используйте те же отсчёты. DC — другое напряжение между исходными; "
            "AC — другая амплитуда на той же частоте. По контрольной точке коэффициенты не подгоняются."))
        self.control = WindowRow("Контрольный уровень", "control", self); layout.addWidget(self.control)
        self.capture = CalibrationCapturePanel(self); layout.addWidget(self.capture)
        self.save = QtWidgets.QPushButton("Сохранить подбор без проверки…"); self.save.clicked.connect(lambda: self.wizard().save_record(self.wizard().draft))
        layout.addWidget(self.save)
        report = QtWidgets.QPushButton("Сохранить отчёт PDF…")
        report.clicked.connect(lambda: self.wizard().save_report(self.wizard().draft)); layout.addWidget(report)
        self.error = label(""); self.error.setStyleSheet("color:#ffcb66"); layout.addWidget(self.error); layout.addStretch()

    def initializePage(self):
        self.capture.cancel(); self.capture.hide()
        w = self.wizard(); self.control.reset(3 if w.plan.mode_id == "DC_WIDE" else 2)
        self.summary.setText(f"Подбор: U_CH1 = {w.draft.a:.9g} × код + ({w.draft.b:.9g}) В. Это ещё не калибровка.")
        self.error.clear()

    def validatePage(self):
        try:
            if self.capture.pending or self.capture.window is not None:
                raise ValueError("Сначала примите или отмените показанный участок")
            if self.control.window is None: raise ValueError("Выберите независимый контрольный участок")
            wizard = self.wizard()
            if wizard.plan.origin == "device" and not self.control.measured.isChecked():
                raise ValueError("Подтвердите измеренное значение контрольного уровня")
            record = validate_control(wizard.draft, self.control.window, self.control.reference.value())
            if wizard.record is not None and not wizard.allow_discard(): return False
            wizard.record = record
            self.error.clear(); return True
        except ValueError as exc:
            self.error.setText(str(exc)); return False


def record_summary(record):
    status = ("Контроль НЕ пройден — нельзя применять к прибору" if record.state == "control_failed" else
              "Учебный результат — нельзя применять к прибору" if record.plan.origin == "synthetic" else
              "Контроль пройден по введённым данным" if record.can_apply else "Калибровка не принята")
    error = "не выполнена" if record.control_error_v is None else f"{record.control_error_v:.6g} В"
    bound = "—" if record.control_bound_v is None else f"{record.control_bound_v:.6g} В"
    return (f"{status}\n\n{record.plan.mode_id} · {record.plan.raw_format.sample_rate_hz} отсчётов/с · {record.plan.hardware_instance_id}\n"
        f"U_CH1 = {record.a:.10g} × код + ({record.b:.10g}) В\n"
        f"Ошибка независимой проверки: {error}\nОшибка с учётом погрешностей: {bound}\n"
        f"Заранее выбранный предел: {record.plan.tolerance_v:g} В\n\n"
        + (f"AC: {record.plan.frequency_hz:g} Гц, амплитуда {record.plan.amplitude_kind}. "
           "Постоянная составляющая не измеряется. Проверка относится только к этой частоте и уровням.\n" if record.plan.mode_id != "DC_WIDE" else
           "Проверены три точки, а не весь диапазон или полоса.\n")
        + "Сохраните файл калибровки вместе с исходными записями. Он содержит использованные коды и условия. "
        "Применение к следующему потоку — через «Настройка входа» → «Загрузить калибровку…» после проверки режима и экземпляра. "
        "Защита входа и готовность к автомобилю этим опытом не подтверждаются.")


class ResultPage(QtWidgets.QWizardPage):
    def __init__(self):
        super().__init__(); self.setTitle("4. Результат и сохранение")
        layout = QtWidgets.QVBoxLayout(self); self.summary = QtWidgets.QTextBrowser(); layout.addWidget(self.summary)
        button = QtWidgets.QPushButton("Сохранить результат и исходные отсчёты…")
        button.clicked.connect(lambda: self.wizard().save_record(self.wizard().record)); layout.addWidget(button)
        self.report_button = QtWidgets.QPushButton("Сохранить отчёт PDF…")
        self.report_button.clicked.connect(lambda: self.wizard().save_report(self.wizard().record)); layout.addWidget(self.report_button)

    def initializePage(self):
        self.summary.setPlainText(record_summary(self.wizard().record))


class CalibrationWizard(QtWidgets.QWizard):
    def __init__(self, parent=None, *, resume_record=None, live_current=None):
        super().__init__(parent)
        from .calibration_live import LiveCalibrationProvider
        from .calibration_simulation import SyntheticCalibrationStream
        self.live_current = live_current or (lambda: None)
        self.live_provider = LiveCalibrationProvider(self.live_current)
        self.simulation = SyntheticCalibrationStream(self)
        self.teaching_provider = LiveCalibrationProvider(self.simulation.current)
        self.method = "synthetic"
        self.plan = self.draft = self.record = None
        self.setWindowTitle("Калибровка аналогового входа CH1")
        self.setStyleSheet(STYLE + "\nQWizard, QWizardPage { background:#091720; } QGroupBox { color:#e6f1f5; }")
        self.setWizardStyle(QtWidgets.QWizard.WizardStyle.ModernStyle)
        self.resize(900, 700)
        self.setButtonText(QtWidgets.QWizard.WizardButton.NextButton, "Далее →")
        self.setButtonText(QtWidgets.QWizard.WizardButton.BackButton, "← Назад")
        self.setButtonText(QtWidgets.QWizard.WizardButton.CancelButton, "Закрыть")
        self.setButtonText(QtWidgets.QWizard.WizardButton.FinishButton, "Готово")
        self.plan_page = PlanPage(); self.fit_page = FitPage(); self.control_page = ControlPage(); self.result_page = ResultPage()
        for page in (self.plan_page, self.fit_page, self.control_page, self.result_page): self.addPage(page)
        self.saved_path = None
        self.saved_record = resume_record
        self.currentIdChanged.connect(self.cancel_capture)
        if resume_record is not None:
            self.plan = resume_record.plan
            if len(resume_record.windows) == 2:
                self.draft = resume_record
                self.setStartId(2)
            else:
                self.record = resume_record
                self.setStartId(3)

    def capture_provider(self, row):
        if self.method == "synthetic_live":
            self.simulation.prepare(self.plan, row.role, row.reference.value())
            return self.teaching_provider
        return self.live_provider

    def cancel_capture(self, *_):
        for page in (getattr(self, "fit_page", None), getattr(self, "control_page", None)):
            if page is not None:
                page.capture.cancel()
        self.simulation.close()

    def save_report(self, record):
        if record is None:
            return False
        from .calibration_report import export_calibration_report
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Новое имя отчёта", "", "Отчёт калибровки (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            export_calibration_report(path, record)
            QtWidgets.QMessageBox.information(self, "Отчёт сохранён", "PDF сохранён. Для применения и исходных отсчётов сохраните также .mtcal.json.\n" + path)
            return True
        except (ValueError, OSError, RuntimeError) as exc:
            QtWidgets.QMessageBox.warning(self, "Не удалось сохранить отчёт", str(exc))
            return False

    def save_record(self, record):
        if record is None: return False
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Новое имя файла калибровки", "", "Калибровка CH1 (*.mtcal.json)")
        if not path: return False
        if not path.lower().endswith(".json"): path += ".mtcal.json"
        try:
            save_calibration(path, record); self.saved_path = path
            self.saved_record = record
            QtWidgets.QMessageBox.information(self, "Сохранено", "Результат и исходные отсчёты сохранены.\n" + path)
            return True
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.warning(self, "Не удалось сохранить", str(exc))
            return False

    def allow_discard(self):
        record = self.record or self.draft
        if record is not None and record is not self.saved_record:
            choice = QtWidgets.QMessageBox.question(self, "Сохранить опыт?",
                "Коэффициенты и использованные исходные отсчёты ещё не сохранены.",
                QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard |
                QtWidgets.QMessageBox.StandardButton.Cancel, QtWidgets.QMessageBox.StandardButton.Save)
            if choice == QtWidgets.QMessageBox.StandardButton.Cancel: return False
            if choice == QtWidgets.QMessageBox.StandardButton.Save and not self.save_record(record): return False
        return True

    def done(self, result):
        if not self.allow_discard(): return
        self.cancel_capture()
        self.live_provider.close(); self.teaching_provider.close()
        super().done(result)


def open_calibration_wizard(parent=None, *, live_current=None):
    return CalibrationWizard(parent, live_current=live_current).exec()
