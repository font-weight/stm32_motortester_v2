"""Focused Windows GUI/package evidence for V2-18; all signals artificial."""
from dataclasses import replace
import json
from pathlib import Path
import platform
import sys
import time
import traceback
from unittest.mock import patch


def run(output):
    from PySide6 import QtCore, QtWidgets
    from .unified_gui import MainWindow
    from .calibration_ui import CalibrationWizard
    from .calibration import load_calibration, save_calibration, validate_control
    from .calibration_report import export_calibration_report
    from .calibration_live import LiveCalibrationProvider
    from .analog_profile import nominal_selection, RawFormat
    from .stream_device import StreamDeviceBridge, StreamContext
    from .stream_demo import PacedStreamPeer

    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(['Calibration-live-check'])
    app.setStyle('Fusion')
    report = dict(status='RUNNING', platform=platform.platform(), qt_platform=app.platformName(),
        frozen=bool(getattr(sys, 'frozen', False)), executable=sys.executable,
        physical_measurements=False, real_serial_open_calls=0, checks=[], callback_errors=[])
    old_hook = sys.excepthook
    sys.excepthook = lambda typ, val, tb: report['callback_errors'].append(''.join(traceback.format_exception(typ, val, tb)))
    windows = []; bridge = provider = None

    def pump():
        app.processEvents()
        if report['callback_errors']:
            raise AssertionError(report['callback_errors'][-1])

    def wait(predicate, message, seconds=6):
        deadline = time.monotonic() + seconds
        while not predicate():
            pump()
            if time.monotonic() > deadline:
                raise AssertionError(message)
            time.sleep(.005)
        pump()

    def check(name, condition=True):
        assert condition, name
        report['checks'].append(name)

    def shot(widget, name):
        pump(); assert widget.grab().save(str(output / name))

    def forbid(*args, **kwargs):
        report['real_serial_open_calls'] += 1
        raise AssertionError('Physical COM forbidden')

    def capture(wizard, row, filename=None):
        panel = row.page.capture
        boundary = wizard.simulation.end
        row.button.click(); pump()
        wait(lambda: not panel.pending, 'Capture did not finish: ' + panel.notice.text())
        assert panel.window is not None, panel.notice.text()
        check('Fresh preview requires manual acceptance', row.window is None and not panel.use_button.isEnabled()
              and panel.window.first_sample_index >= boundary and not panel.window.settled_confirmed)
        if filename:
            shot(wizard, filename)
        panel.settled.setChecked(True); panel.use_button.click(); pump()
        assert row.window is not None and row.window.settled_confirmed

    try:
        with patch('serial.serialwin32.Serial.open', side_effect=forbid), \
             patch('motortester.transport._serial_factory', side_effect=forbid), \
             patch('serial.tools.list_ports.comports', return_value=[]):
            main = MainWindow(settings_path=output / 'settings.ini', port_provider=lambda: [])
            windows.append(main); main.resize(1366, 768); main.show(); pump()
            def inspect_entry():
                try:
                    w = app.activeModalWidget()
                    assert isinstance(w, CalibrationWizard)
                    assert w.live_current() is not None  # Inert current owner, no COM opened.
                    w.plan_page.origin.setCurrentIndex(w.plan_page.origin.findData('live'))
                    assert 'поток' in w.plan_page.error.text().lower() or 'вход' in w.plan_page.error.text().lower()
                    w.reject()
                except Exception:
                    report['callback_errors'].append(traceback.format_exc())
                    if app.activeModalWidget(): app.activeModalWidget().reject()
            QtCore.QTimer.singleShot(0, inspect_entry)
            main.input_controls.calibration_button.click(); pump()
            check('Main entry supplies current owner, refuses unavailable physical stream')
            main.close(); pump()

            records = []
            for index, mode in enumerate(('DC_WIDE', 'AC_WIDE', 'AC_SENSITIVE')):
                w = CalibrationWizard(); windows.append(w); w.resize(900, 680); w.show(); pump()
                p = w.plan_page
                p.origin.setCurrentIndex(p.origin.findData('synthetic_live'))
                p.mode.setCurrentIndex(index); p.rate.setCurrentIndex(index)
                if index == 0: shot(w, '01-plan.png')
                w.next(); pump(); assert w.currentId() == 1, p.error.text()
                if index == 0:
                    row = w.fit_page.first; panel = w.fit_page.capture
                    row.button.click(); panel.cancel_button.click(); pump()
                    check('Cancel detaches pending capture without result', row.window is None and not panel.pending and not w.teaching_provider.active)
                    row.button.click(); row.reference.setValue(1.1); pump()
                    check('Changed reference cancels pending capture', row.window is None and not panel.pending)
                    row.reference.setValue(1)
                    row.button.click(); row.measured.setChecked(False); pump()
                    check('Withdrawing measurement confirmation cancels pending capture',
                          row.window is None and not panel.pending and not w.teaching_provider.active)
                    capture(w, row)
                    row.measured.setChecked(False)
                    check('Withdrawing measurement confirmation invalidates accepted raw', row.window is None)
                capture(w, w.fit_page.first)
                capture(w, w.fit_page.second, '02-new-raw.png' if index == 0 else None)
                w.next(); pump(); assert w.currentId() == 2, w.fit_page.error.text()
                draft = w.draft
                if index == 0:
                    export_calibration_report(output / 'pending.pdf', draft)
                    save_calibration(output / 'pending.mtcal.json', draft)
                capture(w, w.control_page.control, '03-ac-raw.png' if index == 2 else None)
                w.next(); pump(); assert w.currentId() == 3, w.control_page.error.text()
                record = w.record
                assert record.state == 'synthetic_verified' and not record.can_apply, (record.state, record.control_bound_v)
                assert abs(record.a - (.02 if index == 0 else .005)) < .00003
                assert len({point.source_id for point in record.windows}) == 1
                assert all(a.first_sample_index + len(a.codes) <= b.first_sample_index
                           for a, b in zip(record.windows, record.windows[1:]))
                path = output / f'{mode}.mtcal.json'
                with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(path), '')), \
                     patch.object(QtWidgets.QMessageBox, 'information', return_value=QtWidgets.QMessageBox.StandardButton.Ok):
                    assert w.save_record(record)
                assert load_calibration(path) == record
                pdf = output / f'{mode}.pdf'
                with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(pdf), '')), \
                     patch.object(QtWidgets.QMessageBox, 'information', return_value=QtWidgets.QMessageBox.StandardButton.Ok):
                    w.result_page.report_button.click(); pump()
                assert pdf.read_bytes().startswith(b'%PDF-')
                check(f'{mode}: new stream excerpts, independent control, raw round-trip and PDF; synthetic blocked')
                if index == 0:
                    shot(w, '04-result.png')
                    failed = validate_control(draft, record.windows[2], 4.)
                    assert failed.state == 'control_failed'
                    export_calibration_report(output / 'failed.pdf', failed)
                records.append(record)
                w.accept(); pump()
                assert not w.simulation.timer.isActive() and not w.teaching_provider.active

            resumed = CalibrationWizard(resume_record=records[-1]); windows.append(resumed)
            resumed.show(); pump()
            check('Saved result reopens directly with PDF action', resumed.currentId() == 3 and resumed.result_page.report_button.isEnabled())
            resumed.accept(); pump()

            # Original synthetic/offline wizard path remains available.
            old = CalibrationWizard(); windows.append(old); old.show(); pump(); old.next(); pump()
            old.fit_page.first.button.click(); old.fit_page.second.button.click(); old.next(); pump()
            old.control_page.control.button.click(); old.next(); pump()
            check('Original offline teaching flow retained', old.record.state == 'synthetic_verified')
            old.saved_record = old.record; old.accept(); pump()

            # Use the actual running controller and immutable display signal,
            # beyond the teaching timer, without opening any physical serial.
            bridge = StreamDeviceBridge(peer=PacedStreamPeer())
            assert bridge.start_live()
            wait(lambda: bridge.state.bridge is not None and bridge.state.bridge.identity is not None
                 and bridge.state.ring_samples >= 12000, 'Real controller synthetic live')
            fmt = RawFormat.from_identity(bridge.state.bridge.identity)
            profile, snapshot = nominal_selection('DC_WIDE', fmt, hardware_instance_id='Учебный пример')
            context = StreamContext(input_profile=profile, analog_snapshot=snapshot)
            provider = LiveCalibrationProvider(lambda: (bridge, context))
            plan = replace(records[0].plan, raw_format=fmt)
            provider.begin(plan, 1024)
            captured = []
            def ready():
                value = provider.poll()
                if value is not None: captured.append(value)
                return bool(captured)
            wait(ready, 'Actual controller raw capture')
            check('Actual StreamDeviceBridge delivers immutable new raw without COM',
                  captured[0].origin == 'synthetic' and len(captured[0].codes) == 1024 and not captured[0].settled_confirmed)
            provider.close(); bridge.shutdown()
            wait(lambda: bridge._closed, 'Artificial owners closed')
            report['status'] = 'PASS'
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if provider is not None: provider.close()
        if bridge is not None and not bridge._closed:
            bridge.shutdown()
        for w in windows:
            if isinstance(w, CalibrationWizard):
                w.saved_record = w.record or w.draft
                w.reject()
            else: w.close()
        app.processEvents()
        sys.excepthook = old_hook
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
