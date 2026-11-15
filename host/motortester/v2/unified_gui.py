"""One persistent CH1 workspace; hardware and DEMO both require explicit intent."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .inline_input import InlineAnalogControls
from .legacy_view import LegacyRecordingView
from .storage import load
from .stream_device import SerialStreamSelection, StreamDeviceBridge
from .stream_search_ui import StreamSearchControls
from .unified_panel import UnifiedStreamPanel
from .widgets import Knob, STYLE


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, *, settings_path=None, bridge_factory=StreamDeviceBridge,
                 port_provider=None):
        super().__init__()
        self.setWindowTitle('Мотортестер V2')
        self.resize(1440, 940)
        self.setMinimumSize(1120, 700)
        self.setStyleSheet(STYLE)
        self._syncing = False
        self._closing = False
        self._display_key = None
        self._port_provider = port_provider
        self._settings = (QtCore.QSettings(str(settings_path), QtCore.QSettings.Format.IniFormat)
                          if settings_path else QtCore.QSettings('MotortesterV2', 'Desktop'))
        self._legacy_future = None
        self._file_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='legacy-file')
        self._legacy_source_token = None
        self._stream_open_requested = None
        self._ringdown_demo_directory = None
        root = QtWidgets.QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel('∿  МОТОРТЕСТЕР')
        title.setStyleSheet('font-size:22px; font-weight:700')
        header.addWidget(title)
        header.addStretch(1)
        self.source_badge = QtWidgets.QLabel('Прибор не подключён')
        header.addWidget(self.source_badge)
        self.open_button = QtWidgets.QPushButton('Открыть запись…')
        self.open_button.clicked.connect(self.open_dialog)
        header.addWidget(self.open_button)
        shot = QtWidgets.QPushButton('Снимок')
        shot.clicked.connect(self.save_screenshot)
        header.addWidget(shot)
        self.service_button = QtWidgets.QPushButton('Сервис')
        self.service_menu = QtWidgets.QMenu(self.service_button)
        self.service_button.setMenu(self.service_menu)
        header.addWidget(self.service_button)
        layout.addLayout(header)
        connections = QtWidgets.QHBoxLayout()
        connections.setSpacing(8)
        layout.addLayout(connections)
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)
        self.panel = UnifiedStreamPanel(self, bridge_factory=bridge_factory)
        self.panel.setStyleSheet('')
        self.panel.open_button.hide()
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.panel)
        self.legacy = LegacyRecordingView()
        self.stack.addWidget(self.legacy)
        self.legacy.changed.connect(self.sync_knobs)
        body.addWidget(self.stack, 1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(364)
        self.sidebar = QtWidgets.QWidget()
        self.sidebar.setObjectName('sidecontent')
        self.sidebar.setStyleSheet('QPushButton { padding: 5px 7px; } QToolButton { background:#192d3a; border:1px solid #345063; border-radius:4px; padding:4px; }')
        side = QtWidgets.QVBoxLayout(self.sidebar)
        side.setContentsMargins(10, 8, 10, 8)
        side.setSpacing(7)
        scroll.setWidget(self.sidebar)
        body.addWidget(scroll)
        connections.addWidget(QtWidgets.QLabel('STM32'))
        ports = QtWidgets.QHBoxLayout()
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.port_combo.lineEdit().setPlaceholderText('COM-порт')
        self.port_combo.setMinimumWidth(80)
        ports.addWidget(self.port_combo, 1)
        self.refresh_button = QtWidgets.QPushButton('Обновить')
        self.refresh_button.clicked.connect(self.refresh_ports)
        ports.addWidget(self.refresh_button)
        connections.addLayout(ports, 1)
        self.rate_combo = QtWidgets.QComboBox()
        for rate, bits in ((50_000, 12), (100_000, 12), (150_000, 10)):
            self.rate_combo.addItem(f'{rate // 1000} тыс. отсчётов/с · {bits} бит', rate)
        self.rate_combo.setCurrentIndex(1)
        connections.addWidget(self.rate_combo, 1)
        connection = QtWidgets.QHBoxLayout()
        self.connect_button = QtWidgets.QPushButton('Подключить')
        self.disconnect_button = QtWidgets.QPushButton('Отключить')
        self.connect_button.clicked.connect(self.connect_device)
        self.disconnect_button.clicked.connect(self.panel.disconnect_device)
        connection.addWidget(self.connect_button)
        connection.addWidget(self.disconnect_button)
        connections.addLayout(connection, 1)
        self.connection_note = QtWidgets.QLabel('')
        self.connection_note.setWordWrap(True)
        self.connection_note.setStyleSheet('color:#ffcb66')
        layout.insertWidget(2, self.connection_note)
        self.input_controls = InlineAnalogControls()
        self.input_controls.bind_panel(self.panel)
        input_layout = self.input_controls.layout()
        input_layout.removeWidget(self.input_controls.details_toggle)
        input_layout.removeWidget(self.input_controls.calibration_button)
        input_row = QtWidgets.QHBoxLayout()
        self.input_controls.details_toggle.setText('Настройка входа')
        input_row.addWidget(self.input_controls.details_toggle, 1)
        input_row.addWidget(self.input_controls.calibration_button)
        input_layout.insertLayout(0, input_row)
        side.addWidget(self.input_controls)
        channel = QtWidgets.QHBoxLayout()
        channel.addWidget(QtWidgets.QLabel('CH1'))
        self.channel_name = QtWidgets.QLineEdit(str(self._settings.value('channel_name', 'Канал 1'))[:80])
        self.channel_name.setMaxLength(80)
        self.channel_name.setPlaceholderText('Имя канала')
        self.channel_name.editingFinished.connect(self._commit_channel)
        channel.addWidget(self.channel_name, 1)
        side.addLayout(channel)
        profile_row = QtWidgets.QHBoxLayout()
        self.profile_buttons = {}
        for key, label in (('oscilloscope', 'Осциллограф'), ('ignition', 'Зажигание')):
            button = QtWidgets.QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=key: self.change_profile(value))
            self.profile_buttons[key] = button
            profile_row.addWidget(button)
        side.addLayout(profile_row)
        units = QtWidgets.QHBoxLayout()
        self.units = QtWidgets.QComboBox()
        self.units.addItems(('В', 'мВ'))
        self.units.setAccessibleName('Единицы напряжения')
        self.units.setMaximumWidth(75)
        self.units.currentTextChanged.connect(self._unit_changed)
        units.addWidget(self.units)
        side.addLayout(units)
        self.raw_view = QtWidgets.QCheckBox('Показать коды АЦП')
        units.insertWidget(0, self.raw_view, 1)
        self.raw_view.show()
        self.raw_view.toggled.connect(self._raw_changed)
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(5)
        self.sweep = Knob('Развёртка', .00002, 360, .002, .001, 'мс/дел', logarithmic=True)
        self.sweep.set_display(1000, 'мс/дел')
        self.yscale = Knob('Масштаб Y', 1, 4096, 512, 1, 'код/дел', logarithmic=True)
        self.xposition = Knob('Положение X', 0, 3600, 0, .002, 'мс')
        self.xposition.set_display(1000, 'мс')
        self.yposition = Knob('Положение Y', 0, 4095, 2048, 1, 'код')
        for i, knob in enumerate((self.sweep, self.yscale, self.xposition, self.yposition)):
            grid.addWidget(knob, i // 2, i % 2)
            knob.changed.connect(self.view_changed)
        side.addLayout(grid)
        self.search = StreamSearchControls(self.panel)
        for knob in (self.sweep, self.yscale, self.xposition, self.yposition,
                     self.search.threshold, self.search.holdoff):
            knob.dial.setFixedSize(64, 64)
        side.addWidget(self.search)
        autos = QtWidgets.QHBoxLayout()
        self.auto_button = QtWidgets.QPushButton('Автомасштаб')
        self.full_button = QtWidgets.QPushButton('Весь сигнал')
        self.auto_button.clicked.connect(self.auto_scale)
        self.full_button.clicked.connect(self.full_signal)
        autos.addWidget(self.auto_button)
        autos.addWidget(self.full_button)
        side.addLayout(autos)
        side.addStretch(1)
        self.service_menu.addAction('Калибровка входа DC / AC…', self.open_calibration)
        self.demo_menu = self.service_menu.addMenu('ДЕМО для проверки')
        for key, text in (('oscilloscope', 'Осциллограф'), ('ignition', 'Зажигание')):
            self.demo_menu.addAction(text, lambda value=key: self.panel.start_demo(value))
        self.demo_menu.addAction('Затухающие колебания · учебная запись', self.open_ringdown_example)
        self.service_menu.aboutToShow.connect(self._refresh)
        self.panel.input_changed.connect(self._input_changed)
        self.panel.viewer.plot_drawn.connect(self.sync_knobs)
        self.panel.viewer.plot.getViewBox().sigRangeChangedManually.connect(lambda *_: self.sync_knobs())
        self.panel.settled.connect(self._settled)
        self.panel.close_cancelled.connect(self._close_cancelled)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(100)
        self.refresh_ports()
        self._commit_channel()
        self._input_changed()
        self._refresh()

    def refresh_ports(self):
        """List names only; discovery neither opens a port nor starts acquisition."""
        current = self.port_combo.currentText().strip()
        try:
            if self._port_provider is None:
                from serial.tools.list_ports import comports
                names = [port.device for port in comports()]
            else:
                names = list(self._port_provider())
            with QtCore.QSignalBlocker(self.port_combo):
                self.port_combo.clear()
                self.port_combo.addItems(names)
                if current:
                    self.port_combo.setCurrentText(current)
                elif len(names) != 1:
                    self.port_combo.setCurrentIndex(-1)
            self.connection_note.clear()
        except Exception as exc:
            self.connection_note.setText('Не удалось обновить список портов: ' + str(exc))

    def connect_device(self):
        try:
            port = self.port_combo.currentText().strip()
            if not port:
                raise ValueError('Выберите COM-порт.')
            self._commit_channel()
            selection = SerialStreamSelection(port, requested_sample_rate_hz=self.rate_combo.currentData())
            if self.panel.connect_selection(selection):
                self.connection_note.clear()
        except (ValueError, RuntimeError) as exc:
            self.connection_note.setText(str(exc))
        self._refresh()

    def _context_editable(self):
        return not self.legacy_active and self._legacy_future is None and not self.panel._opening and self.panel.can_change_source()

    def _commit_channel(self):
        if self._context_editable():
            name = self.channel_name.text().strip() or 'Канал 1'
            context = replace(self.panel.bridge.context, channel_name=name)
            self.panel.context = self.panel.bridge.context = context
            self._settings.setValue('channel_name', name)
            self.panel._heading(context)

    def change_profile(self, value):
        if value not in self.profile_buttons or not self._context_editable():
            return
        context = replace(self.panel.bridge.context, ui_profile=value)
        self.panel.context = self.panel.bridge.context = context
        self.panel._heading(context)
        self._refresh()

    def _refresh(self):
        if self.panel.closed:
            return
        if self._legacy_future is not None and self._legacy_future.done():
            future, self._legacy_future = self._legacy_future, None
            try:
                recording, path = future.result()
                self.legacy.load_recording(recording, path=path)
                self._legacy_source_token = id(self.panel.bridge)
                self.stack.setCurrentWidget(self.legacy)
                self._display_key = None
                self._input_changed()
                self.sync_knobs()
                self.connection_note.clear()
            except Exception as exc:
                self.connection_note.setText('Не удалось открыть запись: ' + str(exc))
            if self._closing:
                self.panel.close()
        if (self.legacy_active and id(self.panel.bridge) != self._legacy_source_token
                and ((self.panel.bridge.state.ready and self.panel.bridge.connection is not None)
                     or (self.panel.demo_enabled and self.panel.bridge.state.phase == 'preview'))):
            self.stack.setCurrentWidget(self.panel)
            self._display_key = None
        if self._stream_open_requested is not None and not self.panel.busy:
            if self.panel.archive is not self._stream_open_requested and self.panel._opening:
                self.stack.setCurrentWidget(self.panel)
                self._display_key = None
            self._stream_open_requested = None
        can_connect = self.panel.can_select_connection() and self._legacy_future is None
        for widget in (self.port_combo, self.rate_combo, self.refresh_button, self.connect_button):
            widget.setEnabled(can_connect and not self._closing)
        self.disconnect_button.setEnabled(self.panel.selection is not None and
                                         self.panel.disconnect_button.isEnabled() and not self._closing)
        self.disconnect_button.setText(self.panel.disconnect_button.text())
        self.demo_menu.setEnabled(can_connect and not self._closing)
        self.open_button.setEnabled(can_connect and not self._closing)
        context = self.legacy.recording if self.legacy_active else self.panel.active_context
        editable = self._context_editable()
        self.channel_name.setEnabled(editable)
        if not self.channel_name.hasFocus():
            self.channel_name.setText(context.channel_name)
        for key, button in self.profile_buttons.items():
            button.setChecked(key == context.ui_profile)
            button.setEnabled(editable)
        if self.panel._opening or self.legacy_active:
            badge = 'Открытая запись'
        elif self.panel.demo_enabled:
            badge = 'ДЕМО · искусственный сигнал'
        elif self.panel.bridge.connection is not None:
            badge = 'STM32 · ' + self.panel.selection.port
        else:
            badge = 'Прибор не подключён'
        self.source_badge.setText(badge)
        if self.legacy_active and self.panel.error_label.text():
            self.connection_note.setText(self.panel.error_label.text())
        self.connection_note.setVisible(bool(self.connection_note.text()))
        self.input_controls.setVisible(not self.legacy_active)
        if not self.legacy_active:
            self.input_controls.refresh()
        self.search.setVisible(not self.legacy_active)
        has_data = self.legacy_active or self.panel.viewer.selection is not None
        for widget in (self.sweep, self.yscale, self.xposition, self.yposition,
                       self.auto_button, self.full_button):
            widget.setEnabled(has_data)
        self._input_changed()

        # Cursor workers can complete after the source's last state signal.
        # Reflow their readout even while a saved file is otherwise idle.
        self.panel._compact_notes()

    def _input_changed(self):
        if not hasattr(self, 'yscale'):
            return
        profile = self.legacy.recording.input_profile if self.legacy_active else self.panel.active_input_profile
        raw = not profile.configured or not (self.legacy.voltage_display if self.legacy_active else self.panel.viewer.voltage_display)
        unit = self.units.currentText()
        key = (profile, raw, unit, self.legacy_active)
        if key != self._display_key:
            self._display_key = key
            factor = 1 if raw or unit == 'В' else 1000
            unit = 'код' if raw else unit
            extent = 4096 if raw else max(100, abs(profile.voltage(0)), abs(profile.voltage(4095))) * 2
            self.yscale.set_bounds(1 if raw else .000001, extent)
            self.yposition.set_bounds(0 if raw else -extent, 4095 if raw else extent)
            self.yscale.set_display(factor, unit + '/дел')
            self.yposition.set_display(factor, unit)
            for knob in (self.yscale, self.yposition):
                with QtCore.QSignalBlocker(knob.spin):
                    knob.spin.setDecimals(0 if raw else 1 if unit == 'мВ' else 3)
            with QtCore.QSignalBlocker(self.search.threshold.spin):
                self.search.threshold.spin.setDecimals(0 if raw else 1 if unit == 'мВ' else 4)
            self.units.setEnabled(profile.configured)
            self.raw_view.setEnabled(profile.configured)
            with QtCore.QSignalBlocker(self.raw_view):
                self.raw_view.setChecked(raw)
            self.sync_knobs()

    def sync_knobs(self):
        if self.legacy_active:
            xr, yr = self.legacy.plot.viewRange()
            self.sweep.set_bounds(.00002, max(360, (xr[1] - xr[0]) / 10))
            self.sweep.set_value((xr[1] - xr[0]) / 10)
            self.xposition.set_bounds(0, max(3600, xr[1]))
            self.xposition.set_value(max(0, xr[0]))
            self.yposition.set_value(sum(yr) / 2)
            self.yscale.set_value(max(self.yscale.low, (yr[1] - yr[0]) / 8))
            return
        viewer = self.panel.viewer
        selection, identity = viewer.selection, viewer._identity
        if selection is None or identity is None or viewer._first is None:
            return
        self._syncing = True
        try:
            fs = identity[3]
            duration = max(0, viewer._end - viewer._first) / fs
            self.xposition.set_bounds(0, max(3600, duration))
            self.sweep.set_bounds(.00002, max(360, duration / 10))
            self.sweep.set_value(selection.width / fs / 10)
            self.xposition.set_value(max(0, selection.start - viewer._first) / fs)
            lower, upper = viewer.plot.viewRange()[1]
            self.yposition.set_value((lower + upper) / 2)
            self.yscale.set_value(max(self.yscale.low, (upper - lower) / 8))
        finally:
            self._syncing = False

    def view_changed(self, *_):
        if self._syncing or (not self.legacy_active and self.panel.viewer.selection is None):
            return
        sender = self.sender()
        time_change = sender in (self.sweep, self.xposition)
        if time_change:
            self.panel.capture.cancel()
        view = self.legacy if self.legacy_active else self.panel
        view.apply_scope_view(seconds_per_div=self.sweep.value,
            x_start_s=self.xposition.value, y_center=self.yposition.value,
            codes_per_div=self.yscale.value,
            follow_tail=self.panel.viewer.follow_tail and sender is not self.xposition,
            change_time=time_change, sync_sweep=sender is self.sweep)

    def auto_scale(self):
        if self.legacy_active:
            self.legacy.auto_scale()
            self.sync_knobs()
            return
        import numpy as np
        values = self.panel.viewer.curve.getData()[1]
        if values is None:
            return
        finite = values[np.isfinite(values)]
        if not len(finite):
            return
        lo, hi = float(finite.min()), float(finite.max())
        self.yposition.set_value((lo + hi) / 2)
        self.yscale.set_value(max(self.yscale.low, (hi - lo) * 1.15 / 8))
        self.view_changed()

    @property
    def legacy_active(self):
        return hasattr(self, 'stack') and self.stack.currentWidget() is self.legacy

    def full_signal(self):
        if self.legacy_active:
            self.legacy.full_signal()
        else:
            viewer = self.panel.viewer
            self.panel.capture.cancel()
            viewer.set_event_sync(False)
            if viewer._recording is not None:
                viewer.show_whole_recording()
            elif viewer._raw_first is not None and viewer._end > viewer._raw_first:
                viewer.select_range(viewer._raw_first, viewer._end, hold_live=False, follow_tail=True)
        self.sync_knobs()

    def _unit_changed(self, unit):
        self.panel.set_voltage_unit(unit)
        self.legacy.set_voltage_unit(unit)
        self._input_changed()

    def _raw_changed(self, checked):
        if self.legacy_active:
            self.legacy.set_raw(checked)
        else:
            self.panel.raw_view.setChecked(checked)
        self._input_changed()

    def open_dialog(self):
        if not self.panel.can_change_source() or self._legacy_future is not None:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Открыть запись', '',
            'Записи (*.mtstream *.mtshot *.mtv2 *.mtcap);;Все файлы (*)')
        if path:
            self.open_path(path)

    def open_path(self, path):
        if not self.panel.can_change_source() or self._legacy_future is not None:
            return False
        if self.panel.capture.dirty:
            self.panel.capture.confirm_discard(lambda: self.open_path(path))
            return False
        if Path(path).suffix.lower() in ('.mtv2', '.mtcap'):
            def read():
                return load(path), Path(path)
            self._legacy_future = self._file_worker.submit(read)
            self.connection_note.setText('Открытие записи…')
        else:
            previous = self.panel.archive
            self.panel.open_path(path)
            self._stream_open_requested = previous if previous is not None else False
        self._refresh()
        return True

    def open_calibration(self):
        self.input_controls.open_calibration()

    def open_ringdown_example(self):
        if not self.panel.can_change_source() or self._legacy_future is not None:
            return False
        from .ringdown_examples import write_capture
        directory = self._ringdown_demo_directory
        if directory is None:
            directory = QtCore.QTemporaryDir()
            if not directory.isValid():
                self.connection_note.setText('Не удалось создать учебный пример.')
                return False
            write_capture(Path(directory.path()) / 'Учебные колебания.mtshot')
            # One immutable temporary source; keep it alive for background reads.
            self._ringdown_demo_directory = directory
        path = Path(directory.path()) / 'Учебные колебания.mtshot'
        return self.open_path(path)

    def save_screenshot(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Снимок', 'Мотортестер.png', 'PNG (*.png)')
        if path and not self.grab().save(str(Path(path).with_suffix('.png'))):
            self.connection_note.setText('Не удалось сохранить снимок.')

    def closeEvent(self, event):
        if self.panel.closed:
            self._timer.stop()
            self.legacy.close()
            self._file_worker.shutdown(wait=False)
            event.accept()
            return
        self._closing = True
        if self._legacy_future is None:
            self.panel.close()
        event.ignore()

    def _close_cancelled(self):
        self._closing = False
        self._refresh()

    def _settled(self):
        self._timer.stop()
        QtCore.QTimer.singleShot(0, self.close)
