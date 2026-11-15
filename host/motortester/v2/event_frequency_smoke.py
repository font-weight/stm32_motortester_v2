"""Windows witness for the reported flicker and independent live event rate.

Only synthetic peers/fixtures; opening any physical serial port is a failure.
"""
import json
import math
import platform
import struct
import sys
import time
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def run(output):
    from PySide6 import QtWidgets
    from .unified_gui import MainWindow
    from .event_frequency_ui import EventFrequencyReadout
    from .stream_capture import StreamCapture, save_capture
    from .stream_device import StreamContext
    from .stream_demo import PacedStreamPeer
    from .segment_measurements import read_segment
    from ..stream_model import StreamIdentity
    from ..stream_view import EventConfig, EventEntry, DetectorStatus

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(['Event-frequency-check'])
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
                raise AssertionError(message + '\n' + window.panel.event_frequency.text()
                                     + '\n' + window.panel.measurement_label.text())
            time.sleep(.005)
        pump()

    def check(name, condition=True):
        assert condition, name
        report['checks'].append(name)

    def shot(name):
        p = window.panel
        wait(lambda: p.measurement_label.geometry().bottom() < p.event_frequency.geometry().top()
             and p.event_frequency.geometry().bottom() < p.cursors.geometry().top(),
             'Readouts must not overlap cursor controls')
        assert window.grab().save(str(output / name))

    def forbid(*args, **kwargs):
        report['real_serial_open_calls'] += 1
        raise AssertionError('Physical COM forbidden')

    def slow_read(reader, start, stop):
        time.sleep(.16)  # Deliberately spans multiple incoming display frames.
        return read_segment(reader, start, stop)

    original_sample = PacedStreamPeer._sample

    def clipped_pulse(peer, index):
        # Reproduce the user's rail-code pulse without a physical source.
        return 4095 if peer.waveform == 'ignition' and index % 2000 == 0 else original_sample(peer, index)

    try:
        with patch('serial.serialwin32.Serial.open', side_effect=forbid), \
             patch('motortester.transport._serial_factory', side_effect=forbid), \
             patch('motortester.v2.analog_view.read_segment', side_effect=slow_read), \
             patch.object(PacedStreamPeer, '_sample', clipped_pulse):
            window = MainWindow(settings_path=output / 'settings.ini', port_provider=lambda: [])
            window.resize(1366, 768)
            window.show()
            p, view = window.panel, window.panel.viewer
            check('Cold start has no live event value', p.event_frequency.result is None)
            assert p.start_demo('ignition')
            wait(lambda: p.event_frequency.result is not None and p.event_frequency.result.frequency_hz == 25,
                 'Synthetic ignition events at 25 Hz')
            wait(lambda: view.selection is not None and view._measurement_completed is not None, 'First frame')
            p.sync_button.setChecked(True)
            view.set_sync_width(1000)  # 20 ms visible, shorter than the 40 ms event spacing.
            wait(lambda: view.event_sync and view._measurement_completed is not None
                 and view._measurement_completed.count == 1000, 'One-event synchronized frame')
            check('One visible pulse still has 25 Hz live event frequency',
                  view.selection.width == 1000 and p.event_frequency.result.frequency_hz == 25
                  and view._measurement_completed.period_s is None)
            check('Rail-code warning remains explicit with a threshold-event frequency',
                  'крайние коды' in p.measurement_label.text()
                  and 'крайние коды' in p.event_frequency.text())
            messages, published = [], []
            view.measurements_changed.connect(messages.append)
            view._measurement_runner.ready.connect(lambda value: published.append(value))
            before = p.bridge.state.validated_samples
            wait(lambda: len(published) >= 6, 'Repeated slow asynchronous measurements')
            check('Live measurements never alternate with loading after first result',
                  len(messages) > 6 and not any('чтение исходных' in s or 'ожидание нового графика' in s for s in messages))
            check('Reception and event synchronization continue during slow analysis',
                  p.bridge.state.validated_samples > before + 50000 and view.event_sync)
            check('Live values explicitly name the last calculated frame',
                  'Последний рассчитанный кадр' in p.measurement_label.text())
            shot('01-live-single-event.png')

            wait(lambda: view._measurement_runner.busy, 'Slow automatic job in flight')
            p.sync_button.setChecked(False)
            check('Disabling synchronization clears an older automatic result immediately',
                  view._measurement_completed is None)
            wait(lambda: view._measurement_completed is not None and not view._measurement_runner.busy,
                 'Exact held frame after disabling synchronization')
            check('Held result is bound to its exact visible sample interval',
                  view._measurement_runner.key[-2:] == (view.selection.start, view.selection.stop))
            p.sync_button.setChecked(True)
            wait(lambda: view.event_sync and view._measurement_completed is not None,
                 'Resume automatic frames')

            p.pause_button.click()
            check('Pausing clears automatic values even at unchanged viewport endpoints',
                  view._measurement_completed is None)
            wait(lambda: view._measurement_runner.result is not None and not view._measurement_runner.busy,
                 'Paused graph recomputed from its held raw')
            key = view._measurement_runner.key
            seq = p.event_frequency._sequence
            wait(lambda: p.event_frequency._sequence > seq + 3, 'Event frequency still receives snapshots during view pause')
            check('Pause freezes graph but live event frequency keeps updating',
                  view._measurement_runner.key == key and p.event_frequency.result.frequency_hz == 25
                  and 'живой приём' in p.event_frequency.text())
            shot('02-paused-view-live-frequency.png')
            view.select_range(view.selection.start, view.selection.start + 50)
            check('Manual range immediately clears the former frame values', view._measurement_completed is None)
            wait(lambda: view._measurement_completed is not None and view._measurement_completed.count == 50,
                 'Manually selected raw range')
            check('Zoom changes segment measurements, not the live event frequency',
                  p.event_frequency.result.frequency_hz == 25)
            p.stop_button.click()
            wait(lambda: p.bridge.state.can_open, 'Stop synthetic source')
            check('Stop removes the live frequency', p.event_frequency.result is None and '≈25' not in p.event_frequency.text())

            # A small immutable file also verifies clearing of source ownership.
            identity = StreamIdentity('synthetic-event-fixture', 1, 0, 50000, 'synthetic')
            cfg = EventConfig(2600, 2200, 'above', 50, 150, 25, 100, 500, 0, 4095)
            event = EventEntry(0, 50, 0, 400, 25, 50, 100, ())
            capture = StreamCapture(identity, StreamContext(), cfg, 1, 1, 0, 0, event,
                struct.pack('<400H', *([550]*50 + [3000]*10 + [550]*340)),
                'event_closed', (), None, 'unknown', datetime.now(timezone.utc).isoformat())
            path = output / 'single-event.mtshot'
            save_capture(path, capture)
            assert window.open_path(path)
            wait(lambda: p.archive is not None and view._measurement_completed is not None, 'Opened file')
            check('Opened file cannot inherit live event rate', p.event_frequency.result is None)
            shot('03-opened-single-event.png')

            # Deterministic lifecycle/stall boundaries for the actual Qt readout.
            readout = EventFrequencyReadout(window)
            readout.hide()
            readout.set_active(True)
            events = tuple(EventEntry(i, 100 + 2000*i, 50 + 2000*i, 400 + 2000*i,
                                      75 + 2000*i, 100 + 2000*i, 150 + 2000*i, ()) for i in range(3))
            status = DetectorStatus('running', 3, 4500, None, None, 0, next_ordinal=3)
            source = SimpleNamespace(revision=1, identity=identity, config_revision=1, config=cfg,
                                     sequence=1, end=4500, events=events, detector=status)
            owner = object()
            readout.observe(owner, source)
            check('Readout fixture has correct sample-clock frequency', readout.result.frequency_hz == 25)
            source.sequence = 2
            source.end = 60000
            source.detector = replace(status, processed_until=60000)
            readout.observe(owner, source)
            check('Advancing samples without new events remove old Hz with reason',
                  readout.result.frequency_hz is None and 'Новых событий' in readout.text())
            source.sequence = 3
            source.end = 60001
            source.detector = replace(status, processed_until=60001)
            readout.observe(owner, source)
            readout._advanced_at -= 3
            readout._watchdog()
            check('Frozen source does not retain a live number or invent zero Hz',
                  readout.result is None and 'нет свежих данных' in readout.text() and '0 Гц' not in readout.text())
            source.config_revision = 2
            source.sequence = 1
            source.events = ()
            source.detector = replace(status, indexed_events=0, processed_until=60001, next_ordinal=0)
            readout.observe(owner, source)
            check('Changed search configuration starts with no previous frequency', readout.result.frequency_hz is None)
            readout.set_active(False)
            readout.observe(owner, source)
            check('Late snapshot after stop cannot resurrect a frequency', readout.result is None)
            readout._timer.stop()

            window.close()
            wait(lambda: p.closed and not window.isVisible(), 'Close')
            check('Measurement worker shuts down cleanly', view._measurement_runner._closed)
            report['measurement_updates_observed'] = len(published)
            report['readout_messages_observed'] = len(messages)
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
