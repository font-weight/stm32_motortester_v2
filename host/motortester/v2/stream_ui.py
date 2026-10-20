"""V2 streaming workspace: paced wire DEMO, bounded display, disk recording."""
from concurrent.futures import ThreadPoolExecutor

from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg

from ..gui_stream import LiveEventIndex, LiveSnapshot, StreamViewerPanel
from ..stream_controller import EVENT_CAPACITY
from ..stream_recording import AttemptReport
from .stream_device import StreamContext, StreamDeviceBridge
from .stream_files import open_stream, export_stream
from .widgets import STYLE


class StreamDialog(QtWidgets.QDialog):
    """One immutable channel/profile per workspace; no physical COM factory."""
    settled = QtCore.Signal()
    close_cancelled = QtCore.Signal()

    def __init__(self, parent=None, *, context=StreamContext(), bridge_factory=StreamDeviceBridge):
        super().__init__(parent)
        self.setWindowTitle("Мотортестер V2 · непрерывный приём")
        self.resize(1220, 870)
        self.setMinimumSize(850, 650)
        self.setStyleSheet(STYLE)
        self.context = context
        self.bridge = bridge_factory(self, context=context)
        self._revision = self._handle = None
        self._sent_view = None
        self._paused = self._closing = self.closed = False
        self._opening = False
        self._future = None
        self._operation = None
        self._context_prompting = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-stream-files")
        self.archive = self.verified_context = None
        self.saved_path = None
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel()
        self.heading.setObjectName("heading")
        self.heading.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.heading)
        self._heading(context)
        self.notice = QtWidgets.QLabel(
            "ДЕМО ПОТОКА · 50 000 отсчётов/с · CH1\n"
            "STM32 на COM6 пока передаёт отдельные окна. Для потока нужна другая проверенная прошивка.\n"
            "Шкала напряжения не настроена. Здесь проверяются передача и запись исходных кодов.")
        self._live_notice = self.notice.text()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        row = QtWidgets.QHBoxLayout()
        for name, text, action in (
            ("live_button", "Живой поток", self.start_live),
            ("record_button", "Начать запись…", self.record_dialog),
            ("stop_button", "Остановить", self.stop),
            ("pause_button", "Пауза просмотра", self.toggle_pause),
            ("open_button", "Открыть запись…", self.open_dialog),
        ):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(action)
            setattr(self, name, button)
            row.addWidget(button)
        layout.addLayout(row)
        self.state_label = QtWidgets.QLabel("Готово")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.raw_view = QtWidgets.QCheckBox("Показать служебные коды АЦП")
        self.raw_view.toggled.connect(self._raw_changed)
        layout.addWidget(self.raw_view)
        self.quality = QtWidgets.QLabel("Полнота данных ещё не определена.")
        self.quality.setWordWrap(True)
        layout.addWidget(self.quality)
        self.viewer = StreamViewerPanel(event_config=self.bridge.state.config)
        self.viewer.plot.setBackground("#081b25")
        self.viewer.curve.setPen(pg.mkPen("#ffe500", width=1.6))
        self.viewer.plot.setYRange(0, 4095, padding=0)
        self.viewer.plot.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                       QtWidgets.QSizePolicy.Policy.Ignored)
        self.viewer.plot.setLabel("left", "Код АЦП · шкала напряжения не настроена")
        self.viewer.open_button.hide()
        self.viewer.source_label.hide()
        self.viewer.index_label.hide()
        self.viewer.range_label.hide()
        self.viewer.status_label.hide()
        self.viewer.storage_label.hide()
        self.viewer.event_label.hide()
        self.viewer.previous_button.setToolTip("Пороговые события — только навигация, без диагноза и времени горения.")
        self.viewer.next_button.setToolTip(self.viewer.previous_button.toolTip())
        self.viewer.view_requested.connect(self._view_requested)
        self.viewer.plot.hide()
        layout.addWidget(self.viewer, 1)
        footer = QtWidgets.QHBoxLayout()
        self.export_button = QtWidgets.QPushButton("Экспорт открытой записи CSV + JSON…")
        self.export_button.clicked.connect(self.export_dialog)
        footer.addWidget(self.export_button)
        self.details = QtWidgets.QCheckBox("Технические сведения")
        self.details.toggled.connect(self._details)
        footer.addWidget(self.details)
        layout.addLayout(footer)
        self.file_label = QtWidgets.QLabel("Запись сохраняется сразу в файл. Пауза просмотра не останавливает запись.")
        self.file_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)
        self.error_label = QtWidgets.QLabel()
        self.error_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #ffce68")
        layout.addWidget(self.error_label)
        self.retry_context_button = QtWidgets.QPushButton("Повторить сохранение контекста записи")
        self.retry_context_button.clicked.connect(
            lambda: self.bridge.retry_context(self.bridge.metadata_error))
        self.retry_context_button.hide()
        layout.addWidget(self.retry_context_button)
        self.bridge.live_ready.connect(self._display)
        self.bridge.state_changed.connect(self._state)
        self.bridge.recording_ready.connect(self._saved)
        self.bridge.error.connect(self.error_label.setText)
        self.bridge.finished.connect(self._bridge_finished)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll_file)
        self._timer.start()
        self._state(self.bridge.state)

    @property
    def busy(self):
        return self._future is not None

    def _heading(self, context):
        profile = "Зажигание" if context.ui_profile == "ignition" else "Осциллограф"
        self.heading.setText(f"Непрерывный приём · {context.channel_name} · CH1 · {profile}")

    def _details(self, visible):
        for widget in (self.viewer.source_label, self.viewer.index_label,
                       self.viewer.range_label, self.viewer.status_label, self.viewer.storage_label,
                       self.viewer.event_label):
            widget.setVisible(visible)

    def _raw_changed(self, checked):
        self.viewer.plot.setVisible(checked)

    def _resume(self):
        self._paused = False
        self.pause_button.setText("Пауза просмотра")
        self.viewer._timer.start()

    def start_live(self):
        if self.busy or self._closing:
            return False
        accepted = self.bridge.start_live()
        if accepted:
            self.archive = self.verified_context = None
            self._opening = False
            self._revision = None
            self._resume()
            self.viewer._reset_source()
            self.quality.setText("Новый поток: ожидание данных; потери ещё неизвестны.")
            self.error_label.clear()
            self._heading(self.context)
            self.notice.setText(self._live_notice)
        return accepted

    def record_dialog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Новая потоковая запись", "", "Потоковая запись (*.mtstream)")
        if path:
            self.record_path(path)

    def record_path(self, path):
        if self.busy or self._closing:
            return False
        new_source = self.bridge.state.can_preview
        accepted = self.bridge.record(path)
        if accepted:
            self.archive = self.verified_context = None
            self._opening = False
            self.saved_path = None
            if new_source:
                self._revision = None
                self._resume()
                self.viewer._reset_source()
                self.quality.setText("Новая запись: ожидание данных; потери ещё неизвестны.")
            self.error_label.clear()
            self._heading(self.context)
            self.notice.setText(self._live_notice)
            self.file_label.setText("Запись в файл: " + str(path))
        return accepted

    def stop(self):
        return self.bridge.stop()

    def toggle_pause(self):
        self._paused = not self._paused
        self.pause_button.setText("Продолжить просмотр" if self._paused else "Пауза просмотра")
        if self._paused:
            self.viewer._timer.stop()
        else:
            self.viewer._timer.start()
            self.viewer.follow()

    def _display(self, result):
        if self._opening or self._closing:
            return
        source = result.source
        tail = {"running": "приём продолжается", "unknown": "полнота хвоста неизвестна",
                "reported_stopped": "источник сообщил об остановке"}[source.tail_state]
        loss = "неизвестны" if source.loss_samples is None else str(source.loss_samples)
        self.quality.setText(f"Потери по данным источника: {loss}; {tail}.")
        if self._revision != source.revision:
            self._revision = source.revision
            self._handle = self.viewer.begin_live(source.identity, event_config=source.config,
                                                  event_config_revision=source.config_revision)
            self.viewer.source_label.setText(
                "Программный источник → потоковый протокол 0.2 → проверка → файл и ограниченный обзор. "
                "COM-порт не используется. Частота времени номинальная.")
        if self._paused:
            return
        index = LiveEventIndex(self._handle, source.sequence, source.config_revision,
                               source.config, source.events, source.detector, EVENT_CAPACITY)
        snapshot = LiveSnapshot(source.identity, source.sequence, source.first, source.end,
                                result.envelope, source.loss_samples, source.tail_state,
                                source.flags, source.raw_first, index)
        self.viewer.post_live_snapshot(self._handle, snapshot)

    def _view_requested(self, selection):
        QtCore.QTimer.singleShot(0, self._publish_view)

    def _publish_view(self):
        selection = self.viewer.selection
        if self._revision is not None and selection is not None and not self._opening and not self._closing:
            key = (self._revision, selection.start, selection.stop, self.viewer.follow_tail)
            if key != self._sent_view:
                self.bridge.controller.request_view(self._revision, selection.start, selection.stop,
                                                     follow=self.viewer.follow_tail)
                self._sent_view = key

    def _state(self, status):
        self._publish_view()
        idle = not self._closing and not self.busy and not self.bridge.metadata_pending
        self.live_button.setEnabled(idle and status.can_preview)
        self.record_button.setEnabled(idle and status.can_record)
        self.open_button.setEnabled(idle and status.can_open)
        self.stop_button.setEnabled(not self._closing and not status.can_open)
        self.pause_button.setEnabled(not self._closing and not self._opening and self._revision is not None)
        self.export_button.setEnabled(idle and self.archive is not None and
                                      not isinstance(self.archive, AttemptReport))
        phases = {"idle": "Готово", "preview": "Живой поток", "recording": "Идёт запись",
                  "saved": "Запись завершена", "preview stopped": "Поток остановлен",
                  "negotiating": "Согласование", "starting preview": "Запуск потока",
                  "preparing": "Подготовка файла", "waiting for boundary": "Ожидание начала записи",
                  "draining": "Завершение записи", "fault": "Поток прерван",
                  "closed": "Закрыто", "closing": "Закрытие",
                  "stopped without R": "Нет отсчётов записи", "error": "Ошибка"}
        text = phases.get(status.phase, status.phase)
        if self._closing:
            text = "Завершение потока и сохранение файла перед закрытием…"
        elif self.busy:
            text = "Проверка файла…" if self._operation == "open" else "Экспорт…"
        elif self.bridge.metadata_pending and status.can_open:
            text = "Сохранение контекста записи…"
        elif self._opening:
            text = "Просмотр открытой записи"
        if self._opening:
            count = 0 if self.archive is None or isinstance(self.archive, AttemptReport) else (
                self.archive.end_sample_index - self.archive.first_sample_index)
            text += f" · В открытом файле: {count:,} отсчётов".replace(",", " ")
        else:
            text += f" · Получено: {status.validated_samples:,} отсчётов".replace(",", " ")
        if self._paused:
            text += " · Просмотр на паузе"
        if not self._opening and status.bridge and status.bridge.session and status.bridge.session.first_failure:
            failure = status.bridge.session.first_failure
            text += f" · НЕПОЛНЫЕ ДАННЫЕ: {failure.code}"
        self.state_label.setText(text)
        failure = self.bridge.metadata_error
        self.retry_context_button.setVisible(failure is not None and not self._closing)
        if self._closing and failure is not None and not self._context_prompting:
            self._context_prompting = True
            QtCore.QTimer.singleShot(0, lambda: self._resolve_context_error(failure))

    def _resolve_context_error(self, failure):
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("Контекст записи не сохранён")
        dialog.setText(
            "Файлы записи не удаляются. Не удалось сохранить имя канала и профиль.\n" +
            str(failure))
        retry = dialog.addButton("Повторить", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        abandon = dialog.addButton("Закрыть без контекста", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton("Отмена", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        self._context_prompting = False
        if dialog.clickedButton() is retry:
            self.bridge.retry_context(failure)
        elif dialog.clickedButton() is abandon:
            self.bridge.abandon_context(failure)
        else:
            self._closing = False
            self.bridge.cancel_shutdown()
            self.close_cancelled.emit()

    def _saved(self, path):
        self.saved_path = path
        self.file_label.setText("Файл закрыт: " + path +
                               "\nХраните вместе с соседним файлом .v2.json. Полнота указана в сведениях записи.")

    def open_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Открыть потоковую запись", "", "Потоковая запись (*.mtstream)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        if self.busy or self._closing or self.bridge.metadata_pending or not self.bridge.controller.claim_open():
            return False
        self._opening = True
        self._revision = self._handle = None
        self.archive = self.verified_context = None
        self._resume()
        self.viewer._reset_source()
        self.viewer.source_label.clear()
        self.quality.setText("Проверка открываемой записи…")
        self.error_label.clear()
        self._operation = "open"
        self._future = self._executor.submit(open_stream, path)
        return True

    def export_dialog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Экспорт всей открытой записи", "", "CSV (*.csv)")
        if path:
            self.export_path(path)

    def export_path(self, path):
        if self.busy or self._closing or self.archive is None or isinstance(self.archive, AttemptReport):
            return False
        self._operation = "export"
        self._future = self._executor.submit(export_stream, path, self.archive, self.verified_context)
        return True

    def _poll_file(self):
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        try:
            result = future.result()
            if self._operation == "open":
                self.verified_context, archive = result
                self.archive = archive.recording if isinstance(archive, AttemptReport) and archive.recording else archive
                self.viewer._accept_archive(archive)
                rec = self.archive
                if isinstance(rec, AttemptReport):
                    self.quality.setText("Нет подтверждённых отсчётов. Полнота записи неизвестна.")
                else:
                    terminal = rec.terminal
                    loss = "неизвестны" if terminal is None or terminal.loss_samples is None else str(terminal.loss_samples)
                    state = ("Источник сообщил о полном завершении" if rec.clean_stop_reported else
                             "НЕПОЛНЫЕ ДАННЫЕ · полнота хвоста не подтверждена")
                    self.quality.setText(f"{state}. Потери по записи: {loss}.")
                self._heading(self.verified_context.context)
                self.notice.setText(
                    "ОТКРЫТАЯ ПОТОКОВАЯ ЗАПИСЬ · происхождение указано над графиком.\n"
                    "Шкала напряжения не настроена. Отображаются только исходные коды; время номинальное.")
                if not self.verified_context.companion_present:
                    self.error_label.setText("Файл контекста отсутствует: имя и профиль неизвестны; шкала не настроена.")
            else:
                self.file_label.setText("Экспорт завершён: " + result)
        except Exception as exc:
            self.error_label.setText("Ошибка файла: " + str(exc))
            if self._closing:
                self._closing = False
                self.close_cancelled.emit()
        if self._closing:
            self.bridge.shutdown()
        self._state(self.bridge.state)

    def _bridge_finished(self):
        self.viewer.shutdown()
        self._timer.stop()
        self._executor.shutdown(wait=False)
        self.closed = True
        self.settled.emit()
        self.close()

    def closeEvent(self, event):
        if self.closed:
            event.accept()
            return
        self._closing = True
        self._state(self.bridge.state)
        if not self.busy:
            self.bridge.shutdown()
        event.ignore()

    def reject(self):
        # Esc must take the same asynchronous Stop/drain path as the close icon.
        self.close()
