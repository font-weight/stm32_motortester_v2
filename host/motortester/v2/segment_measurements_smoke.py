"""Focused native/frozen Windows witness; synthetic signals and no serial I/O."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import struct
import sys
import time
import traceback
from unittest.mock import patch


def run(output):
    from PySide6 import QtWidgets
    from .unified_gui import MainWindow
    from .input import InputProfile
    from .data import Recording, SignalBlock
    from .storage import save
    from .stream_capture import StreamCapture, save_capture
    from .stream_device import StreamContext
    from .analog_profile import nominal_selection
    from ..stream_model import StreamIdentity
    from ..stream_view import EventConfig, EventEntry
    from ..stream_wire import BATCH1024_REVISION

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(['Segment-measurements-check'])
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    report = dict(status='RUNNING', platform=platform.platform(), qt_platform=app.platformName(),
        frozen=bool(getattr(sys, 'frozen', False)), executable=sys.executable,
        physical_measurements=False, real_serial_open_calls=0, checks=[], callback_errors=[])
    old_hook = sys.excepthook
    sys.excepthook = lambda *exc: report['callback_errors'].append(''.join(traceback.format_exception(*exc)))
    window = None

    def pump():
        app.processEvents()
        if report['callback_errors']:
            raise AssertionError(report['callback_errors'][-1])

    def wait(predicate, message, seconds=12):
        deadline = time.monotonic() + seconds
        while not predicate():
            pump()
            if time.monotonic() >= deadline:
                raise AssertionError(message + '\n' + window.panel.measurement_label.text())
            time.sleep(.005)
        pump()

    def check(name, condition=True):
        assert condition, name
        report['checks'].append(name)

    def shot(name):
        pump()
        if not window.legacy_active:
            p = window.panel
            wait(lambda: p.measurement_label.geometry().bottom() < p.cursors.geometry().top(),
                 'Measurement text must not overlap cursor controls')
        assert window.grab().save(str(output / name))

    def forbid(*args, **kwargs):
        report['real_serial_open_calls'] += 1
        raise AssertionError('Physical COM forbidden')

    def capture_file(name, *, ac=False):
        fs, step, bits, count, cycle = (150000, 4, 10, 18000, 600) if ac else (50000, 1, 12, 8000, 200)
        trigger = cycle // 2
        codes = tuple(step * round((2000 + 600*math.sin(2*math.pi*(i-trigger)/cycle))/step)
                      for i in range(count))
        identity = StreamIdentity('synthetic-measurement-'+name, 1, 5 if ac else 0, fs, 'synthetic',
            protocol_revision=BATCH1024_REVISION if ac else None, acquisition_mode=5 if ac else 0,
            retained_bits=bits, discarded_lsb=2 if ac else 0,
            wire_sample_encoding='u10packed_le' if ac else 'u16le',
            normalization='left_shift_2' if ac else 'identity',
            quantization='truncate_lsb' if ac else 'none')
        profile, snapshot = nominal_selection('AC_SENSITIVE' if ac else 'DC_WIDE', identity,
                                             hardware_instance_id='Искусственный пример')
        cfg = EventConfig(2000, 1800, 'above', trigger, 10, 10, 0, count, 0, 4092 if ac else 4095)
        event = EventEntry(0, trigger, 0, count, trigger-10, trigger, None, ())
        capture = StreamCapture(identity, StreamContext(input_profile=profile, analog_snapshot=snapshot), cfg, 1, 1, 0, 0,
            event, struct.pack('<' + str(count) + 'H', *codes), 'event_closed', (), None, 'unknown',
            datetime.now(timezone.utc).isoformat())
        path = output / (name + '.mtshot')
        save_capture(path, capture)
        return path, capture

    try:
        with patch('serial.serialwin32.Serial.open', side_effect=forbid), \
             patch('motortester.transport._serial_factory', side_effect=forbid):
            window = MainWindow(settings_path=output / 'settings.ini', port_provider=lambda: [])
            window.resize(1366, 768)
            window.show()
            p, view = window.panel, window.panel.viewer
            runner = view._measurement_runner
            pump()
            dc_path, dc = capture_file('dc-sine')
            ac_path, ac = capture_file('ac-sine-10bit', ac=True)
            hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (dc_path, ac_path)}
            assert window.open_path(dc_path)
            wait(lambda: p.archive is not None and runner.result is not None and not p.busy, 'DC raw result')
            window.full_signal()
            wait(lambda: runner.result is not None and runner.result.count == 8000, 'Full DC result')
            result = runner.result
            expected_mean = dc.context.input_profile.voltage(2000)
            check('DC mean uses all raw codes with stored gain and original offset',
                  result.mean_code == 2000 and ('Среднее DC на CH1: '+view.value_text(expected_mean)) in p.measurement_label.text())
            check('250 Hz sine / 4 ms period from raw, not display bins',
                  math.isclose(result.frequency_hz, 250, rel_tol=.001) and result.count > len(view._raw_plot_y))
            check('Mean and period shown in main window', p.measurement_label.isVisible())
            window.auto_scale()
            wait(lambda: p.measurement_label.height() >= p.measurement_label.heightForWidth(p.measurement_label.width()),
                 'All measurement lines fit')
            check('All raw measurement lines visible at 1366x768', p.measurement_label.height() >= 4*p.measurement_label.fontMetrics().height())
            shot('01-dc-measurements.png')
            window.units.setCurrentText('мВ')
            wait(lambda: ('Среднее DC на CH1: '+view.value_text(expected_mean)) in p.measurement_label.text(), 'mV mean')
            window.raw_view.setChecked(True)
            check('Service codes do not change physical DC mean', ('Среднее DC на CH1: '+view.value_text(expected_mean)) in p.measurement_label.text())
            window.raw_view.setChecked(False)
            window.units.setCurrentText('В')
            view.select_range(0, 70)
            wait(lambda: runner.result is not None and runner.result.count == 70, 'Short selection')
            check('Short interval clears former frequency and explains insufficient cycles',
                  runner.result.period_s is None and bool(runner.result.period_reason)
                  and 'Частота ≈' not in p.measurement_label.text())
            shot('02-short-interval.png')
            view.select_range(1000, 5000)
            wait(lambda: runner.result is not None and runner.result.count == 4000, 'Pan and zoom')
            check('Pan/zoom reads selected raw interval', math.isclose(runner.result.frequency_hz, 250, rel_tol=.001))
            assert window.open_path(ac_path)
            wait(lambda: p.archive is not None and view.input_profile.coupling == 'AC' and
                         runner.result is not None and runner.result.count == 18000, 'AC10 result')
            check('AC suppresses DC mean and canonical10 preserves frequency',
                  'AC не измеряет постоянную составляющую' in p.measurement_label.text()
                  and math.isclose(runner.result.frequency_hz, 250, rel_tol=.001))
            window.auto_scale()
            wait(lambda: p.measurement_label.height() >= p.measurement_label.heightForWidth(p.measurement_label.width()),
                 'AC explanation fits')
            shot('03-ac-10bit.png')

            # Legacy readers include explicit discontinuities not present in a
            # continuous USB prefix. Check those in the actual embedded view.
            fs = 50000.5
            profile = InputProfile(a=-.002, b=5., state='nominal', profile_id='synthetic-negative-gain',
                                   coupling='DC', coefficient_source='synthetic_test_definition')
            wave = tuple(round(2000+600*math.sin(2*math.pi*250*i/fs)) for i in range(5000))
            old = Recording((SignalBlock(123456789000, fs, wave),), input_profile=profile,
                            channel_name='Искусственная синусоида', time_basis='synthetic_exact')
            old_path = output / 'legacy-sine.mtv2'
            save(old_path, old)
            assert window.open_path(old_path)
            wait(lambda: window.legacy_active and window.legacy.measurement_result is not None, 'Legacy result')
            legacy = window.legacy
            check('Legacy uses its own fractional Fs and stored profile',
                  math.isclose(legacy.measurement_result.frequency_hz, 250, rel_tol=.001)
                  and legacy.recording == old)
            gap = replace(old, blocks=(SignalBlock(0, fs, wave[:2000]),
                                      SignalBlock(2000, fs, wave[2000:], gap_before='synthetic_gap')))
            gap_path = output / 'legacy-gap.mtv2'
            save(gap_path, gap)
            assert window.open_path(gap_path)
            wait(lambda: legacy.recording == gap and legacy.measurement_result is not None, 'Gap result')
            check('Internal gap suppresses both mean and period with a reason',
                  legacy.measurement_result.mean_code is None and legacy.measurement_result.period_s is None
                  and bool(legacy.measurement_result.data_reason))
            shot('04-gap-reason.png')
            random_source = random.Random(19)
            noisy = replace(old, blocks=(SignalBlock(0, fs, tuple(random_source.randrange(1400, 2600) for _ in wave)),))
            noisy_path = output / 'legacy-noise.mtv2'
            save(noisy_path, noisy)
            assert window.open_path(noisy_path)
            wait(lambda: legacy.recording == noisy and legacy.measurement_result is not None, 'Noise result')
            check('Noise retains DC mean but does not claim a period',
                  legacy.measurement_result.mean_code is not None and legacy.measurement_result.period_s is None)

            assert p.start_demo('oscilloscope')
            wait(lambda: not window.legacy_active and runner.result is not None and p.bridge.state.phase == 'preview', 'Live measurements')
            check('New source clears the previous opened-capture label and save action',
                  p.capture.shot is None and 'файл открыт' not in p.capture.note.text()
                  and not p.capture.save_button.isEnabled())
            published = []
            runner.ready.connect(lambda r: published.append((runner.key, r)))
            wait(lambda: len(published) >= 3, 'Continuously updating live measurements')
            check('Live measurements update repeatedly without freezing reception', len({key for key, r in published}) >= 3)
            view.hold_current_view()
            wait(lambda: runner.result is not None and not runner.busy, 'Held live raw')
            held_key, held_result = runner.key, runner.result
            received = p.bridge.state.validated_samples
            wait(lambda: p.bridge.state.validated_samples > received + 10000, 'Reception continues')
            check('Held view keeps the same raw measurement while receiver advances', runner.key == held_key and runner.result == held_result)
            check('Unknown physical scale does not invent a mean voltage', 'шкала или режим DC входа не настроены' in p.measurement_label.text())
            shot('05-live-held.png')
            p.stop_button.click()
            wait(lambda: p.bridge.state.can_open, 'Stop synthetic live')
            p.capture.shot, p.capture.dirty = dc, True
            p.capture.source_reset()
            check('Source reset preserves unsaved capture raw', p.capture.shot is dc and p.capture.dirty)
            p.capture.dirty = False
            p.capture.source_reset()
            for path, digest in hashes.items():
                check('Original unchanged: '+path.name, hashlib.sha256(path.read_bytes()).hexdigest() == digest)
            window.close()
            wait(lambda: p.closed and not window.isVisible(), 'Close')
            check('Measurement workers stopped on close', runner._closed and legacy.measurement_runner._closed)
            report['status'] = 'PASS'
    except BaseException:
        report['status'] = 'FAIL'
        report['error'] = traceback.format_exc()
    finally:
        if window is not None and window.isVisible():
            try:
                window.close()
                wait(lambda: window.panel.closed, 'Cleanup close')
            except BaseException:
                report['cleanup_error'] = traceback.format_exc()
        sys.excepthook = old_hook
        if report['callback_errors']:
            report['status'] = 'FAIL'
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
