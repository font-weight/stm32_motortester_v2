"""Immutable raw source blocks and bounded, one-channel recording snapshots."""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import uuid4
from .input import InputProfile, DEMO_PROFILE, V2Error, finite, text

MAX_SAMPLES = 2_000_000
MAX_BLOCKS = 4096
MAX_INDEX = (1 << 53) - 1


@dataclass(frozen=True, slots=True)
class CaptureSettings:
    threshold_v: float | None = 1.65
    edge: str = "rising"
    holdoff_s: float = 0.001
    pretrigger_fraction: float = 0.2
    window_s: float = 0.02
    hardware_threshold_code: int | None = None
    trigger_kind: str = "software"

    def __post_init__(self):
        if self.threshold_v is not None:
            finite(self.threshold_v, "threshold_v")
        for name in ("holdoff_s", "pretrigger_fraction", "window_s"):
            finite(getattr(self, name), name)
        if self.edge not in ("rising", "falling"):
            raise V2Error("Неизвестное направление фронта")
        if not 0 <= self.holdoff_s <= 60 or not 0 <= self.pretrigger_fraction < 1:
            raise V2Error("Некорректная пауза запуска или предыстория")
        if not 0 < self.window_s <= MAX_SAMPLES:
            raise V2Error("Некорректная длительность окна захвата")
        if self.hardware_threshold_code is not None and (
                type(self.hardware_threshold_code) is not int or not 0 <= self.hardware_threshold_code <= 4095):
            raise V2Error("Некорректный аппаратный порог")
        if self.trigger_kind not in ("software", "signal", "external", "auto_timeout"):
            raise V2Error("Неизвестный источник запуска")


@dataclass(frozen=True, slots=True)
class SignalBlock:
    start_index: int
    sample_rate_hz: float
    samples: tuple[int, ...]
    quality_flags: tuple[str, ...] = ()
    gap_before: str | None = None

    def __post_init__(self):
        if type(self.start_index) is not int or not 0 <= self.start_index <= MAX_INDEX:
            raise V2Error("Некорректный индекс начала блока")
        finite(self.sample_rate_hz, "Частота выборки")
        if not 1 <= self.sample_rate_hz <= 1_000_000:
            raise V2Error("Частота выборки вне поддерживаемых границ")
        if type(self.samples) is not tuple or not 1 <= len(self.samples) <= MAX_SAMPLES:
            raise V2Error("Нужен ограниченный неизменяемый массив отсчётов")
        if self.end_index > MAX_INDEX:
            raise V2Error("Индекс конца блока превышает предел")
        if any(type(code) is not int or not 0 <= code <= 4095 for code in self.samples):
            raise V2Error("Требуются исходные 12-битные коды 0…4095")
        if type(self.quality_flags) is not tuple or len(self.quality_flags) > 32:
            raise V2Error("Некорректные флаги качества")
        for flag in self.quality_flags:
            text(flag, "Флаг качества", 128)
        text(self.gap_before, "Причина разрыва", optional=True)

    @property
    def end_index(self):
        return self.start_index + len(self.samples)


@dataclass(frozen=True, slots=True)
class Gap:
    start_index: int
    end_index: int
    reason: str = "missing_samples"


@dataclass(frozen=True, slots=True)
class Recording:
    blocks: tuple[SignalBlock, ...]
    channel_name: str = "Канал 1"
    ui_profile: str = "oscilloscope"
    input_profile: InputProfile = DEMO_PROFILE
    source: str = "demo"
    capture_settings: CaptureSettings = field(default_factory=CaptureSettings)
    session_id: str = field(default_factory=lambda: str(uuid4()))
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    application_version: str = "2.0.0-dev1"
    firmware_version: str | None = None
    protocol_version: str | None = None
    time_basis: str = "synthetic_exact"
    legacy_format: str | None = None
    legacy_sequence: int | None = None
    trigger_index: int | None = None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.blocks) is not tuple or not 1 <= len(self.blocks) <= MAX_BLOCKS:
            raise V2Error("Запись должна содержать 1…4096 неизменяемых блоков")
        if any(type(block) is not SignalBlock for block in self.blocks):
            raise V2Error("Неизвестный тип блока")
        if self.sample_count > MAX_SAMPLES:
            raise V2Error("Достигнут предел записи: 2 000 000 отсчётов")
        previous = None
        for block in self.blocks:
            if block.sample_rate_hz != self.sample_rate_hz:
                raise V2Error("Смена частоты внутри сеанса пока не поддерживается")
            if previous is not None and block.start_index < previous:
                raise V2Error("Перекрывающиеся или переставленные блоки")
            previous = block.end_index
        text(self.channel_name, "Имя канала", 80)
        text(self.session_id, "Идентификатор сеанса", 128)
        if self.ui_profile not in ("oscilloscope", "ignition"):
            raise V2Error("Неизвестный профиль интерфейса")
        if self.source not in ("demo", "device"):
            raise V2Error("Неизвестное происхождение исходных измерений")
        if type(self.input_profile) is not InputProfile or type(self.capture_settings) is not CaptureSettings:
            raise V2Error("Некорректный снимок настроек")
        if self.time_basis not in ("synthetic_exact", "nominal_unverified", "measured"):
            raise V2Error("Неизвестная временная основа")
        if self.source == "device" and self.time_basis == "synthetic_exact":
            raise V2Error("Аппаратная запись не имеет синтетической временной основы")
        if self.source == "device" and self.input_profile.coefficient_source == "synthetic_demo_definition":
            raise V2Error("Синтетическая шкала не может назначаться аппаратным данным")
        for name in ("application_version", "created_at_utc"):
            text(getattr(self, name), name, 128)
        try:
            stamp = datetime.fromisoformat(self.created_at_utc.replace("Z", "+00:00"))
            if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
                raise ValueError()
        except ValueError as exc:
            raise V2Error("Нужна корректная дата UTC") from exc
        for name in ("firmware_version", "protocol_version", "legacy_format"):
            text(getattr(self, name), name, 128, optional=True)
        if self.legacy_sequence is not None and (
                type(self.legacy_sequence) is not int or not 0 <= self.legacy_sequence <= 0xFFFFFFFF):
            raise V2Error("Некорректный номер старого окна")
        if self.trigger_index is not None:
            if type(self.trigger_index) is not int or not any(
                    b.start_index <= self.trigger_index < b.end_index for b in self.blocks):
                raise V2Error("Индекс запуска не принадлежит исходным данным")
        if type(self.quality_flags) is not tuple or len(self.quality_flags) > 32:
            raise V2Error("Некорректные флаги записи")
        for flag in self.quality_flags:
            text(flag, "Флаг качества", 128)

    @property
    def sample_count(self):
        return sum(len(block.samples) for block in self.blocks)

    @property
    def sample_rate_hz(self):
        return self.blocks[0].sample_rate_hz

    @property
    def start_index(self):
        return self.blocks[0].start_index

    @property
    def end_index(self):
        return self.blocks[-1].end_index

    @property
    def duration_s(self):
        return (self.end_index - self.start_index) / self.sample_rate_hz

    @property
    def gaps(self):
        result = []
        previous = self.start_index
        for block in self.blocks:
            if block.start_index > previous or block.gap_before:
                result.append(Gap(previous, block.start_index, block.gap_before or "missing_samples"))
            previous = block.end_index
        return tuple(result)

    def iter_samples(self):
        for block in self.blocks:
            for offset, code in enumerate(block.samples):
                index = block.start_index + offset
                yield index, index / block.sample_rate_hz, code

    def sample_at_time(self, time_s):
        """Nearest sampled point; None outside data or inside a known gap.

        No interpolation across lost time. The returned timestamp describes the
        actual sample, so the caller can expose the <= half-sample quantization.
        """
        finite(time_s, "Время курсора")
        position = time_s * self.sample_rate_hz
        index = int(round(position))
        if abs(position - index) < 1e-7:
            position = index
        if not any(block.start_index <= position < block.end_index for block in self.blocks):
            return None
        for block in self.blocks:
            if block.start_index <= index < block.end_index:
                code = block.samples[index - block.start_index]
                voltage = self.input_profile.voltage(code) if self.input_profile.configured else None
                return index / self.sample_rate_hz, code, voltage
        return None

    def slice(self, start, stop):
        """Select actual available raw data without fabricating missing context."""
        if type(start) is not int or type(stop) is not int or start >= stop:
            raise V2Error("Нужны целочисленные границы непустого участка")
        selected = []
        for block in self.blocks:
            left, right = max(start, block.start_index), min(stop, block.end_index)
            if left < right:
                selected.append(replace(block, start_index=left,
                    samples=block.samples[left - block.start_index:right - block.start_index],
                    gap_before=block.gap_before if left == block.start_index else None))
        if not selected:
            raise V2Error("В выбранном участке нет отсчётов")
        flags = set(self.quality_flags)
        if start < selected[0].start_index:
            flags.add("left_truncated")
        if stop > selected[-1].end_index:
            flags.add("right_truncated")
        trigger = self.trigger_index if self.trigger_index is not None and start <= self.trigger_index < stop else None
        return replace(self, blocks=tuple(selected), trigger_index=trigger,
                       quality_flags=tuple(sorted(flags)))
