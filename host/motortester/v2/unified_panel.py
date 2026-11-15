"""Persistent main-window workspace over the established stream lifecycle.

Selecting a device negotiates its actual capabilities without starting ADC.
The initial inert peer has no source; synthetic data require an explicit
Service action. A new owner is created only after the old owner has settled.
"""
from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from .input import UNKNOWN_PROFILE
from .stream_device import SerialStreamSelection, StreamContext, StreamDeviceBridge
from .stream_ui import StreamDialog


class UnifiedStreamPanel(StreamDialog):
    def __init__(self, parent=None, *, context=StreamContext(),
                 bridge_factory=StreamDeviceBridge, acquire_serial=None, release_serial=None):
        self.demo_enabled = False
        self._next_demo = False
        self._next_demo_profile = None
        self._pending_open = None
        self._file_display_owner = None
        self._assembled = False
        super().__init__(parent, context=context, bridge_factory=bridge_factory,
                         acquire_serial=acquire_serial, release_serial=release_serial)
        self.setWindowFlags(QtCore.Qt.WindowType.Widget)
        self.setMinimumSize(600, 500)
        # The legacy page creates these only with a preselected COM. Keep a
        # real, hidden set for its state API without inventing a device name.
        self.connect_button = QtWidgets.QPushButton('Подключить', self)
        self.connect_button.clicked.connect(self.connect_device)
        self.disconnect_button = QtWidgets.QPushButton('Отключить', self)
        self.disconnect_button.clicked.connect(self.disconnect_device)
        self.rate_combo = QtWidgets.QComboBox(self)
        for rate, bits in ((50_000, 12), (100_000, 12), (150_000, 10)):
            self.rate_combo.addItem(f'{rate // 1000} тыс. отсчётов/с · {bits} бит', rate)
        self.rate_combo.setCurrentIndex(1)
        self.assemble_main_view()
        self._state(self.bridge.state)

    def assemble_main_view(self):
        """Move the existing tools into one expanding plot, with no inner scroll."""
        if self._assembled:
            return
        self._assembled = True
        self._storage = QtWidgets.QWidget(self)
        self._storage.hide()
        layout = self.layout()

        def park(items):
            while items.count():
                item = items.takeAt(0)
                if item.widget() is not None:
                    item.widget().setParent(self._storage)
                elif item.layout() is not None:
                    park(item.layout())

        park(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        for widget in (self.connect_button, self.disconnect_button, self.rate_combo,
                       self.input_button, self.input_note, self.raw_view,
                       self.close_panel_button):
            widget.setParent(self._storage)
            widget.hide()

        def visible(widget):
            layout.addWidget(widget)
            widget.show()

        layout.addWidget(self.heading)
        self.heading.hide()
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(5)
        for button in (self.live_button, self.record_button, self.stop_button,
                       self.pause_button, self.open_button):
            toolbar.addWidget(button)
            button.show()
        layout.addLayout(toolbar)
        visible(self.state_label)
        visible(self.quality)
        visible(self.error_label)
        layout.addWidget(self.retry_context_button)
        self.retry_context_button.hide()
        visible(self.capture)

        # The viewer object retains its workers, mailbox and timers. Only its
        # visual content moves; shutdown is still owned by StreamDialog.close.
        self.viewer.scroll_area.takeWidget()
        self.viewer.hide()
        self.viewer.content.setParent(self)
        self.viewer.content.layout().setContentsMargins(0, 0, 0, 0)
        self.viewer.content.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetDefaultConstraint)
        self.viewer.plot.setMaximumHeight(16_777_215)
        self.viewer.plot.setMinimumHeight(200)
        self.viewer.plot.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                       QtWidgets.QSizePolicy.Policy.Expanding)
        layout.addWidget(self.viewer.content, 1)
        self.viewer.content.show()
        self.viewer.origin_label.setStyleSheet('border: none; padding: 0; color: #ffce68; font-size: 11px;')
        # Two short navigation messages share one line; neither is discarded.
        content_layout = self.viewer.content.layout()
        nav_index = content_layout.indexOf(self.viewer.navigation_label)
        content_layout.removeWidget(self.viewer.navigation_label)
        content_layout.removeWidget(self.viewer.view_mode_label)
        navigation = QtWidgets.QHBoxLayout()
        navigation.addWidget(self.viewer.navigation_label, 1)
        navigation.addWidget(self.viewer.view_mode_label)
        content_layout.insertLayout(nav_index, navigation)
        visible(self.measurement_label)
        self.measurement_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                            QtWidgets.QSizePolicy.Policy.Minimum)
        visible(self.event_frequency)
        self.event_frequency.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                          QtWidgets.QSizePolicy.Policy.Minimum)
        visible(self.ringdown)
        self.ringdown.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                   QtWidgets.QSizePolicy.Policy.Minimum)
        visible(self.cursors)
        self.cursors.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                   QtWidgets.QSizePolicy.Policy.Minimum)
        self.cursors.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        self.cursors.readout.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                           QtWidgets.QSizePolicy.Policy.Minimum)
        footer = QtWidgets.QHBoxLayout()
        self.ringdown.layout().removeWidget(self.ringdown.toggle)
        footer.addWidget(self.ringdown.toggle)
        self.ringdown.toggle.show()
        self.ringdown.toggle.toggled.connect(self._ringdown_visibility)
        self.ringdown.hide()
        footer.addWidget(self.export_button)
        self.export_button.setText('Экспорт записи CSV + JSON…')
        self.export_button.show()
        footer.addStretch(1)
        footer.addWidget(self.details)
        self.details.show()
        layout.addLayout(footer)
        layout.addWidget(self.notice)
        layout.addWidget(self.file_label)
        self._details(False)
        self._refresh_input_display()

    def _ringdown_visibility(self, enabled):
        # This optional analysis replaces the generic numerical readouts while
        # expanded; the graph, receiver and ordinary controls remain in place.
        self.measurement_label.setVisible(not enabled)
        self.event_frequency.setVisible(not enabled)
        self.ringdown.setVisible(enabled)
        self._compact_notes()

    def _refresh_input_display(self):
        # An unconfigured connector still has valid ADC codes. Keep the only
        # graph present and label those codes explicitly, without inventing a
        # volts-per-code scale or requiring another window to reveal the data.
        configured = self.active_input_profile.configured
        if not self._opening or self.archive is None:
            self._file_display_owner = None
        elif self.archive is not self._file_display_owner:
            # During asynchronous loading the context is temporarily unknown.
            # Its forced raw fallback must not override the file's own voltage
            # profile. Apply the default once; later raw toggles are explicit.
            self._file_display_owner = self.archive
            if configured:
                with QtCore.QSignalBlocker(self.raw_view):
                    self.raw_view.setChecked(False)
        if not configured and not self.raw_view.isChecked():
            with QtCore.QSignalBlocker(self.raw_view):
                self.raw_view.setChecked(True)
        super()._refresh_input_display()
        self.raw_view.setEnabled(configured)
        self.raw_view.setToolTip('Без профиля входа доступны только исходные коды АЦП; это не напряжение CH1.'
                                if not configured else
                                'Служебный просмотр исходных кодов. Сохранённая шкала CH1 не изменяется.')
        self.viewer.plot.show()
        self.cursors.show()

    def _details(self, visible):
        super()._details(visible)
        if hasattr(self, 'file_label'):
            self.file_label.setVisible(visible)
        if self._assembled:
            self.heading.setVisible(visible)
            self._compact_notes()

    def _compact_notes(self):
        details = self.details.isChecked()
        capture_instruction = self.capture.note.text().startswith('Одиночный захват: запустите')
        self.capture.note.setVisible(details or not capture_instruction)
        cursor_instruction = self.cursors.readout.text().startswith('Включите курсоры для измерения')
        self.cursors.readout.setVisible(details or not cursor_instruction)
        readout = self.cursors.readout
        # QLabel's wrapped two-line cursor text can arrive after the parent
        # layout's height negotiation. Reserve its measured text height so the
        # expanding plot yields space instead of clipping delta-t/delta-U.
        height = (max(readout.fontMetrics().height(), readout.heightForWidth(max(1, readout.width())))
                  if not readout.isHidden() and readout.text() else 0)
        if readout.minimumHeight() != height:
            readout.setMinimumHeight(height)
            self.cursors.updateGeometry()
        # Raw statistics now contain independent DC/period refusal reasons.
        # Reserve all wrapped lines instead of showing only the old Min/Max row.
        for label, lines in ((self.measurement_label, 4), (self.event_frequency, 2)):
            height = max(lines * label.fontMetrics().height(), label.heightForWidth(max(1, label.width())))
            if label.minimumHeight() == height:
                continue
            label.setMinimumHeight(height)
            label.updateGeometry()
            # Qt's wrapped-label layout item can retain its former one-line
            # height-for-width even after invalidate(). Replace only that item
            # when the text height changes, preserving the widget and signals.
            position = self.layout().indexOf(label)
            self.layout().removeWidget(label)
            self.layout().insertWidget(position, label)
            self.layout().activate()
        if self.ringdown.toggle.isChecked():
            label = self.ringdown.readout
            height = max(label.fontMetrics().height(), label.heightForWidth(max(1, label.width())))
            # An unconstrained QLabel sizeHint assumes a much narrower line
            # than the actual plot width. Using it for the body creates empty
            # vertical space and can push the plot's bottom axis out of view.
            # Reserve only the text at the current width plus the button row.
            label.setFixedHeight(height)
            body = self.ringdown.body
            height += body.layout().itemAt(0).sizeHint().height() + body.layout().spacing()
            body.setFixedHeight(height)
            if self.ringdown.minimumHeight() != height or self.ringdown.maximumHeight() != height:
                self.ringdown.setFixedHeight(height)
                self.ringdown.updateGeometry()
                position = self.layout().indexOf(self.ringdown)
                self.layout().removeWidget(self.ringdown)
                self.layout().insertWidget(position, self.ringdown)
                self.layout().activate()
        self.error_label.setVisible(bool(self.error_label.text()))

    def can_change_source(self):
        status = self.bridge.state
        return (not self.closed and not self._closing and not self.busy
                and not self.bridge.metadata_pending and self._record_picker is None
                and self.capture.picker is None and self.capture.prompt is None
                and not status.command_pending and not status.stop_pending
                and not status.can_retry_close and not status.worker_unresolved
                and not status.close_requested
                and (status.can_connect or status.can_open or
                     (status.ready and status.can_preview)))

    @property
    def busy(self):
        return super().busy or self._pending_open is not None

    def can_select_connection(self):
        return self.can_change_source()

    def connect_selection(self, selection):
        if type(selection) is not SerialStreamSelection:
            raise ValueError('Требуется выбранный COM-порт и частота приёма')
        selection.__post_init__()
        if not self.can_select_connection():
            return False
        if self.capture.dirty:
            self.capture.confirm_discard(lambda: self.connect_selection(selection))
            return False
        return self._replace_source(selection)

    def connect_device(self):
        if self.selection is None:
            return False
        return self.connect_selection(replace(self.selection,
            requested_sample_rate_hz=self.rate_combo.currentData()))

    def start_demo(self, ui_profile=None):
        """Explicit Service-only synthetic source; never reuse physical calibration."""
        if ui_profile not in (None, 'oscilloscope', 'ignition'):
            raise ValueError('Неизвестный профиль ДЕМО')
        if not self.can_change_source():
            return False
        if self.capture.dirty:
            self.capture.confirm_discard(lambda: self.start_demo(ui_profile))
            return False
        return self._replace_source(None, demo=True, demo_profile=ui_profile)

    def _replace_source(self, selection, *, demo=False, demo_profile=None):
        if not self.can_change_source():
            return False
        if (not self._opening and (self.demo_enabled or self.bridge.connection is not None)
                and self.search_editable() and
                self.prepare_search is not None and not self.prepare_search()):
            return False
        connection = self.bridge.connection
        if not demo and connection is not None and self.bridge.search_config is not None:
            caps = connection.observed_caps
            self._reconnect_search = (self.bridge.search_config,
                (caps[4], caps[8] if connection.protocol_revision == '0.3' else 12))
        elif demo:
            self._reconnect_search = None
        self._reconnect_selection = selection
        self._next_demo = demo
        self._next_demo_profile = demo_profile
        self._reconnecting = True
        self.capture.cancel('Ожидание отменено: смена источника')
        # shutdown may emit finished synchronously for the initial inert peer.
        self.bridge.shutdown()
        self._state(self.bridge.state)
        return True

    def _bridge_finished(self, bridge=None):
        if bridge is not None and bridge is not self.bridge:
            return
        if not self._reconnecting or self._closing:
            return super()._bridge_finished(bridge)
        old = self.bridge
        if self._serial_reserved and self._release_serial is not None:
            self._release_serial(self)
        self._serial_reserved = False
        self.selection = self._reconnect_selection
        self.demo_enabled = self._next_demo
        self.context = replace(self.context, input_profile=UNKNOWN_PROFILE, analog_snapshot=None,
                               ui_profile=self._next_demo_profile or self.context.ui_profile)
        options = {'selection': self.selection} if self.selection is not None else {}
        self.bridge = self._bridge_factory(self, context=self.context, **options)
        self._bind_bridge()
        old.deleteLater()
        self._reconnecting = False
        self._return_to_device = not self.demo_enabled
        if self.demo_enabled:
            self.raw_view.setChecked(True)
            self._live_notice = 'ДЕМО · искусственные исходные коды АЦП; напряжение CH1 не измеряется.'
            self.start_live()
        else:
            rate = self.selection.requested_sample_rate_hz or 100_000
            self.rate_combo.setCurrentIndex(self.rate_combo.findData(rate))
            self._connect_current_bridge()
        self._state(self.bridge.state)

    def start_live(self):
        if self.selection is None and not self.demo_enabled:
            return False
        return super().start_live()

    def record_dialog(self):
        if self.selection is None and not self.demo_enabled:
            return False
        return super().record_dialog()

    def record_path(self, path):
        if self.selection is None and not self.demo_enabled:
            return False
        return super().record_path(path)

    def open_dialog(self):
        if not self.can_change_source():
            return False
        return super().open_dialog()

    def open_path(self, path):
        status = self.bridge.state
        if self.capture.dirty:
            self.error_label.setText('Сначала сохраните отдельный захват или явно продолжите без сохранения.')
            return False
        if not self.can_change_source():
            return False
        if status.ready and status.can_preview and not status.can_open:
            # READY owns an open COM but has not started acquisition. Closing
            # that handle does not discard samples and needs no artificial
            # Live/Stop cycle. The actual file read waits for confirmed close.
            self._pending_open = str(path)
            if not self.bridge.disconnect_source():
                self._pending_open = None
                return False
            self._state(self.bridge.state)
            return True
        return super().open_path(path)

    def closeEvent(self, event):
        self._pending_open = None
        return super().closeEvent(event)

    def _state(self, status):
        super()._state(status)
        if (self._pending_open is not None and not self._closing and
                status.can_open and status.phase == 'disconnected' and
                status.serial is not None and status.serial.handle_settled and
                not status.serial_unresolved and not status.command_pending and
                not status.stop_pending and not status.worker_unresolved and
                not self.bridge.metadata_pending):
            path, self._pending_open = self._pending_open, None
            super().open_path(path)
        if self._pending_open is not None:
            self.state_label.setText('Порт не закрыт. Нажмите «Повторить закрытие порта», чтобы открыть запись.'
                                     if status.can_retry_close else
                                     'Закрытие соединения перед открытием записи…')
        elif (not self._closing and not self.busy and status.ready and status.can_preview
                and self.can_change_source()):
            self.open_button.setEnabled(True)
        if self._assembled:
            self._compact_notes()
        if self.selection is None and not self.demo_enabled:
            self.live_button.setEnabled(False)
            self.record_button.setEnabled(False)
            self.sync_button.setEnabled(False)
            if not self._opening and not self._closing and not self._reconnecting:
                self.heading.setText('CH1 · подключите STM32 или откройте запись')
                self.state_label.setText('Прибор не подключён')
                self.quality.setText('Данные ещё не получены.')
                self.viewer.origin_label.setText('НЕТ ДАННЫХ')
                self.notice.setText('Выберите COM-порт и частоту приёма в верхней строке, затем нажмите «Подключить».')

