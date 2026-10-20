"""Explicit controls for separately timed STM32 windows; no serial I/O in Qt UI."""
from PySide6 import QtCore, QtWidgets
from ..session import Phase
from .device import DeviceBridge, available_ports


def note(text):
    widget = QtWidgets.QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    return widget


class Combo(QtWidgets.QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class Spin(QtWidgets.QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class DevicePanel(QtWidgets.QDialog):
    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.setWindowTitle("STM32 · подключение и захват")
        self.resize(510, 670)
        self.setStyleSheet("QDialog { background: #0d1d28; }")
        box = QtWidgets.QVBoxLayout(self)
        box.addWidget(note("Wire 0.1 · отдельные окна CH1\n"
                          "Подключение проверяет версию и возможности. АЦП запускается отдельной кнопкой."))
        row = QtWidgets.QHBoxLayout()
        self.port = Combo()
        self.port.setEditable(True)
        self.port.setPlaceholderText("Выберите COM-порт")
        row.addWidget(self.port, 1)
        refresh = QtWidgets.QPushButton("Обновить")
        refresh.clicked.connect(self.refresh_ports)
        row.addWidget(refresh)
        box.addLayout(row)
        self.reset = QtWidgets.QCheckBox("После прошлой попытки я физически сбросил плату")
        box.addWidget(self.reset)
        self.connect_button = QtWidgets.QPushButton("Подключить")
        self.connect_button.clicked.connect(self.connect_device)
        self.disconnect_button = QtWidgets.QPushButton("Отключить")
        self.disconnect_button.clicked.connect(viewer.device.disconnect_source)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.connect_button)
        row.addWidget(self.disconnect_button)
        box.addLayout(row)
        self.status = note("Не подключено")
        box.addWidget(self.status)
        form = QtWidgets.QFormLayout()
        self.level = Spin()
        self.level.setRange(1, 4094)
        self.level.setValue(2048)
        self.level.setSuffix(" код АЦП")
        self.edge = Combo()
        self.edge.addItem("Нарастающий код", "rising")
        self.edge.addItem("Спадающий код", "falling")
        self.pre = Combo()
        form.addRow("Служебный порог", self.level)
        form.addRow("Фронт CH1", self.edge)
        form.addRow("Предыстория", self.pre)
        box.addLayout(form)
        box.addWidget(note("Шкала напряжения не настроена. Эти коды не являются вольтами на разъёме.\n"
                          "2048 отсчёта · номинальные 50 кГц · 40,96 мс внутри окна. "
                          "Промежутки между окнами неизвестны. Аппаратной паузы запуска нет."))
        self.live = QtWidgets.QPushButton("Получать окна · Auto")
        self.live.clicked.connect(lambda: viewer.start_device(0))
        self.single = QtWidgets.QPushButton("Один захват · ждать фронта")
        self.single.clicked.connect(lambda: viewer.start_device(2))
        self.stop = QtWidgets.QPushButton("Остановить получение")
        self.stop.clicked.connect(viewer.device.stop)
        for button in (self.live, self.single, self.stop):
            box.addWidget(button)
        self.fragments = QtWidgets.QPushButton("Сохранить неполные данные · JSON")
        self.fragments.clicked.connect(viewer.save_device_fragments)
        box.addWidget(self.fragments)
        self.error = note("")
        box.addWidget(self.error)
        box.addStretch()
        hide = QtWidgets.QPushButton("Скрыть панель")
        hide.clicked.connect(self.hide)
        box.addWidget(hide)
        self.port.currentTextChanged.connect(self.update_state)
        self.refresh_ports()
        self.update_state()

    def refresh_ports(self):
        previous = self.port.currentText()
        try:
            ports = available_ports()
        except Exception:
            self.error.setText("Не удалось получить список портов. Имя можно ввести вручную.")
            return
        self.port.clear()
        for name, description in ports:
            self.port.addItem(name)
            self.port.setItemData(self.port.count() - 1, description, QtCore.Qt.ItemDataRole.ToolTipRole)
        if previous:
            self.port.setCurrentText(previous)
        else:
            self.port.setCurrentIndex(-1)

    def connect_device(self):
        if not self.port.currentText().strip():
            return
        if not self.viewer.enter_device():
            return
        if self.viewer.dirty and not self.viewer._confirm_discard():
            return
        self.error.setText("")
        if self.viewer.device.connect_source(self.port.currentText().strip(), self.reset.isChecked()):
            self.viewer._clear_device_window("Проверка соединения")
            self.viewer._update_actions()
        else:
            if not self.error.text():
                self.error.setText("Подключение сейчас недоступно. Проверьте порт и состояние.")
        self.reset.setChecked(False)

    def update_state(self):
        state = self.viewer.device.state
        snapshot = state.snapshot
        ready = (state.connected and snapshot is not None and snapshot.phase is Phase.READY
                 and not state.busy and not state.has_capture and not state.has_incomplete)
        caps = snapshot.capabilities if snapshot else None
        current = self.pre.currentData()
        supported = caps.pretrigger_samples if caps else ()
        if tuple(self.pre.itemData(i) for i in range(self.pre.count())) != supported:
            self.pre.clear()
            for count in supported:
                self.pre.addItem(f"{count / 2048 * 100:g} % · {count} отсчётов", count)
            self.pre.setCurrentIndex(max(0, self.pre.findData(current if current in supported else 512)))
        self.reset.setVisible(state.reset_required and not state.connected)
        self.port.setEnabled(not state.connected and not state.busy)
        self.connect_button.setEnabled(not state.connected and not state.busy and not state.closing
                                       and not state.close_failed and not state.has_incomplete
                                       and not self.viewer.busy and not self.viewer.recording
                                       and bool(self.port.currentText().strip()))
        self.disconnect_button.setEnabled(state.connected or state.close_failed)
        for widget in (self.level, self.edge, self.pre):
            widget.setEnabled(ready)
        for widget, mode in ((self.live, 0), (self.single, 2)):
            widget.setEnabled(ready and bool(caps.mode_bits & (1 << mode)) and not self.viewer.busy)
        self.stop.setEnabled(state.connected and self.viewer.device_acquiring
                             and not (snapshot and snapshot.stop_barrier))
        self.fragments.setEnabled(self.viewer.device.pending_incomplete is not None and not self.viewer.busy)
        if state.close_failed:
            message = "Закрытие порта не подтверждено. Повторите отключение."
        elif snapshot and snapshot.phase is Phase.RECOVERY:
            message = "Ошибка обмена. Сохраните неполные данные; затем отключите и сбросьте плату."
        elif state.connected and caps:
            message = f"Протокол 0.1 совместим · сборка {caps.firmware_build}\n"
            message += "Получение / ожидание окна" if self.viewer.device_acquiring else "Готов к команде захвата"
        elif state.busy:
            message = "Проверка соединения…"
        else:
            message = "Не подключено"
        self.status.setText(message)


class DeviceControlsMixin:
    def _init_device(self, factory=None):
        self.device = (factory or DeviceBridge)(self)
        self.device_active = False
        self.device_last = None
        self.device_acquiring = False
        self.device_capture_mode = 0
        self.device_panel = None
        self._device_shutdown = False
        self._device_closing = False
        self._axis_kind = None
        self._demo_settings = None
        self.device.state_changed.connect(self._device_state)
        self.device.recording_ready.connect(self._device_window)
        self.device.incomplete_ready.connect(self._device_incomplete)
        self.device.error.connect(self._device_error)
        self.device.finished.connect(self._device_finished)

    def device_info(self):
        if self.device_panel is None:
            self.device_panel = DevicePanel(self)
        self.device_panel.show()
        self.device_panel.raise_()

    def enter_device(self):
        if self.recording or self.busy or self.armed_after is not None:
            return False
        if self.device_active:
            return True
        if self.dirty and not self._confirm_discard():
            return False
        self.timer.stop()
        self._demo_settings = self.capture_settings()
        self.device_active = True
        with QtCore.QSignalBlocker(self.waveform_combo):
            self.waveform_combo.setCurrentIndex(3)
        self._clear_device_window("Подключение не запускает захват")
        self.raw_view.setChecked(False)
        self.raw_view.setVisible(True)
        self._update_actions()
        return True

    def _clear_device_window(self, subtitle):
        """Begin a new acquisition boundary; old file/window is never new data."""
        self.device_last = None
        self.mode = 0
        self.paused = False
        self.recent.clear()
        self.single = self.completed = self.display_recording = None
        self.single_dirty = self.record_dirty = False
        self.live_settings = None
        self.events = ()
        self.event_ordinal = -1
        self._analysis_key += 1
        self._analysis_pending = None
        self.curve.clear()
        self.overview_curve.clear()
        for item in self.gap_items:
            self.plot.removeItem(item)
        self.gap_items.clear()
        self.trigger_line.hide()
        self.threshold_line.hide()
        self.overview_label.setText("Ожидание первого окна")
        self.quality_label.setText("")
        for value in self.metric_values:
            value.setText("—")
        self.cursor_label.setText("Данных устройства ещё нет")
        self.plot_title.setText("STM32 · ожидание данных CH1")
        self.plot_subtitle.setText(subtitle)
        self.origin_badge.setText("ПРИБОР")
        self.provenance_label.setText("CH1 · STM32 · ожидание данных")
        self.scale_label.setText("Шкала напряжения не настроена")
        self.threshold.spin.setSpecialValueText("Не настроен")
        self.threshold.set_value(self.threshold.low)
        self.holdoff.spin.setSpecialValueText("Недоступна")
        self.holdoff.set_value(0)
        self.pre_label.setText("Выбор в панели STM32")

    def start_device(self, mode):
        if self.busy or self.device_acquiring:
            return
        if not self.enter_device():
            return
        if self.dirty and not self._confirm_discard():
            return
        if self.device_panel is None:
            self.device_info()
        panel = self.device_panel
        accepted = self.device.start(mode=mode, threshold_code=panel.level.value(),
            edge=panel.edge.currentData(), pretrigger_samples=panel.pre.currentData(),
            channel_name=self.channel_name, ui_profile=self.ui_profile)
        if accepted:
            self._clear_device_window("Ожидание нового окна CH1")
            self.device_capture_mode = mode
            self.device_acquiring = True
            self.mode = 1 if mode == 2 else 0
            self.paused = False
            self._update_actions()
        panel.update_state()

    def _device_window(self, recording):
        # Retain the exact immutable result BEFORE releasing its MCU buffer.
        # Only one latest live window is kept; this is not a session recorder.
        self.device_last = recording
        if self.device_active:
            self._load_saved_controls(recording)
            self.holdoff.spin.setSpecialValueText("Недоступна")
            # The worker can publish READY before capture_ready in one drain.
            # A late final Auto result must replace the previously held window.
            if self.device_capture_mode == 2 or not self.device_acquiring:
                self.single = recording
                self.single_dirty = True
                self.mode = 1
                self._display(recording, reset=True)
            elif self.mode == 0 and not self.paused:
                self._display(recording, reset=self.display_recording is None, live=True)
            self._update_actions()
        self.device.accept(recording)

    def _device_state(self, state):
        snapshot = state.snapshot
        was_acquiring = self.device_acquiring
        self.device_acquiring = (state.start_pending or bool(snapshot and
            (snapshot.phase is Phase.ARMED or snapshot.stop_barrier)))
        # Stop finishes the current stream of independent windows. Keep its
        # last admitted full result, even if transport recovery followed it.
        if (self.device_active and was_acquiring and not self.device_acquiring
                and self.device_last is not None and self.device_capture_mode == 0):
            self.single = self.device_last
            self.single_dirty = True
            self.mode = 1
            self._display(self.single, reset=True)
        if state.close_failed:
            self._device_closing = False
        if self.device_panel:
            self.device_panel.update_state()
        self._update_actions()

    def _device_incomplete(self, result):
        self._device_error("Неполное окно сохранено в памяти. Сохраните исходные фрагменты в JSON.")
        self.device_info()
        self.device_panel.update_state()

    def _device_error(self, message):
        self.statusBar().showMessage(message)
        if self.device_panel:
            self.device_panel.error.setText(message)

    def save_device_fragments(self):
        result = self.device.pending_incomplete
        if result is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Новый файл неполных данных", "", "Диагностика (*.json)")
        if path:
            def done(_):
                self.device.acknowledge_incomplete(result)
                self.statusBar().showMessage("Исходные фрагменты сохранены: " + path)
            self._submit(lambda: self.device.save_incomplete(path, result), done)

    def _device_finished(self):
        self._device_shutdown = True
        if self._device_closing:
            self._device_closing = False
            QtCore.QTimer.singleShot(0, self.close)

    def _device_actions(self):
        state = self.device.state
        snapshot = state.snapshot
        running = self.device_acquiring or state.busy
        ready = (state.connected and snapshot and snapshot.phase is Phase.READY and not running
                 and not state.has_capture and not state.has_incomplete)
        for widget in (self.threshold, self.holdoff, self.rising, self.falling, self.pretrigger):
            widget.setEnabled(False)
        for widget in (self.scope_button, self.ignition_button, self.rename_button):
            widget.setEnabled(not running and self.mode == 0 and not self.busy)
        self.waveform_combo.setEnabled(not state.connected and not running and not state.has_incomplete
                                       and not state.has_capture and not self.busy)
        self.gap_button.setEnabled(False)
        self.units_combo.setEnabled(bool(self.display_recording and self.display_recording.input_profile.configured))
        self.tabs[1].setEnabled(not running and self.single is not None and not self.busy)
        self.tabs[2].setEnabled(not running and self.completed is not None and not self.busy)
        self.tabs[0].setEnabled(not self.busy and not running)
        self.record_button.setText("■  Остановить получение" if running else "▶  Получать окна")
        self.record_button.setEnabled(not self.busy and (bool(ready) or
            (self.device_acquiring and not (snapshot and snapshot.stop_barrier))))
        self.record_button.setToolTip("Отдельные окна; непрерывная запись STM32 пока недоступна.")
        self.single_button.setEnabled(bool(ready) and not self.busy)
        self.single_button.setText("◎  Один захват")
        self.save_button.setEnabled(self.mode == 1 and self.single is not None and not running and not self.busy)
        self.save_button.setText("Сохранить окно")
        self.open_button.setEnabled(not running and not self.busy)
        self.export_button.setEnabled(self.display_recording is not None and not self.busy)
        self.follow_button.setEnabled(not self.busy and self.device_last is not None)
        self.pause_button.setEnabled(self.mode == 0 and not self.busy)
        self.capture_note.setText("Порог и предыстория — в панели STM32. Аппаратного holdoff нет.")
        if snapshot and snapshot.capabilities:
            self.device_button.setText(f"STM32 · сборка {snapshot.capabilities.firmware_build}")
        else:
            self.device_button.setText("STM32 · подключение")
        if snapshot and snapshot.phase is Phase.RECOVERY:
            text = "Ошибка обмена · последнее полное окно"
        elif self.device_acquiring:
            text = "Ⅱ  Пауза просмотра" if self.paused else "◎  Получение / ожидание окна"
        elif state.busy:
            text = "Подключение…"
        else:
            text = "✓  Окно удержано" if self.device_last else "STM32 · готов" if ready else "STM32 · не подключён"
        self.state_label.setText(text)
        if self.device_panel:
            self.device_panel.update_state()
