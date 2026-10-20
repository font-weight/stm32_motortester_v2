"""Small Qt controls; dial, editor and buttons share one physical value."""
import math
from PySide6 import QtCore, QtGui, QtWidgets


class SafeSpinBox(QtWidgets.QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()

    def textFromValue(self, value):
        return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")

    def valueFromText(self, text):
        cleaned = text.removesuffix(self.suffix()).strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return self.value()


class Dial(QtWidgets.QDial):
    def __init__(self):
        super().__init__()
        self.setRange(0, 1000)
        self.setFixedSize(78, 78)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(6, 6, self.width() - 12, self.height() - 12)
        painter.setPen(QtGui.QPen(QtGui.QColor("#284252"), 6))
        painter.drawArc(rect, -45 * 16, 270 * 16)
        fraction = self.value() / 1000
        color = "#00d9df" if self.isEnabled() else "#46616c"
        painter.setPen(QtGui.QPen(QtGui.QColor(color), 5))
        painter.drawArc(rect, 225 * 16, -round(270 * fraction * 16))
        gradient = QtGui.QLinearGradient(0, 10, 0, 70)
        gradient.setColorAt(0, QtGui.QColor("#344450"))
        gradient.setColorAt(1, QtGui.QColor("#16232d"))
        painter.setBrush(gradient)
        painter.setPen(QtGui.QPen(QtGui.QColor("#050e16"), 3))
        painter.drawEllipse(rect.adjusted(5, 5, -5, -5))
        angle = math.radians(225 - 270 * fraction)
        center = QtCore.QPointF(self.width() / 2, self.height() / 2)
        end = center + QtCore.QPointF(math.cos(angle) * 24, -math.sin(angle) * 24)
        start = center + QtCore.QPointF(math.cos(angle) * 12, -math.sin(angle) * 12)
        painter.setPen(QtGui.QPen(QtGui.QColor(color), 4, QtCore.Qt.PenStyle.SolidLine,
                                  QtCore.Qt.PenCapStyle.RoundCap))
        painter.drawLine(start, end)
        if self.hasFocus():
            painter.setPen(QtGui.QPen(QtGui.QColor("#b8eef1"), 1))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 8, 8)


class Knob(QtWidgets.QWidget):
    changed = QtCore.Signal(float)

    def __init__(self, title, low, high, value, step, suffix, *, logarithmic=False):
        super().__init__()
        self.low, self.high, self.logarithmic = low, high, logarithmic
        self.factor, self.suffix, self.step = 1.0, suffix, step
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)
        label = QtWidgets.QLabel(title)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        self.dial = Dial()
        self.dial.setAccessibleName(title)
        layout.addWidget(self.dial, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(0)
        self.minus = QtWidgets.QPushButton("−")
        self.plus = QtWidgets.QPushButton("+")
        for button in (self.minus, self.plus):
            button.setFixedWidth(24)
            button.setObjectName("step")
        self.spin = SafeSpinBox()
        # Qt 6.12's stylesheet geometry collapses the editor with NoButtons.
        # Keep the standard subcontrols at zero size; the visible +/- are ours.
        self.spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.spin.setLocale(QtCore.QLocale("ru_RU"))
        self.spin.setDecimals(4)
        self.spin.setMinimumWidth(0)
        self.spin.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.spin.setKeyboardTracking(False)
        self.spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.spin.setAccessibleName(title)
        row.addWidget(self.minus)
        row.addWidget(self.spin, 1)
        row.addWidget(self.plus)
        layout.addLayout(row)
        self._value = value
        self.set_display(1, suffix)
        self.dial.valueChanged.connect(self._dial_changed)
        self.spin.valueChanged.connect(self._spin_changed)
        self.minus.clicked.connect(lambda: self._step(-1))
        self.plus.clicked.connect(lambda: self._step(1))

    @property
    def value(self):
        return self._value

    def set_display(self, factor, suffix):
        self.factor, self.suffix = factor, suffix
        with QtCore.QSignalBlocker(self.spin):
            self.spin.setRange(self.low * factor, self.high * factor)
            self.spin.setSingleStep(self.step * factor)
            self.spin.setSuffix(" " + suffix)
        self.set_value(self._value)

    def set_bounds(self, low, high):
        self.low, self.high = low, max(high, low + 1e-9)
        self.set_display(self.factor, self.suffix)

    def set_value(self, value, *, emit=False):
        value = min(self.high, max(self.low, float(value)))
        self._value = value
        if self.logarithmic:
            fraction = math.log(value / self.low) / math.log(self.high / self.low)
        else:
            fraction = (value - self.low) / (self.high - self.low)
        with QtCore.QSignalBlocker(self.dial), QtCore.QSignalBlocker(self.spin):
            self.dial.setValue(round(fraction * 1000))
            self.spin.setValue(value * self.factor)
        if emit:
            self.changed.emit(value)

    def _dial_changed(self, value):
        fraction = value / 1000
        physical = (self.low * (self.high / self.low) ** fraction if self.logarithmic
                    else self.low + fraction * (self.high - self.low))
        self.set_value(physical, emit=True)

    def _spin_changed(self, value):
        self.set_value(value / self.factor, emit=True)

    def _step(self, direction):
        value = self._value * 2 ** direction if self.logarithmic else self._value + direction * self.step
        self.set_value(value, emit=True)


STYLE = """
QMainWindow, QWidget#root { background: #091720; color: #e9f4fa; }
QWidget { color: #e9f4fa; font-family: 'Segoe UI'; font-size: 14px; }
QWidget#sidecontent { background: #0d1d28; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 23px; font-weight: 700; }
QLabel#state { color: #00dbe1; font-size: 18px; font-weight: 600; }
QLabel#heading { font-size: 17px; font-weight: 600; }
QLabel#muted { color: #a1bccb; }
QLabel#badge { color: #fff400; border: 1px solid #d8cf00; border-radius: 5px; padding: 5px 12px; }
QLabel#metricValue { font-size: 22px; font-weight: 600; }
QFrame#panel, QFrame#card { background: #0d1d28; border: 1px solid #1c3443; border-radius: 7px; }
QPushButton { background: #192d3a; border: 1px solid #345063; border-radius: 5px; padding: 8px 10px; }
QPushButton:hover { background: #234150; border-color: #61a3b5; }
QPushButton:checked, QPushButton#primary { color: #03232b; background: #00d9df; border-color: #00edf4; font-weight: 600; }
QPushButton:focus { border-color: #00e4eb; }
QPushButton:disabled { background: #13232e; color: #647d8b; border-color: #233c49; }
QPushButton#tab { background: transparent; border: none; border-bottom: 3px solid transparent; border-radius: 0; padding: 9px 15px; }
QPushButton#tab:checked { color: #eaffff; border-bottom-color: #00e0e6; }
QPushButton#step { padding: 4px 0; border-radius: 3px; }
QDoubleSpinBox, QLineEdit, QComboBox { background: #081822; border: 1px solid #2b495b; border-radius: 4px; padding: 5px 2px; }
QLineEdit { padding: 0; }
QDoubleSpinBox QLineEdit { border: none; padding: 0; background: transparent; color: #e9f4fa; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; height: 0; border: none; }
QComboBox { padding: 5px 7px; }
QComboBox QAbstractItemView { background: #122b39; color: #e9f4fa; selection-background-color: #245364; }
QDoubleSpinBox:disabled { color: #647d8b; }
QSlider::groove:horizontal { height: 6px; background: #314f60; border-radius: 3px; }
QSlider::handle:horizontal { background: #00d9df; width: 15px; margin: -4px 0; border-radius: 7px; }
QSlider::sub-page:horizontal { background: #00bfc8; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 9px; background: #112633; }
QScrollBar::handle:vertical { background: #355364; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #0d202c; color: #b5d5e4; }
QStatusBar::item { border: none; }
QDialog, QMessageBox, QFileDialog { background: #102632; }
QToolTip { color: #e9f4fa; background: #233f4e; border: 1px solid #537384; }
"""
