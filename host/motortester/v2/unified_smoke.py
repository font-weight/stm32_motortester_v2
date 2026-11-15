"""Focused Windows/package witness for the single workspace, no physical I/O."""
import hashlib
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
    from .stream_device import StreamDeviceBridge
    from .serial_smoke import _Factory
    from .stream_profiles_smoke import ProfilesBackend
    from .calibration_ui import CalibrationWizard
    from .data import Recording, SignalBlock
    from .storage import save
    from ..stream_wire import Kind

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(['Unified-check'])
    app.setStyle('Fusion')
    report = dict(status='RUNNING', platform=platform.platform(), qt_platform=app.platformName(),
        frozen=bool(getattr(sys, 'frozen', False)), executable=sys.executable,
        physical_measurements=False, real_serial_open_calls=0, checks=[], callback_errors=[])
    factory = _Factory(ProfilesBackend)
    old_hook = sys.excepthook
    sys.excepthook = lambda typ, val, tb: report['callback_errors'].append(''.join(traceback.format_exception(typ, val, tb)))
    window = None

    def pump():
        app.processEvents()
        if report['callback_errors']:
            raise AssertionError(report['callback_errors'][-1])

    def wait(predicate, message, seconds=10):
        deadline = time.monotonic() + seconds
        while not predicate():
            pump()
            if time.monotonic() >= deadline:
                raise AssertionError(message + ': ' + str(window.panel.bridge.state) + '\n' + window.panel.error_label.text())
            time.sleep(.005)
        pump()

    def check(name, condition=True):
        assert condition, name
        report['checks'].append(name)

    def shot(name):
        pump()
        assert window.grab().save(str(output / name))

    def bridge(parent, **options):
        if 'selection' in options:
            options['fake_backend_factory'] = factory
        return StreamDeviceBridge(parent, **options)

    def forbid(*a, **k):
        report['real_serial_open_calls'] += 1
        raise AssertionError('Physical COM forbidden')

    try:
        with patch('serial.serialwin32.Serial.open', side_effect=forbid), \
             patch('motortester.transport._serial_factory', side_effect=forbid):
            window = MainWindow(settings_path=output / 'settings.ini', bridge_factory=bridge,
                                port_provider=lambda: ['SYNTHETIC_CH1'])
            window.resize(1366, 768)
            window.show()
            p = window.panel
            pump()
            check('Cold startup: no COM open, no acquisition and no automatic DEMO',
                  not factory.backends and not p.demo_enabled and not p.live_button.isEnabled()
                  and not window.disconnect_button.isEnabled())
            check('Only Service contains DEMO launch', any('ДЕМО' in a.text() for a in window.service_menu.actions()) and
                  not any('ДЕМО' in b.text() for b in window.findChildren(QtWidgets.QPushButton)))
            check('Single plot and visible cursor controls', p.viewer.plot.isVisible() and p.cursors.enabled.isVisible())
            shot('01-cold-1366.png')
            window.channel_name.setText('Моя плата')
            window._commit_channel()
            check('Channel name persisted without physical profile', window._settings.value('channel_name') == 'Моя плата')
            window.connect_button.click()
            wait(lambda: p.bridge.state.ready and p.bridge.connection is not None, 'Connect READY')
            check('Inline Connect negotiates selected 100k without START',
                  Kind.START not in factory.backends[-1].commands and p.bridge.connection.observed_caps[4] == 100_000)
            p.live_button.click()
            wait(lambda: p.viewer.selection is not None and p.viewer.curve.getData()[0] is not None, 'Live raw')
            check('Unknown PA0 displays raw codes, no invented voltage', not p.viewer.voltage_display and p.raw_view.isChecked())
            window.sweep.set_value(.001, emit=True)
            wait(lambda: p.viewer.selection is not None and p.viewer.selection.width <= 1000, 'Time knob')
            p.cursors.enabled.setChecked(True)
            wait(lambda: p.cursors.values is not None, 'Raw cursors')
            p.cursors.enabled.setChecked(False)
            window.full_signal()
            wait(lambda: p.viewer.selection.width > 1000, 'Available live range')
            window.sweep.set_value(.001, emit=True)
            shot('02-live-1366.png')
            p.stop_button.click()
            wait(lambda: p.bridge.state.can_open and window.connect_button.isEnabled(), 'Stop live')
            window.rate_combo.setCurrentIndex(0)
            window.connect_button.click()
            wait(lambda: p.bridge.state.ready and p.bridge.connection is not None and p.bridge.connection.observed_caps[4] == 50_000, 'Reconnect 50k')
            check('Same workspace reconnects after stop and changes Fs', len(factory.backends) == 2 and not factory.backends[0].is_open)
            controls = window.input_controls
            controls.mode.setCurrentIndex(1)
            controls.instance.setText('Искусственный экземпляр')
            check('Nominal scale requires physical confirmation', not controls.apply_button.isEnabled())
            controls.confirm.setChecked(True)
            controls.apply_button.click()
            check('Inline DC WIDE nominal scale, not calibrated',
                  p.active_input_profile.state == 'nominal' and p.active_analog_snapshot.mode_id == 'DC_WIDE')
            controls.details_toggle.setChecked(False)
            p.live_button.click()
            wait(lambda: p.bridge.state.phase == 'preview' and p.viewer.selection is not None, 'Nominal live')
            target = output / 'synthetic.mtstream'
            assert p.record_path(str(target))
            wait(lambda: p.bridge.state.phase == 'recording' and p.viewer.selection is not None, 'Record')
            # Enough time for one synthetic event and its complete context.
            wait(lambda: p.capture.arm_button.isEnabled(), 'Capture action ready')
            p.capture.arm_button.click()
            wait(lambda: p.capture.shot is not None, 'Single capture')
            capture_path = output / 'synthetic.mtshot'
            p.capture.save_path(str(capture_path))
            wait(lambda: not p.busy and capture_path.exists() and not p.capture.dirty, 'Save capture')
            p.stop_button.click()
            wait(lambda: p.saved_path is not None and not p.bridge.metadata_pending, 'Stop and save context')
            check('Recording and single capture saved through same workspace', target.exists() and capture_path.exists())
            original_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            assert window.open_path(str(target))
            wait(lambda: p._opening and p.archive is not None and not p.busy, 'Open stream')
            wait(lambda: p.viewer.selection is not None, 'File plot')
            check('Saved input profile used read-only', p.active_input_profile.state == 'nominal' and not p.input_editable())
            window.units.setCurrentText('мВ')
            window.yscale.set_value(.2, emit=True)
            p.cursors.enabled.setChecked(True)
            wait(lambda: p.cursors.values is not None, 'File cursors')
            check('mV and Y knob share same voltage projection', p.viewer.voltage_display and p.voltage_unit == 'мВ')
            window.auto_scale()
            window.sweep.set_value(.002, emit=True)
            p.cursors.center_button.click()
            wait(lambda: not p.viewer.busy and not p.cursors.busy and
                         p.cursors.values is not None and p.cursors.readout.text().startswith('A:') and
                         p.cursors.readout.height() >= p.cursors.readout.heightForWidth(p.cursors.readout.width()),
                 'Complete cursor readout visible')
            check('Cursor readout fits at 1366x768', p.cursors.readout.geometry().bottom() < p.cursors.height())
            shot('03-file-1366.png')
            p.cursors.enabled.setChecked(False)
            wait(lambda: window.connect_button.isEnabled(), 'File reconnect available')
            window.connect_button.click()
            wait(lambda: p.bridge.state.ready and p.bridge.connection is not None and not p._opening, 'Reconnect after file')
            check('Reconnect clears manual confirmation and stale scale',
                  not controls.confirm.isChecked() and not p.active_input_profile.configured)
            check('Source recording unchanged', hashlib.sha256(target.read_bytes()).hexdigest() == original_hash)
            old = Recording((SignalBlock(10, 1000.5, (12, 25, 48)), SignalBlock(20, 1000.5, (51, 20, 10))),
                            channel_name='Старый CH1', time_basis='measured')
            old_path = output / 'old.mtv2'
            save(old_path, old)
            old_hash = hashlib.sha256(old_path.read_bytes()).hexdigest()
            window.open_path(old_path)
            wait(lambda: window.legacy_active, 'Old format embedded')
            window.sweep.set_value(.001, emit=True)
            window.legacy.cursor_toggle.setChecked(True)
            check('Old MTV2 embedded with original gaps and time basis', window.legacy.recording == old)
            check('Explicit axis units have no automatic SI multiplier',
                  not window.legacy.axis.autoSIPrefix and not p.viewer.connector_axis.autoSIPrefix)
            shot('04-old-file-1366.png')
            window.connect_button.click()
            wait(lambda: p.bridge.state.ready and p.bridge.connection is not None and not window.legacy_active, 'Reconnect old file')
            check('Legacy file unchanged after reconnect', hashlib.sha256(old_path.read_bytes()).hexdigest() == old_hash)

            def close_wizard():
                try:
                    dialog = app.activeModalWidget()
                    assert isinstance(dialog, CalibrationWizard)
                    dialog.reject()
                except Exception:
                    report['callback_errors'].append(traceback.format_exc())
            QtCore.QTimer.singleShot(0, close_wizard)
            controls.calibration_button.click()
            pump()
            check('Calibration remains separate and reachable directly')
            # Service action is the only normal entry into artificial streaming.
            window.demo_menu.actions()[1].trigger()
            wait(lambda: p.demo_enabled and p.viewer.selection is not None and p.bridge.state.phase == 'preview', 'Explicit DEMO')
            check('Explicit Service DEMO clears physical scale', not p.active_input_profile.configured)
            p.stop_button.click()
            wait(lambda: p.bridge.state.can_open, 'Demo stop')
            p.capture.dirty = True
            owner = p.bridge
            window.close()
            wait(lambda: p.capture.prompt is not None, 'Close confirmation')
            p.capture.prompt.button(QtWidgets.QMessageBox.StandardButton.Cancel).click()
            pump()
            check('Cancel close preserves owner and main window', window.isVisible() and p.bridge is owner and not p._closing)
            p.capture.dirty = False
            window.close()
            wait(lambda: p.closed and not window.isVisible(), 'Orderly close')
            check('All injected ports closed', all(not b.is_open for b in factory.backends))
        report['status'] = 'PASS'
    except Exception:
        report['status'] = 'FAIL'
        report['error'] = traceback.format_exc()
    finally:
        if window is not None and not window.panel.closed:
            window.panel.capture.dirty = False
            if window.panel.capture.prompt:
                window.panel.capture.prompt.reject()
            window.close()
            deadline = time.monotonic() + 5
            while not window.panel.closed and time.monotonic() < deadline:
                app.processEvents(); time.sleep(.01)
        sys.excepthook = old_hook
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
