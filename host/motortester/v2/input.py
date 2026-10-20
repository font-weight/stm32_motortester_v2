"""Connector voltage, kept separate from the oscilloscope/ignition UI profile."""
from dataclasses import dataclass
from math import isfinite


class V2Error(ValueError):
    """Invalid input or unavailable measurement; suitable for a user message."""


def finite(value, name):
    if type(value) not in (int, float) or not isfinite(value):
        raise V2Error(f"{name}: требуется конечное число")


def text(value, name, maximum=256, optional=False):
    if value is None and optional:
        return
    if type(value) is not str or not 1 <= len(value) <= maximum:
        raise V2Error(f"{name}: недопустимая строка")
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise V2Error(f"{name}: недопустимый символ")


@dataclass(frozen=True, slots=True)
class InputProfile:
    """U_CH1 = a * code + b; 4096 levels, raw codes 0..4095.

    Values describe the input CONNECTOR, never ignition secondary kilovolts.
    None coefficients deliberately prevent a nominal ADC scale being mistaken
    for an unknown external analog front end.
    """

    a: float | None = None
    b: float | None = None
    state: str = "unconfigured"
    profile_id: str = "unknown"
    adc_bits: int = 12
    channel_id: str = "CH1"
    device_id: str | None = None
    frontend_id: str | None = None
    frontend_revision: str | None = None
    range_id: str | None = None
    coupling: str = "unknown"
    coefficient_source: str | None = None
    calibration_id: str | None = None
    calibration_version: str | None = None
    calibration_date: str | None = None
    measurement_point: str | None = None
    ground_reference: str | None = None
    sensor: str | None = None
    vref_v: float | None = None
    bandwidth_hz: float | None = None
    linear_min_v: float | None = None
    linear_max_v: float | None = None
    conditions: str | None = None

    def __post_init__(self):
        if self.state not in ("calibrated", "nominal", "unconfigured"):
            raise V2Error("Неизвестное состояние шкалы")
        if self.adc_bits != 12 or type(self.adc_bits) is not int:
            raise V2Error("В этой версии поддерживается 12-битный АЦП")
        if self.channel_id != "CH1":
            raise V2Error("В этой версии доступен один физический вход CH1")
        if self.coupling not in ("DC", "AC", "unknown"):
            raise V2Error("Неизвестный режим связи входа")
        if self.configured:
            finite(self.a, "a"); finite(self.b, "b")
            if self.a == 0:
                raise V2Error("Коэффициент a не может быть нулевым")
            if self.coefficient_source is None:
                raise V2Error("Нужно происхождение коэффициентов")
            if not isfinite(self.a * 4095 + self.b) or self.a * 4095 + self.b == self.b:
                raise V2Error("Коэффициенты не дают конечного различимого диапазона")
        elif self.a is not None or self.b is not None:
            raise V2Error("Неизвестная шкала не должна содержать коэффициенты")
        if self.state == "calibrated" and self.calibration_id is None:
            raise V2Error("Нужен идентификатор калибровки")
        for name in ("profile_id", "channel_id"):
            text(getattr(self, name), name)
        for name in ("device_id", "frontend_id", "frontend_revision", "range_id",
                     "coefficient_source", "calibration_id", "calibration_version",
                     "calibration_date", "measurement_point", "ground_reference",
                     "sensor", "conditions"):
            text(getattr(self, name), name, optional=True)
        for name in ("vref_v", "bandwidth_hz", "linear_min_v", "linear_max_v"):
            value = getattr(self, name)
            if value is not None:
                finite(value, name)
        if self.vref_v is not None and self.vref_v <= 0:
            raise V2Error("Vref должен быть положительным")
        if self.bandwidth_hz is not None and self.bandwidth_hz <= 0:
            raise V2Error("Полоса должна быть положительной")
        if (self.linear_min_v is None) != (self.linear_max_v is None):
            raise V2Error("Границы линейного диапазона задаются вместе")
        if self.linear_min_v is not None and self.linear_min_v >= self.linear_max_v:
            raise V2Error("Некорректный линейный диапазон")

    @property
    def configured(self):
        return self.state != "unconfigured"

    def voltage(self, code):
        if not self.configured:
            raise V2Error("Шкала напряжения не настроена")
        finite(code, "Код")
        if not 0 <= code <= 4095:
            raise V2Error("Код вне диапазона 12-битного АЦП")
        return self.a * code + self.b

    @property
    def voltage_limits(self):
        return tuple(sorted((self.voltage(0), self.voltage(4095))))

    def code(self, voltage):
        """Nearest code, with explicit range rejection; never silent clipping."""
        finite(voltage, "Напряжение")
        low, high = self.voltage_limits
        if self.linear_min_v is not None:
            low, high = max(low, self.linear_min_v), min(high, self.linear_max_v)
        if not low <= voltage <= high:
            raise V2Error(f"Порог вне диапазона {low:g}…{high:g} В")
        return int(round((voltage - self.b) / self.a))

    def code_edge(self, edge):
        if edge not in ("rising", "falling"):
            raise V2Error("Неизвестное направление фронта")
        if not self.configured:
            raise V2Error("Шкала напряжения не настроена")
        return edge if self.a > 0 else ("falling" if edge == "rising" else "rising")

    def clipping(self, samples):
        """Rail evidence is a warning, not an extrapolated peak."""
        for code in samples:
            if code in (0, 4095):
                return True
            if self.configured and self.linear_min_v is not None:
                if not self.linear_min_v < self.voltage(code) < self.linear_max_v:
                    return True
        return False


UNKNOWN_PROFILE = InputProfile()
DEMO_PROFILE = InputProfile(
    a=3.3 / 4096, b=0.0, state="nominal", profile_id="demo-3v3-12bit-v1",
    frontend_id="synthetic-direct", frontend_revision="1", range_id="synthetic",
    coupling="DC", coefficient_source="synthetic_demo_definition",
    measurement_point="Синтетический вход CH1", ground_reference="synthetic-zero",
    sensor="Синтетический сигнал", vref_v=3.3,
    conditions="ДЕМО; коэффициенты заданы программно, не измерены на приборе",
)
