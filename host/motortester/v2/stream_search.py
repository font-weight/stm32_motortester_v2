"""Host event-search settings; time in ms, codes on the original ADC12 scale."""
from dataclasses import asdict, dataclass
import math

from ..stream_view import EventConfig, DETECTOR_VERSION
from ..stream_wire import SUPPORTED_SAMPLE_RATES


@dataclass(frozen=True, slots=True)
class SearchSnapshot:
    config: EventConfig
    config_revision: int
    algorithm_version: str = DETECTOR_VERSION

    def __post_init__(self):
        if type(self.config) is not EventConfig:
            raise ValueError("Нужен точный снимок параметров поиска")
        self.config.__post_init__()
        if type(self.config_revision) is not int or not 0 <= self.config_revision < 2**64:
            raise ValueError("Некорректная версия параметров поиска")
        if (type(self.algorithm_version) is not str or
                not 1 <= len(self.algorithm_version) <= 80):
            raise ValueError("Неизвестное описание алгоритма поиска")

    @classmethod
    def from_dict(cls, value):
        if (type(value) is not dict or set(value) != set(cls.__dataclass_fields__) or
                type(value['config']) is not dict or
                set(value['config']) != set(EventConfig.__dataclass_fields__)):
            raise ValueError("Некорректный снимок поиска событий")
        return cls(EventConfig(**value['config']), value['config_revision'], value['algorithm_version'])


def validate_config(config, fs, retained_bits):
    """Bounded V2 context; reduced bit depth still uses ADC12-scaled codes."""
    if fs not in SUPPORTED_SAMPLE_RATES or retained_bits not in (10, 12):
        raise ValueError("Неизвестная частота или разрядность поиска")
    config.__post_init__()
    high = 4092 if retained_bits == 10 else 4095
    if not (0 <= config.release_code <= high and 0 <= config.threshold_code <= high):
        raise ValueError(f"Порог и уровень возврата должны быть в пределах 0…{high} код")
    if config.rail_low != 0 or config.rail_high != high:
        raise ValueError("Границы кодов не соответствуют разрядности записи")
    if config.max_event_samples > round(fs * .2):
        raise ValueError("Контекст события не должен превышать 200 мс")
    return config


def make_config(*, fs, retained_bits, threshold, hysteresis, falling,
                holdoff_ms, window_ms, pre_percent, post_ms):
    values = (threshold, hysteresis, holdoff_ms, window_ms, pre_percent, post_ms)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Параметры должны быть конечными числами")
    if (not 0 < window_ms <= 200 or not 0 < pre_percent < 100 or
            not 0 <= post_ms <= 200 or not 0 <= holdoff_ms <= 1000 or hysteresis < 1):
        raise ValueError("Проверьте длительность, предысторию и гистерезис")
    if fs not in SUPPORTED_SAMPLE_RATES:
        raise ValueError("Сначала дождитесь согласования частоты")
    count = lambda ms: round(ms * fs / 1000)
    threshold, hysteresis = round(threshold), round(hysteresis)
    pre = count(window_ms * pre_percent / 100)
    if pre < 1:
        raise ValueError("Предыстория должна содержать хотя бы один отсчёт")
    baseline = min(pre, max(1, count(.5)))
    post, maximum = count(post_ms), count(window_ms)
    if pre + baseline + post + 1 > maximum:
        raise ValueError("Предыстория, возврат и хвост не помещаются в предел события")
    cfg = EventConfig(threshold, threshold + hysteresis if falling else threshold - hysteresis,
                      'below' if falling else 'above', pre, post, baseline,
                      count(holdoff_ms), maximum, 0, 4092 if retained_bits == 10 else 4095)
    return validate_config(cfg, fs, retained_bits)


def describe(config, fs):
    ms = lambda n: f'{n * 1000 / fs:g}'
    return (f"Порог {config.threshold_code} · возврат {config.release_code} код; "
            f"до {ms(config.pre_samples)} мс; хвост {ms(config.post_samples)} мс "
            f"после {ms(config.baseline_samples)} мс возврата; "
            f"предел {ms(config.max_event_samples)} мс; пауза {ms(config.holdoff_samples)} мс.")
