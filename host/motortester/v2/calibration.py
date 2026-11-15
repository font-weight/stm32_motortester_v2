"""Bounded, auditable CH1 calibration, independent of acquisition and the GUI.

All raw values are canonical ADC12 coordinates, including retained-10 data.
An accepted control point only verifies the stated conditions, not protection,
bandwidth or the whole input range. Device provenance is an operator/file
declaration; the hashes below detect changes, not forged measurements.
"""
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
import struct

import numpy as np

from .analog_profile import RawFormat, nominal_mode
from .input import InputProfile, V2Error, finite, text


MAX_SAMPLES = 16384
MAX_FILE_BYTES = 2_000_000
ALGORITHM = "ch1-dc-affine-ac-sine-lstsq-v1"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _stamp(value):
    text(value, "Время", 80)
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise V2Error("Требуется дата UTC") from exc
    if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
        raise V2Error("Требуется дата UTC")
    return stamp


def _strict(cls, value):
    names = {f.name for f in fields(cls) if f.init}
    if type(value) is not dict or set(value) != names:
        raise V2Error("Неизвестные или отсутствующие поля " + cls.__name__)
    return dict(value)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class CalibrationPlan:
    mode_id: str
    raw_format: RawFormat
    hardware_instance_id: str
    origin: str
    instrument: str
    conditions: str
    reference_uncertainty_v: float
    tolerance_v: float
    frequency_hz: float | None = None
    amplitude_kind: str = "Vpp"
    polarity: int = 1
    polarity_basis: str = ""
    dc_max_stddev_codes: float = 8.0
    dc_max_drift_codes: float = 4.0
    ac_max_residual_ratio: float = .02
    created_at_utc: str = field(default_factory=utc_now)

    def __post_init__(self):
        mode = nominal_mode(self.mode_id)
        if type(self.raw_format) is not RawFormat:
            raise V2Error("Нужен фактический формат исходных кодов")
        self.raw_format.__post_init__()
        for name in ("hardware_instance_id", "instrument", "conditions"):
            text(getattr(self, name), name, 80 if name == "hardware_instance_id" else 256)
            if not getattr(self, name).strip():
                raise V2Error("Заполните экземпляр платы, прибор и условия")
        if self.origin not in ("synthetic", "device"):
            raise V2Error("Неизвестное происхождение калибровки")
        for name in ("reference_uncertainty_v", "tolerance_v", "dc_max_stddev_codes",
                     "dc_max_drift_codes", "ac_max_residual_ratio"):
            finite(getattr(self, name), name)
        if (self.reference_uncertainty_v < 0 or self.tolerance_v <= 0 or
                self.dc_max_stddev_codes <= 0 or self.dc_max_drift_codes <= 0 or
                not 0 < self.ac_max_residual_ratio <= .1):
            raise V2Error("Некорректные заранее заданные критерии качества")
        if self.origin == "device" and self.reference_uncertainty_v == 0:
            raise V2Error("У реального контрольного прибора укажите ненулевую погрешность")
        if self.amplitude_kind not in ("Vpp", "Vpk", "Vrms"):
            raise V2Error("Вид амплитуды должен быть Vpp, Vpk или Vrms")
        if type(self.polarity) is not int or self.polarity not in (-1, 1):
            raise V2Error("Укажите подтверждённый знак передачи +1 или −1")
        if mode.coupling == "AC":
            finite(self.frequency_hz, "Частота контрольной синусоиды")
            if not 0 < self.frequency_hz <= self.raw_format.sample_rate_hz / 10:
                raise V2Error("Для оценки синусоиды нужны не менее 10 отсчётов на период")
            text(self.polarity_basis, "Основание знака передачи", 256)
        elif self.frequency_hz is not None:
            raise V2Error("DC WIDE калибруется постоянными уровнями")
        _stamp(self.created_at_utc)

    @classmethod
    def from_dict(cls, value):
        value = _strict(cls, value)
        value["raw_format"] = RawFormat.from_dict(value["raw_format"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class SampleWindow:
    """Raw excerpt; prepared_at_utc is host preparation, not acquisition time.

    The stream journal has no measured UTC timestamp for this excerpt. Any
    operator-reported measurement time belongs in the plan's conditions.
    """
    codes: tuple[int, ...]
    source_id: str
    raw_format: RawFormat
    mode_id: str
    hardware_instance_id: str
    origin: str = "synthetic"
    first_sample_index: int = 0
    has_gaps: bool = False
    settled_confirmed: bool = True
    prepared_at_utc: str = field(default_factory=utc_now)

    def __post_init__(self):
        nominal_mode(self.mode_id)
        if type(self.raw_format) is not RawFormat:
            raise V2Error("Нужен формат исходного участка")
        self.raw_format.__post_init__()
        text(self.source_id, "Источник участка", 256)
        text(self.hardware_instance_id, "Экземпляр платы", 80)
        if self.origin not in ("device", "synthetic"):
            raise V2Error("Неизвестное происхождение участка")
        if type(self.codes) is not tuple or not 128 <= len(self.codes) <= MAX_SAMPLES:
            raise V2Error(f"Выберите непрерывный участок из 128…{MAX_SAMPLES} отсчётов")
        fmt = self.raw_format
        if any(type(n) is not int or not 0 <= n <= fmt.canonical_max or
               n % fmt.canonical_step for n in self.codes):
            raise V2Error("Коды участка не соответствуют сохранённому формату ADC12")
        if type(self.first_sample_index) is not int or not 0 <= self.first_sample_index < 2**63:
            raise V2Error("Некорректный исходный индекс")
        if type(self.has_gaps) is not bool or type(self.settled_confirmed) is not bool:
            raise V2Error("Неизвестное качество участка")
        _stamp(self.prepared_at_utc)

    @classmethod
    def from_dict(cls, value):
        value = _strict(cls, value)
        if type(value["codes"]) is not list:
            raise V2Error("Коды должны быть массивом")
        value["codes"] = tuple(value["codes"])
        value["raw_format"] = RawFormat.from_dict(value["raw_format"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class PointSummary:
    source_id: str
    first_sample_index: int
    count: int
    raw_sha256: str
    prepared_at_utc: str
    mean_code: float
    stddev_codes: float
    drift_codes: float
    minimum_code: int
    maximum_code: int
    amplitude_pk_codes: float | None
    residual_rms_codes: float | None

    @classmethod
    def from_dict(cls, value):
        return cls(**_strict(cls, value))


def _summarize(plan, window, ac=False):
    if type(window) is not SampleWindow:
        raise V2Error("Нужен исходный участок")
    window.__post_init__()
    if any(getattr(plan, name) != getattr(window, name) for name in
           ("raw_format", "mode_id", "hardware_instance_id", "origin")):
        raise V2Error("Участок относится к другому входу, режиму, формату АЦП или происхождению")
    if window.has_gaps or not window.settled_confirmed:
        raise V2Error("Калибровка требует установившийся непрерывный участок без пропусков")
    samples = np.asarray(window.codes, dtype=np.float64)
    minimum, maximum = min(window.codes), max(window.codes)
    if minimum == 0 or maximum == plan.raw_format.canonical_max:
        raise V2Error("В участке есть крайние корзины АЦП; исключите ограничение сигнала")
    quarter = len(samples) // 4
    drift = abs(float(samples[-quarter:].mean() - samples[:quarter].mean()))
    amplitude = residual = None
    if ac:
        # Least squares estimates sinusoid and independent DC offset. The
        # fitted offset does NOT replace the separately measured zero point.
        cycles = len(samples) * plan.frequency_hz / plan.raw_format.sample_rate_hz
        if cycles < 10:
            raise V2Error("Для AC выберите не менее 10 периодов синусоиды")
        phase = np.arange(len(samples)) * (2 * np.pi * plan.frequency_hz / plan.raw_format.sample_rate_hz)
        matrix = np.column_stack((np.sin(phase), np.cos(phase), np.ones(len(samples))))
        fitted, _, rank, _ = np.linalg.lstsq(matrix, samples, rcond=None)
        if rank != 3:
            raise V2Error("Не удалось различить синусоиду и её смещение")
        amplitude = float(np.hypot(*fitted[:2]))
        residual = float(np.sqrt(np.mean((samples - matrix @ fitted) ** 2)))
        if amplitude < 16 * plan.raw_format.canonical_step:
            raise V2Error("Амплитуда кодов слишком мала относительно шага АЦП")
        if residual / (amplitude / sqrt(2)) > plan.ac_max_residual_ratio:
            raise V2Error("Участок не согласуется с синусоидой: проверьте частоту, шум и ограничение")
    return PointSummary(window.source_id, window.first_sample_index, len(window.codes),
        hashlib.sha256(struct.pack(f"<{len(window.codes)}H", *window.codes)).hexdigest(),
        window.prepared_at_utc, float(samples.mean()), float(samples.std()), drift,
        minimum, maximum, amplitude, residual)


def validate_sample_window(plan, window, *, ac_signal=False):
    """Same raw quality checks for preview and fitting; no gain is applied."""
    point = _summarize(plan, window, ac=ac_signal)
    if not ac_signal and (point.stddev_codes > plan.dc_max_stddev_codes or
                          point.drift_codes > plan.dc_max_drift_codes):
        raise V2Error("DC/нулевой участок не установился: слишком велики шум или дрейф")
    return point


def _validate_summaries(plan, summaries, references):
    if len(summaries) not in (2, 3) or len(references) != len(summaries):
        raise V2Error("Нужны две точки подбора и отдельная контрольная точка")
    for value in references:
        finite(value, "Измеренное значение CH1")
    for i, point in enumerate(summaries):
        text(point.source_id, "Источник", 256)
        _stamp(point.prepared_at_utc)
        if (type(point.count) is not int or not 128 <= point.count <= MAX_SAMPLES or
                type(point.first_sample_index) is not int or not 0 <= point.first_sample_index < 2**63 or
                type(point.raw_sha256) is not str or len(point.raw_sha256) != 64 or
                any(c not in "0123456789abcdef" for c in point.raw_sha256)):
            raise V2Error("Некорректное свидетельство исходного участка")
        for name in ("mean_code", "stddev_codes", "drift_codes"):
            finite(getattr(point, name), name)
        if (type(point.minimum_code) is not int or type(point.maximum_code) is not int or
                not 0 < point.minimum_code <= point.mean_code <= point.maximum_code < plan.raw_format.canonical_max or
                min(point.stddev_codes, point.drift_codes) < 0):
            raise V2Error("Недопустимая статистика/насыщение участка")
        ac = plan.mode_id != "DC_WIDE" and i != 0
        if ac:
            finite(point.amplitude_pk_codes, "Амплитуда кодов")
            finite(point.residual_rms_codes, "Остаток синусоиды")
            if (point.amplitude_pk_codes < 16 * plan.raw_format.canonical_step or
                    point.residual_rms_codes < 0 or
                    point.residual_rms_codes / (point.amplitude_pk_codes / sqrt(2)) > plan.ac_max_residual_ratio or
                    point.count * plan.frequency_hz / plan.raw_format.sample_rate_hz < 10 or
                    references[i] <= plan.reference_uncertainty_v):
                raise V2Error("Некорректная оценка синусоиды")
        elif (point.amplitude_pk_codes is not None or point.residual_rms_codes is not None or
                point.stddev_codes > plan.dc_max_stddev_codes or
                point.drift_codes > plan.dc_max_drift_codes):
            raise V2Error("DC/нулевой участок не установился: слишком велики шум или дрейф")
        for before in summaries[:i]:
            if point.source_id == before.source_id and max(point.first_sample_index, before.first_sample_index) < min(
                    point.first_sample_index + point.count, before.first_sample_index + before.count):
                raise V2Error("Точки должны использовать разные, не перекрывающиеся исходные участки")
    if plan.mode_id == "DC_WIDE":
        delta = abs(summaries[1].mean_code - summaries[0].mean_code)
        if delta < max(16 * plan.raw_format.canonical_step,
                       8 * max(summaries[0].stddev_codes, summaries[1].stddev_codes)):
            raise V2Error("Постоянные уровни слишком близки относительно шума и шага АЦП")
        if abs(references[1] - references[0]) <= 2 * plan.reference_uncertainty_v:
            raise V2Error("Опорные напряжения неразличимы с учётом погрешности прибора")
        if len(references) == 3 and not min(references[:2]) < references[2] < max(references[:2]):
            raise V2Error("Выберите независимую контрольную точку строго между двумя опорными напряжениями")
    else:
        if references[0] != 0:
            raise V2Error("Нулевая AC-точка должна быть отдельной записью при CH1–AGND")
        if len(references) == 3 and abs(references[2] - references[1]) <= 2 * plan.reference_uncertainty_v:
            raise V2Error("Для контроля AC задайте другую, различимую амплитуду")


def _amplitude_factor(kind):
    # Multiply Vpk to obtain the selected amplitude of a SINUSOID only.
    return {"Vpk": 1., "Vpp": 2., "Vrms": 1 / sqrt(2)}[kind]


def _coefficients(plan, points, references):
    if plan.mode_id == "DC_WIDE":
        a = (references[1] - references[0]) / (points[1].mean_code - points[0].mean_code)
        return a, references[0] - a * points[0].mean_code
    a = plan.polarity * references[1] / _amplitude_factor(plan.amplitude_kind) / points[1].amplitude_pk_codes
    return a, -a * points[0].mean_code


def _mean_uncertainty(point, step):
    # Conservative bounded quantization and observed drift, plus 3 SEM noise.
    # This is an acceptance budget, not a certified metrological uncertainty.
    return step / 2 + point.drift_codes / 2 + 3 * point.stddev_codes / sqrt(point.count)


def _control(plan, points, references):
    if len(points) < 3:
        return None, None
    a, b = _coefficients(plan, points, references)
    step, ref = plan.raw_format.canonical_step, plan.reference_uncertainty_v
    p1, p2, p3 = points
    if plan.mode_id == "DC_WIDE":
        value = a * p3.mean_code + b
        fraction = (p3.mean_code - p1.mean_code) / (p2.mean_code - p1.mean_code)
        weights = (abs(1 - fraction), abs(fraction))
        uncertainty = ref * (1 + sum(weights)) + abs(a) * (
            _mean_uncertainty(p3, step) + sum(w * _mean_uncertainty(p, step)
                                            for w, p in zip(weights, (p1, p2))))
    else:
        factor = _amplitude_factor(plan.amplitude_kind)
        value = abs(a) * p3.amplitude_pk_codes * factor
        def amp_uncertainty(p):
            # The two fitted sine/cosine coefficients share quantization
            # error. Use a full code step for amplitude, not half a step of
            # an individual sample; the >=10-cycle gate keeps conditioning
            # close to the orthogonal sine/cosine case.
            return step + 3 * p.residual_rms_codes * sqrt(2 / p.count)
        uncertainty = ref + value * (ref / references[1] +
            amp_uncertainty(p2) / p2.amplitude_pk_codes +
            amp_uncertainty(p3) / p3.amplitude_pk_codes)
    error = value - references[2]
    bound = abs(error) + uncertainty
    if not all(isfinite(v) for v in (error, bound)):
        raise V2Error("Контрольная ошибка или её граница не определена")
    return error, bound


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    plan: CalibrationPlan
    windows: tuple[SampleWindow, ...]
    reference_values: tuple[float, ...]
    fit_at_utc: str = field(default_factory=utc_now)
    control_checked_at_utc: str | None = None
    format_version: int = 1
    algorithm: str = ALGORITHM
    _summaries: tuple[PointSummary, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self.plan) is not CalibrationPlan:
            raise V2Error("Нужен зафиксированный план калибровки")
        self.plan.__post_init__()
        if type(self.windows) is not tuple or type(self.reference_values) is not tuple or len(self.windows) not in (2, 3):
            raise V2Error("Некорректный набор исходных точек")
        if type(self.format_version) is not int or self.format_version != 1 or self.algorithm != ALGORITHM:
            raise V2Error("Неизвестная версия калибровки")
        if _stamp(self.fit_at_utc) < _stamp(self.plan.created_at_utc):
            raise V2Error("Критерии должны быть заданы до подбора коэффициентов")
        if len(self.windows) == 3:
            if self.control_checked_at_utc is None or _stamp(self.control_checked_at_utc) < _stamp(self.fit_at_utc):
                raise V2Error("Контроль проводится отдельно после подбора коэффициентов")
        elif self.control_checked_at_utc is not None:
            raise V2Error("Контрольной точки ещё нет")
        summaries = tuple(_summarize(self.plan, w, self.plan.mode_id != "DC_WIDE" and i != 0)
                          for i, w in enumerate(self.windows))
        _validate_summaries(self.plan, summaries, self.reference_values)
        object.__setattr__(self, "_summaries", summaries)
        a, b = _coefficients(self.plan, summaries, self.reference_values)
        if not all(isfinite(v) for v in (a, b, a * 4095 + b)) or a == 0:
            raise V2Error("Коэффициенты не определены")

    @property
    def summaries(self):
        return self._summaries

    @property
    def a(self):
        return _coefficients(self.plan, self.summaries, self.reference_values)[0]

    @property
    def b(self):
        return _coefficients(self.plan, self.summaries, self.reference_values)[1]

    @property
    def control_error_v(self):
        return _control(self.plan, self.summaries, self.reference_values)[0]

    @property
    def control_bound_v(self):
        return _control(self.plan, self.summaries, self.reference_values)[1]

    @property
    def state(self):
        if self.control_bound_v is None:
            return "fit_pending_validation"
        if self.control_bound_v > self.plan.tolerance_v:
            return "control_failed"
        return "synthetic_verified" if self.plan.origin == "synthetic" else "validated_operator"

    @property
    def can_apply(self):
        return self.state == "validated_operator"

    def to_dict(self):
        return {"format_version": self.format_version, "algorithm": self.algorithm,
                "plan": asdict(self.plan),
                "windows": [{**asdict(w), "codes": list(w.codes)} for w in self.windows],
                "reference_values": list(self.reference_values), "fit_at_utc": self.fit_at_utc,
                "control_checked_at_utc": self.control_checked_at_utc}

    @classmethod
    def from_dict(cls, value):
        value = _strict(cls, value)
        if type(value["windows"]) is not list or type(value["reference_values"]) is not list:
            raise V2Error("Нужны массивы исходных точек")
        value["plan"] = CalibrationPlan.from_dict(value["plan"])
        value["windows"] = tuple(SampleWindow.from_dict(w) for w in value["windows"])
        value["reference_values"] = tuple(value["reference_values"])
        return cls(**value)


def fit_dc(plan, first, first_v, second, second_v):
    if plan.mode_id != "DC_WIDE":
        raise V2Error("Две постоянные точки применимы только к DC WIDE")
    return CalibrationRecord(plan, (first, second), (first_v, second_v))


def fit_ac(plan, zero, signal, known_amplitude):
    if plan.mode_id == "DC_WIDE":
        raise V2Error("Выберите отдельный AC WIDE или AC SENSITIVE")
    return CalibrationRecord(plan, (zero, signal), (0., known_amplitude))


def validate_control(draft, window, known_value):
    if type(draft) is not CalibrationRecord or len(draft.windows) != 2:
        raise V2Error("Контроль добавляется один раз к неизменённому подбору; сохраните прежний результат")
    return CalibrationRecord(draft.plan, (*draft.windows, window), (*draft.reference_values, known_value),
                             draft.fit_at_utc, utc_now())


def save_calibration(path, record):
    if type(record) is not CalibrationRecord:
        raise V2Error("Нужна запись калибровки")
    payload = _canonical(record.to_dict())
    if len(payload) > MAX_FILE_BYTES:
        raise V2Error("Запись калибровки слишком велика")
    with Path(path).open("xb") as handle:
        handle.write(payload)
    return str(path)


def load_calibration(path):
    from ..recording import _object, _invalid_number
    with Path(path).open("rb") as handle:
        payload = handle.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise V2Error("Файл калибровки слишком велик")
    try:
        value = json.loads(payload, object_pairs_hook=_object, parse_constant=_invalid_number)
        return CalibrationRecord.from_dict(value)
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError) as exc:
        raise V2Error("Невозможно прочитать калибровку: " + str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CalibrationCertificate:
    """Small evidence snapshot; full source windows remain in calibration JSON."""
    plan: CalibrationPlan
    summaries: tuple[PointSummary, ...]
    reference_values: tuple[float, ...]
    record_sha256: str
    fit_at_utc: str
    control_checked_at_utc: str
    algorithm: str = ALGORITHM

    def __post_init__(self):
        if type(self.plan) is not CalibrationPlan or self.plan.origin != "device":
            raise V2Error("Искусственные данные не калибруют физический вход")
        self.plan.__post_init__()
        if (type(self.summaries) is not tuple or len(self.summaries) != 3 or
                any(type(p) is not PointSummary for p in self.summaries) or
                type(self.reference_values) is not tuple or self.algorithm != ALGORITHM):
            raise V2Error("Неполное свидетельство калибровки")
        if (type(self.record_sha256) is not str or len(self.record_sha256) != 64 or
                any(c not in "0123456789abcdef" for c in self.record_sha256)):
            raise V2Error("Нужен SHA-256 полной записи калибровки")
        if not _stamp(self.plan.created_at_utc) <= _stamp(self.fit_at_utc) <= _stamp(self.control_checked_at_utc):
            raise V2Error("Нарушен порядок критерии — подбор — контроль")
        _validate_summaries(self.plan, self.summaries, self.reference_values)
        if _control(self.plan, self.summaries, self.reference_values)[1] > self.plan.tolerance_v:
            raise V2Error("Независимая контрольная точка не прошла выбранный критерий")

    @classmethod
    def from_record(cls, record):
        if not record.can_apply:
            raise V2Error("Применение требует реальных данных и успешной независимой проверки")
        return cls(record.plan, record.summaries, record.reference_values, _digest(record.to_dict()),
                   record.fit_at_utc, record.control_checked_at_utc)

    @classmethod
    def from_dict(cls, value):
        value = _strict(cls, value)
        if type(value["summaries"]) not in (list, tuple) or type(value["reference_values"]) not in (list, tuple):
            raise V2Error("Некорректные контрольные точки")
        value["plan"] = CalibrationPlan.from_dict(value["plan"])
        value["summaries"] = tuple(PointSummary.from_dict(p) for p in value["summaries"])
        value["reference_values"] = tuple(value["reference_values"])
        return cls(**value)

    @property
    def profile(self):
        a, b = _coefficients(self.plan, self.summaries, self.reference_values)
        mode = nominal_mode(self.plan.mode_id)
        scope = ("DC; проверены 2 опорных уровня и 1 контрольный." if mode.coupling == "DC" else
                 f"Синусоида {self.plan.frequency_hz:g} Гц; DC не измеряется; полоса не проверена.")
        return InputProfile(a=a, b=b, state="calibrated", profile_id="r5-measured-" + self.record_sha256,
            frontend_id="Analog_LUT_R5", frontend_revision="R5.1", range_id=mode.range_id,
            coupling=mode.coupling, coefficient_source="operator_measurements_and_independent_control",
            calibration_id=self.record_sha256, calibration_version="1",
            calibration_date=self.control_checked_at_utc, measurement_point="CH1_before_input_divider",
            ground_reference="AGND", conditions=scope + " Происхождение заявлено; защита и весь диапазон не подтверждены.")


def calibrated_selection(record, identity, *, hardware_instance_id, confirmed_at_utc=None):
    from .analog_profile import AnalogSnapshot
    certificate = CalibrationCertificate.from_record(record)
    fmt = identity if type(identity) is RawFormat else RawFormat.from_identity(identity)
    if fmt != record.plan.raw_format or hardware_instance_id != record.plan.hardware_instance_id:
        raise V2Error("Калибровка относится к другому экземпляру или режиму приёма АЦП")
    snapshot = AnalogSnapshot(record.plan.mode_id, fmt, confirmed_at_utc or utc_now(),
        hardware_instance_id, schema_version=2, profile_version=2,
        calibration_progress="validated_operator", calibration=certificate)
    return certificate.profile, snapshot
