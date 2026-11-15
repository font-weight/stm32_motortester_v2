"""Physical CH1 profile controls for the main-window sidebar.

The draft belongs to one negotiated connection. Refreshing display state never
applies a scale or copies a file's calibration onto the next acquisition.
"""
from dataclasses import replace
from datetime import datetime, timezone

from PySide6 import QtCore, QtWidgets

from .analog_profile import RawFormat, nominal_selection, profile_description
from .input import UNKNOWN_PROFILE


class InlineAnalogControls(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.panel = None
        self.measured_pair = None
        self._observed_key = None
        self._dirty = False
        self._loaded_note = ""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.details_toggle = QtWidgets.QToolButton()
        self.details_toggle.setText("Настройка входа CH1")
        self.details_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_toggle.setCheckable(True)
        self.details_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.details_toggle.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        layout.addWidget(self.details_toggle)
        self.mode = QtWidgets.QComboBox()
        self.mode.setObjectName("inlineAnalogMode")
        self.mode.addItem("Прямой PA0 / неизвестный вход", None)
        self.mode.addItem("DC + WIDE", "DC_WIDE")
        self.mode.addItem("AC + WIDE", "AC_WIDE")
        self.mode.addItem("AC + SENSITIVE", "AC_SENSITIVE")
        layout.addWidget(self.mode)
        self.note = self._label("")
        layout.addWidget(self.note)
        self.details_body = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(self.details_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)
        body.addWidget(self._label("Имя экземпляра платы"))
        self.instance = QtWidgets.QLineEdit()
        self.instance.setObjectName("inlineAnalogInstance")
        self.instance.setMaxLength(80)
        self.instance.setPlaceholderText("Например: Моя R53 №1")
        body.addWidget(self.instance)
        body.addWidget(self._label("S1/S2 переключаются на самой плате. Выберите их фактическое положение."))
        self.confirm = QtWidgets.QCheckBox()
        self.confirm.setObjectName("inlineAnalogConfirmed")
        body.addWidget(self.confirm)
        self.calibration_note = self._label("")
        body.addWidget(self.calibration_note)
        self.load_button = QtWidgets.QPushButton("Загрузить калибровку…")
        self.nominal_button = QtWidgets.QPushButton("Расчётная шкала")
        body.addWidget(self.load_button)
        body.addWidget(self.nominal_button)
        self.apply_button = QtWidgets.QPushButton("Применить вход")
        body.addWidget(self.apply_button)
        self.error = self._label("")
        self.error.setStyleSheet("color: #ffcb66")
        body.addWidget(self.error)
        layout.addWidget(self.details_body)
        self.calibration_button = QtWidgets.QPushButton("Калибровка…")
        layout.addWidget(self.calibration_button)
        self.details_toggle.toggled.connect(self._toggle_details)
        self.mode.currentIndexChanged.connect(self._draft_changed)
        self.instance.textChanged.connect(self._draft_changed)
        self.confirm.toggled.connect(self._update_enabled)
        self.apply_button.clicked.connect(self.apply_input)
        self.load_button.clicked.connect(self.load_calibration)
        self.nominal_button.clicked.connect(self.clear_calibration)
        self.calibration_button.clicked.connect(self.open_calibration)
        self._toggle_details(False)
        self.refresh()

    @staticmethod
    def _label(text):
        widget = QtWidgets.QLabel(text)
        widget.setWordWrap(True)
        widget.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        return widget

    def _toggle_details(self, expanded):
        self.details_body.setVisible(expanded)
        self.details_toggle.setArrowType(QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow)

    def bind_panel(self, panel):
        if panel is self.panel:
            self.refresh()
            return
        self.panel = panel
        self._observed_key = None
        self.refresh()

    def _editable(self):
        return self.panel is not None and self.panel.input_editable()

    def _format(self):
        if self.panel is None:
            return None
        value = self.panel.bridge.input_format
        if value is None:
            return None
        return value if isinstance(value, RawFormat) else RawFormat.from_identity(value)

    def _key(self):
        panel = self.panel
        if panel is None:
            return (None,)
        bridge = panel.bridge
        return (id(panel), id(bridge), id(getattr(bridge, "connection", None)),
                bool(getattr(panel, "_opening", False)), panel.active_input_profile,
                panel.active_analog_snapshot, self._format())

    def refresh(self):
        key = self._key()
        if key != self._observed_key:
            self._observed_key = key
            profile = self.panel.active_input_profile if self.panel is not None else UNKNOWN_PROFILE
            snapshot = self.panel.active_analog_snapshot if self.panel is not None else None
            with QtCore.QSignalBlocker(self.mode), QtCore.QSignalBlocker(self.instance):
                self.mode.setCurrentIndex(max(0, self.mode.findData(None if snapshot is None else snapshot.mode_id)))
                self.instance.setText("" if snapshot is None else snapshot.hardware_instance_id or "")
            self.confirm.setChecked(False)
            self.measured_pair = ((profile, snapshot) if snapshot is not None and snapshot.calibration is not None else None)
            self._loaded_note = ""
            self._dirty = False
            self.error.clear()
        self._update_labels()
        self._update_enabled()

    def _update_labels(self):
        mode = self.mode.currentData()
        if mode is not None:
            coupling, gain = mode.split("_")
            self.confirm.setText(f"На плате: {coupling} + {gain} — подтверждаю")
        else:
            self.confirm.setText("Положение S1/S2")
        self.confirm.setVisible(mode is not None)
        if self.panel is None:
            self.note.setText("Прибор не подключён. Мастер калибровки доступен без платы.")
        else:
            description = profile_description(self.panel.active_input_profile, self.panel.active_analog_snapshot)
            if getattr(self.panel, "_opening", False):
                description = "Шкала открытой записи: " + description
            elif self._dirty:
                description += "\nИзменения ещё не применены."
            self.note.setText(description)
        if self._loaded_note:
            self.calibration_note.setText(self._loaded_note)
        elif self.measured_pair is not None:
            self.calibration_note.setText(profile_description(*self.measured_pair))
        elif mode is None:
            self.calibration_note.setText("Неизвестный вход: только исходные коды АЦП.")
        else:
            text = "Расчётная шкала, не калибровано."
            if mode.startswith("AC_"):
                text += " Постоянная составляющая не измеряется; коэффициент действует в полосе пропускания."
            self.calibration_note.setText(text)

    def _update_enabled(self, *_):
        editable = self._editable()
        selected = self.mode.currentData() is not None
        self.mode.setEnabled(editable)
        self.instance.setEnabled(editable and selected)
        self.confirm.setEnabled(editable and selected)
        self.load_button.setEnabled(editable and selected)
        self.nominal_button.setEnabled(editable and selected)
        self.apply_button.setEnabled(editable and (not selected or self.confirm.isChecked()))
        self.calibration_button.setEnabled(True)

    def _draft_changed(self, *_):
        self.measured_pair = None
        self._loaded_note = ""
        self._dirty = True
        self.confirm.setChecked(False)
        self.error.clear()
        self.details_toggle.setChecked(True)
        self._update_labels()
        self._update_enabled()

    def clear_calibration(self, *_):
        self._draft_changed()

    def apply_input(self):
        if not self._editable():
            return False
        mode = self.mode.currentData()
        if mode is not None and not self.confirm.isChecked():
            self.error.setText("Подтвердите фактическое положение S1/S2.")
            return False
        try:
            if mode is None:
                pair = (UNKNOWN_PROFILE, None)
            elif self.measured_pair is not None:
                profile, snapshot = self.measured_pair
                if (snapshot.mode_id != mode or snapshot.hardware_instance_id != self.instance.text().strip()
                        or snapshot.raw_format != self._format()):
                    raise ValueError("Калибровка относится к другому режиму, экземпляру или частоте приёма.")
                pair = profile, replace(snapshot, confirmed_at_utc=datetime.now(timezone.utc).isoformat())
            else:
                pair = nominal_selection(mode, self._format(), hardware_instance_id=self.instance.text().strip() or None)
            if not self.panel.apply_input_profile(*pair):
                raise ValueError("Приём изменил состояние. Остановите его перед настройкой входа.")
            self._observed_key = None
            self.refresh()
            return True
        except ValueError as exc:
            self.error.setText(str(exc))
            return False

    def load_calibration(self):
        if not self._editable() or self.mode.currentData() is None:
            return False
        from .calibration import load_calibration, calibrated_selection
        request_key = self._key()
        mode, hardware_id = self.mode.currentData(), self.instance.text().strip()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Калибровка CH1", "", "Калибровка (*.mtcal.json *.json)")
        if not path:
            return False
        try:
            if (not self._editable() or self._key() != request_key
                    or self.mode.currentData() != mode or self.instance.text().strip() != hardware_id):
                raise ValueError("Соединение или источник изменился. Выберите калибровку снова.")
            record = load_calibration(path)
            if record.plan.mode_id != mode:
                raise ValueError("Калибровка не соответствует выбранному режиму входа.")
            self.measured_pair = calibrated_selection(record, self._format(), hardware_instance_id=hardware_id)
            self.confirm.setChecked(False)
            self._dirty = True
            self._loaded_note = "Калибровка загружена. " + profile_description(*self.measured_pair)
            self.error.clear()
            self._update_labels()
            self._update_enabled()
            return True
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return False

    def open_calibration(self):
        from .calibration_ui import open_calibration_wizard
        def current():
            panel = self.panel
            if panel is None or panel.closed or panel.archive is not None:
                return None
            return panel.bridge, panel.active_context
        return open_calibration_wizard(self, live_current=current)
