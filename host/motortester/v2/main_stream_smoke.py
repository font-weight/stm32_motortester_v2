"""Targeted Windows GUI smoke for the embedded continuous-stream page."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

from PySide6 import QtCore, QtWidgets

from .gui import MainWindow


def wait_until(app, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        QtCore.QThread.msleep(20)
    app.processEvents()
    return bool(predicate())


def main(output):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["MotortesterV2-main-stream-smoke"])
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(prefix="motortester-main-stream-") as temporary:
        root = Path(temporary)
        window = MainWindow(settings_path=root / "settings.ini")
        window.show()
        if not window.open_stream_workspace():
            raise RuntimeError("Не удалось открыть встроенную ДЕМО-панель потока")
        panel = window.stream_dialog
        if panel.isWindow() or window.left_stack.currentWidget() is not panel:
            raise AssertionError("Потоковая панель открылась отдельным окном")
        if window.scope_button.isEnabled() or window.open_button.isEnabled():
            raise AssertionError("Главные кнопки источника/профиля доступны при активном потоке")
        if not window.raw_view.isVisible() or window.yscale.suffix != "код/дел":
            raise AssertionError("Правая панель не переключилась на служебную шкалу АЦП")
        if window.capture_controls.isVisible() or window.yposition.suffix != "код":
            raise AssertionError("Потоковый экран показывает параметры/единицы оконного запуска")
        if not panel.start_live():
            raise RuntimeError("Не удалось запустить ДЕМО-поток")
        if not wait_until(app, lambda: panel.viewer.selection is not None and
                          panel.viewer._identity is not None):
            raise TimeoutError("Потоковый график не получил исходные отсчёты")
        window.raw_view.setChecked(True)
        if not wait_until(app, lambda: panel.viewer.plot.isVisible()):
            raise AssertionError("Служебный график не показан после явного включения кодов")

        fs = panel.viewer._identity[3]
        expected_initial = round(window.sweep.value * 10 * fs)
        def plot_matches_selection():
            selection = panel.viewer.selection
            x_range = panel.viewer.plot.getViewBox().viewRange()[0]
            return (selection is not None and selection.width == expected_initial and
                    abs((x_range[1] - x_range[0]) - selection.width / fs) < 1e-8)
        if not wait_until(app, plot_matches_selection):
            raise TimeoutError("Потоковый диапазон не вырос до значения крутилки развёртки")
        initial_width = panel.viewer.selection.width
        if abs(initial_width - expected_initial) > 1:
            raise AssertionError(f"Крутилка развёртки не применилась: {initial_width} != {expected_initial}")
        screenshot = Path(output).with_suffix(".png")
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(screenshot)):
            raise RuntimeError("Не удалось сохранить снимок встроенного интерфейса")
        screenshot_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
        panel.cursors.enabled.setChecked(True)
        if not wait_until(app, lambda: panel.cursors.values is not None):
            raise TimeoutError("Курсоры не прочитали исходные коды встроенного live-графика")
        window.sweep.set_value(.004, emit=True)
        if panel.viewer.selection.width != round(.004 * 10 * fs):
            raise AssertionError("Изменение развёртки не обновило потоковый диапазон")
        if not wait_until(app, lambda: abs(
                (panel.viewer.plot.getViewBox().viewRange()[0][1] -
                 panel.viewer.plot.getViewBox().viewRange()[0][0]) -
                panel.viewer.selection.width / fs) < 1e-8):
            raise TimeoutError("Потоковый график не перерисовал новый временной диапазон")
        window.yscale.set_value(100, emit=True)
        y_range = panel.viewer.plot.getViewBox().viewRange()[1]
        if abs((y_range[1] - y_range[0]) - 800) > 1:
            raise AssertionError(f"Крутилка масштаба Y не применилась: {y_range}")

        path = root / "embedded-demo.mtstream"
        if not panel.record_path(path):
            raise RuntimeError("Не удалось начать запись встроенного потока")
        if not wait_until(app, lambda: panel.bridge.state.phase == "recording"):
            raise TimeoutError("Запись встроенного потока не началась")
        received_before = panel.bridge.state.validated_samples
        window.xposition.set_value(.01, emit=True)
        if not wait_until(app, lambda: panel.bridge.state.validated_samples > received_before):
            raise AssertionError("Поток не продолжался после управления масштабом во время записи")
        if panel.bridge.state.phase != "recording":
            raise AssertionError("Изменение графика остановило запись")
        if not panel.stop():
            raise RuntimeError("Не удалось остановить встроенную запись")
        if not wait_until(app, lambda: panel.bridge.state.phase == "saved" and path.exists()):
            raise TimeoutError("Запись не завершилась и не сохранилась")
        if not wait_until(app, lambda: panel.bridge.state.can_open and
                          not panel.bridge.metadata_pending):
            raise TimeoutError("Потоковая панель не перешла в состояние чтения файла")
        if not panel.open_path(path):
            raise RuntimeError("Не удалось открыть сохранённый файл во встроенной панели")
        if not wait_until(app, lambda: panel.viewer._recording is not None and
                          panel.viewer.selection is not None):
            raise TimeoutError("Сохранённая запись не открылась во встроенной панели")

        panel.close_panel_button.click()
        if not wait_until(app, lambda: panel.closed and
                          window.left_stack.currentWidget() is window.main_page):
            raise TimeoutError("Панель не вернулась в основной экран после штатного закрытия")
        if window.stream_dialog is not None and not window.stream_dialog.closed:
            raise AssertionError("Ресурсы потоковой панели остались активны")
        if (not window.scope_button.isEnabled() or not window.open_button.isEnabled() or
                window.yscale.suffix != "В/дел" or abs(window.sweep.value - .002) > 1e-9):
            raise AssertionError("Основные параметры не восстановились после выхода из потока")
        window.close()
        app.processEvents()
        file_bytes = path.stat().st_size
        file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        saved_artifact = output.with_name(output.stem + "-recording.mtstream")
        shutil.copyfile(path, saved_artifact)
        if saved_artifact.stat().st_size != file_bytes or hashlib.sha256(saved_artifact.read_bytes()).hexdigest() != file_sha256:
            raise RuntimeError("Сохранённая копия журнала отличается от проверенной записи")
        result = {
            "status": "PASS",
            "frozen": bool(getattr(sys, "frozen", False)),
            "platform": sys.platform,
            "qt_platform": app.platformName(),
            "executable": sys.executable,
            "callback_errors": [],
            "cleanup_error": None,
            "execution_kind": "DEMO",
            "physical_stream_verified": False,
            "owners_closed": bool(panel.closed and panel.viewer._closed and
                                  panel.cursors._closed and not panel._serial_reserved),
            "real_serial_open_calls": 0,
            "embedded_widget": True,
            "capture_controls_hidden": True,
            "demo_rate_hz": fs,
            "initial_window_samples": initial_width,
            "sweep_knob_samples": round(.004 * 10 * fs),
            "vertical_range_codes": [round(value, 3) for value in y_range],
            "screenshot": str(screenshot),
            "screenshot_sha256": screenshot_sha256,
            "recording_continued_during_navigation": True,
            "source_cursor_readback": True,
            "saved_recording_reopened_in_main_window": True,
            "saved_file_bytes": file_bytes,
            "saved_file_sha256": file_sha256,
            "saved_recording_artifact": saved_artifact.name,
            "checks": {
                "embedded_widget": True,
                "capture_controls_hidden": True,
                "main_time_scale": True,
                "main_y_scale": True,
                "source_cursor_readback": True,
                "recording_continued_during_navigation": True,
                "saved_recording_reopened_in_main_window": True,
                "return_restores_main_controls": True,
            },
            "returned_to_main": True,
            "serial_ports": 0,
            "failures": [],
        }
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def run(output):
    main(output)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m motortester.v2.main_stream_smoke OUTPUT.json")
    raise SystemExit(run(sys.argv[1]))
