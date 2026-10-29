"""Focused native Qt witness: held live raw, pause/zoom and saved-file edges.

Uses only the existing DEMO peer; never constructs a serial connection.
The same short scenario runs from sources and the relocated Windows package.
"""
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import traceback
from unittest.mock import patch


def run(output_name):
    from PySide6 import QtCore, QtGui, QtTest, QtWidgets
    import numpy as np
    from .stream_device import StreamContext
    from .stream_ui import StreamDialog
    from ..gui_stream import DETAIL_SAMPLES

    output = Path(output_name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    report = dict(status='FAIL', platform=sys.platform, windows=platform.platform(),
                  qt_platform=app.platformName(), frozen=bool(getattr(sys, 'frozen', False)),
                  executable=sys.executable, execution_kind='DEMO', physical_stream_verified=False,
                  callback_errors=[], checks={})
    old_hook = sys.excepthook
    sys.excepthook = lambda *exc: report['callback_errors'].append(''.join(traceback.format_exception(*exc)))
    dialog = None

    def wait(predicate, timeout=10):
        deadline = time.monotonic()+timeout
        while not predicate():
            app.processEvents()
            if report['callback_errors']:
                raise AssertionError(report['callback_errors'])
            if time.monotonic() > deadline:
                raise AssertionError('Viewport wait timeout: ' + dialog.viewer.status_label.text())
            time.sleep(.005)
        app.processEvents()

    def drawn():
        p=dialog.viewer
        return not p.busy and p.selection is not None and p._display_origin == p.selection.start

    def wheel(delta):
        viewport=dialog.viewer.plot.viewport()
        pos=QtCore.QPointF(viewport.rect().center())
        event=QtGui.QWheelEvent(pos, viewport.mapToGlobal(pos.toPoint()), QtCore.QPoint(),
            QtCore.QPoint(0, delta), QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier, QtCore.Qt.ScrollPhase.NoScrollPhase, False)
        app.sendEvent(viewport, event)
        wait(drawn)

    def capture(name):
        app.processEvents()
        assert dialog.grab().save(str(output/name))

    try:
        assert sys.platform == 'win32' and app.platformName() == 'windows'
        # Guard against accidentally turning a GUI test into a COM test.
        with patch('serial.Serial.open', side_effect=AssertionError('COM forbidden')) as serial_open:
            dialog=StreamDialog(context=StreamContext(ui_profile='oscilloscope'))
            dialog.show(); dialog.raw_view.setChecked(True)
            assert dialog.start_live()
            wait(lambda: dialog.bridge.state.validated_samples > DETAIL_SAMPLES and
                         dialog.viewer._drawn_live is not None)
            path=output/'viewport.mtstream'
            assert dialog.record_path(path)
            wait(lambda: dialog.bridge.state.phase == 'recording')
            panel=dialog.viewer
            wheel(120)
            assert panel.holding_live and not panel.follow_tail
            held=panel._held_live
            selection=panel.selection
            arrays=tuple(a.copy() for a in panel.curve.getData())
            count=dialog.bridge.state.validated_samples
            wait(lambda: dialog.bridge.state.validated_samples > held.end_sample_index+DETAIL_SAMPLES+4096
                         and panel._raw_first > held.end_sample_index)
            assert dialog.bridge.state.phase == 'recording'
            assert panel._raw_first > held.end_sample_index
            assert panel.selection == selection
            assert all(np.array_equal(a,b) for a,b in zip(arrays,panel.curve.getData()))
            report['checks']['held_after_ring_eviction']=True
            report['live']={'held_first':held.raw_available_start,'held_end':held.end_sample_index,
                'held_bytes':len(held.raw_u16le),'held_raw_sha256':hashlib.sha256(held.raw_u16le).hexdigest(),
                'received_before':count,'received_after':dialog.bridge.state.validated_samples}
            width=panel.selection.width
            wheel(-120)  # Exactly one wheel; no later mouse move to repair edges.
            assert panel.selection.width > width
            xs,ys=panel.curve.getData()
            assert xs[0] == 0 and abs(xs[-1]-(panel.selection.width-1)/50000)<1e-12
            report['checks']['one_wheel_repaints_live_edges']=True
            viewport=panel.plot.viewport(); center=viewport.rect().center()
            before=panel.selection
            QtTest.QTest.mousePress(viewport,QtCore.Qt.MouseButton.LeftButton,pos=center)
            QtTest.QTest.mouseMove(viewport,center+QtCore.QPoint(35,0),delay=30)
            QtTest.QTest.mouseRelease(viewport,QtCore.Qt.MouseButton.LeftButton,pos=center+QtCore.QPoint(35,0))
            wait(drawn)
            assert panel.selection != before and panel.curve.getData()[0] is not None
            report['checks']['drag_repaints_held']=True
            capture('viewport-held.png')
            dialog.toggle_pause()
            width=panel.selection.width
            wheel(120)
            assert panel.selection.width < width and dialog._paused and panel._timer.isActive()
            count=dialog.bridge.state.validated_samples
            arrays=tuple(a.copy() for a in panel.curve.getData())
            wait(lambda: dialog.bridge.state.validated_samples > count+10000)
            assert all(np.array_equal(a,b) for a,b in zip(arrays,panel.curve.getData()))
            assert dialog.bridge.state.phase == 'recording'
            report['checks']['paused_zoom_repaints_while_recording']=True
            capture('viewport-paused.png')
            dialog.toggle_pause()
            wait(lambda: not panel.holding_live and panel.follow_tail and
                         panel.selection.stop > held.end_sample_index and panel._drawn_live is not None)
            report['checks']['resume_returns_fresh_tail']=True
            capture('viewport-tail.png')
            assert dialog.stop()
            wait(lambda: dialog.saved_path is not None and not dialog.bridge.metadata_pending)
            assert not dialog.error_label.text(),dialog.error_label.text()
            original=hashlib.sha256(path.read_bytes()).hexdigest()
            assert dialog.open_path(path)
            wait(lambda: dialog.archive is not None and not dialog.busy and not panel.busy)
            first=dialog.archive.first_sample_index
            panel.select_range(first+1000,first+61000); wait(drawn)
            wheel(-120)
            assert panel.selection.width > DETAIL_SAMPLES
            assert panel.selection.stop > first+61000
            xs,ys=panel.curve.getData()
            # Overview preserves real extrema/endpoints, but the partial edge
            # bins may be shorter than the exact requested sample interval.
            edge_tolerance=2*panel._summary.bin_samples/50000
            assert 0<=xs[0]<=edge_tolerance
            assert abs(xs[-1]-(panel.selection.width-1)/50000)<=edge_tolerance
            assert panel.plot.viewportUpdateMode()==QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate
            report['checks']['file_detail_to_overview_edges']=True
            report['checks']['one_wheel_repaints_file_edges']=True
            assert panel._held_live is None and panel._drawn_live is None
            report['checks']['source_swap_clears_held_raw']=True
            assert hashlib.sha256(path.read_bytes()).hexdigest()==original
            report['checks']['recording_unchanged']=True
            report['recording']={'sha256':original,'samples':dialog.archive.end_sample_index-first}
            capture('viewport-file.png')
            dialog.close(); wait(lambda: dialog.closed)
            report['owners_closed']=True
            report['real_serial_open_calls']=serial_open.call_count
            assert serial_open.call_count==0
            report['status']='PASS'
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        if dialog is not None and not dialog.closed:
            try:
                dialog.close(); wait(lambda: dialog.closed)
            except BaseException:
                report['cleanup_error']=traceback.format_exc()
                report['status']='FAIL'
        sys.excepthook=old_hook
        if report['callback_errors']:
            report['status']='FAIL'
        report['files']={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in output.iterdir() if p.is_file()}
        (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'checks':report['checks'],'error':report.get('error')},ensure_ascii=False))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(run(sys.argv[1]))
