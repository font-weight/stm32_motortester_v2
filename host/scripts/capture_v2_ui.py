"""Capture real Qt views without hardware or user settings.

Run from repository root: .venv\\Scripts\\python host\\scripts\\capture_v2_ui.py OUTPUT
Set QT_SCALE_FACTOR=1.5 before starting for the separate 150% DPI observation.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtWidgets
from motortester.v2.core import cursor_measurement
from motortester.v2.gui import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication([])
    app.setStyle("Fusion")
    evidence = {"platform": app.platformName(), "qt": QtCore.qVersion(), "images": {}}

    def capture(widget, name):
        app.processEvents()
        # Allow posted layout requests after a resize to settle before grabbing.
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(80, loop.quit)
        loop.exec()
        image = widget.grab()
        assert image.save(str(output / (name + ".png")))
        evidence["images"][name] = {
            "logical_size": [widget.width(), widget.height()],
            "pixels": [image.width(), image.height()],
            "device_pixel_ratio": image.devicePixelRatio(),
        }

    with tempfile.TemporaryDirectory(dir=output) as temporary:
        window = MainWindow(settings_path=Path(temporary) / "isolated.ini")
        window.timer.stop()
        window.show()
        app.processEvents()
        capture(window, "01_scope")
        original = window.display_recording
        before = cursor_measurement(original, window.cursor_a.value() / 1000,
                                    window.cursor_b.value() / 1000)
        window.units_combo.setCurrentIndex(1)
        after = cursor_measurement(window.display_recording, window.cursor_a.value() / 1000,
                                   window.cursor_b.value() / 1000)
        assert before == after and window.display_recording is original
        assert window.voltage_axis.factor == 1000 and window.threshold.factor == 1000
        capture(window, "08_millivolts")
        window.units_combo.setCurrentIndex(0)
        window.change_profile("ignition")
        window.waveform_combo.setCurrentIndex(2)
        window._tick()
        capture(window, "04_ignition")
        window.resize(1024, 700)
        capture(window, "05_compact")
        assert window.plot.height() >= 170 and window.axis_units.isVisible()
        assert not window.plot.getAxis("bottom").label.isVisible()
        assert window.plot.geometry().bottom() < window.cursor_label.geometry().top()
        assert window.cursor_label.geometry().bottom() < window.plot_card.height()
        window.resize(1440, 920)
        window.arm_single()
        for _ in range(4):
            window._tick()
            if window.armed_after is None:
                break
        assert window.single and window.single.sample_count == 250
        capture(window, "06_single_ignition")
        assert "Неполное" not in window.quality_label.text()
        selected = window._visible_slice(window.single, 1079, 1084)
        assert selected.sample_count == 250 and not selected.quality_flags

        def capture_dialog():
            dialog = app.activeModalWidget()
            assert isinstance(dialog, QtWidgets.QDialog)
            capture(dialog, "07_rename")
            dialog.reject()

        QtCore.QTimer.singleShot(50, capture_dialog)
        window.rename_dialog()
        window.single_dirty = False
        window.close()
    evidence["checks"] = [
        "V/mV display keeps the same raw snapshot and physical cursor measurement",
        "compact plot >=170px; plot/cursor geometries do not overlap; explicit units",
        "ignition 5ms single capture has 250 samples; rename dialog opens",
        "floating viewport boundaries do not add false truncated flags to a complete capture",
    ]
    evidence["status"] = "PASS"
    (output / "result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: real Qt visual capture; {output.resolve()}")


if __name__ == "__main__":
    main()
