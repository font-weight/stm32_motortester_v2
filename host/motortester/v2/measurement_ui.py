"""Shared raw-result presentation and one bounded background job per view."""
from PySide6 import QtCore

from ..gui_stream import _Mailbox, _Request


def format_segment_measurements(result, profile, raw=False, unit='В'):
    """Project mean through the same affine CH1 profile, without removing DC."""
    def number(value):
        return f'{value:.6g}'.replace('.', ',')

    def voltage(value):
        return f'{number(value * (1000 if unit == "мВ" else 1))} {unit}'

    if result.data_reason:
        return 'Среднее DC, период и частота: — · ' + result.data_reason
    if result.min_code is None:
        return 'Измерения: — · нет исходных отсчётов.'
    if profile.configured and not raw:
        low, high = sorted((profile.a * result.min_code + profile.b,
                            profile.a * result.max_code + profile.b))
        span = f'Min {voltage(low)} · Max {voltage(high)} · Размах {voltage(high-low)}'
    else:
        span = (f'Min {number(result.min_code)} код · Max {number(result.max_code)} код'
                f' · Размах {number(result.max_code-result.min_code)} код')
    if profile.configured and profile.coupling == 'DC':
        mean = 'Среднее DC на CH1: ' + voltage(profile.a * result.mean_code + profile.b)
    elif profile.coupling == 'AC':
        mean = 'Среднее DC: — · AC не измеряет постоянную составляющую'
    else:
        mean = 'Среднее DC: — · шкала или режим DC входа не настроены'
    if result.period_s is not None:
        factor, suffix = ((1e6, 'мкс') if result.period_s < .001 else
                          (1e3, 'мс') if result.period_s < 1 else (1, 'с'))
        period = (f'Период ≈ {number(result.period_s * factor)} {suffix}'
                  f' · Частота ≈ {number(result.frequency_hz)} Гц')
    else:
        period = 'Период / частота: — · ' + (result.period_reason or 'не определены')
    if result.clipped:
        span += ' · крайние коды АЦП: возможно ограничение'
    return span + '\n' + mean + '\n' + period


class MeasurementRunner(QtCore.QObject):
    """A running read plus one replaceable request; no Qt objects in the job.

    ``key`` binds the source, immutable raw snapshot and integer interval.
    Only the latest revision may publish; cancel never touches acquisition.
    """
    ready = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = None
        self.result = None
        self._revision = 0
        self._pending = None
        self._closed = False
        self._mailbox = _Mailbox()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        mailbox = self._mailbox
        self.destroyed.connect(lambda: mailbox.close())

    @property
    def busy(self):
        with self._mailbox.lock:
            return bool(self._mailbox.running or self._mailbox.result or self._pending)

    def submit(self, key, operation):
        if self._closed or self.key == key:
            return False
        self.key, self.result = key, None
        self._revision += 1
        request = _Request(0, self._revision, 'measurement', key, operation)
        with self._mailbox.lock:
            occupied = self._mailbox.running or self._mailbox.result is not None
        if occupied:
            self._pending = request
        else:
            self._pending = None
            self._mailbox.start(request)
        return True

    def cancel(self):
        self._revision += 1
        self.key = self.result = self._pending = None

    def _poll(self):
        if self._closed:
            return
        with self._mailbox.lock:
            completed, self._mailbox.result = self._mailbox.result, None
            idle = not self._mailbox.running
        if completed is not None:
            request, result, error = completed
            if request.revision == self._revision and request.recording == self.key:
                self.result = result
                if error:
                    self.failed.emit(error)
                else:
                    self.ready.emit(result)
        if idle and self._pending is not None:
            request, self._pending = self._pending, None
            self._mailbox.start(request)

    def shutdown(self):
        self.cancel()
        self._closed = True
        self._timer.stop()
        self._mailbox.close()
