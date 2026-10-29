"""One short Windows witness of cursor gestures, recording and reopening; no COM."""
import hashlib
import json
from pathlib import Path
import platform
import struct
import sys
import time
import traceback
from unittest.mock import patch


def run(output_name):
    from PySide6 import QtCore, QtGui, QtTest, QtWidgets
    from .stream_ui import StreamDialog
    output = Path(output_name).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle('Fusion'); app.setQuitOnLastWindowClosed(False)
    report = dict(status='FAIL', platform=sys.platform, windows=platform.platform(),
        qt_platform=app.platformName(), frozen=bool(getattr(sys,'frozen',False)),
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
            if time.monotonic()>deadline:
                raise AssertionError('Cursor wait timeout')
            time.sleep(.005)
        app.processEvents()

    def capture(name):
        app.processEvents()
        assert dialog.grab().save(str(output/name))

    try:
        assert sys.platform=='win32' and app.platformName()=='windows'
        with patch('serial.Serial.open', side_effect=AssertionError('COM forbidden')) as serial_open:
            dialog=StreamDialog(); dialog.show(); dialog.raw_view.setChecked(True)
            panel, tool=dialog.viewer, dialog.cursors
            assert dialog.start_live()
            wait(lambda: dialog.bridge.state.validated_samples>70000 and panel._drawn_live is not None)
            path=output/'cursors.mtstream'
            assert dialog.record_path(path)
            wait(lambda: dialog.bridge.state.phase=='recording')
            QtTest.QTest.mouseClick(tool.enabled,QtCore.Qt.MouseButton.LeftButton)
            wait(lambda: tool.values is not None and not tool.busy and not panel.busy)
            assert panel.holding_live and not panel.follow_tail
            held=panel._held_live
            values=tool.values
            for index,code in ((values.a,values.code_a),(values.b,values.code_b)):
                assert code==struct.unpack_from('<H',held.raw_u16le,2*(index-held.raw_available_start))[0]
            count=dialog.bridge.state.validated_samples
            wait(lambda: panel._raw_first>held.end_sample_index)
            assert tool.values==values and dialog.bridge.state.phase=='recording'
            report['checks']['held_values_survive_eviction']=True
            report['live']={'held_first':held.raw_available_start,'held_end':held.end_sample_index,
                'held_bytes':len(held.raw_u16le),'received_before':count,
                'received_after':dialog.bridge.state.validated_samples}
            # Real mouse drag on A, no direct index API for this gesture.
            box=panel.plot.getViewBox(); viewport=panel.plot.viewport()
            y=sum(box.viewRange()[1])/2
            point=panel.plot.mapFromScene(box.mapViewToScene(QtCore.QPointF(tool.lines[0].value(),y)))
            QtTest.QTest.mousePress(viewport,QtCore.Qt.MouseButton.LeftButton,pos=point)
            QtTest.QTest.mouseMove(viewport,point+QtCore.QPoint(45,0),delay=30)
            QtTest.QTest.mouseRelease(viewport,QtCore.Qt.MouseButton.LeftButton,pos=point+QtCore.QPoint(45,0))
            wait(lambda: tool.values is not None and not tool.busy)
            assert tool.values.a!=values.a and tool.values.b==values.b
            assert tool.values.delta_s==(tool.values.b-tool.values.a)/50000
            report['checks']['mouse_drag_reads_raw']=True
            pair=tool._indices
            center=QtCore.QPointF(viewport.rect().center())
            app.sendEvent(viewport,QtGui.QWheelEvent(center,viewport.mapToGlobal(center.toPoint()),
                QtCore.QPoint(),QtCore.QPoint(0,120),QtCore.Qt.MouseButton.NoButton,
                QtCore.Qt.KeyboardModifier.NoModifier,QtCore.Qt.ScrollPhase.NoScrollPhase,False))
            wait(lambda:not panel.busy)
            assert tool._indices==pair and panel.curve.getData()[0] is not None
            report['checks']['zoom_preserves_indices_and_graph']=True
            capture('cursors-live.png')
            dialog.toggle_pause(); tool.center()
            wait(lambda: tool.values is not None and not tool.busy)
            count=dialog.bridge.state.validated_samples
            wait(lambda:dialog.bridge.state.validated_samples>count+10000)
            assert dialog._paused and dialog.bridge.state.phase=='recording'
            report['checks']['pause_cursors_recording_continues']=True
            capture('cursors-pause.png')
            dialog.toggle_pause()
            wait(lambda:panel.follow_tail and not panel.holding_live)
            assert not tool.enabled.isChecked() and tool.values is None
            report['checks']['follow_clears_cursors']=True
            assert dialog.stop()
            wait(lambda:dialog.saved_path is not None and not dialog.bridge.metadata_pending)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            assert dialog.open_path(path)
            wait(lambda:dialog.archive is not None and not dialog.busy and not panel.busy)
            assert tool.values is None and not tool.enabled.isChecked()
            panel.show_whole_recording(); wait(lambda:not panel.busy)
            assert panel.selection.width>65536
            QtTest.QTest.mouseClick(tool.enabled,QtCore.Qt.MouseButton.LeftButton)
            first=dialog.archive.first_sample_index
            tool.set_indices(first+9000,first+1234)
            wait(lambda:tool.values is not None and not tool.busy)
            values=tool.values
            assert values.code_a==dialog.archive.read_samples(values.a,1)[0]
            assert values.code_b==dialog.archive.read_samples(values.b,1)[0]
            assert values.delta_s==(1234-9000)/50000
            assert 'B−A' in tool.readout.text() and 'не настроена' in tool.readout.text()
            report['checks']['overview_raw_values_signed_delta']=True
            assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
            report['checks']['file_unchanged']=True
            report['recording']={'sha256':digest,'samples':panel.selection.width,
                'a':values.a,'b':values.b,'code_a':values.code_a,'code_b':values.code_b,
                'delta_s':values.delta_s}
            capture('cursors-file.png')
            dialog.raw_view.setChecked(False)
            assert not tool.enabled.isChecked() and tool.values is None
            report['checks']['raw_visibility_clears_values']=True
            dialog.close(); wait(lambda:dialog.closed)
            assert tool._closed and not tool._timer.isActive()
            assert serial_open.call_count==0
            report.update(owners_closed=True,real_serial_open_calls=serial_open.call_count,status='PASS')
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        if dialog is not None and not dialog.closed:
            try:
                dialog.close(); wait(lambda:dialog.closed)
            except BaseException:
                report['cleanup_error']=traceback.format_exc(); report['status']='FAIL'
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
