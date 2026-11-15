"""Bounded Windows GUI/package witness; every signal is explicitly artificial."""
import hashlib
import json
import math
import platform
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


def run(output):
    from PySide6 import QtWidgets
    from .unified_gui import MainWindow
    from .ringdown import read_ringdown
    from .ringdown_examples import write_capture, write_series
    from .stream_device import default_event_config

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(['Ringdown-check'])
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
        deadline = time.monotonic()+seconds
        while not predicate():
            pump()
            if time.monotonic() > deadline:
                raise AssertionError(message + '\n' + window.panel.ringdown.readout.text())
            time.sleep(.005)
        pump()

    def check(name, condition=True):
        assert condition, name
        report['checks'].append(name)

    def forbid(*args, **kwargs):
        report['real_serial_open_calls'] += 1
        raise AssertionError('Physical COM forbidden')

    def shot(name):
        pump()
        p = window.panel
        wait(lambda: p.ringdown.geometry().bottom() < p.cursors.geometry().top(), 'Ringdown/cursor overlap')
        wait(lambda: p.ringdown.readout.height() >= p.ringdown.readout.heightForWidth(p.ringdown.readout.width()),
             'Readout must fit all wrapped lines')
        wait(lambda: p.ringdown.rect().contains(p.ringdown.readout.mapTo(
                  p.ringdown, p.ringdown.readout.rect().bottomRight())) and
             p.ringdown.body.rect().contains(p.ringdown.readout.geometry()),
             'Readout must not be clipped by parent widgets')
        wait(lambda: p.viewer.content.rect().contains(p.viewer.plot.geometry()),
             'Whole plot including bottom axis must fit its parent')
        check('Visible layout fits: '+name,
              p.ringdown.toggle.isVisible() and window.rect().contains(
                  p.ringdown.toggle.mapTo(window, p.ringdown.toggle.rect().bottomRight())))
        assert window.grab().save(str(output/name))

    def calculate(start=None, stop=None):
        if start is not None:
            r.set_indices(start, stop)
        r.calculate_button.click()
        wait(lambda: r.result is not None, 'Ringdown result')

    try:
        with patch('serial.serialwin32.Serial.open', side_effect=forbid), \
             patch('motortester.transport._serial_factory', side_effect=forbid):
            window = MainWindow(settings_path=output/'settings.ini', port_provider=lambda: [])
            window.resize(1366, 768)
            window.show()
            p, v, r = window.panel, window.panel.viewer, window.panel.ringdown
            check('Cold start has collapsed analysis and no source', not r.toggle.isChecked() and r.result is None)
            assert window.open_ringdown_example()
            wait(lambda: p.archive is not None and v._measurement_completed is not None, 'Service example opens')
            archive = p.archive
            check('Service example is declared synthetic', archive.identity.origin == 'synthetic')
            window.auto_scale()
            r.toggle.click()
            r.propose_button.click()
            wait(lambda: r._operation is None and not r.runner.busy, 'Tail proposal')
            check('Automatic proposal finds a candidate without applying a result',
                  r.suggestion is not None and r.suggestion.available and r.result is None)
            calculate()
            check('Known artificial frequency and damping recovered', r.result.available
                  and math.isclose(r.result.frequency_hz, 2500, rel_tol=.03)
                  and math.isclose(r.result.tau_s, .0012, rel_tol=.15)
                  and r.result.cycle_count >= 3)
            report['example_result'] = dict(frequency_hz=r.result.frequency_hz, tau_s=r.result.tau_s,
                ratio=r.result.amplitude_ratio_per_cycle, cycles=r.result.cycle_count,
                selected_range=r._indices)
            check('Peak markers show original selected samples',
                  len(r.peaks_item.getData()[0]) == len(r.result.peaks) and len(r.result.peaks) >= 4)
            raw_result = r.result
            window.raw_view.setChecked(True)
            check('Raw markers retain exact ADC codes',
                  tuple(r.peaks_item.getData()[1]) == tuple(code for _, code in raw_result.peaks))
            window.raw_view.setChecked(False)
            profile = v.input_profile
            expected = tuple(profile.a*code+profile.b for _, code in raw_result.peaks)
            check('Voltage markers use the same saved affine scale as the trace',
                  all(math.isclose(a,b,abs_tol=1e-10) for a,b in zip(r.peaks_item.getData()[1], expected)))
            window.units.setCurrentText('мВ')
            check('mV changes display units without changing raw analysis', r.result is raw_result
                  and all(math.isclose(a,b,abs_tol=1e-10) for a,b in zip(r.peaks_item.getData()[1], expected)))
            window.units.setCurrentText('В')
            r.add_button.click()
            check('One chosen event is one series member', len(r.series) == 1)
            first, last = r._indices
            calculate(first+5, last)
            check('Manual boundary correction recalculates successfully', r.result.available)
            r.add_button.click()
            check('Reanalysis of the same event does not create another observation', len(r.series) == 1)
            shot('01-ringdown-result.png')

            def slow(reader, start, stop):
                time.sleep(.18)
                return read_ringdown(reader, start, stop)

            with patch('motortester.v2.ringdown_ui.read_ringdown', side_effect=slow):
                r.calculate()
                r.set_indices(first+10, last)
                wait(lambda: not r.runner.busy, 'Cancelled old region job')
                check('Moving region cancels delayed results and clears peak markers',
                      r.result is None and not r.peaks_item.isVisible())
            calculate(first+10, first+20)
            check('Too short interval shows a reason, no invented damping',
                  not r.result.available and bool(r.result.reason) and r.result.tau_s is None)
            shot('02-short-interval.png')

            clipped_path, clipped, tail = write_capture(output/'clipped.mtshot', kind='clipped')
            sustained_path, sustained, sustained_tail = write_capture(output/'sustained.mtshot', kind='sustained')
            inverted_path, inverted, inverted_tail = write_capture(output/'inverted-10bit.mtshot', fs=150000, bits=10, inverted=True)
            series_path = write_series(output/'series.mtstream')
            hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (clipped_path, sustained_path, inverted_path, series_path)}
            with patch('motortester.v2.ringdown_ui.read_ringdown', side_effect=slow):
                r.set_indices(first, last)
                r.calculate()
                assert window.open_path(clipped_path)
                wait(lambda: p.archive is not None and p.archive.identity == clipped.identity
                     and v._measurement_completed is not None and not r.runner.busy, 'Source replacement')
                check('Source replacement removes previous results, peaks and series',
                      r.result is None and not r.series and not r.peaks_item.isVisible())
            r.propose()
            wait(lambda: r._operation is None and not r.runner.busy, 'Clipped proposal refusal')
            check('Automatic proposal cannot silently bypass rail codes', r.suggestion is None and r.result is None)
            calculate(*tail)
            check('Rail codes in selected tail prevent damping result', not r.result.available and 'крайние' in r.result.reason)
            window.auto_scale()
            shot('03-clipped-reason.png')

            assert window.open_path(sustained_path)
            wait(lambda: p.archive is not None and p.archive.identity == sustained.identity
                 and v._measurement_completed is not None, 'Sustained fixture')
            r.propose()  # Also binds the new immutable reader, even on refusal.
            wait(lambda: not r.runner.busy and r._operation is None, 'Sustained proposal')
            calculate(*sustained_tail)
            check('Sustained oscillation is not reported as damped', not r.result.available and r.result.tau_s is None)

            assert window.open_path(inverted_path)
            wait(lambda: p.archive is not None and p.archive.identity == inverted.identity
                 and v._measurement_completed is not None, 'Canonical 10 bit inverted fixture')
            r.propose()
            wait(lambda: not r.runner.busy and r._operation is None, 'Inverted proposal')
            calculate(*inverted_tail)
            check('150k canonical10 and inverted polarity retain timing', r.result.available
                  and math.isclose(r.result.frequency_hz, 2500, rel_tol=.03)
                  and math.isclose(r.result.tau_s, .0012, rel_tol=.15))

            assert window.open_path(series_path)
            wait(lambda: p.archive is not None and p.archive.identity.session_id == 'synthetic-ringdown-series', 'Series archive')
            config = replace(default_event_config(100000), post_samples=700, max_event_samples=2000)
            assert p.apply_search(config)
            wait(lambda: len(v._events) >= 5 and not v.busy, 'Series event index')
            events = tuple(v._events[:3])
            for event in events:
                v._select_event(event)
                wait(lambda: not v.busy, 'Selected series event')
                r.propose()
                wait(lambda: not r.runner.busy and r._operation is None, 'Bind selected event')
                calculate(event.trigger_index+80, min(event.end_index, event.trigger_index+750))
                check('Series event fits: '+str(event.ordinal), r.result.available)
                r.add_button.click()
            check('Series aggregates three distinct events with spread', len(r.series) == 3 and 'Серия 3/20' in r.readout.text())
            window.auto_scale()
            shot('04-distinct-event-series.png')
            r.toggle.click()
            check('Collapsing analysis restores ordinary readouts',
                  not r.isVisible() and p.measurement_label.isVisible() and p.event_frequency.isVisible())
            for path, digest in hashes.items():
                check('Source bytes unchanged: '+path.name, hashlib.sha256(path.read_bytes()).hexdigest() == digest)

            assert p.start_demo('ignition')
            wait(lambda: p.bridge.state.phase == 'preview' and v._drawn_live is not None, 'Live synthetic source')
            r.toggle.click()
            before = p.bridge.state.validated_samples
            wait(lambda: p.bridge.state.validated_samples > before+15000, 'Reception while inspecting')
            check('Analysis holds graph without stopping live reception', v.holding_live and p.bridge.state.phase == 'preview')
            p.stop_button.click()
            wait(lambda: p.bridge.state.can_open, 'Stop synthetic source')
            window.close()
            wait(lambda: p.closed and not window.isVisible(), 'Close')
            check('Ringdown background worker closes', r.runner._closed)
            report['status'] = 'PASS'
    except BaseException:
        report['status'] = 'FAIL'
        report['error'] = traceback.format_exc()
        if window is not None and window.isVisible():
            window.grab().save(str(output/'failure.png'))
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
        (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
