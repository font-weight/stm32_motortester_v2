"""Explicit operator choice of the physical CH1 input, separate from UI profiles.

The caller owns the connection and only opens this dialog while reception is
stopped. Accepting returns an immutable profile/snapshot pair; the dialog never
changes switches, starts acquisition, or alters an existing recording.
"""
from PySide6 import QtCore, QtWidgets
from dataclasses import replace
from datetime import datetime, timezone

from .analog_profile import nominal_selection
from .input import UNKNOWN_PROFILE
from .widgets import STYLE


MODE_LABELS = {
    "DC_WIDE": "R5 · DC + WIDE — постоянное и переменное напряжение",
    "AC_WIDE": "R5 · AC + WIDE — переменная составляющая",
    "AC_SENSITIVE": "R5 · AC + SENSITIVE — переменная составляющая, усиление",
}


class AnalogInputDialog(QtWidgets.QDialog):
    """A new invocation always requires a new physical-switch confirmation.

    Public result after Accepted: ``profile`` and ``snapshot``. Unknown/direct
    PA0 deliberately returns UNKNOWN_PROFILE and None. ``identity`` must come
    from the negotiated connection, not from a selected sample-rate label.
    """

    def __init__(self, parent=None, *, identity, current_profile=UNKNOWN_PROFILE,
                 current_snapshot=None):
        super().__init__(parent)
        self.identity = identity
        self.profile, self.snapshot = UNKNOWN_PROFILE, None
        self.measured_pair = None
        self.setWindowTitle("Аналоговый вход CH1")
        self.setStyleSheet(STYLE + "\nQDialog { background: #091720; }")
        self.resize(690, 430)
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel("Что сейчас подключено перед PA0?")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        layout.addWidget(self._label(
            "Выбор задаёт шкалу CH1. Приложение не считывает и не переключает S1/S2; "
            "профили «Осциллограф» и «Зажигание» на них не влияют."))
        self.mode = QtWidgets.QComboBox()
        self.mode.setObjectName("analogMode")
        self.mode.addItem("Прямой PA0 / неизвестный тракт — только коды АЦП", None)
        for mode_id, label in MODE_LABELS.items():
            self.mode.addItem(label, mode_id)
        layout.addWidget(self.mode)
        self.explanation = self._label("")
        self.explanation.setMinimumHeight(85)
        layout.addWidget(self.explanation)
        instance_row = QtWidgets.QFormLayout()
        self.instance = QtWidgets.QLineEdit()
        self.instance.setObjectName("analogHardwareInstance")
        self.instance.setMaxLength(80)
        self.instance.setPlaceholderText("Например: моя плата №1; можно оставить пустым")
        instance_row.addRow("Имя экземпляра платы", self.instance)
        layout.addLayout(instance_row)
        self.confirm = QtWidgets.QCheckBox()
        self.confirm.setObjectName("analogSwitchConfirmed")
        layout.addWidget(self.confirm)
        layout.addWidget(self._label(
            "После нового подключения режим нужно подтвердить снова. "
            "Для смены переключателей сначала остановите приём и запись."))
        self.calibration_note = self._label("Используется расчётная шкала")
        layout.addWidget(self.calibration_note)
        calibration_row = QtWidgets.QHBoxLayout()
        load_button = QtWidgets.QPushButton("Загрузить калибровку…")
        load_button.clicked.connect(self.load_calibration)
        reset_button = QtWidgets.QPushButton("Вернуть расчётную шкалу")
        reset_button.clicked.connect(self.clear_calibration)
        calibration_row.addWidget(load_button); calibration_row.addWidget(reset_button)
        layout.addLayout(calibration_row)
        help_button = QtWidgets.QPushButton("Мастер калибровки DC / AC…")
        help_button.clicked.connect(self.show_calibration_guide)
        layout.addWidget(help_button)
        self.error = self._label("")
        self.error.setStyleSheet("color: #ffcb66")
        layout.addWidget(self.error)
        layout.addStretch()
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Применить шкалу")
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.confirm.toggled.connect(self._enable_apply)
        self.instance.textChanged.connect(self.clear_calibration)
        if current_snapshot is not None and current_profile.configured:
            self.mode.setCurrentIndex(max(0, self.mode.findData(current_snapshot.mode_id)))
            self.instance.setText(current_snapshot.hardware_instance_id or "")
        self._mode_changed()
        if current_snapshot is not None and current_snapshot.calibration is not None:
            self.measured_pair = (current_profile, current_snapshot)
            self.calibration_note.setText("Сохранена действующая калибровка. Подтвердите положение переключателей.")

    @staticmethod
    def _label(text):
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        return label

    def _mode_changed(self, *_):
        self.clear_calibration()
        mode_id = self.mode.currentData()
        self.confirm.setChecked(False)
        self.confirm.setVisible(mode_id is not None)
        self.instance.setEnabled(mode_id is not None)
        self.error.clear()
        if mode_id is None:
            self.explanation.setText(
                "Показываются исходные коды АЦП. Коэффициенты R5 к прямому PA0 "
                "или неизвестному входу не применяются. Запись кодов остаётся доступна.")
        else:
            coupling, gain = mode_id.split("_")
            self.confirm.setText(f"На моей плате физически установлены S1: {coupling}, S2: {gain}")
            measurement = (
                "Показывается напряжение на разъёме CH1 перед делителем относительно AGND."
                if coupling == "DC" else
                "Показывается переменная составляющая на CH1 перед делителем. "
                "Постоянная составляющая не измеряется; коэффициент действует в полосе пропускания.")
            self.explanation.setText(
                "Аналоговый вход R5.1 / плата R5.3.\n" + measurement +
                "\nВыбор шкалы не подтверждает допустимое напряжение или защиту входа.")
        self._enable_apply()

    def _enable_apply(self, *_):
        self.apply_button.setEnabled(self.mode.currentData() is None or self.confirm.isChecked())

    def accept(self):
        mode_id = self.mode.currentData()
        if mode_id is not None and not self.confirm.isChecked():
            self.error.setText("Подтвердите фактическое положение переключателей на плате.")
            return
        try:
            if mode_id is None:
                profile, snapshot = UNKNOWN_PROFILE, None
            else:
                if self.measured_pair is not None:
                    profile, snapshot = self.measured_pair
                    if snapshot.mode_id != mode_id or snapshot.hardware_instance_id != self.instance.text().strip():
                        raise ValueError("Калибровка не соответствует выбранному режиму или экземпляру")
                    snapshot = replace(snapshot, confirmed_at_utc=datetime.now(timezone.utc).isoformat())
                else:
                    profile, snapshot = nominal_selection(
                        mode_id, self.identity,
                        hardware_instance_id=self.instance.text().strip() or None)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.profile, self.snapshot = profile, snapshot
        super().accept()

    def show_calibration_guide(self):
        from .calibration_ui import open_calibration_wizard
        open_calibration_wizard(self)

    def clear_calibration(self, *_):
        self.measured_pair = None
        self.calibration_note.setText("Используется расчётная шкала, не калибровано")

    def load_calibration(self):
        from .calibration import load_calibration, calibrated_selection
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Калибровка CH1", "", "Калибровка (*.mtcal.json *.json)")
        if not path:
            return
        try:
            record = load_calibration(path)
            if record.plan.mode_id != self.mode.currentData():
                raise ValueError("Сначала выберите физический режим, для которого сохранена калибровка")
            pair = calibrated_selection(record, self.identity, hardware_instance_id=self.instance.text().strip())
            self.measured_pair = pair
            self.calibration_note.setText("Калибровка загружена · " + record.plan.mode_id +
                (f" · синусоида {record.plan.frequency_hz:g} Гц" if record.plan.frequency_hz else " · три DC-точки"))
            self.confirm.setChecked(False)
            self.error.clear()
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
