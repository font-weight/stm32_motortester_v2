"""Connector-voltage projection of bounded display points; raw stays ADC12."""
import math
import time

from PySide6 import QtCore
import pyqtgraph as pg

from .input import UNKNOWN_PROFILE
from .stream_sync import SynchronizedStreamViewer
from .measurement_ui import MeasurementRunner, format_segment_measurements
from .segment_measurements import read_segment
from ..gui_stream import _HeldReader


class ConnectorAxis(pg.AxisItem):
    factor = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Values stay in volts; only this axis applies the explicit В/мВ
        # display factor. An automatic SI multiplier would label it twice.
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        return [f'{v * self.factor:.6g}'.replace('.', ',') for v in values]


class AnalogStreamViewer(SynchronizedStreamViewer):
    measurements_changed = QtCore.Signal(str)

    def __init__(self, *args, **kwargs):
        self.input_profile = UNKNOWN_PROFILE
        self.raw_display = True
        self.voltage_unit = 'В'
        self._raw_plot_y = ()
        self._overview_measurement = False
        self._measurement_runner = None
        self._measurement_selection = None
        self._measurement_error = None
        self._measurement_completed = None
        self._measurement_submitted_at = 0.0
        super().__init__(*args, **kwargs)
        self.connector_axis = ConnectorAxis(orientation='left')
        self.plot.setAxisItems({'left': self.connector_axis})
        self._measurement_runner = MeasurementRunner(self)
        self._measurement_runner.ready.connect(self._measurement_ready)
        self._measurement_runner.failed.connect(self._measurement_failed)

    @property
    def voltage_display(self):
        return self.input_profile.configured and not self.raw_display

    def value_text(self, voltage):
        factor = 1000 if self.voltage_unit == 'мВ' else 1
        return f'{voltage * factor:.6g} {self.voltage_unit}'.replace('.', ',')

    def set_input_display(self, profile, raw=False, unit='В'):
        if unit not in ('В', 'мВ'):
            raise ValueError('Неизвестная единица напряжения')
        old = self.input_profile
        was_voltage = self.voltage_display
        low, high = self.plot.getViewBox().viewRange()[1]
        raw_bounds = [(v-old.b)/old.a for v in (low, high)] if was_voltage else [low, high]
        self.input_profile, self.raw_display, self.voltage_unit = profile, raw, unit
        self.connector_axis.factor = 1000 if self.voltage_display and unit == 'мВ' else 1
        self.connector_axis.picture = None
        self.connector_axis.update()
        label = 'CH1 · AC' if profile.coupling == 'AC' else 'CH1'
        self.plot.setLabel('left', f'{label}, {unit}' if self.voltage_display else 'Код АЦП')
        bounds = [v*profile.a+profile.b for v in raw_bounds] if self.voltage_display else raw_bounds
        if all(math.isfinite(v) for v in bounds) and bounds[0] != bounds[1]:
            self.plot.setYRange(*sorted(bounds), padding=0)
        # Reproject the exact last display points, without changing X/selection,
        # waiting for mouse movement or touching the receiver.
        xs, _ = self.curve.getData()
        if xs is not None and len(xs) == len(self._raw_plot_y):
            self.curve.setData(xs, self._plot_y_values(self._raw_plot_y), connect='finite')
        self._measurements()

    def _plot_y_values(self, values):
        self._raw_plot_y = tuple(values)
        if self.voltage_display:
            p = self.input_profile
            return [p.a*v+p.b for v in values]
        return values

    def _draw(self, payload):
        if payload.selection != self.selection:
            return
        self._overview_measurement = payload.overview
        super()._draw(payload)
        # The envelope can omit most samples. Read the exact immutable backing
        # of this painted frame; never use a newer live tail for its statistics.
        self._measurement_selection = payload.selection
        self._measurement_error = None
        if self._recording is not None:
            reader, owner = self._recording, self._recording
        else:
            owner = self._held_live if self._held_live is not None else self._drawn_live
            reader = _HeldReader(owner) if owner is not None and owner.raw_u16le is not None else None
        if reader is None:
            self._measurement_runner.cancel()
            self._measurement_completed = None
            self._measurement_error = 'Исходные отсчёты этого кадра недоступны.'
        else:
            start, stop = payload.selection.start, payload.selection.stop
            # Automatic frames can arrive faster than analysis completes. Keep
            # one immutable raw job in flight, publish complete results at up
            # to 4 Hz, and never blank the readout between those jobs. Manual
            # selections cancel old work in _request_plot instead.
            now = time.monotonic()
            automatic = self._automatic_measurements
            if not automatic or (not self._measurement_runner.busy and
                                 now - self._measurement_submitted_at >= .25):
                self._measurement_submitted_at = now
                self._measurement_runner.submit((self._source, id(owner), start, stop),
                                                lambda: read_segment(reader, start, stop))
        self._measurements()

    @property
    def _automatic_measurements(self):
        return self._recording is None and (self.event_sync or self.follow_tail)

    def _measurement_ready(self, result):
        self._measurement_completed = result
        self._measurements()

    def set_event_sync(self, enabled):
        was_enabled = self.event_sync
        accepted = super().set_event_sync(enabled)
        if was_enabled and not self.event_sync and self._measurement_runner is not None:
            # The last published automatic measurement may be one frame old.
            # Once this frame is held, recalculate its exact raw interval even
            # when its endpoints have not changed.
            self._request_plot()
        return accepted

    def _measurements(self):
        if self._measurement_runner is None:
            return
        xs, _ = self.curve.getData()
        if xs is None or not len(xs):
            self._measurement_runner.cancel()
            self._measurement_completed = None
            self.measurements_changed.emit('Ожидание полного кадра по событию.' if self.event_sync
                                           else 'Показатели появятся после получения данных.')
            return
        if self._source_failure:
            result = 'Измерения: — · ошибка целостности исходных данных.'
        elif self._measurement_error:
            result = 'Измерения: — · ' + self._measurement_error
        elif self._measurement_completed is None:
            result = 'Измерения видимого участка: чтение исходных отсчётов…'
        else:
            result = format_segment_measurements(self._measurement_completed, self.input_profile,
                                                  self.raw_display, self.voltage_unit)
            frame = 'Последний рассчитанный кадр' if self._automatic_measurements else 'Видимый участок'
            result += f'\n{frame} · исходные отсчёты · время по номинальной частоте приёма'
        self.measurements_changed.emit(result)

    def _measurement_failed(self, message):
        self._measurement_completed = None
        self._measurement_error = 'Не удалось прочитать участок: ' + message
        if self._recording is not None:
            self._latch_source_failure(self._measurement_error)
        self._measurements()

    def _request_plot(self):
        if self._measurement_runner is not None and not self._aligning:
            self._measurement_runner.cancel()
            self._measurement_completed = None
            self._measurement_submitted_at = 0.0
            self._measurement_error = None
            self.measurements_changed.emit('Измерения видимого участка: ожидание нового графика…')
        return super()._request_plot()

    def _select_event(self, event):
        super()._select_event(event)
        self._measurements()

    def _latch_source_failure(self, message):
        super()._latch_source_failure(message)
        if self._measurement_runner is not None:
            self._measurement_runner.cancel()
            self._measurement_completed = None
            self._measurements()

    def _consume_live_view(self, snapshot):
        consumed = super()._consume_live_view(snapshot)
        if consumed:
            xs, _ = self.curve.getData()
            if xs is None or not len(xs):
                self.measurements_changed.emit('Ожидание полного кадра по событию.')
            else:
                self._measurements()
        return consumed

    def _reset_source(self):
        self._raw_plot_y = ()
        self._measurement_completed = None
        self._measurement_submitted_at = 0.0
        self._measurement_selection = self._measurement_error = None
        if self._measurement_runner is not None:
            self._measurement_runner.cancel()
        super()._reset_source()
        self.measurements_changed.emit('Показатели появятся после получения данных.')

    def shutdown(self):
        if self._measurement_runner is not None:
            self._measurement_runner.shutdown()
        super().shutdown()
