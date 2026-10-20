"""V2 desktop: independent view, capture and bounded DEMO recording states."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import replace
import math
from pathlib import Path
import sys
import uuid

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from .core import (CaptureSettings, DEMO_PROFILE, DemoSource, Recording,
                   V2Error, analyze, cursor_measurement, find_events,
                   load, save, export_csv)
from .data import MAX_SAMPLES
from .widgets import Knob, STYLE
from .device_ui import DeviceControlsMixin


def label(text="", name="", wrap=False):
    widget = QtWidgets.QLabel(text)
    widget.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def number(value, decimals=3):
    return f"{value:.{decimals}f}".replace(".", ",")


def time_text(seconds):
    return number(seconds * 1000, 2) + " мс" if abs(seconds) < 1 else number(seconds, 3) + " с"


class VoltageAxis(pg.AxisItem):
    factor = 1.0

    def tickStrings(self, values, scale, spacing):
        return [f"{v * self.factor:.4g}".replace(".", ",") for v in values]


class JobSignals(QtCore.QObject):
    finished = QtCore.Signal(object, object)


class FileJob(QtCore.QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = JobSignals()

    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            self.signals.finished.emit(None, str(exc))
        else:
            self.signals.finished.emit(result, None)


class Plot(pg.PlotWidget):
    def minimumSizeHint(self):
        return QtCore.QSize(100, 80)

    def sizeHint(self):
        return QtCore.QSize(800, 350)


class MainWindow(DeviceControlsMixin, QtWidgets.QMainWindow):
    """DEMO and explicit STM32 windows have separate acquisition state."""

    def __init__(self, *, settings_path=None, device_bridge_factory=None):
        super().__init__()
        if settings_path:
            self.settings = QtCore.QSettings(str(settings_path), QtCore.QSettings.Format.IniFormat)
        else:
            self.settings = QtCore.QSettings("MotortesterV2", "Desktop")
        self.channel_name = str(self.settings.value("channel_name", "Канал 1"))[:80].strip() or "Канал 1"
        self.ui_profile = "oscilloscope"
        self.source = DemoSource("sine")
        self.recent = deque(maxlen=20)  # one second, acquisition runs independently of view pause
        self.mode = 0
        self.paused = False
        self.follow = True
        self.display_recording = None
        self.completed = None
        self.single = None
        self.recording = False
        self.record_blocks = []
        self.record_count = 0
        self.record_metadata = None
        self.armed_after = None
        self.arm_blocks = []
        self.events = ()
        self.event_ordinal = -1
        self.single_dirty = False
        self.record_dirty = False
        self.live_settings = None
        self.busy = False
        self._job = None
        self._analysis_job = None
        self._analysis_pending = None
        self._analysis_key = 0
        self._rendering = False
        self._ticks = 0
        self.gap_items = []
        self.stream_dialog = None
        self._stream_close_pending = False
        self._serial_owner = None
        self._serial_port = None
        self._init_device(device_bridge_factory)
        self.setWindowTitle("Мотортестер V2")
        self.resize(1440, 920)
        self.setMinimumSize(1024, 700)
        self.setStyleSheet(STYLE)
        self._build_ui()
        for _ in range(20):
            self.recent.append(self.source.next_block(2500))
        self._show_live(reset=True)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._update_actions()

    def _button(self, text, slot, *, check=False, name=""):
        button = QtWidgets.QPushButton(text)
        button.setCheckable(check)
        button.setObjectName(name)
        button.clicked.connect(slot)
        return button

    def _build_ui(self):
        root = QtWidgets.QWidget(objectName="root")
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(8)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(label("∿  МОТОРТЕСТЕР", "brand"))
        header.addStretch()
        self.tabs = []
        for index, title in enumerate(("Живой сигнал", "Одиночный захват", "Запись")):
            button = self._button(title, lambda checked=False, i=index: self.set_mode(i), check=True, name="tab")
            self.tabs.append(button)
            header.addWidget(button)
        header.addStretch()
        self.origin_badge = label("ДЕМО", "badge")
        header.addWidget(self.origin_badge)
        self.open_button = self._button("Открыть", self.open_dialog)
        header.addWidget(self.open_button)
        self.png_button = self._button("Снимок", self.png_dialog)
        header.addWidget(self.png_button)
        layout.addLayout(header)
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(6)
        body.addLayout(left, 1)
        actions = QtWidgets.QGridLayout()
        self.action_layout = actions
        self.state_label = label("●  Живой сигнал", "state")
        actions.addWidget(self.state_label, 0, 0)
        self.pause_button = self._button("Ⅱ  Пауза просмотра", self.toggle_pause)
        self.record_button = self._button("●  Начать запись", self.toggle_record)
        self.single_button = self._button("◎  Одиночный захват", self.arm_single)
        self.cursor_button = self._button("Курсоры A–B", self.toggle_cursors, check=True)
        self.cursor_button.setChecked(True)
        self.action_buttons = (self.pause_button, self.record_button, self.single_button, self.cursor_button)
        for index, button in enumerate(self.action_buttons):
            actions.addWidget(button, 0, index + 1)
        left.addLayout(actions)
        self.plot_card = QtWidgets.QFrame(objectName="panel")
        card_layout = QtWidgets.QVBoxLayout(self.plot_card)
        card_layout.setContentsMargins(10, 8, 10, 6)
        card_layout.setSpacing(4)
        plot_header = QtWidgets.QHBoxLayout()
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(3)
        self.plot_title = label("", "heading")
        self.plot_subtitle = label("", "muted")
        titles.addWidget(self.plot_title)
        titles.addWidget(self.plot_subtitle)
        self.axis_units = label("X: мс · Y: В", "muted")
        self.axis_units.hide()
        titles.addWidget(self.axis_units)
        plot_header.addLayout(titles, 1)
        self.prev_button = self._button("‹ Предыдущая", lambda: self.select_event(-1))
        self.next_button = self._button("Следующая ›", lambda: self.select_event(1))
        plot_header.addWidget(self.prev_button)
        plot_header.addWidget(self.next_button)
        card_layout.addLayout(plot_header)
        self.voltage_axis = VoltageAxis(orientation="left")
        self.plot = Plot(axisItems={"left": self.voltage_axis}, background="#0a1b25")
        self.plot.setMinimumHeight(170)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=True, y=True, alpha=.18)
        self.plot.setLabel("bottom", "Время", units="мс", color="#abc8d8")
        self.plot.setLabel("left", "Напряжение на входе", units="В", color="#abc8d8")
        for axis in ("left", "bottom"):
            self.plot.getAxis(axis).enableAutoSIPrefix(False)
            self.plot.getAxis(axis).setTextPen("#bed4df")
            self.plot.getAxis(axis).setPen("#476373")
        self.plot.getAxis("bottom").setHeight(46)
        self.curve = self.plot.plot(pen=pg.mkPen("#ffe500", width=1.8), connect="finite", antialias=True)
        self.threshold_line = pg.InfiniteLine(angle=0, pen=pg.mkPen("#7da9c0", style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self.threshold_line)
        self.trigger_line = pg.InfiniteLine(angle=90, pen=pg.mkPen("#8faaba", style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self.trigger_line)
        self.trigger_line.hide()
        self.cursor_a = pg.InfiniteLine(pos=0, angle=90, movable=True,
            pen=pg.mkPen("#00e2e8", width=1.5, style=QtCore.Qt.PenStyle.DashLine),
            label="A", labelOpts={"position": .92, "color": "#00e2e8"})
        self.cursor_b = pg.InfiniteLine(pos=1, angle=90, movable=True,
            pen=pg.mkPen("#00e2e8", width=1.5, style=QtCore.Qt.PenStyle.DashLine),
            label="B", labelOpts={"position": .92, "color": "#00e2e8"})
        for cursor in (self.cursor_a, self.cursor_b):
            self.plot.addItem(cursor)
            cursor.sigPositionChanged.connect(self._update_cursors)
        self.unconfigured_text = pg.TextItem("Шкала напряжения не настроена", color="#f5cd77", anchor=(.5, .5))
        self.plot.addItem(self.unconfigured_text)
        self.unconfigured_text.hide()
        card_layout.addWidget(self.plot, 1)
        self.cursor_label = label("", "muted", wrap=True)
        card_layout.addWidget(self.cursor_label)
        left.addWidget(self.plot_card, 1)
        metrics = QtWidgets.QGridLayout()
        self.metrics_layout = metrics
        self.metric_cards = []
        self.metric_titles, self.metric_values = [], []
        for title in ("Размах", "Период / частота", "Мин. / макс.", "Между курсорами A–B"):
            card = QtWidgets.QFrame(objectName="card")
            card_box = QtWidgets.QVBoxLayout(card)
            card_box.setContentsMargins(8, 6, 8, 6)
            card_box.setSpacing(3)
            heading, value = label(title, "muted"), label("—", "metricValue")
            heading.setWordWrap(True)
            value.setWordWrap(True)
            card_box.addWidget(heading)
            card_box.addWidget(value)
            metrics.addWidget(card, 0, len(self.metric_cards))
            self.metric_cards.append(card)
            self.metric_titles.append(heading)
            self.metric_values.append(value)
        left.addLayout(metrics)
        overview_card = QtWidgets.QFrame(objectName="panel")
        overview_layout = QtWidgets.QVBoxLayout(overview_card)
        overview_layout.setContentsMargins(10, 6, 10, 4)
        self.overview_label = label("Недавний сигнал", "muted")
        overview_layout.addWidget(self.overview_label)
        self.overview = Plot(background="#0b2631")
        self.overview.setFixedHeight(100)
        self.overview.setMouseEnabled(x=False, y=False)
        self.overview.setMenuEnabled(False)
        self.overview.hideButtons()
        self.overview.hideAxis("left")
        self.overview.getAxis("bottom").enableAutoSIPrefix(False)
        self.overview.setLabel("bottom", "Время", units="мс")
        self.overview.getAxis("bottom").showLabel(False)
        self.overview.getAxis("bottom").setHeight(24)
        self.overview_curve = self.overview.plot(pen=pg.mkPen("#ffe500", width=1), connect="finite")
        self.region = pg.LinearRegionItem((0, 20), brush=(0, 211, 222, 35), pen="#00dce3")
        self.overview.addItem(self.region)
        self.region.sigRegionChangeFinished.connect(self._region_changed)
        overview_layout.addWidget(self.overview)
        left.addWidget(overview_card)
        file_actions = QtWidgets.QGridLayout()
        self.save_button = self._button("Сохранить запись", self.save_dialog)
        self.export_button = self._button("Экспорт участка CSV + JSON", self.export_dialog)
        self.follow_button = self._button("Следовать за сигналом", self.resume_follow)
        self.quality_label = label("", "muted", wrap=True)
        file_actions.addWidget(self.save_button, 0, 0)
        file_actions.addWidget(self.export_button, 0, 1)
        file_actions.addWidget(self.follow_button, 0, 2)
        file_actions.addWidget(self.quality_label, 1, 0, 1, 3)
        left.addLayout(file_actions)
        sidebar = QtWidgets.QFrame(objectName="panel")
        sidebar.setFixedWidth(342)
        side_outer = QtWidgets.QVBoxLayout(sidebar)
        side_outer.setContentsMargins(8, 8, 8, 8)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        side_outer.addWidget(scroll)
        content = QtWidgets.QWidget(objectName="sidecontent")
        scroll.setWidget(content)
        side = QtWidgets.QVBoxLayout(content)
        side.setContentsMargins(5, 4, 5, 4)
        side.setSpacing(9)
        side.addWidget(label("Управление", "heading"))
        channel_row = QtWidgets.QHBoxLayout()
        channel_row.addWidget(label("CH1"))
        self.name_label = label(self.channel_name)
        channel_row.addWidget(self.name_label, 1)
        self.rename_button = self._button("✎", self.rename_dialog)
        pencil = QtGui.QPixmap(20, 20)
        pencil.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pencil)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor("#b8e1f4"), 5, QtCore.Qt.PenStyle.SolidLine,
                                  QtCore.Qt.PenCapStyle.FlatCap))
        painter.drawLine(6, 14, 15, 5)
        painter.setPen(QtGui.QPen(QtGui.QColor("#b8e1f4"), 2))
        painter.drawLine(3, 17, 6, 14)
        painter.end()
        self.rename_button.setText("")
        self.rename_button.setIcon(QtGui.QIcon(pencil))
        self.rename_button.setFixedSize(34, 34)
        self.rename_button.setToolTip("Переименовать пользовательское имя CH1")
        channel_row.addWidget(self.rename_button)
        side.addLayout(channel_row)
        side.addWidget(label("Профиль", "muted"))
        profile_row = QtWidgets.QHBoxLayout()
        profile_row.setSpacing(0)
        self.scope_button = self._button("Осциллограф", lambda: self.change_profile("oscilloscope"), check=True)
        self.ignition_button = self._button("Зажигание", lambda: self.change_profile("ignition"), check=True)
        profile_row.addWidget(self.scope_button)
        profile_row.addWidget(self.ignition_button)
        side.addLayout(profile_row)
        source_row = QtWidgets.QHBoxLayout()
        self.waveform_combo = QtWidgets.QComboBox()
        self.waveform_combo.addItem("ДЕМО · синусоида", "sine")
        self.waveform_combo.addItem("ДЕМО · прямоугольный", "square")
        self.waveform_combo.addItem("ДЕМО · зажигание", "ignition")
        self.waveform_combo.addItem("STM32 · COM-порт", "device")
        self.waveform_combo.currentIndexChanged.connect(self.change_waveform)
        source_row.addWidget(self.waveform_combo, 1)
        self.file_source_label = label("Просмотр записи", "muted")
        self.file_source_label.hide()
        source_row.addWidget(self.file_source_label, 1)
        self.units_combo = QtWidgets.QComboBox()
        self.units_combo.addItems(["В", "мВ"])
        self.units_combo.currentIndexChanged.connect(self._units_changed)
        source_row.addWidget(self.units_combo)
        side.addLayout(source_row)
        self.scale_label = label("Номинальная шкала · ДЕМО", "muted", wrap=True)
        side.addWidget(self.scale_label)
        self.raw_view = QtWidgets.QCheckBox("Показать служебные коды АЦП")
        self.raw_view.setToolTip("Коды 0…4095. Это не напряжение на входном разъёме.")
        self.raw_view.toggled.connect(self._raw_view_changed)
        self.raw_view.hide()
        side.addWidget(self.raw_view)
        controls = QtWidgets.QGridLayout()
        controls.setHorizontalSpacing(4)
        controls.setVerticalSpacing(8)
        self.sweep = Knob("Развёртка", .00002, 4, .002, .001, "мс/дел", logarithmic=True)
        self.yscale = Knob("Масштаб Y", .001, 100, .5, .1, "В/дел", logarithmic=True)
        self.xposition = Knob("Положение X", 0, 3600, 0, .002, "мс")
        self.yposition = Knob("Положение Y", -100, 100, 1.65, .1, "В")
        self.threshold = Knob("Уровень запуска", 0, DEMO_PROFILE.voltage(4095), 1.65, .05, "В")
        self.holdoff = Knob("Пауза запуска", 0, .1, .001, .001, "мс")
        self.sweep.set_display(1000, "мс/дел")
        self.xposition.set_display(1000, "мс")
        self.holdoff.set_display(1000, "мс")
        for index, knob in enumerate((self.sweep, self.yscale, self.xposition, self.yposition, self.threshold, self.holdoff)):
            controls.addWidget(knob, index // 2, index % 2)
        for knob in (self.sweep, self.yscale, self.xposition, self.yposition):
            knob.changed.connect(lambda value, sender=knob: self._view_changed(sender))
        self.threshold.changed.connect(self._capture_settings_changed)
        self.holdoff.changed.connect(self._capture_settings_changed)
        self.yposition.setToolTip("Центр видимой оси Y. Значения отсчётов и калибровка не меняются.")
        self.sweep.setToolTip("Ширина экрана — 10 делений; частота выборки источника не меняется.")
        self.holdoff.setToolTip("Минимальный интервал программного поиска событий; это не команда аппаратуре.")
        side.addLayout(controls)
        edge_row = QtWidgets.QHBoxLayout()
        edge_row.addWidget(label("Запуск по CH1"), 1)
        self.rising = self._button("↗", lambda: self.set_edge("rising"), check=True)
        self.falling = self._button("↘", lambda: self.set_edge("falling"), check=True)
        self.rising.setChecked(True)
        edge_row.addWidget(self.rising)
        edge_row.addWidget(self.falling)
        side.addLayout(edge_row)
        self.capture_note = label("Программный поиск события · ДЕМО", "muted", wrap=True)
        side.addWidget(self.capture_note)
        pre_row = QtWidgets.QHBoxLayout()
        pre_row.addWidget(label("Предыстория"))
        pre_row.addStretch()
        self.pre_label = label("20 %", "muted")
        pre_row.addWidget(self.pre_label)
        side.addLayout(pre_row)
        self.pretrigger = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.pretrigger.setRange(0, 99)
        self.pretrigger.setValue(20)
        self.pretrigger.valueChanged.connect(lambda value: self.pre_label.setText(f"{value} %"))
        side.addWidget(self.pretrigger)
        fit_row = QtWidgets.QHBoxLayout()
        fit_row.addWidget(self._button("Автомасштаб", self.auto_scale))
        fit_row.addWidget(self._button("Весь сигнал", self.full_signal))
        side.addLayout(fit_row)
        self.device_button = self._button("STM32 · подключение", self.device_info)
        self.stream_button = self._button("Непрерывный приём · ДЕМО", self.open_stream_workspace)
        side.addWidget(self.stream_button)
        self.device_stream_button = self._button("Непрерывный приём · STM32",
                                                 self.open_device_stream_workspace)
        side.addWidget(self.device_stream_button)
        side.addWidget(self.device_button)
        self.gap_button = self._button("ДЕМО · пропуск 100 мс", self.inject_gap)
        self.gap_button.setToolTip("Явно пропустить синтетические отсчёты для проверки записи и отображения разрывов.")
        side.addWidget(self.gap_button)
        self.raw_button = self._button("Сведения о шкале / исходных кодах", self.raw_info)
        side.addWidget(self.raw_button)
        side.addStretch()
        body.addWidget(sidebar)
        self.provenance_label = label("1 канал · CH1", "muted")
        self.statusBar().addPermanentWidget(self.provenance_label)

    def capture_settings(self):
        return CaptureSettings(threshold_v=self.threshold.value,
            edge="rising" if self.rising.isChecked() else "falling",
            holdoff_s=self.holdoff.value, pretrigger_fraction=self.pretrigger.value() / 100,
            window_s=.005 if self.ui_profile == "ignition" else self.sweep.value * 10)

    @property
    def dirty(self):
        return self.single_dirty or self.record_dirty

    def _live_snapshot(self):
        return Recording(tuple(self.recent), channel_name=self.channel_name,
            ui_profile=self.ui_profile, input_profile=DEMO_PROFILE, source="demo",
            capture_settings=self.capture_settings())

    def _tick(self):
        if self.device_active:
            return
        self._ticks += 1
        block = self.source.next_block(2500)
        self.recent.append(block)
        if self.recording:
            self.record_blocks.append(block)
            self.record_count += len(block.samples)
            if self.record_count >= MAX_SAMPLES:
                self.stop_recording()
                self.statusBar().showMessage("Запись остановлена: достигнут предел 2 000 000 отсчётов (40 с ДЕМО).")
        if self.armed_after is not None:
            self.arm_blocks.append(block)
            if sum(len(b.samples) for b in self.arm_blocks) > MAX_SAMPLES:
                self.armed_after = None
                self.arm_blocks.clear()
                self.statusBar().showMessage("Ожидание завершено: событие не получено в пределах буфера 40 с.")
                self._update_actions()
                return
            if self._pending_trigger is None:
                candidate = replace(self._live_snapshot(), capture_settings=self._armed_settings)
                for event in find_events(candidate):
                    if event.trigger_index >= self.armed_after:
                        self._pending_trigger = event.trigger_index
                        break
            if self._pending_trigger is not None:
                count = max(2, round(self._armed_settings.window_s * 50000))
                start = self._pending_trigger - round(count * self._armed_settings.pretrigger_fraction)
                stop = start + count
                if block.end_index < stop:
                    return
                captured = Recording(tuple(self.arm_blocks), channel_name=self.channel_name,
                    ui_profile=self.ui_profile, capture_settings=self._armed_settings).slice(start, stop)
                flags = set(captured.quality_flags)
                if captured.gaps:
                    flags.add("missing_context")
                if any(captured.input_profile.clipping(b.samples) for b in captured.blocks):
                    flags.add("clipping")
                self.single = replace(captured, trigger_index=self._pending_trigger,
                    quality_flags=tuple(sorted(flags)))
                self.armed_after = None
                self.arm_blocks.clear()
                self.mode = 1
                self._display(self.single, reset=True)
                self.single_dirty = True
                self._update_actions()
        if self.mode == 0 or (self.mode == 2 and self.recording):
            if not self.paused:
                self._show_live()
        if self.recording:
            self.state_label.setText(f"●  Запись · {self.record_count / 50000:.1f} с")

    def _show_live(self, reset=False):
        if self.device_active:
            if self.device_last is not None:
                self._display(self.device_last, reset=reset, live=True)
            return
        snapshot = self._live_snapshot()
        history_s = max(.1 if self.ui_profile == "oscilloscope" else 1, self.sweep.value * 10)
        start = max(snapshot.start_index, snapshot.end_index - round(history_s * snapshot.sample_rate_hz))
        self._display(snapshot.slice(start, snapshot.end_index), reset=reset, live=True)

    def _display(self, recording, *, reset=False, live=False):
        self.display_recording = recording
        profile = recording.input_profile
        configured = profile.configured
        self._rendering = True
        try:
            self.raw_view.setVisible(not configured)
            raw_view = not configured and self.raw_view.isChecked()
            self._set_axis_mode(raw_view)
            self.units_combo.setEnabled(configured)
            times, values = [], []
            previous = None
            for block in recording.blocks:
                if previous is not None and (previous != block.start_index or block.gap_before):
                    times.append(np.array([np.nan]))
                    values.append(np.array([np.nan]))
                x = (np.arange(len(block.samples)) + block.start_index) / block.sample_rate_hz * 1000
                raw = np.asarray(block.samples, dtype=float)
                times.append(x)
                values.append(raw * profile.a + profile.b if configured else
                              raw if raw_view else np.full(len(raw), np.nan))
                previous = block.end_index
            x, y = np.concatenate(times), np.concatenate(values)
            self.curve.setData(x, y, connect="finite", autoDownsample=True, downsampleMethod="peak")
            self.overview_curve.setData(x, y, connect="finite", autoDownsample=True, downsampleMethod="peak")
            start, end = recording.start_index / recording.sample_rate_hz, recording.end_index / recording.sample_rate_hz
            self.xposition.set_bounds(start, max(end, start + .00002))
            if reset:
                if not live:
                    self.sweep.set_value(max(.00002, (end - start) / 10))
                self.xposition.set_value(max(start, end - self.sweep.value * 10) if live else start)
                self.follow = live
            elif live and self.follow:
                self.xposition.set_value(max(start, end - self.sweep.value * 10))
            self.overview.setXRange(start * 1000, end * 1000, padding=0)
            self.overview.enableAutoRange(axis="y")
            self.region.setBounds((start * 1000, end * 1000))
            self.unconfigured_text.setVisible(not configured and not raw_view)
            self.threshold_line.setVisible(configured and self.mode == 0)
            if recording.capture_settings.threshold_v is not None:
                self.threshold_line.setValue(recording.capture_settings.threshold_v)
            self.trigger_line.setVisible(recording.trigger_index is not None)
            if recording.trigger_index is not None:
                self.trigger_line.setValue(recording.trigger_index / recording.sample_rate_hz * 1000)
            self._apply_view(reset_cursors=reset or (live and self.follow))
            self._draw_gaps(recording)
            title = "Зажигание" if recording.ui_profile == "ignition" else "Осциллограф"
            mode_title = ("живой сигнал", "один разряд" if recording.ui_profile == "ignition" else "одиночный захват", "запись")[self.mode]
            if recording.source == "device":
                mode_title = "одно окно" if "window_local_time" in recording.quality_flags else "захват"
            self.plot_title.setText(f"{title} · {mode_title}")
            self.plot_subtitle.setText(f"CH1 · {recording.channel_name}  |  {recording.sample_rate_hz:g} отсч./с · "
                                      + ("синтетический сигнал" if recording.source == "demo" else "данные устройства"))
            self.name_label.setText(recording.channel_name)
            self.origin_badge.setText("ДЕМО" if recording.source == "demo" else
                "ПРИБОР · ОКНО" if self.device_active and self.mode != 2 else "ФАЙЛ · ПРИБОР")
            self.provenance_label.setText("CH1 · " + ("Запись · " if self.mode == 2 else "") +
                ("ДЕМО · синтетические данные" if recording.source == "demo" else
                 "Прибор · время номинальное"))
            self.scale_label.setText("Шкала напряжения не настроена" if not configured else
                ("Калиброванная шкала" if profile.state == "calibrated" else "Номинальная шкала")
                + (" · ДЕМО" if recording.source == "demo" else "") + f" · {profile.coupling}")
            self.overview_label.setText(("Недавний сигнал" if live else "Весь захват / сеанс")
                                       + f" · {time_text(end - start)}  ·  пропусков: {len(recording.gaps)}")
            if recording.source == "device" and "window_local_time" in recording.quality_flags:
                self.overview_label.setText(f"Одно окно · {time_text(end - start)} · промежутки между окнами неизвестны")
                self.plot_subtitle.setText(f"CH1 · {recording.channel_name} | окно {recording.legacy_sequence} · "
                                          f"{recording.sample_rate_hz:g} отсч./с, номинально")
                trigger = {"signal": "фронт кода АЦП", "auto_timeout": "Auto · без фронта"}.get(
                    recording.capture_settings.trigger_kind, "тип запуска не указан")
                self.plot_subtitle.setText(self.plot_subtitle.text() + " | " + trigger)
            # Analyze a bounded visible range, not the full session every refresh.
            left, right = self.plot.viewRange()[0]
            try:
                visible = self._visible_slice(recording, left, right)
            except V2Error:
                visible = None
            self._measurements(visible)
        finally:
            self._rendering = False
        self._update_cursors()

    @staticmethod
    def _visible_slice(recording, left_ms, right_ms):
        """Intersect a viewport with raw data, without inventing missing context.

        UI times are floating-point milliseconds: 1084 ms * 50 kHz can become
        54200.00000000001. Snap only floating noise at an integer boundary,
        then retain the usual half-open floor/ceil range and real recording limits.
        """
        def boundary(milliseconds, rounding):
            samples = milliseconds / 1000 * recording.sample_rate_hz
            nearest = round(samples)
            if abs(samples - nearest) <= max(1e-7, 2 * math.ulp(samples)):
                return nearest
            return rounding(samples)
        start = max(recording.start_index, boundary(left_ms, math.floor))
        stop = min(recording.end_index, boundary(right_ms, math.ceil))
        return recording.slice(start, stop)

    def _draw_gaps(self, recording):
        for item in self.gap_items:
            self.plot.removeItem(item)
        self.gap_items.clear()
        for gap in recording.gaps:
            region = pg.LinearRegionItem((gap.start_index / recording.sample_rate_hz * 1000,
                                          gap.end_index / recording.sample_rate_hz * 1000),
                                          movable=False, brush=(224, 166, 35, 35), pen="#99752b")
            region.setZValue(-5)
            self.plot.addItem(region)
            self.gap_items.append(region)

    @property
    def unit_factor(self):
        return 1000.0 if self.units_combo.currentIndex() == 1 else 1.0

    def voltage_text(self, value):
        return "—" if value is None else f"{number(value * self.unit_factor, 3)} {self.units_combo.currentText()}"

    def _measurements(self, recording):
        self._analysis_key += 1
        if recording is None or not recording.input_profile.configured:
            self._analysis_pending = None
            for value in self.metric_values[:3]:
                value.setText("—")
            if recording and self.raw_view.isChecked():
                codes = [code for block in recording.blocks for code in block.samples]
                low, high = min(codes), max(codes)
                self.metric_titles[0].setText("Размах · коды АЦП")
                self.metric_titles[1].setText("Период / частота")
                self.metric_titles[2].setText("Мин. / макс. · коды АЦП")
                self.metric_values[0].setText(f"{high - low} код")
                self.metric_values[2].setText(f"{low} / {high} код")
                self.quality_label.setText(("Достигнута граница АЦП · " if low == 0 or high == 4095 else "")
                                          + "Служебные коды · напряжение неизвестно · время номинальное")
            else:
                self.quality_label.setText("Шкала напряжения не настроена")
            return
        if recording.sample_count > 65536:
            self._analysis_pending = (recording, self._analysis_key)
            for value in self.metric_values[:3]:
                value.setText("Расчёт…")
            self._start_analysis()
            return
        result = analyze(recording)
        self._present_measurements(recording, result)

    def _start_analysis(self):
        if self._analysis_job is not None or self._analysis_pending is None:
            return
        recording, key = self._analysis_pending
        self._analysis_pending = None
        self._analysis_job = FileJob(lambda: analyze(recording))
        self._analysis_job.signals.finished.connect(
            lambda result, error: self._analysis_finished(recording, key, result, error))
        QtCore.QThreadPool.globalInstance().start(self._analysis_job)

    def _analysis_finished(self, recording, key, result, error):
        self._analysis_job = None
        if key == self._analysis_key:
            if error:
                self.quality_label.setText("Анализ недоступен: " + error)
            else:
                self._present_measurements(recording, result)
        self._start_analysis()

    def _present_measurements(self, recording, result):
        ignition = recording.ui_profile == "ignition"
        self.metric_titles[0].setText("Пик сигнала датчика" if ignition else "Размах")
        self.metric_titles[1].setText("Интервал / частота событий" if ignition else "Период / частота")
        self.metric_titles[2].setText("Мин. / макс.")
        self.metric_values[0].setText(self.voltage_text(result.maximum_v if ignition else result.peak_to_peak_v))
        self.metric_values[1].setText("—" if result.period_s is None else
            f"{number(result.period_s * 1000, 2)} мс\n{number(result.frequency_hz, 1)} Гц")
        self.metric_values[2].setText(f"{number(result.minimum_v * self.unit_factor, 2)} / "
                                    f"{number(result.maximum_v * self.unit_factor, 2)} {self.units_combo.currentText()}")
        flags = []
        if result.clipping:
            flags.append("Перегрузка / обрезание")
        if recording.gaps:
            flags.append("Есть пропуски")
        if any("truncated" in flag or "incomplete" in flag for flag in recording.quality_flags):
            flags.append("Неполное событие")
        self.quality_label.setText(" · ".join(flags) or "Исходные отсчёты не изменены")

    def _apply_view(self, reset_cursors=False):
        start, width = self.xposition.value, self.sweep.value * 10
        self.plot.setXRange(start * 1000, (start + width) * 1000, padding=0)
        center, height = self.yposition.value, self.yscale.value * 8
        self.plot.setYRange(center - height / 2, center + height / 2, padding=0)
        self.plot.getAxis("bottom").setTickSpacing(major=self.sweep.value * 1000,
                                                  minor=self.sweep.value * 200)
        self.voltage_axis.setTickSpacing(major=self.yscale.value, minor=self.yscale.value / 5)
        self.unconfigured_text.setPos((start + width / 2) * 1000, center)
        with QtCore.QSignalBlocker(self.region):
            self.region.setRegion((start * 1000, (start + width) * 1000))
        if reset_cursors:
            self.cursor_a.setValue((start + width * .2) * 1000)
            self.cursor_b.setValue((start + width * .4) * 1000)

    def _view_changed(self, sender):
        if self._rendering or self.display_recording is None:
            return
        if sender is self.xposition:
            self.follow = False
        self._display(self.display_recording)

    def _region_changed(self):
        if self._rendering:
            return
        start, stop = self.region.getRegion()
        if stop <= start:
            return
        self.follow = False
        self.xposition.set_value(start / 1000)
        self.sweep.set_value((stop - start) / 10000)
        if self.display_recording:
            self._display(self.display_recording)

    def _update_cursors(self):
        if not self.display_recording:
            return
        if not self.cursor_button.isChecked():
            self.cursor_label.setText("Курсоры выключены")
            self.metric_values[3].setText("—")
            return
        a, b = self.cursor_a.value() / 1000, self.cursor_b.value() / 1000
        result = cursor_measurement(self.display_recording, a, b)
        self.metric_values[3].setText(time_text(result.delta_t_s))
        if not self.display_recording.input_profile.configured and self.raw_view.isChecked():
            points = [self.display_recording.sample_at_time(t) for t in (a, b)]
            codes = [f"{point[1]} код" if point else "—" for point in points]
            self.cursor_label.setText(f"A: {time_text(a)} · {codes[0]}     B: {time_text(b)} · {codes[1]}"
                                      "   |   ΔU неизвестно · время номинальное")
            return
        self.cursor_label.setText(
            f"A: {time_text(a)} · {self.voltage_text(result.voltage_a_v)}     "
            f"B: {time_text(b)} · {self.voltage_text(result.voltage_b_v)}     "
            f"ΔU: {self.voltage_text(result.delta_v)}   |   — = нет отсчёта / шкалы")

    def _raw_view_changed(self):
        if self.display_recording is not None:
            self._display(self.display_recording)

    def _set_axis_mode(self, raw):
        """Raw diagnostics is a separate, explicit axis, never a calibration."""
        kind = "raw" if raw else "voltage"
        if kind == self._axis_kind:
            return
        self._axis_kind = kind
        factor, unit = (1, "код") if raw else (self.unit_factor, self.units_combo.currentText())
        self.voltage_axis.factor = factor
        self.voltage_axis.picture = None
        self.voltage_axis.update()
        self.plot.setLabel("left", "Служебные коды АЦП" if raw else "Напряжение на входе",
                           units="" if raw else unit, color="#abc8d8")
        self.plot.getAxis("left").showLabel(not getattr(self, "_compact", False))
        self.axis_units.setText(f"X: мс · Y: {unit}" + (" · не напряжение" if raw else ""))
        self.yscale.set_bounds(1 if raw else .001, 4096 if raw else 100)
        self.yposition.set_bounds(0 if raw else -100, 4095 if raw else 100)
        self.yscale.set_display(factor, unit + "/дел")
        self.yposition.set_display(factor, unit)
        self.yscale.set_value(512 if raw else .5)
        self.yposition.set_value(2048 if raw else 1.65)

    def _units_changed(self):
        if self.display_recording and not self.display_recording.input_profile.configured:
            return
        factor, unit = self.unit_factor, self.units_combo.currentText()
        self.voltage_axis.factor = factor
        self.voltage_axis.picture = None
        self.voltage_axis.update()
        self.plot.setLabel("left", "Напряжение на входе", units=unit, color="#abc8d8")
        self.plot.getAxis("left").showLabel(not getattr(self, "_compact", False))
        self.axis_units.setText(f"X: мс · Y: {unit}")
        self.yscale.set_display(factor, unit + "/дел")
        self.yposition.set_display(factor, unit)
        self.threshold.set_display(factor, unit)
        if self.display_recording:
            self._display(self.display_recording)

    def _capture_settings_changed(self, *args):
        if self.device_active:
            return
        if self.mode == 0 and not self.paused:
            self._show_live()

    def set_edge(self, edge):
        self.rising.setChecked(edge == "rising")
        self.falling.setChecked(edge == "falling")
        self._capture_settings_changed()

    def toggle_cursors(self):
        for cursor in (self.cursor_a, self.cursor_b):
            cursor.setVisible(self.cursor_button.isChecked())
        self._update_cursors()

    def toggle_pause(self):
        self.paused = not self.paused
        if not self.paused:
            self.follow = True
            self._show_live()
        self._update_actions()

    def resume_follow(self):
        self.paused = False
        self.follow = True
        self.set_mode(0)

    def change_profile(self, profile):
        if self.recording or self.armed_after is not None or self.mode != 0:
            return
        self.ui_profile = profile
        if self.device_active:
            # Presentation choice applies to the next capture, not its saved metadata.
            self._update_actions()
            return
        self.sweep.set_value(.02 if profile == "ignition" else .002)
        self.holdoff.set_value(.005 if profile == "ignition" else .001)
        self.threshold.set_value(1.2 if profile == "ignition" else 1.65)
        self._show_live(reset=True)
        self._update_actions()
        self.auto_scale()

    def change_waveform(self, *args):
        kind = self.waveform_combo.currentData()
        if kind == "device":
            if not self.device_active:
                with QtCore.QSignalBlocker(self.waveform_combo):
                    self.waveform_combo.setCurrentIndex(("sine", "square", "ignition").index(self.source.waveform))
            self.device_info()
            return
        if self.device_active:
            state = self.device.state
            if state.connected or state.busy or state.has_capture or state.has_incomplete:
                with QtCore.QSignalBlocker(self.waveform_combo):
                    self.waveform_combo.setCurrentIndex(3)
                return
            if self.dirty and not self._confirm_discard():
                with QtCore.QSignalBlocker(self.waveform_combo):
                    self.waveform_combo.setCurrentIndex(3)
                return
            self.device_active = False
            self.mode = 0
            self.device_last = None
            self.single = self.completed = None
            self.single_dirty = self.record_dirty = False
            self.live_settings = None
            self.raw_view.setChecked(False)
            self.holdoff.spin.setSpecialValueText("")
            self.timer.start()
        if self.recording or self.armed_after is not None or self.mode != 0:
            return
        self.source = DemoSource(self.waveform_combo.currentData())
        self.recent.clear()
        for _ in range(20):
            self.recent.append(self.source.next_block(2500))
        if self._demo_settings is not None:
            self._load_saved_controls(replace(self._live_snapshot(), capture_settings=self._demo_settings))
            self._demo_settings = None
        self.paused = False
        self.follow = True
        self._show_live(reset=True)
        self._update_actions()
        self.auto_scale()

    def set_mode(self, mode):
        if self.busy:
            return
        if self.device_active:
            if self.device_acquiring:
                return
            self.mode = mode
            if mode == 0:
                self._show_live(reset=True)
            elif mode == 1 and self.single:
                self._display(self.single, reset=True)
            elif mode == 2 and self.completed:
                self._display(self.completed, reset=True)
            self._update_actions()
            return
        if self.armed_after is not None and mode != 1:
            self.armed_after = None
            self.arm_blocks.clear()
        if self.mode == 0 and mode != 0:
            self.live_settings = self.capture_settings()
        self.mode = mode
        if mode == 0:
            if self.live_settings:
                self._load_saved_controls(replace(self._live_snapshot(), capture_settings=self.live_settings))
            self._show_live(reset=True)
        elif mode == 1:
            if self.single is None:
                self.arm_single()
                return
            self._display(self.single, reset=True)
            self._load_saved_controls(self.single)
        elif self.completed is not None and not self.recording:
            self._display(self.completed, reset=True)
            self._load_saved_controls(self.completed)
        else:
            self._show_live()
        self._update_actions()

    def _load_saved_controls(self, recording):
        settings = recording.capture_settings
        self.holdoff.spin.setSpecialValueText("Недоступна" if recording.source == "device"
            and "window_local_time" in recording.quality_flags else "")
        if recording.input_profile.configured:
            self.threshold.set_bounds(*recording.input_profile.voltage_limits)
        self.holdoff.set_bounds(0, max(.1, settings.holdoff_s))
        if settings.threshold_v is not None:
            # A recorded software threshold is displayed exactly even if it
            # was outside that input's range; the snapshot is not reconfigured.
            self.threshold.set_bounds(min(self.threshold.low, settings.threshold_v),
                                      max(self.threshold.high, settings.threshold_v))
            self.threshold.set_value(settings.threshold_v)
        else:
            self.threshold.spin.setSpecialValueText("Не настроен")
            self.threshold.set_value(self.threshold.low)
        if settings.threshold_v is not None:
            self.threshold.spin.setSpecialValueText("")
        self.holdoff.set_value(settings.holdoff_s)
        self.pretrigger.setValue(round(settings.pretrigger_fraction * 100))
        self.pre_label.setText(f"{number(settings.pretrigger_fraction * 100, 2)} %")
        self.rising.setChecked(settings.edge == "rising")
        self.falling.setChecked(settings.edge == "falling")

    def arm_single(self):
        if self.device_active:
            self.start_device(2)
            return
        if self.recording or self.busy:
            return
        if self.armed_after is not None:
            self.armed_after = None
            self.arm_blocks.clear()
            self._update_actions()
            return
        if self.single_dirty and not self._confirm_discard():
            return
        if self.mode == 0:
            self.live_settings = self.capture_settings()
        self._armed_settings = self.live_settings or self.capture_settings()
        # Single ignition window is a stated context, not an inferred burn time.
        if self.ui_profile == "ignition":
            self._armed_settings = replace(self._armed_settings, window_s=.005)
        if self._armed_settings.window_s > 1:
            self.statusBar().showMessage("Одиночный захват: уменьшите развёртку до 100 мс/дел или меньше (окно ≤ 1 с).")
            return
        self.mode = 1
        self.armed_after = self.source.next_index
        self.arm_blocks = list(self.recent)
        self._pending_trigger = None
        self._update_actions()

    def toggle_record(self):
        if self.device_active:
            if self.device_acquiring:
                self.device.stop()
            else:
                self.start_device(0)
            return
        if self.recording:
            self.stop_recording()
            return
        if self.busy or self.armed_after is not None:
            return
        if self.completed is not None and self.record_dirty and not self._confirm_discard():
            return
        self.live_settings = self.capture_settings()
        self.record_blocks, self.record_count = [], 0
        self.record_metadata = dict(channel_name=self.channel_name, ui_profile=self.ui_profile,
            capture_settings=self.capture_settings(), input_profile=DEMO_PROFILE, source="demo",
            session_id=str(uuid.uuid4()))
        self.recording = True
        self.mode = 2
        self._update_actions()

    def stop_recording(self):
        self.recording = False
        if self.record_blocks:
            self.completed = Recording(tuple(self.record_blocks), **self.record_metadata)
            self.events = ()
            self.event_ordinal = -1
            self.record_dirty = True
            self.mode = 2
            self._display(self.completed, reset=True)
            if self.completed.ui_profile == "ignition" and self.completed.sample_count > 65536:
                recording = self.completed
                def complete(result):
                    self.events, warning = result
                    if warning:
                        self.statusBar().showMessage(warning)
                self._submit(lambda: self._safe_events(recording), complete)
            else:
                self.events, warning = self._safe_events(self.completed)
                if warning:
                    self.statusBar().showMessage(warning)
        self._update_actions()

    def select_event(self, direction):
        if not self.events or not self.completed:
            return
        self.event_ordinal = min(len(self.events) - 1, max(0, self.event_ordinal + direction))
        event = self.events[self.event_ordinal]
        self.xposition.set_value(event.start_index / self.completed.sample_rate_hz)
        self.sweep.set_value((event.end_index - event.start_index) / self.completed.sample_rate_hz / 10)
        self._display(self.completed)
        self.plot_title.setText(f"Событие {self.event_ordinal + 1} из {len(self.events)} · кандидат на искру")
        self.quality_label.setText("Неполное событие" if event.quality_flags else "Пороговый поиск · без диагностики горения")
        self.cursor_a.setValue(event.trigger_index / self.completed.sample_rate_hz * 1000)
        self.cursor_b.setValue((event.trigger_index / self.completed.sample_rate_hz + .0015) * 1000)

    def _update_actions(self):
        self.save_button.setText("Сохранить запись")
        self.record_button.setToolTip("")
        viewing_file = self.mode == 2 and not self.recording
        self.waveform_combo.setVisible(not viewing_file)
        self.file_source_label.setVisible(viewing_file)
        self.units_combo.setEnabled(bool(self.display_recording and
                                         self.display_recording.input_profile.configured))
        for index, tab in enumerate(self.tabs):
            tab.setChecked(self.mode == index)
            tab.setEnabled(not self.busy and (not self.recording or index != 1))
        display_profile = self.display_recording.ui_profile if self.mode != 0 and self.display_recording else self.ui_profile
        self.scope_button.setChecked(display_profile == "oscilloscope")
        self.ignition_button.setChecked(display_profile == "ignition")
        single_title = "Одна искра" if display_profile == "ignition" else "Одиночный захват"
        if self.device_active or (self.display_recording and self.display_recording.source == "device"):
            single_title = "Одиночный захват"
        self.tabs[1].setText(single_title)
        locked = self.recording or self.armed_after is not None or self.mode != 0 or self.busy
        for widget in (self.scope_button, self.ignition_button, self.waveform_combo,
                       self.rename_button, self.threshold, self.holdoff, self.rising,
                       self.falling, self.pretrigger):
            widget.setEnabled(not locked)
        self.pause_button.setEnabled((self.mode == 0 or self.recording) and not self.busy)
        self.pause_button.setText("▶  Продолжить просмотр" if self.paused else "Ⅱ  Пауза просмотра")
        self.record_button.setText("■  Остановить запись" if self.recording else "●  Начать запись")
        self.record_button.setEnabled(not self.busy and self.armed_after is None and (self.mode == 0 or self.recording))
        self.single_button.setText("Отменить ожидание" if self.armed_after is not None else
                                   ("◎  Поймать следующую" if self.mode == 1 else "◎  " + single_title))
        self.single_button.setEnabled(not self.recording and not self.busy and self.mode != 2)
        self.capture_note.setText("Параметры фиксированы на время записи" if self.recording else
            "Ожидание программного события по CH1" if self.armed_after is not None else
            "Сохранённые параметры захвата" if self.mode != 0 else "Программный поиск события · ДЕМО")
        has_record = (self.mode == 1 and self.single is not None) or (self.mode == 2 and self.completed is not None)
        self.save_button.setEnabled(has_record and not self.recording and not self.busy and self.armed_after is None)
        self.export_button.setEnabled(self.display_recording is not None and not self.busy and not self.recording)
        self.open_button.setEnabled(not self.recording and not self.busy and self.armed_after is None)
        self.follow_button.setEnabled(not self.busy)
        self.gap_button.setEnabled((self.mode == 0 or self.recording) and not self.busy)
        show_events = self.mode == 2 and not self.recording and bool(self.events)
        self.prev_button.setVisible(show_events)
        self.next_button.setVisible(show_events)
        if self.armed_after is not None:
            state = "◎  Ожидание события"
        elif self.recording:
            state = f"●  Запись · {self.record_count / 50000:.1f} с"
        elif self.mode == 1:
            state = "✓  Импульс захвачен" if self.single else "Ожидание захвата"
        elif self.mode == 2:
            state = "✓  Запись завершена" if self.completed else "Нет завершённой записи"
        else:
            state = "Ⅱ  Пауза просмотра" if self.paused else "●  Живой сигнал"
        self.state_label.setText(state)
        if self.device_active:
            self._device_actions()
        elif self.device_panel:
            self.device_panel.update_state()

    def auto_scale(self):
        rec = self.display_recording
        if rec is None:
            return
        profile = rec.input_profile
        if not profile.configured:
            if not self.raw_view.isChecked():
                return
            low, high = min(min(b.samples) for b in rec.blocks), max(max(b.samples) for b in rec.blocks)
        else:
            low, high = sorted((profile.voltage(min(min(b.samples) for b in rec.blocks)),
                                profile.voltage(max(max(b.samples) for b in rec.blocks))))
        wanted = max(.001, (high - low) * 1.15 / 8)
        decade = 10 ** math.floor(math.log10(wanted))
        scale = next(step * decade for step in (1, 2, 5, 10) if step * decade >= wanted)
        self.yposition.set_value(round((high + low) / 2 / (scale / 5)) * (scale / 5))
        self.yscale.set_value(scale)
        self._display(rec)

    def full_signal(self):
        rec = self.display_recording
        if rec:
            self.follow = False
            self.xposition.set_value(rec.start_index / rec.sample_rate_hz)
            self.sweep.set_value(rec.duration_s / 10)
            self._display(rec)

    def rename_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Переименовать канал")
        dialog.setMinimumWidth(360)
        box = QtWidgets.QVBoxLayout(dialog)
        box.addWidget(label("Пользовательское имя", "muted"))
        editor = QtWidgets.QLineEdit(self.channel_name)
        editor.setMaxLength(80)
        box.addWidget(editor)
        box.addWidget(label("Вход: CH1\nПрофиль: " + ("Зажигание" if self.ui_profile == "ignition" else "Осциллограф"), "muted"))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.rename_channel(editor.text())

    def rename_channel(self, name):
        name = name.strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            self.statusBar().showMessage("Имя должно содержать 1–80 печатных символов.")
            return False
        self.channel_name = name
        self.settings.setValue("channel_name", name)
        self.settings.sync()
        if self.mode == 0:
            self._show_live()
        return True

    def inject_gap(self):
        if self.device_active:
            return
        self.source.skip(5000)
        self.statusBar().showMessage("Добавлен синтетический пропуск 100 мс; он сохранится в записи.")

    def raw_info(self):
        rec = self.display_recording
        if not rec:
            return
        profile = rec.input_profile
        raw_min = min(min(b.samples) for b in rec.blocks)
        raw_max = max(max(b.samples) for b in rec.blocks)
        QtWidgets.QMessageBox.information(self, "Шкала и исходные данные",
            f"CH1 · {rec.channel_name}\nПроисхождение: {rec.source}\n"
            f"Профиль входа: {profile.profile_id}\nСостояние: {profile.state}\n"
            f"U_CH1 = a × code + b\n a = {profile.a}; b = {profile.b}\n"
            f"Исходные коды: {raw_min}…{raw_max}; ADC: 12 бит\n"
            f"Отсчётов: {rec.sample_count}; пропусков: {len(rec.gaps)}\n"
            f"Временная основа: {rec.time_basis}\n\n"
            "В/дел и положение Y меняют только вид графика. Коэффициент датчика и кВ не применяются.")

    def _confirm_discard(self):
        answer = QtWidgets.QMessageBox.question(self, "Несохранённые данные",
            "Захват или запись не сохранены. Продолжить без сохранения?",
            QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel)
        return answer == QtWidgets.QMessageBox.StandardButton.Discard

    def _submit(self, operation, complete):
        self.busy = True
        self._update_actions()
        self._job = FileJob(operation)
        self._job.signals.finished.connect(lambda result, error: self._finished(result, error, complete))
        QtCore.QThreadPool.globalInstance().start(self._job)

    def _finished(self, result, error, complete):
        self.busy = False
        self._job = None
        if error:
            QtWidgets.QMessageBox.warning(self, "Не удалось выполнить действие", error)
        else:
            complete(result)
        self._update_actions()

    def open_dialog(self):
        if self.device_active and self.device_acquiring:
            return
        if self.dirty and not self._confirm_discard():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Открыть запись", "",
                                                       "Записи (*.mtv2 *.mtcap);;Все файлы (*)")
        if path:
            def read():
                recording = load(path)
                events, warning = self._safe_events(recording)
                return recording, events, warning
            self._submit(read, lambda result: self.open_recording(*result))

    @staticmethod
    def _safe_events(recording):
        if recording.ui_profile != "ignition" or not recording.input_profile.configured:
            return (), None
        try:
            return find_events(recording), None
        except V2Error as exc:
            return (), "События не рассчитаны: " + str(exc)

    def open_recording(self, recording, events=None, warning=None):
        if self.device_active and (self.device_acquiring or self.device.state.busy):
            return
        if events is None:
            events, warning = self._safe_events(recording)
        if self.mode == 0 and not self.device_active:
            self.live_settings = self.capture_settings()
        self.completed = recording
        self.events = events
        self.event_ordinal = -1
        self.record_dirty = False
        self.mode = 2
        self._load_saved_controls(recording)
        self._display(recording, reset=True)
        if recording.input_profile.configured:
            self.auto_scale()
        if warning:
            self.statusBar().showMessage(warning)
        self._update_actions()

    def _choose_path(self, title, suffix, file_filter):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, "запись" + suffix, file_filter,
            options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return None, False
        path = Path(path)
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        exists = path.exists() or (suffix == ".csv" and path.with_suffix(".csv.json").exists())
        if exists and QtWidgets.QMessageBox.question(self, "Заменить файл?",
            "Выбранный файл или файл метаданных уже существует. Заменить?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No) != QtWidgets.QMessageBox.StandardButton.Yes:
            return None, False
        return path, exists

    def save_dialog(self):
        rec = self.single if self.mode == 1 else self.completed
        if rec is None:
            return
        path, overwrite = self._choose_path("Сохранить исходную запись", ".mtv2", "Мотортестер V2 (*.mtv2)")
        if path:
            def done(_):
                if rec is self.single:
                    self.single_dirty = False
                if rec is self.completed:
                    self.record_dirty = False
                self.statusBar().showMessage(f"Запись сохранена: {path}")
            self._submit(lambda: save(path, rec, overwrite=overwrite), done)

    def export_dialog(self):
        rec = self.display_recording
        if rec is None:
            return
        left, right = self.plot.viewRange()[0]
        try:
            selected = self._visible_slice(rec, left, right)
        except V2Error as exc:
            self.statusBar().showMessage(str(exc))
            return
        path, overwrite = self._choose_path("Экспорт видимого участка", ".csv", "CSV с метаданными JSON (*.csv)")
        if path:
            self._submit(lambda: export_csv(path, selected, overwrite=overwrite),
                lambda _: self.statusBar().showMessage(f"Экспортирован видимый участок: {path} + JSON"))

    def png_dialog(self):
        path, overwrite = self._choose_path("Снимок окна", ".png", "Изображение (*.png)")
        if path and not self.grab().save(str(path)):
            self.statusBar().showMessage("Не удалось сохранить снимок.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "action_layout"):
            return
        compact = self.width() < 1280 or self.height() < 820
        if getattr(self, "_compact", None) == compact:
            return
        self._compact = compact
        # At the minimum window height Qt's plot layout can place axis titles
        # outside the plot. Keep units explicitly above it in the compact view.
        self.axis_units.setVisible(compact)
        for axis in ("left", "bottom"):
            self.plot.getAxis(axis).showLabel(not compact)
        self.plot.getAxis("bottom").setHeight(24 if compact else 46)
        for widget in (self.state_label, *self.action_buttons):
            self.action_layout.removeWidget(widget)
        for column in range(5):
            self.action_layout.setColumnStretch(column, 0)
        self.action_layout.addWidget(self.state_label, 0, 0, 1, 4 if compact else 1)
        for index, button in enumerate(self.action_buttons):
            self.action_layout.addWidget(button, 1 if compact else 0, index if compact else index + 1)
        if not compact:
            self.action_layout.setColumnStretch(0, 1)
        for card in self.metric_cards:
            self.metrics_layout.removeWidget(card)
        for index, card in enumerate(self.metric_cards):
            self.metrics_layout.addWidget(card, 0, index)
        for title in self.metric_titles:
            title.setStyleSheet("font-size: 12px;" if compact else "")
        for value in self.metric_values:
            value.setStyleSheet("font-size: 16px;" if compact else "")
        self.overview.setFixedHeight(48 if compact else 100)

    def open_stream_workspace(self):
        return self._open_stream_workspace(None)

    def open_device_stream_workspace(self):
        from .device import available_ports
        from .stream_device import SerialStreamSelection
        if self.stream_dialog is not None and not self.stream_dialog.closed:
            self.stream_dialog.show()
            self.stream_dialog.raise_()
            self.statusBar().showMessage("Для смены источника сначала закройте текущее окно потока.")
            return False
        try:
            ports = [name for name, _ in available_ports()]
        except Exception:
            ports = []
        dialog = QtWidgets.QInputDialog(self)
        dialog.setWindowTitle("STM32 · порт непрерывного приёма")
        dialog.setLabelText("Выберите или введите COM-порт.\n"
                            "Следующая кнопка подключения проверит протокол без запуска АЦП.")
        dialog.setComboBoxItems(["", *ports])
        dialog.setComboBoxEditable(True)
        dialog.setOkButtonText("Открыть панель")
        dialog.setCancelButtonText("Отмена")
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return False
        try:
            selection = SerialStreamSelection(dialog.textValue().strip())
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return False
        return self._open_stream_workspace(selection)

    def _reserve_serial(self, owner, port):
        self._release_window_serial_if_closed()
        if self._serial_owner is not None and self._serial_owner is not owner:
            return False
        self._serial_owner, self._serial_port = owner, port
        if self.device_panel:
            self.device_panel.update_state()
        return True

    def _release_serial(self, owner):
        if self._serial_owner is owner:
            self._serial_owner = self._serial_port = None
        if self.device_panel:
            self.device_panel.update_state()

    def _release_window_serial_if_closed(self):
        state = self.device.state
        if (self._serial_owner is self.device and not state.connected and
                not state.busy and not state.close_failed and not self.device.bridge.active):
            self._serial_owner = self._serial_port = None

    def _open_stream_workspace(self, selection):
        from .stream_device import StreamContext
        from .stream_ui import StreamDialog
        if (self.stream_dialog is not None and not self.stream_dialog.closed and
                self.stream_dialog.selection != selection):
            self.stream_dialog.show()
            self.stream_dialog.raise_()
            self.statusBar().showMessage("Для смены источника сначала закройте текущее окно потока.")
            return False
        if self.stream_dialog is None or self.stream_dialog.closed:
            if self.stream_dialog is not None:
                self.stream_dialog.deleteLater()
            self.stream_dialog = StreamDialog(
                self, context=StreamContext(self.channel_name, self.ui_profile),
                selection=selection, acquire_serial=self._reserve_serial,
                release_serial=self._release_serial)
            self.stream_dialog.settled.connect(self._stream_settled)
            self.stream_dialog.close_cancelled.connect(self._stream_close_cancelled)
        self.stream_dialog.show()
        self.stream_dialog.raise_()
        self.stream_dialog.activateWindow()
        return True

    def _stream_settled(self):
        if self._stream_close_pending:
            self._stream_close_pending = False
            QtCore.QTimer.singleShot(0, self.close)

    def _stream_close_cancelled(self):
        self._stream_close_pending = False

    def closeEvent(self, event):
        if self._incomplete_close_prompting:
            event.ignore()
            return
        if self.busy:
            self.statusBar().showMessage("Дождитесь завершения файловой операции.")
            event.ignore()
            return
        if self.recording:
            self.stop_recording()
        if self.dirty and not self._confirm_discard():
            event.ignore()
            return
        pending = self.device.pending_incomplete
        if pending is not None and pending is not self._incomplete_exit_result:
            choice = self._choose_incomplete_exit(pending)
            if choice == "save":
                self.save_device_fragments(close_after=True, result=pending)
                event.ignore()
                return
            if choice != "discard":
                self._device_closing = False
                event.ignore()
                return
            if not self.device.discard_incomplete(pending):
                self._device_error("Не удалось освободить фрагменты. Дождитесь завершения операции и повторите закрытие.")
                event.ignore()
                return
            self._incomplete_exit_result = pending
        if self.device.bridge.running and not self._device_shutdown:
            self._device_closing = True
            self.device.shutdown()
            event.ignore()
            return
        if self.stream_dialog is not None and not self.stream_dialog.closed:
            self._stream_close_pending = True
            self.stream_dialog.close()
            event.ignore()
            return
        self.timer.stop()
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Мотортестер V2 · один CH1, ДЕМО и файлы")
    parser.add_argument("--screenshot", type=Path, help="Сохранить фактическое окно Qt и завершиться")
    parser.add_argument("--profile", choices=("oscilloscope", "ignition"), default="oscilloscope")
    parser.add_argument("--settings", type=Path, help="Отдельный INI для воспроизводимой проверки")
    args = parser.parse_args(argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setApplicationName("Мотортестер V2")
    window = MainWindow(settings_path=args.settings)
    if args.profile != "oscilloscope":
        window.change_profile(args.profile)
        window.waveform_combo.setCurrentIndex(2)
    window.show()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(args.screenshot)):
                app.exit(1)
                return
            app.quit()
        QtCore.QTimer.singleShot(800, capture)
    return app.exec()
