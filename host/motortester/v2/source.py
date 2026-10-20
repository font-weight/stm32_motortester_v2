"""Deterministic synthetic data; no device capability is implied."""
import math
from .data import SignalBlock, MAX_INDEX
from .input import DEMO_PROFILE, V2Error


class DemoSource:
    def __init__(self, waveform="sine", sample_rate_hz=50_000):
        if waveform not in ("sine", "square", "ignition"):
            raise V2Error("Неизвестный демонстрационный сигнал")
        if type(sample_rate_hz) is not int or not 1_000 <= sample_rate_hz <= 1_000_000:
            raise V2Error("Некорректная частота ДЕМО")
        self.waveform = waveform
        self.sample_rate_hz = sample_rate_hz
        self.next_index = 0
        self._gap = None

    def skip(self, count):
        if type(count) is not int or count < 1 or self.next_index + count > MAX_INDEX:
            raise V2Error("Некорректная длина пропуска")
        self.next_index += count
        self._gap = "synthetic_missing_samples"

    def next_block(self, count=2500):
        if type(count) is not int or not 1 <= count <= 100_000:
            raise V2Error("Демонстрационный блок: 1…100000 отсчётов")
        raw = []
        for index in range(self.next_index, self.next_index + count):
            time = index / self.sample_rate_hz
            if self.waveform == "sine":
                voltage = 1.65 + 0.8 * math.sin(2 * math.pi * 250 * time)
            elif self.waveform == "square":
                voltage = 2.45 if (index * 250) % self.sample_rate_hz < self.sample_rate_hz // 2 else 0.85
            else:
                # 25 Hz, synthetic breakdown/plateau/ringing. These are model
                # features for demonstrations, not measured combustion stages.
                # Integer phase keeps exact cycle boundaries identical; floating
                # time % period can turn a zero phase into almost one period.
                phase = ((index * 25) % self.sample_rate_hz) / self.sample_rate_hz / 25
                voltage = 0.4
                if phase < 0.0016:
                    voltage += 2.05 * math.exp(-phase / 0.000045) + 0.65 - 90 * phase
                elif phase < 0.004:
                    tail = phase - 0.0016
                    voltage += 0.33 * math.exp(-tail / 0.00055) * math.sin(2 * math.pi * 7000 * tail)
            raw.append(DEMO_PROFILE.code(voltage))
        result = SignalBlock(self.next_index, self.sample_rate_hz, tuple(raw), gap_before=self._gap)
        self.next_index = result.end_index
        self._gap = None
        return result
