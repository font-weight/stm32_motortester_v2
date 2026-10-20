"""Read one existing synthetic archive; inspect layout only, without capture."""
import json
from pathlib import Path
import time
from unittest.mock import patch
from PySide6 import QtCore, QtWidgets
from motortester.v2.stream_ui import StreamDialog

output = Path(__file__).parent
app = QtWidgets.QApplication([])
app.setStyle("Fusion")
dialog = StreamDialog()
report = {"status": "FAIL", "scope": "layout only; existing synthetic file; no capture"}

def wait(predicate):
    deadline = time.monotonic() + 10
    while not predicate():
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("layout/open settlement")
        time.sleep(.005)
    app.processEvents()

try:
    with patch("serial.serialwin32.Serial.open", side_effect=AssertionError("COM forbidden")) as port:
        dialog.show()
        dialog.raw_view.setChecked(True)
        assert dialog.open_path("build/v5aw1/frozen-smoke/stop-unknown-tail.mtstream")
        wait(lambda: dialog.archive is not None and not dialog.busy and not dialog.viewer.busy)
        dialog.details.setChecked(True)
        frames = []
        for width, height in ((1220, 870), (850, 650)):
            dialog.resize(width, height)
            for _ in range(10):
                app.processEvents()
                time.sleep(.01)
            scroll = dialog.viewer.scroll_area
            for bottom in (False, True):
                scroll.verticalScrollBar().setValue(
                    scroll.verticalScrollBar().maximum() if bottom else 0)
                app.processEvents()
                content = dialog.viewer.content
                plot = dialog.viewer.plot
                plot_rect = QtCore.QRect(plot.mapTo(content, QtCore.QPoint()), plot.size())
                labels = {}
                for name in ("source_label", "range_label", "storage_label",
                             "index_label", "event_label", "status_label"):
                    label = getattr(dialog.viewer, name)
                    rect = QtCore.QRect(label.mapTo(content, QtCore.QPoint()), label.size())
                    assert not plot_rect.intersects(rect), name
                    labels[name] = [rect.x(), rect.y(), rect.width(), rect.height()]
                name = f"layout-{width}-{'bottom' if bottom else 'top'}.png"
                assert dialog.grab().save(str(output / name))
                frames.append({"png": name, "plot": [plot_rect.x(), plot_rect.y(),
                    plot_rect.width(), plot_rect.height()], "labels": labels})
        report.update(status="PASS", frames=frames, real_COM_opens=port.call_count)
finally:
    dialog.close()
    wait(lambda: dialog.closed)
    (output / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": report["status"], "frames": len(report.get("frames", []))}))
