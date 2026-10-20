"""Plot saved model.py output; requires matplotlib, never touches the MCU.

python hardware/v2-input/p1-lv/model.py
python hardware/v2-input/p1-lv/plot.py
Writes model-report.png and model-report.svg into this directory.
"""

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from model import response


def main():
    folder = Path(__file__).resolve().parent
    data = json.loads((folder / "calculations.json").read_text(encoding="utf-8"))
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.alpha": 0.22, "svg.hashsalt": "HW-V2-02-P1",
    })
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("P1: расчёт низковольтного макета без датчика\n"
                 "РАСЧЁТ · ИДЕАЛЬНАЯ ЛИНЕЙНАЯ МОДЕЛЬ · НЕ ИЗМЕРЕНИЕ",
                 fontsize=16, weight="bold", y=0.99)
    colors = ("#d45c35", "#c38f18", "#18827d", "#4769ae")

    ax = axes[0, 0]
    time = [0.002 * n / 300 for n in range(301)]
    r_p1 = data["dc_nominal"]["r_input_thevenin_ohm"]
    for r, color, label in zip(
            (r_p1, 10e6, 100e6, 200e6), colors,
            (f"P1: {r_p1/1e6:.3f} МОм", "10 МОм", "100 МОм", "200 МОм")):
        tau = r * (1e-12 + 200e-12)
        ax.plot([t*1e3 for t in time], [100*math.exp(-t/tau) for t in time],
                label=label, color=color, linewidth=2)
    ax.set(title="Влияние нагрузки: условные Cs=1 пФ, Cg=200 пФ",
           xlabel="После скачка условного источника, мс",
           ylabel="Остаток от начального отклика, %", ylim=(0, 105))
    ax.legend(loc="center right", fontsize=9)
    ax.text(0.03, 0.04, "Модель малых изменений; DC-смещение BNC исключено.\n"
            "P1 не заменяет высокоомный вход для датчика.",
            transform=ax.transAxes, fontsize=8)

    ax = axes[0, 1]
    freq = [10 ** (1 + n * (math.log10(50e3)-1) / 500) for n in range(501)]
    for cp, color in zip((10e-12, 20e-12, 30e-12), ("#4769ae", "#18827d", "#d45c35")):
        ax.semilogx(freq, [20*math.log10(abs(response(f, cp=cp))) for f in freq],
                    label=f"C SUM = {cp*1e12:g} пФ", color=color)
    ax.axvline(3000, color="0.5", ls=":", linewidth=1)
    ax.axvline(25000, color="0.5", ls=":", linewidth=1)
    ax.set(title="Частотная характеристика: SUM + ФНЧ + RC",
           xlabel="Частота, Гц", ylabel="Относительно передачи на DC, дБ",
           ylim=(-100, 2), xlim=(10, 50e3))
    ax.legend(loc="lower left", fontsize=9)

    ax = axes[1, 0]
    step = next(s for s in data["steps_nominal_ideal"] if s["start_ch1_v"] == -10)
    for col, label, color in zip((1, 2, 3, 4), ("BUF", "ФНЧ 1", "ФНЧ 2", "Узел АЦП"), colors):
        ax.plot([row[0]*1e3 for row in step["trace"]],
                [row[col] for row in step["trace"]], label=label, color=color,
                linewidth=1.5, linestyle="--" if col == 3 else "-")
    ax.axhline(3.3, color="0.3", ls=":", label="Идеальная VDDA = 3,3 В")
    ax.axhline(0, color="0.3", ls=":")
    ax.set(title="Условный скачок CH1 −10 → +10 В",
           xlabel="Время, мс", ylabel="Напряжение узлов, В",
           xlim=(0, 0.8), ylim=(-0.1, 3.5))
    ax.legend(loc="lower right", fontsize=8)
    ax.text(0.39, 0.49, "±10 В — математический диапазон,\n"
            "не разрешение подавать его на макет.",
            transform=ax.transAxes, fontsize=8)

    ax = axes[1, 1]
    points = data["dc_points"]
    ax.plot([p["ch1_v"] for p in points], [p["adc_nominal_v"] for p in points],
            color="#18827d", marker="o", linewidth=2)
    ax.fill_between([p["ch1_v"] for p in points],
                    [p["adc_corner_min_max_v"][0] for p in points],
                    [p["adc_corner_min_max_v"][1] for p in points],
                    color="#18827d", alpha=0.18,
                    label="R ±0,1%; VDDA 3,2…3,4 В")
    ax.axvspan(0, 1, color="#e8b44c", alpha=0.3,
               label="План первого опыта: 0…1 В")
    ax.set(title="Расчётная DC-передача и выбранные углы допусков",
           xlabel="U CH1 относительно AGND, В", ylabel="U АЦП, В",
           xlim=(-10, 10), ylim=(0, 3.4))
    ax.legend(loc="upper left", fontsize=8)
    dc = data["dc_nominal"]
    ax.text(0.04, 0.05, f"U АЦП = {dc['k_v_per_v']:.6f} × U CH1 + {dc['offset_v']:.6f} В\n"
            f"Открытый BNC: {dc['v_open_bnc_v']:.3f} В; номинал, не измерение",
            transform=ax.transAxes, fontsize=9)

    fig.text(0.5, 0.018, "Не учтены реальные ОУ, защита, выключенное питание и АЦП во время выборки. "
             "Датчик, кабель и плата не изготовлены.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 0.92))
    fig.savefig(folder / "model-report.png", dpi=160)
    fig.savefig(folder / "model-report.svg", metadata={"Date": None})
    plt.close(fig)
    print("Written model-report.png and model-report.svg (calculation, not measurement).")


if __name__ == "__main__":
    main()
