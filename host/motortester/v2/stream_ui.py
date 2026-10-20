"""V2 streaming workspace: explicit serial or DEMO, bounded display and disk."""
from concurrent.futures import ThreadPoolExecutor

from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg

from ..gui_stream import LiveEventIndex, LiveSnapshot, StreamViewerPanel
from ..stream_controller import EVENT_CAPACITY
from ..stream_recording import AttemptReport
from .stream_device import StreamContext, StreamDeviceBridge
from .stream_files import open_stream, export_stream
from .widgets import STYLE


STOPPED_UNKNOWN = "Остановлено по команде · полнота хвоста неизвестна"


class StreamDialog(QtWidgets.QDialog):
    """One immutable channel/profile/port; connect never starts acquisition."""
    settled = QtCore.Signal()
    close_cancelled = QtCore.Signal()

    def __init__(self, parent=None, *, context=StreamContext(), bridge_factory=StreamDeviceBridge,
                 selection=None, acquire_serial=None, release_serial=None):
        super().__init__(parent)
        self.setWindowTitle("Мотортестер V2 · непрерывный приём")
        self.resize(1220, 870)
        self.setMinimumSize(850, 650)
        self.setStyleSheet(STYLE)
        self.context = context
        self.bridge = bridge_factory(self, context=context,
                                     **({"selection": selection} if selection is not None else {}))
        self.selection = selection
        self._acquire_serial = acquire_serial
        self._release_serial = release_serial
        self._serial_reserved = False
        self._revision = self._handle = None
        self._sent_view = None
        self._paused = self._closing = self.closed = False
        self._opening = False
        self._future = None
        self._operation = None
        self._context_prompting = False
        self._record_picker = None
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
            ("ДЕМО ПОТОКА · 50 000 отсчётов/с · CH1\n"
             "Программный источник; COM-порт не используется.\n" if selection is None else
             f"STM32 · {selection.port} · CH1 · потоковый протокол 0.2\n"
             "Сначала подключитесь и дождитесь проверки возможностей, затем запустите поток.\n") +
            "Шкала напряжения не настроена. Здесь проверяются передача и запись исходных кодов.")
        self._live_notice = self.notice.text()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.connect_button = self.disconnect_button = None
        if selection is not None:
            connection_row = QtWidgets.QHBoxLayout()
            self.connect_button = QtWidgets.QPushButton(f"Подключить {selection.port}")
            self.connect_button.clicked.connect(self.connect_device)
            self.disconnect_button = QtWidgets.QPushButton("Отключить")
            self.disconnect_button.clicked.connect(self.disconnect_device)
            connection_row.addWidget(self.connect_button)
            connection_row.addWidget(self.disconnect_button)
            layout.addLayout(connection_row)
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
        self.viewer.source_label.setText(
            "Источник и параметры появятся после запуска потока или открытия записи.")
        self.viewer.status_label.setText("Ожидание потока или открытия записи")
        self.viewer.plot.setBackground("#081b25")
        self.viewer.curve.setPen(pg.mkPen("#ffe500", width=1.6))
        self.viewer.plot.setYRange(0, 4095, padding=0)
        self.viewer.plot.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                       QtWidgets.QSizePolicy.Policy.Ignored)
        # The unknown voltage scale is explained above the plot. Keep axis
        # labels short enough for the minimum-height graph and narrow window.
        self.viewer.plot.setLabel("left", "Код АЦП")
        self.viewer.plot.setLabel("bottom", "Время, с · номинально")
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
        self.file_label = QtWidgets.QLabel(
            "Выберите новое имя файла: существующие записи не заменяются. "
            "Пауза просмотра не останавливает запись.")
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

    def connect_device(self):
        if self.selection is None or self._closing or self.busy:
            return False
        if not self._serial_reserved:
            if self._acquire_serial is not None and not self._acquire_serial(self, self.selection.port):
                self.error_label.setText(
                    "Порт занят оконным режимом STM32. Отключите его в панели подключения.")
                return False
            self._serial_reserved = True
        if not self.bridge.connect_source():
            self.error_label.setText("Подключение сейчас недоступно. Проверьте состояние порта.")
            return False
        self.error_label.clear()
        return True

    def disconnect_device(self):
        if self.bridge.state.can_retry_close:
            return self.bridge.retry_close()
        return self.bridge.disconnect_source()

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
        if self._record_picker is not None or self.busy or self._closing:
            return False
        before = self.bridge.state
        if not before.can_record or self.bridge.metadata_pending:
            self.error_label.setText("Запись сейчас недоступна. Дождитесь завершения текущей операции.")
            return False
        picker = QtWidgets.QFileDialog(self)
        # Windows' native modal picker suspends Qt timers. Keep the regular
        # event loop (including the latest-only viewer) running while choosing.
        picker.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        picker.setOption(QtWidgets.QFileDialog.Option.DontConfirmOverwrite, True)
        picker.setWindowTitle("Новая потоковая запись")
        picker.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        picker.setFileMode(QtWidgets.QFileDialog.FileMode.AnyFile)
        picker.setNameFilter("Потоковая запись (*.mtstream)")
        picker.setDefaultSuffix("mtstream")
        picker.setLabelText(QtWidgets.QFileDialog.DialogLabel.FileName, "Новое имя файла:")
        picker.setLabelText(QtWidgets.QFileDialog.DialogLabel.LookIn, "Папка:")
        picker.setLabelText(QtWidgets.QFileDialog.DialogLabel.FileType, "Тип файла:")
        picker.setLabelText(QtWidgets.QFileDialog.DialogLabel.Accept, "Начать запись")
        picker.setLabelText(QtWidgets.QFileDialog.DialogLabel.Reject, "Отмена")
        picker.setStyleSheet(
            "QTreeView, QListView { background: #0b202b; color: #dbe9f4; "
            "selection-background-color: #176479; } "
            "QHeaderView::section { background: #16303e; color: #dbe9f4; }")
        picker.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self._record_picker = picker
        picker.finished.connect(
            lambda result: self._record_selected(picker, before, result))
        picker.open()
        self._state(self.bridge.state)
        return True

    def _record_selected(self, picker, before, result):
        if picker is not self._record_picker:
            return
        self._record_picker = None
        paths = picker.selectedFiles()
        picker.deleteLater()
        if result == QtWidgets.QDialog.DialogCode.Accepted and paths and not self._closing:
            current = self.bridge.state
            # Never silently replace a preview that failed while the user was
            # choosing a filename with an unrelated new generation.
            same_source = current.revision == before.revision
            if not before.can_preview:
                same_source = same_source and current.phase == "preview"
            if (not same_source or not current.can_record or self.bridge.metadata_pending):
                self.error_label.setText(
                    "Запись не началась: состояние потока изменилось во время выбора файла. "
                    "Проверьте сообщение о приёме. После сбоя закройте окно непрерывного "
                    "приёма и откройте его заново.")
            else:
                self.record_path(paths[0])
        self._state(self.bridge.state)

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
        else:
            self.error_label.setText(
                "Запись не началась: поток пока не готов или уже завершился. "
                "Проверьте состояние приёма и повторите запуск явно.")
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
        self.quality.setText(
            STOPPED_UNKNOWN + ". Потери по данным источника: неизвестны."
            if self.bridge.state.phase == "stopped unknown tail" else
            f"Потери по данным источника: {loss}; {tail}.")
        if self._revision != source.revision:
            self._revision = source.revision
            self._handle = self.viewer.begin_live(source.identity, event_config=source.config,
                                                  event_config_revision=source.config_revision)
            self.viewer.source_label.setText(
                ("Программный источник; COM-порт не используется. " if self.selection is None else
                 f"Выбранный порт {self.selection.port}; происхождение: {source.identity.origin}. ") +
                "Потоковый протокол 0.2 → проверка → файл и ограниченный обзор. Время номинальное.")
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
        idle = (not self._closing and not self.busy and not self.bridge.metadata_pending
                and self._record_picker is None)
        physical = self.selection is not None
        self.live_button.setEnabled(idle and status.can_preview and (not physical or status.ready))
        self.record_button.setEnabled(idle and status.can_record and
                                      (not physical or status.phase == "preview"))
        if physical:
            self.connect_button.setEnabled(idle and status.can_connect)
            self.disconnect_button.setEnabled(status.can_retry_close or
                                              (not self._closing and status.can_disconnect))
            self.disconnect_button.setText("Повторить закрытие порта" if status.can_retry_close
                                           else "Отключить")
            connection = self.bridge.connection
            if connection is not None:
                frequency = connection.observed_caps[4] / connection.observed_caps[5]
                self._live_notice = (
                    f"STM32 · {self.selection.port} · CH1 · протокол 0.2 · "
                    f"{frequency:g} отсчётов/с номинально\n"
                    f"Плата сообщила сборку 0x{connection.observed_build_id:08X}. "
                    "Это не проверка файла прошивки или точности частоты.\n"
                    "Шкала напряжения не настроена. Полнота произведённых отсчётов неизвестна.")
                if not self._opening:
                    self.notice.setText(self._live_notice)
            if status.error:
                self.error_label.setText(
                    str(status.error) + "\nНужна потоковая прошивка протокола 0.2. "
                    "Оконная прошивка 0.1 здесь несовместима. "
                    "После сбоя отключите порт; перед новой попыткой перезапустите плату.")
        self.open_button.setEnabled(idle and status.can_open)
        self.stop_button.setEnabled(not self._closing and not status.can_open)
        self.pause_button.setEnabled(not self._closing and not self._opening and self._revision is not None)
        self.export_button.setEnabled(idle and self.archive is not None and
                                      not isinstance(self.archive, AttemptReport))
        phases = {"idle": "Не подключено" if physical else "Готово",
                  "connected": "Соединение открыто", "disconnected": "Отключено",
                  "serial close unconfirmed": "Закрытие порта не подтверждено",
                  "ready": "Подключено · готово к запуску",
                  "preview": "Живой поток", "recording": "Идёт запись",
                  "saved": "Запись завершена", "preview stopped": "Поток остановлен",
                  "negotiating": "Согласование", "starting preview": "Запуск потока",
                  "preparing": "Подготовка файла", "waiting for boundary": "Ожидание начала записи",
                  "draining": "Завершение записи", "fault": "Поток прерван",
                  "fault; writer unresolved": "Поток прерван · завершение файла",
                  "stopped unknown tail": STOPPED_UNKNOWN,
                  "closed": "Закрыто", "closing": "Закрытие",
                  "stopped before START": "Остановлено до запуска",
                  "stopped without R": "Нет отсчётов записи", "error": "Ошибка"}
        text = phases.get(status.phase, status.phase)
        if self._closing:
            text = "Завершение потока и сохранение файла перед закрытием…"
        elif self.busy:
            text = "Проверка файла…" if self._operation == "open" else "Экспорт…"
        elif self.bridge.metadata_pending and status.can_open:
            text = ("Контекст записи не сохранён" if self.bridge.metadata_error is not None
                    else "Сохранение контекста записи…")
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
        if not self._opening and status.phase == "stopped unknown tail":
            self.quality.setText(
                STOPPED_UNKNOWN + ". Потери по данным источника: неизвестны.")
        session = None if status.bridge is None else status.bridge.session
        if not self._opening and session is not None:
            failure = session.first_failure
            first = session.selected_start_sample_index
            if status.path:
                if first is None:
                    text += " · Запись не началась" if failure else " · Подготовка записи"
                    if failure:
                        self.file_label.setText("Запись не началась. Выбранный путь: " + status.path)
                else:
                    accepted = max(0, (session.accepted_end_sample_index or first) - first)
                    confirmed = max(0, (session.checkpointed_end_sample_index or first) - first)
                    text += (f" · Принято в запись: {accepted:,}"
                             f" · Подтверждено в файле: {confirmed:,}").replace(",", " ")
            if failure:
                text += f" · НЕПОЛНЫЕ ДАННЫЕ: {failure.code}"
                self.quality.setText(
                    "Запись неполная. Остановка источника не означает, что все отсчёты сохранены.")
                self.error_label.setText(self._failure_message(failure, status.path))
        self.state_label.setText(text)
        failure = self.bridge.metadata_error
        self.retry_context_button.setVisible(failure is not None and not self._closing)
        if self._closing and failure is not None and not self._context_prompting:
            self._context_prompting = True
            QtCore.QTimer.singleShot(0, lambda: self._resolve_context_error(failure))

    @staticmethod
    def _failure_message(failure, path):
        if failure.code == "host_io":
            if "FileExistsError" in failure.detail:
                explanation = "Файл уже существует. Существующие записи не заменяются; выберите новое имя."
            elif "PermissionError" in failure.detail:
                explanation = "Нет доступа к файлу записи. Проверьте доступность выбранной папки."
            elif "FileNotFoundError" in failure.detail:
                explanation = "Папка записи не найдена. Выберите существующую папку."
            else:
                explanation = "Ошибка работы с файлом записи. Сохранение всех данных не подтверждено."
        elif failure.code in ("capacity_blocks", "capacity_raw"):
            explanation = "Запись остановлена: достигнут предел очереди или объёма данных."
        else:
            explanation = "Поток прерван. Полнота записи не подтверждена."
        operation = {"prepare": "создание файла", "append": "добавление данных",
                     "checkpoint": "подтверждение записи", "finish": "завершение файла",
                     "bind_first_block": "запись первых отсчётов",
                     "close": "закрытие файла"}.get(failure.operation, failure.operation)
        details = f"\nПричина: {failure.detail}"
        if operation:
            details += f" · Операция: {operation}"
        if path:
            details += "\nФайл: " + str(path)
        return (explanation + details +
                "\nДля новой попытки закройте это окно непрерывного приёма и откройте его заново.")

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
                    stopped_unknown = (
                        terminal is not None and terminal.reason == "stopped"
                        and terminal.terminal_observed and terminal.stop_requested
                        and terminal.stop_request_id is not None and terminal.failure is None
                        and terminal.device_generated_end_sample_index is None
                        and terminal.loss_samples is None and not rec.recovery_issue)
                    state = ("Источник сообщил о полном завершении" if rec.clean_stop_reported else
                             STOPPED_UNKNOWN if stopped_unknown else
                             "НЕПОЛНЫЕ ДАННЫЕ · полнота хвоста не подтверждена")
                    self.quality.setText(f"{state}. Потери по записи: {loss}.")
                    if terminal is not None and terminal.failure is not None:
                        self.error_label.setText(self._failure_message(terminal.failure, rec.path))
                self._heading(self.verified_context.context)
                self.notice.setText(
                    "ОТКРЫТАЯ ПОТОКОВАЯ ЗАПИСЬ · происхождение указано над графиком.\n"
                    "Шкала напряжения не настроена. Отображаются только исходные коды; время номинальное.")
                if not self.verified_context.companion_present:
                    self.error_label.setText(
                        (self.error_label.text() + "\n" if self.error_label.text() else "") +
                        "Файл контекста отсутствует: имя и профиль неизвестны; шкала не настроена.")
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
        # Retain the shared serial lease until workers AND the OS handle have
        # settled. A stopped graph or a requested disconnect is insufficient.
        if self._serial_reserved and self._release_serial is not None:
            self._release_serial(self)
        self._serial_reserved = False
        self.settled.emit()
        self.close()

    def closeEvent(self, event):
        if self.closed:
            event.accept()
            return
        self._closing = True
        if self._record_picker is not None:
            self._record_picker.reject()
        self._state(self.bridge.state)
        if not self.busy:
            self.bridge.shutdown()
        event.ignore()

    def reject(self):
        # Esc must take the same asynchronous Stop/drain path as the close icon.
        self.close()
