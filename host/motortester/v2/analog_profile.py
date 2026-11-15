"""R5 electrical model, explicit operator selection, and immutable provenance.

R5.3 changes the PCB placement, not these R5.1 circuit coefficients. This
module never configures hardware switches or identifies a board. Measured
profiles require a separate calibration certificate. ADC12 lower-edge
coordinates use N*Vref/4096, also after retained10
normalization. All voltages refer to CH1 before the divider relative to AGND.
"""
from dataclasses import dataclass, fields
from datetime import datetime, timezone

from .input import InputProfile, V2Error, finite, text


SOURCE_ARCHIVE_SHA256 = "ddec83fd287bb4f7cd5341324f07445ec804d8ef839b7e7ce4ea74b4109cf777"
MODEL_SHA256 = "349fbec1351f64c81d6f25fb8a2819e5d768988da3cd59bd20773f0c48984324"
ASSIGNMENT_SHA256 = "26639b674b5142ac5aeb4ecc6366b7cc64de16e0e3fb987a3a7b45888d0f32aa"


@dataclass(frozen=True, slots=True)
class NominalMode:
    mode_id: str
    label: str
    coupling: str
    range_id: str
    gain: float
    offset_adc_v: float
    gain_scope: str
    calibration_method: str


MODES = (
    NominalMode("DC_WIDE", "DC · WIDE", "DC", "WIDE", 0.036983582897348,
                1.6598232004329785, "DC_low_frequency", "dc_two_point_plus_independent_control"),
    NominalMode("AC_WIDE", "AC · WIDE", "AC", "WIDE", 0.03663767425235315,
                1.7235668789808918, "midband_only", "ac_zero_and_known_amplitude_frequency_plus_control"),
    NominalMode("AC_SENSITIVE", "AC · SENSITIVE", "AC", "SENSITIVE", 0.18628619087334683,
                1.7235668789808918, "midband_only", "ac_zero_and_known_amplitude_frequency_plus_control"),
)
MODE_IDS = tuple(mode.mode_id for mode in MODES)


def nominal_mode(mode_id):
    for mode in MODES:
        if mode.mode_id == mode_id:
            return mode
    raise V2Error("Разрешены только DC WIDE, AC WIDE и AC SENSITIVE")


def _strict_values(cls, value):
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise V2Error("Неполные или неизвестные поля: " + cls.__name__)
    return dict(value)


@dataclass(frozen=True, slots=True)
class RawFormat:
    sample_rate_hz: int
    acquisition_mode: int
    source_adc_bits: int
    retained_bits: int
    discarded_lsb: int
    wire_sample_encoding: str
    normalization: str
    quantization: str
    stored_sample_encoding: str
    stored_code_domain: str
    signed: bool = False
    adc_alignment: str = "right"
    canonical_min: int = 0
    canonical_max: int = 4095
    canonical_step: int = 1
    time_basis: str = "nominal_unverified"

    def __post_init__(self):
        for name in ("sample_rate_hz", "acquisition_mode", "source_adc_bits", "retained_bits",
                     "discarded_lsb", "canonical_min", "canonical_max", "canonical_step"):
            if type(getattr(self, name)) is not int:
                raise V2Error("Формат АЦП требует целые параметры")
        common = (self.source_adc_bits == 12 and self.signed is False and
                  self.adc_alignment == "right" and self.canonical_min == 0 and
                  self.stored_sample_encoding == "u16le" and self.stored_code_domain == "adc12" and
                  self.time_basis == "nominal_unverified")
        full = (self.sample_rate_hz in (50_000, 100_000) and
                self.acquisition_mode in (0, 1, 2) and
                (self.retained_bits, self.discarded_lsb, self.wire_sample_encoding,
                 self.normalization, self.quantization, self.canonical_max, self.canonical_step)
                == (12, 0, "u16le", "identity", "none", 4095, 1))
        packed = (self.sample_rate_hz == 150_000 and self.acquisition_mode == 5 and
                  (self.retained_bits, self.discarded_lsb, self.wire_sample_encoding,
                   self.normalization, self.quantization, self.canonical_max, self.canonical_step)
                  == (10, 2, "u10packed_le", "left_shift_2", "truncate_lsb", 4092, 4))
        if not common or not (full or packed):
            raise V2Error("Фактический формат АЦП не поддерживается профилем R5.1")
        if self.acquisition_mode in (1, 2) and self.sample_rate_hz != self.acquisition_mode * 50_000:
            raise V2Error("Режим АЦП не соответствует частоте")

    @classmethod
    def from_identity(cls, identity):
        from ..stream_model import StreamIdentity
        if type(identity) is not StreamIdentity:
            raise V2Error("Для выбора шкалы нужен фактический формат потока")
        identity.__post_init__()
        names = ("acquisition_mode", "source_adc_bits", "retained_bits", "discarded_lsb",
                 "wire_sample_encoding", "normalization", "quantization", "stored_sample_encoding",
                 "stored_code_domain")
        return cls(identity.nominal_fs_hz, **{name: getattr(identity, name) for name in names},
                   canonical_max=4092 if identity.retained_bits == 10 else 4095,
                   canonical_step=4 if identity.retained_bits == 10 else 1)

    @classmethod
    def from_connection(cls, connection):
        """The accepted CAPS exist before START; no session is invented.

        The wire contract fixes signedness/alignment/normalization for these
        exact capabilities. A combobox request alone is never evidence.
        """
        from .stream_device import StreamConnection
        if type(connection) is not StreamConnection:
            raise V2Error("Для выбора шкалы нужны согласованные возможности STM32")
        connection.__post_init__()
        caps = connection.observed_caps
        mode = caps[0] if connection.protocol_revision == "0.3" else 0
        bits = caps[8] if connection.protocol_revision == "0.3" else 12
        packed = bits == 10
        return cls(sample_rate_hz=caps[4], acquisition_mode=mode, source_adc_bits=caps[3],
            retained_bits=bits, discarded_lsb=2 if packed else 0,
            wire_sample_encoding="u10packed_le" if packed else "u16le",
            normalization="left_shift_2" if packed else "identity",
            quantization="truncate_lsb" if packed else "none", stored_sample_encoding="u16le",
            stored_code_domain="adc12", canonical_max=4092 if packed else 4095,
            canonical_step=4 if packed else 1)

    @classmethod
    def from_dict(cls, value):
        return cls(**_strict_values(cls, value))


@dataclass(frozen=True, slots=True)
class AnalogSnapshot:
    mode_id: str
    raw_format: RawFormat
    confirmed_at_utc: str
    hardware_instance_id: str | None = None
    schema_version: int = 1
    profile_version: int = 1
    frontend_design_id: str = "Analog_LUT_R5"
    schematic_revision: str = "R5"
    documentation_revision: str = "R5.1"
    pcb_reference_revision: str = "R5.3"
    source_archive_sha256: str = SOURCE_ARCHIVE_SHA256
    source_model_sha256: str = MODEL_SHA256
    source_assignment_sha256: str = ASSIGNMENT_SHA256
    switch_state_source: str = "operator"
    nominal_vref_v: float = 3.3
    measured_vref_v: float | None = None
    calculated_bandwidth_hz: float = 17_800.0
    measured_bandwidth_hz: float | None = None
    bandwidth_basis: str = "approx_17.8kHz_100pF_nominal_96_104pF_archive_20pF_SUM_model_not_measured"
    installed_opamp_mpn: str | None = None
    calibration_progress: str = "not_performed"
    verified_operating_range_v: tuple | None = None
    calibration: object | None = None

    def __post_init__(self):
        nominal_mode(self.mode_id)
        if type(self.raw_format) is not RawFormat:
            raise V2Error("Нужен неизменяемый формат АЦП")
        self.raw_format.__post_init__()
        text(self.hardware_instance_id, "Экземпляр входа", 80, optional=True)
        text(self.confirmed_at_utc, "Время подтверждения")
        stamp = datetime.fromisoformat(self.confirmed_at_utc)
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise V2Error("Подтверждение переключателей должно иметь время UTC")
        # A calibration is not a new claim about power, protection, bandwidth
        # or permitted range. Those measured fields deliberately remain None.
        calibrated = self.calibration is not None
        expected = dict(schema_version=2 if calibrated else 1,
            profile_version=2 if calibrated else 1, frontend_design_id="Analog_LUT_R5",
            schematic_revision="R5", documentation_revision="R5.1", pcb_reference_revision="R5.3",
            source_archive_sha256=SOURCE_ARCHIVE_SHA256, source_model_sha256=MODEL_SHA256,
            source_assignment_sha256=ASSIGNMENT_SHA256, switch_state_source="operator",
            nominal_vref_v=3.3, measured_vref_v=None, calculated_bandwidth_hz=17_800.0,
            measured_bandwidth_hz=None,
            bandwidth_basis="approx_17.8kHz_100pF_nominal_96_104pF_archive_20pF_SUM_model_not_measured",
            installed_opamp_mpn=None,
            calibration_progress="validated_operator" if calibrated else "not_performed",
            verified_operating_range_v=None)
        if any(getattr(self, name) != value or type(getattr(self, name)) is not type(value)
               for name, value in expected.items()):
            raise V2Error("Неизвестная редакция или неподтверждённые измеренные параметры R5.1")
        if calibrated:
            from .calibration import CalibrationCertificate
            if type(self.calibration) is not CalibrationCertificate:
                raise V2Error("Нужен неизменяемый протокол калибровки")
            self.calibration.__post_init__()
            plan = self.calibration.plan
            if (self.mode_id != plan.mode_id or self.raw_format != plan.raw_format or
                    self.hardware_instance_id != plan.hardware_instance_id):
                raise V2Error("Калибровка относится к другому режиму, АЦП или экземпляру платы")

    @property
    def dc_component_measured(self):
        return nominal_mode(self.mode_id).coupling == "DC"

    @property
    def calibration_method(self):
        return nominal_mode(self.mode_id).calibration_method

    def validate_identity(self, identity):
        if self.raw_format != RawFormat.from_identity(identity):
            raise V2Error("Снимок аналогового входа не соответствует формату текущего АЦП")

    def validate_profile(self, profile):
        expected = (self.calibration.profile if self.calibration is not None else
                    _nominal_profile(self.mode_id, self.hardware_instance_id))
        if type(profile) is not InputProfile or profile != expected:
            raise V2Error("Коэффициенты шкалы не соответствуют сохранённому профилю входа")

    @classmethod
    def from_dict(cls, value):
        # Existing version-1 recordings predate the optional certificate.
        if type(value) is dict and "calibration" not in value and value.get("schema_version") == 1:
            value = {**value, "calibration": None}
        raw = _strict_values(cls, value)
        raw["raw_format"] = RawFormat.from_dict(raw["raw_format"])
        if raw["calibration"] is not None:
            from .calibration import CalibrationCertificate
            raw["calibration"] = CalibrationCertificate.from_dict(raw["calibration"])
        return cls(**raw)


def _nominal_profile(mode_id, hardware_instance_id):
    mode = nominal_mode(mode_id)
    return InputProfile(a=3.3 / 4096 / mode.gain, b=-mode.offset_adc_v / mode.gain,
        state="nominal", profile_id="analog-lut-r5.1-" + mode_id.lower().replace("_", "-") + "-nominal-v1",
        frontend_id="Analog_LUT_R5", frontend_revision="R5.1", range_id=mode.range_id,
        coupling=mode.coupling, coefficient_source="ideal_circuit_calculation_R5.1",
        measurement_point="CH1_before_input_divider",
        ground_reference="AGND", vref_v=3.3, bandwidth_hz=17_800.0,
        conditions=("Расчётная шкала R5.1, не калибровано; полоса около 17,8 кГц по модели. "
                    + ("DC/низкие частоты." if mode.coupling == "DC" else
                       "Коэффициент только в полосе; постоянная составляющая CH1 не измеряется.")))


def nominal_selection(mode_id, identity, *, confirmed_at_utc=None, hardware_instance_id=None):
    """Called only after explicit manual confirmation, never on reconnect."""
    raw_format = identity if type(identity) is RawFormat else RawFormat.from_identity(identity)
    snapshot = AnalogSnapshot(mode_id, raw_format,
        confirmed_at_utc or datetime.now(timezone.utc).isoformat(), hardware_instance_id)
    return _nominal_profile(mode_id, hardware_instance_id), snapshot


def profile_description(profile, snapshot=None):
    if not profile.configured:
        return "Шкала В/мВ не настроена · служебные коды АЦП"
    if snapshot is not None:
        mode = nominal_mode(snapshot.mode_id)
        suffix = "; постоянная составляющая CH1 не измеряется" if mode.coupling == "AC" else ""
        if snapshot.calibration is not None:
            plan = snapshot.calibration.plan
            scope = "DC, отдельные точки" if mode.coupling == "DC" else f"синусоида {plan.frequency_hz:g} Гц"
            return f"R5 · {mode.label} · калибровка по данным оператора ({scope}){suffix}"
        return f"R5.1 · {mode.label} · расчётная шкала, не калибровано{suffix}"
    return "Расчётная шкала" if profile.state == "nominal" else "Шкала по сохранённому профилю"


def voltage_axis_label(profile):
    return ("Переменная составляющая CH1 (В)" if profile.coupling == "AC"
            else "Напряжение на CH1 (В)")


@dataclass(frozen=True, slots=True)
class QuantizedThresholds:
    trigger_code: int
    release_code: int
    code_polarity: str
    requested_threshold_v: float
    accepted_threshold_v: float
    requested_hysteresis_v: float
    accepted_hysteresis_v: float


def quantize_thresholds(profile, threshold_v, hysteresis_v, polarity, retained_bits):
    """Quantize both voltage levels, preserving polarity for negative gain."""
    if polarity not in ("above", "below") or type(retained_bits) is not int or retained_bits not in (12, 10):
        raise V2Error("Неизвестное направление или сохранённая разрядность")
    finite(hysteresis_v, "Гистерезис")
    if hysteresis_v <= 0:
        raise V2Error("Гистерезис должен быть положительным")
    step = 4 if retained_bits == 10 else 1
    trigger = profile.code(threshold_v, step)
    release_v = threshold_v + (-hysteresis_v if polarity == "above" else hysteresis_v)
    release = profile.code(release_v, step)
    code_polarity = polarity if profile.a > 0 else ("below" if polarity == "above" else "above")
    if trigger == release or (trigger > release) != (code_polarity == "above"):
        raise V2Error("После округления порог и возврат совпали; увеличьте гистерезис")
    accepted = profile.voltage(trigger)
    return QuantizedThresholds(trigger, release, code_polarity, threshold_v, accepted, hysteresis_v,
                               abs(accepted - profile.voltage(release)))
