"""Embedded preview/confirmation for a newly requested calibration excerpt."""
from dataclasses import replace

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .calibration import validate_sample_window


class CalibrationCapturePanel(QtWidgets.QWidget):
    def __init__(self, page):
        super().__init__(page)
        self.page, self.row, self.provider, self.window = page, None, None, None
        self.pending = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        line = QtWidgets.QHBoxLayout()
        line.addWidget(QtWidgets.QLabel("Число отсчётов"))
        self.count = QtWidgets.QSpinBox(); self.count.setRange(128, 16384); self.count.setValue(12000)
        line.addWidget(self.count); line.addStretch()
        self.cancel_button = QtWidgets.QPushButton("Отменить получение")
        self.cancel_button.clicked.connect(self.cancel)
        line.addWidget(self.cancel_button); layout.addLayout(line)
        self.plot = pg.PlotWidget(background="#0b202a")
        self.plot.setLabel("left", "Исходный код АЦП")
        self.plot.setLabel("bottom", "Время участка", "s")
        self.plot.setFixedHeight(145)
        layout.addWidget(self.plot)
        self.notice = QtWidgets.QLabel(); self.notice.setWordWrap(True)
        self.notice.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.notice)
        self.settled = QtWidgets.QCheckBox("Участок установился, переходных процессов и ограничения не видно")
        self.settled.toggled.connect(self.update_enabled); layout.addWidget(self.settled)
        self.use_button = QtWidgets.QPushButton("Использовать участок")
        self.use_button.clicked.connect(self.accept); layout.addWidget(self.use_button)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(30); self.timer.timeout.connect(self.poll)
        self.count.valueChanged.connect(self.cancel)
        self.hide()

    def begin(self, row):
        self.cancel()
        self.row = row
        wizard = self.page.wizard()
        self.show(); self.plot.clear()
        self.settled.setChecked(False)
        try:
            self.provider = wizard.capture_provider(row)
            self.provider.begin(wizard.plan, self.count.value())
            self.pending = True
            self.notice.setText("Получение новых отсчётов после команды… Приём и запись в главном окне продолжаются.")
            self.timer.start()
        except (ValueError, RuntimeError) as exc:
            self.notice.setText(str(exc))
        self.update_enabled()

    def poll(self):
        if not self.pending:
            return
        try:
            window = self.provider.poll()
            if window is None:
                return
            self.timer.stop(); self.pending = False
            self.window = window
            self.plot.plot(np.arange(len(window.codes)) / window.raw_format.sample_rate_hz,
                           window.codes, pen="#ffe523")
            validate_sample_window(self.page.wizard().plan,
                                   replace(window, settled_confirmed=True),
                                   ac_signal=self.page.wizard().plan.mode_id != "DC_WIDE" and self.row.role != "zero")
            self.notice.setText(f"{self.row.title()}: {len(window.codes)} новых отсчётов · начало {window.first_sample_index}. "
                "Проверьте исходный участок и подтвердите установление. "
                + ("Учебный поток: физических измерений нет." if window.origin == "synthetic" else
                   "Полнота всего потока неизвестна; проверяется только этот принятый участок."))
        except (ValueError, RuntimeError) as exc:
            self.timer.stop(); self.pending = False; self.window = None
            if self.provider is not None:
                self.provider.cancel()
            self.notice.setText(str(exc))
        self.update_enabled()
        QtCore.QTimer.singleShot(0, self.reveal_confirmation)

    def reveal_confirmation(self):
        # On small screens the accepted-preview controls must be brought into
        # view automatically, not hidden below the two reference rows.
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QtWidgets.QScrollArea):
                parent.ensureWidgetVisible(self.use_button, 0, 8)
                break
            parent = parent.parentWidget()

    def update_enabled(self, *_):
        self.count.setEnabled(not self.pending)
        self.cancel_button.setEnabled(self.pending or self.window is not None)
        self.settled.setEnabled(self.window is not None)
        self.use_button.setEnabled(self.window is not None and self.settled.isChecked())
        if self.page.wizard() is not None:
            self.page.completeChanged.emit()

    def accept(self):
        if self.window is None or not self.settled.isChecked() or self.row is None:
            return
        self.row.set_window(replace(self.window, settled_confirmed=True))
        self.cancel()
        self.hide()

    def cancel(self, *_):
        self.timer.stop()
        if self.provider is not None:
            self.provider.cancel()
        self.pending = False; self.window = None; self.row = None
        self.settled.setChecked(False)
        self.notice.setText("Получение отменено. Для нового участка нажмите кнопку у нужной точки.")
        self.update_enabled()
