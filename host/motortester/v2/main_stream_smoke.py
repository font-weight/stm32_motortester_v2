"""Targeted Windows GUI smoke for the embedded continuous-stream page."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets

from .data import Recording, SignalBlock
from .gui import MainWindow
from .input import UNKNOWN_PROFILE


def wait_until(app, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        QtCore.QThread.msleep(20)
    app.processEvents()
    return bool(predicate())


def check_connection_entry(app, window, output):
    """Follow the public controls with synthetic wire bytes; never touch COM."""
    from .serial_smoke import _Factory
    from .stream_profiles_smoke import ProfilesBackend
    from .stream_device import StreamDeviceBridge
    from .stream_ui import StreamDialog

    factory = _Factory(ProfilesBackend)

    class FixtureDialog(StreamDialog):
        def __init__(self, *args, **kwargs):
            kwargs["bridge_factory"] = lambda parent, **options: StreamDeviceBridge(
                parent, fake_backend_factory=factory, **options)
            super().__init__(*args, **kwargs)

    def answer_port(accept):
        dialog = app.activeModalWidget()
        if not isinstance(dialog, QtWidgets.QInputDialog):
            raise AssertionError("Выбор STM32 не открыл диалог порта")
        dialog.setTextValue("SYNTHETIC_ENTRY")
        dialog.accept() if accept else dialog.reject()

    with patch("motortester.v2.device.available_ports", return_value=[("SYNTHETIC_ENTRY", "Fixture")]), \
         patch("motortester.transport._serial_factory", side_effect=AssertionError("Real legacy transport forbidden")), \
         patch("serial.serialwin32.Serial.open", side_effect=AssertionError("Real COM forbidden")) as real_open, \
         patch("motortester.v2.stream_ui.StreamDialog", FixtureDialog):
        previous = window.waveform_combo.currentData()
        QtCore.QTimer.singleShot(0, lambda: answer_port(False))
        window.waveform_combo.setCurrentIndex(window.waveform_combo.findData("stream"))
        assert window.waveform_combo.currentData() == previous
        assert window.stream_dialog is None and window.device_panel is None and not factory.backends
        entry_png = Path(output).with_name(Path(output).stem + "-entry.png")
        entry_png.parent.mkdir(parents=True, exist_ok=True)
        app.processEvents()
        top = window.device_stream_button.mapTo(window, QtCore.QPoint(0, 0))
        assert window.device_stream_button.isVisible() and 0 < top.y() < 500
        assert window.grab().save(str(entry_png))

        QtCore.QTimer.singleShot(0, lambda: answer_port(True))
        window.waveform_combo.setCurrentIndex(window.waveform_combo.findData("stream"))
        panel = window.stream_dialog
        assert panel is not None and not panel.isWindow() and window.device_panel is None
        assert not window.device_active and not factory.backends  # Selection is inert.
        panel.rate_combo.setCurrentIndex(panel.rate_combo.findData(150_000))
        panel.connect_button.click()
        assert wait_until(app, lambda: panel.bridge.state.ready and panel.bridge.connection is not None)
        connection = panel.bridge.connection
        backend, = factory.backends
        assert connection.protocol_revision == "0.3"
        assert connection.observed_caps == (5, 5, 0, 12, 150_000, 1, 1024, 1, 10, 2)
        assert backend.commands == [1, 1, 2], "Connect sent acquisition commands"
        assert panel.bridge.state.validated_samples == 0
        ready_png = Path(output).with_name(Path(output).stem + "-connected.png")
        app.processEvents()
        assert window.grab().save(str(ready_png))
        panel.close_panel_button.click()
        assert wait_until(app, lambda: panel.closed and not window._stream_page_active)
        assert not backend.is_open and window._serial_owner is None

        QtCore.QTimer.singleShot(0, lambda: answer_port(True))
        window.device_stream_button.click()
        second = window.stream_dialog
        assert second is not panel and second.selection.port == "SYNTHETIC_ENTRY"
        assert window.device_panel is None and len(factory.backends) == 1
        second.close_panel_button.click()
        assert wait_until(app, lambda: second.closed and not window._stream_page_active)
        window.device_button.click()
        assert "старая прошивка" in window.device_panel.windowTitle()
        assert "Старая прошивка" in window.device_button.text()
        window.device_panel.hide()
        assert real_open.call_count == 0 and len(factory.backends) == 1
        assert panel.viewer._closed and second.viewer._closed
        return {"source_selector_routes_stream": True, "cancel_preserves_source": True,
                "primary_button_routes_stream": True, "legacy_explicit": True,
                "connect_150k_without_start": True, "connection_owners_closed": True}


def main(output, callback_errors):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["MotortesterV2-main-stream-smoke"])
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(prefix="motortester-main-stream-") as temporary:
        root = Path(temporary)
        window = MainWindow(settings_path=root / "settings.ini")
        window.show()
        window.timer.stop()
        route_checks = check_connection_entry(app, window, output)
        original = Recording((SignalBlock(0, 50_000, tuple(1000 + i % 100 for i in range(200)),
                                         quality_flags=("unknown_scale",)),),
                             input_profile=UNKNOWN_PROFILE)
        window.raw_view.setChecked(False)
        window._display(original, reset=True)
        window.sweep.set_value(.002)
        window.xposition.set_value(0)
        if window.raw_view.isChecked() or window._axis_kind != "voltage":
            raise AssertionError("Подготовка проверки не сохранила исходный unknown/raw=False экран")
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
        window.raw_view.setChecked(True)
        window.auto_scale()
        if window.statusBar().currentMessage() != "Ждём отсчёты для автомасштаба потока.":
            raise AssertionError("Автомасштаб без Preview не обработал пустой график")
        window.statusBar().clearMessage()
        if not panel.start_live():
            raise RuntimeError("Не удалось запустить ДЕМО-поток")
        if not wait_until(app, lambda: panel.viewer.selection is not None and
                          panel.viewer._identity is not None):
            raise TimeoutError("Потоковый график не получил исходные отсчёты")
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
                not window.stream_button.isEnabled() or not window.device_stream_button.isEnabled() or
                not window.device_button.isEnabled() or window.raw_view.isChecked() or
                window._axis_kind != "voltage" or window.yscale.suffix != "В/дел" or
                window.yposition.suffix != "В" or abs(window.sweep.value - .002) > 1e-9):
            raise AssertionError("Основные параметры не восстановились после выхода из потока")
        raw_checkbox_restored = not window.raw_view.isChecked()

        window.stream_button.click()
        if not wait_until(app, lambda: window._stream_page_active and
                          window.left_stack.currentWidget() is window.stream_dialog):
            raise AssertionError("Повторное открытие непрерывного приёма после возврата не сработало")
        second_panel = window.stream_dialog
        if not second_panel.start_live() or not wait_until(
                app, lambda: second_panel.viewer._identity is not None):
            raise AssertionError("Повторно открытая панель не запустила ДЕМО-поток")
        second_panel.close_panel_button.click()
        if not wait_until(app, lambda: second_panel.closed and
                          window.left_stack.currentWidget() is window.main_page):
            raise AssertionError("Повторная панель не закрылась с возвратом в главное окно")
        stream_reopened = (window.stream_button.isEnabled() and
                           window.device_stream_button.isEnabled() and
                           window.device_button.isEnabled())
        if not stream_reopened:
            raise AssertionError("Кнопки потока не восстановились после второго закрытия")
        cleanup_error = None
        try:
            if not window.close():
                cleanup_error = "Закрытие основного окна было отклонено"
            app.processEvents()
        except Exception as exc:
            cleanup_error = f"{type(exc).__name__}: {exc}"
        owners_closed = bool(panel.closed and panel.viewer._closed and
                             panel.cursors._closed and not panel._serial_reserved and
                             second_panel.closed and second_panel.viewer._closed and
                             second_panel.cursors._closed and not second_panel._serial_reserved)
        file_bytes = path.stat().st_size
        file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        saved_artifact = output.with_name(output.stem + "-recording.mtstream")
        shutil.copyfile(path, saved_artifact)
        if saved_artifact.stat().st_size != file_bytes or hashlib.sha256(saved_artifact.read_bytes()).hexdigest() != file_sha256:
            raise RuntimeError("Сохранённая копия журнала отличается от проверенной записи")
        failures = []
        if callback_errors:
            failures.append("Qt callback exceptions were captured")
        if cleanup_error is not None:
            failures.append("Cleanup raised or the main window refused to close")
        if not owners_closed:
            failures.append("One or more stream resources remained open")
        result = {
            "status": "PASS" if not failures else "FAIL",
            "frozen": bool(getattr(sys, "frozen", False)),
            "platform": sys.platform,
            "qt_platform": app.platformName(),
            "executable": sys.executable,
            "callback_errors": callback_errors,
            "cleanup_error": cleanup_error,
            "execution_kind": "DEMO + injected serial handshake",
            "physical_stream_verified": False,
            "owners_closed": owners_closed,
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
            "raw_checkbox_restored": raw_checkbox_restored,
            "empty_autoscale_handled": True,
            "stream_can_reopen": stream_reopened,
            "saved_file_bytes": file_bytes,
            "saved_file_sha256": file_sha256,
            "saved_recording_artifact": saved_artifact.name,
            "checks": {
                **route_checks,
                "embedded_widget": True,
                "capture_controls_hidden": True,
                "main_time_scale": True,
                "main_y_scale": True,
                "source_cursor_readback": True,
                "recording_continued_during_navigation": True,
                "saved_recording_reopened_in_main_window": True,
                "raw_checkbox_restored": raw_checkbox_restored,
                "empty_autoscale_handled": True,
                "stream_can_reopen": stream_reopened,
                "return_restores_main_controls": True,
            },
            "returned_to_main": True,
            "serial_ports": 0,
            "failures": failures,
        }
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return result


def run(output):
    callback_errors = []
    previous_excepthook = sys.excepthook

    def capture_qt_callback_error(exc_type, exc_value, traceback):
        callback_errors.append(f"{exc_type.__name__}: {exc_value}")
        previous_excepthook(exc_type, exc_value, traceback)

    sys.excepthook = capture_qt_callback_error
    try:
        result = main(output, callback_errors)
    finally:
        sys.excepthook = previous_excepthook
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m motortester.v2.main_stream_smoke OUTPUT.json")
    raise SystemExit(run(sys.argv[1]))
