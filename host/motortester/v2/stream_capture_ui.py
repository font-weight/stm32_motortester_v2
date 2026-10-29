"""Single-capture actions around the existing receiver and file worker."""
from pathlib import Path
from PySide6 import QtCore, QtWidgets

from .stream_capture import CaptureAttempt, StreamCapture, save_capture
from ..gui_stream import identity_key


class SingleCaptureControls(QtWidgets.QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.attempt = None
        self.shot = None
        self.dirty = False
        self.picker = self.prompt = None
        self.saving = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.arm_button = QtWidgets.QPushButton('Поймать событие')
        self.save_button = QtWidgets.QPushButton('Сохранить захват…')
        self.save_button.setToolTip('Сохранить исходные отсчёты захваченного события независимо от текущего масштаба.')
        self.arm_button.clicked.connect(self.toggle)
        self.save_button.clicked.connect(self.save_dialog)
        row.addWidget(self.arm_button)
        row.addWidget(self.save_button)
        row.addWidget(panel.sync_button)
        layout.addLayout(row)
        self.note = QtWidgets.QLabel('Одиночный захват: запустите живой поток и нажмите «Поймать событие».')
        self.note.setWordWrap(True)
        self.note.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        viewer = panel.viewer
        viewer.source_reset.connect(self.source_reset)
        viewer.sync_changed.connect(lambda enabled: self.cancel() if enabled else None)
        for button in (viewer.follow_button, viewer.previous_button, viewer.next_button):
            button.clicked.connect(self.cancel)
        viewer.plot.getViewBox().sigRangeChangedManually.connect(
            lambda axes: self.cancel() if axes[0] else None)
        viewer.plot_drawn.connect(self.draw_marker)

    def source_reset(self):
        self.cancel('Ожидание отменено: смена источника')
        self.panel.viewer.trigger_marker.hide()

    def confirm_discard(self, callback, *, on_cancel=None):
        if not self.dirty:
            callback()
            return
        if self.prompt is not None:
            return
        prompt = QtWidgets.QMessageBox(self.panel)
        prompt.setWindowTitle('Захват не сохранён')
        prompt.setText('Продолжить без сохранения отдельного захвата?\n'
                       'Для сохранения выберите «Отмена», затем «Сохранить захват».')
        prompt.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Discard |
                                  QtWidgets.QMessageBox.StandardButton.Cancel)
        prompt.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        prompt.button(QtWidgets.QMessageBox.StandardButton.Discard).setText('Продолжить без сохранения')
        prompt.button(QtWidgets.QMessageBox.StandardButton.Cancel).setText('Отмена')
        self.prompt = prompt
        def finished(result):
            self.prompt = None
            prompt.deleteLater()
            if result == QtWidgets.QMessageBox.StandardButton.Discard:
                self.dirty = False
                callback()
            elif on_cancel is not None:
                on_cancel()
        prompt.finished.connect(finished)
        prompt.open()

    def toggle(self):
        if self.attempt is not None:
            self.cancel('Ожидание отменено · приём и запись продолжаются')
        else:
            self.confirm_discard(self.arm)

    def arm(self):
        p = self.panel
        if p._closing or p._opening or p.busy or self.dirty:
            return False
        try:
            attempt = CaptureAttempt(p.bridge.controller.snapshot(), p.context)
            if (p._revision != attempt.revision or p.viewer._identity != identity_key(attempt.identity) or
                    p.viewer._first is None or p.viewer.selection is None):
                raise ValueError('Дождитесь первого кадра текущего потока')
        except ValueError as exc:
            self.note.setText(str(exc))
            return False
        # Release old inspection before installing the request, so those reset
        # signals cannot cancel the new arm. No acquisition command is issued.
        p._resume()
        p.viewer.follow()
        self.shot = None
        self.attempt = attempt
        self.note.setText(attempt.message)
        self.update_state(p.bridge.state)
        return True

    def cancel(self, reason=None):
        if self.attempt is not None:
            self.attempt = None
            self.note.setText(reason if isinstance(reason, str) else 'Ожидание отменено · приём продолжается')
            self.update_state(self.panel.bridge.state)

    def observe(self, source):
        attempt = self.attempt
        if attempt is None:
            return
        shot = attempt.consume(source)
        self.note.setText(attempt.message)
        if shot is not None:
            self.accept(shot)
        elif attempt.done:
            self.attempt = None
        self.update_state(self.panel.bridge.state)

    def finish(self, reason):
        if self.attempt is None:
            return
        attempt, self.attempt = self.attempt, None
        shot = attempt.finish(reason)
        if shot is not None:
            self.accept(shot)
        else:
            self.note.setText(attempt.message)

    def accept(self, shot, *, opened=False):
        self.attempt = None
        self.shot, self.dirty = shot, not opened
        p, viewer = self.panel, self.panel.viewer
        viewer.set_event_sync(False)
        viewer.inspection_reset.emit()
        if opened:
            viewer._reset_source()
            viewer._identity = identity_key(shot.identity)
            viewer._first, viewer._end = shot.first_sample_index, shot.end_sample_index
            viewer._recording = shot
            viewer._config = shot.config
            viewer._events = (shot.event,)
            viewer._origin(shot.identity.origin)
        else:
            viewer._held_live = shot
        viewer._event = shot.event
        viewer._event_notice = None
        viewer.select_range(shot.first_sample_index, shot.end_sample_index, hold_live=False)
        viewer._event = shot.event
        viewer.follow_tail = False
        viewer.view_mode_label.setText('Одиночный захват · кадр удерживается')
        viewer._actions()
        incomplete = shot.completion == 'interrupted' or 'right_truncated' in shot.event.flags or 'left_truncated' in shot.event.flags
        state = 'Неполный контекст' if incomplete else 'Контекст события захвачен'
        labels = {'right_truncated': 'обрезан хвост', 'left_truncated': 'неполная предыстория',
                  'context_limit': 'достигнут предел длительности', 'baseline_unsettled': 'неустойчивый фон',
                  'overlapping_activity': 'несколько пересечений', 'tail_ambiguous': 'неоднозначный хвост',
                  'clipping': 'край диапазона АЦП', 'quantization_edge_bin': 'край диапазона кодов',
                  'capture_context_unavailable': 'часть контекста недоступна'}
        flags = ', '.join(labels[f] for f in shot.event.flags if f in labels)
        flags = flags or ('есть отметки качества' if shot.event.flags else 'нет отметок качества')
        self.note.setText(f'{state} · {shot.end_sample_index - shot.first_sample_index} отсчётов · {flags}'
                          + (' · файл открыт' if opened else ' · можно сохранить отдельно'))
        self.update_state(p.bridge.state)

    def draw_marker(self):
        viewer, shot = self.panel.viewer, self.shot
        if shot is None or not (viewer._held_live is shot or viewer._recording is shot):
            if not viewer.event_sync:
                viewer.trigger_marker.hide()
            return
        at = (shot.event.trigger_index - viewer._display_origin) / shot.identity.nominal_fs_hz
        viewer.trigger_marker.setValue(at)
        viewer.trigger_marker.setVisible(viewer.selection.start <= shot.event.trigger_index < viewer.selection.stop)

    def update_state(self, status):
        p = self.panel
        if self.attempt is not None and status.phase not in ('preview', 'recording', 'preparing', 'waiting for boundary'):
            self.finish('stream_stopped_before_context')
        live = (not p._opening and not p._closing and status.phase in ('preview', 'recording')
                and p.viewer.selection is not None and p._revision == status.revision)
        idle = not p.busy and self.picker is None and self.prompt is None and p._record_picker is None
        self.arm_button.setEnabled(idle and live)
        self.arm_button.setText('Отменить ожидание' if self.attempt is not None else
                               'Поймать следующее…' if self.shot is not None else 'Поймать событие')
        self.save_button.setEnabled(idle and self.shot is not None and not p._closing)

    def save_dialog(self):
        if self.shot is None or self.panel.busy or self.picker is not None:
            return
        picker = QtWidgets.QFileDialog(self.panel)
        picker.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        picker.setOption(QtWidgets.QFileDialog.Option.DontConfirmOverwrite, True)
        picker.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        picker.setWindowTitle('Сохранить отдельный захват')
        picker.setNameFilter('Захват Мотортестера (*.mtshot)')
        picker.setDefaultSuffix('mtshot')
        picker.setLabelText(QtWidgets.QFileDialog.DialogLabel.Accept, 'Сохранить')
        picker.setLabelText(QtWidgets.QFileDialog.DialogLabel.Reject, 'Отмена')
        self.picker = picker
        shot = self.shot
        def selected(result):
            paths = picker.selectedFiles()
            self.picker = None
            picker.deleteLater()
            if result == QtWidgets.QDialog.DialogCode.Accepted and paths and not self.panel._closing:
                self.save_path(paths[0], shot=shot)
            self.update_state(self.panel.bridge.state)
        picker.finished.connect(selected)
        picker.open()
        self.update_state(self.panel.bridge.state)

    def save_path(self, path, *, shot=None):
        p = self.panel
        shot = self.shot if shot is None else shot
        if shot is None or p.busy or p._closing:
            return False
        self.saving = shot
        p.error_label.clear()
        p._operation = 'capture_save'
        p._future = p._executor.submit(save_capture, Path(path), shot)
        self.note.setText('Сохраняется отдельный захват · приём продолжается')
        self.update_state(p.bridge.state)
        return True

    def saved(self, path):
        if self.saving is self.shot:
            self.dirty = False
        self.saving = None
        incomplete = self.shot is not None and (self.shot.completion == 'interrupted' or
            {'right_truncated', 'left_truncated'} & set(self.shot.event.flags))
        self.note.setText(('Неполный контекст · ' if incomplete else '') + 'Захват сохранён: ' + path)

    def close_picker(self):
        if self.picker is not None:
            self.picker.reject()
