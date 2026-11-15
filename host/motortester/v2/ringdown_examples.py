"""Declared artificial records, not a simulation validated against ignition."""
import math
import random
import struct
from pathlib import Path

from ..stream_model import StreamIdentity, StreamStart, StreamBlock, StreamTerminal
from ..stream_recording import StreamWriter
from ..stream_view import EventConfig, EventEntry
from ..stream_wire import BATCH1024_REVISION
from .analog_profile import nominal_selection
from .stream_capture import StreamCapture, save_capture
from .stream_device import StreamContext


def sample_codes(*, fs=100000, frequency=2500., tau=.0012, kind='damped', seed=21, step=1):
    """10 ms fixture: baseline, spike, plateau, decaying sine, baseline noise.

    The 1.3 ms tail onset is a definition of this example, not an automatically
    inferred spark boundary. No kV, coil fault or physical transfer is modelled.
    """
    rng = random.Random(seed)
    codes = []
    count = round(.010 * fs)
    for i in range(count):
        t = i/fs
        if t < .0005:
            value = 2048
        elif t < .00055:
            value = 3700
        elif t < .0013:
            value = 2700 - 100*(t-.00055)/.00075
        else:
            u = t-.0013
            envelope = 850 if kind == 'sustained' else 850*math.exp(-u/tau)
            value = 2048 + envelope*math.cos(2*math.pi*frequency*u)
        value += rng.gauss(0, 1.5)
        if kind == 'clipped' and .0014 <= t < .00145:
            value = 4095
        codes.append(max(0, min(4095//step, round(value/step)))*step)
    return tuple(codes), (round(.0013*fs), count)


def write_capture(path, *, kind='damped', fs=100000, bits=12, inverted=False):
    path = Path(path)
    step = 4 if bits == 10 else 1
    codes, tail = sample_codes(fs=fs, kind=kind, step=step)
    if inverted:
        codes = tuple((4092 if bits == 10 else 4095)-v for v in codes)
    identity = StreamIdentity('synthetic-ringdown-'+kind, 1, 5 if bits == 10 else 0, fs, 'synthetic',
        protocol_revision=BATCH1024_REVISION if bits == 10 else None,
        acquisition_mode=5 if bits == 10 else 0, retained_bits=bits, discarded_lsb=2 if bits == 10 else 0,
        wire_sample_encoding='u10packed_le' if bits == 10 else 'u16le',
        normalization='left_shift_2' if bits == 10 else 'identity',
        quantization='truncate_lsb' if bits == 10 else 'none')
    profile, snapshot = nominal_selection('DC_WIDE', identity,
        hardware_instance_id='Искусственные колебания · не измерение платы')
    trigger = round(.0005*fs)
    cfg = EventConfig(1495 if inverted else 2600, 1895 if inverted else 2200,
                      'below' if inverted else 'above', trigger, 10, 10, 0, len(codes),
                      0, 4092 if bits == 10 else 4095)
    event = EventEntry(0, trigger, 0, len(codes), trigger-10, trigger, None, ())
    capture = StreamCapture(identity,
        StreamContext(channel_name='Учебные колебания', ui_profile='ignition',
                      input_profile=profile, analog_snapshot=snapshot),
        cfg, 1, 1, 0, 0, event, struct.pack('<'+str(len(codes))+'H', *codes),
        'event_closed', (), None, 'unknown', '2026-11-14T00:00:00+00:00')
    save_capture(path, capture)
    return path, capture, tail


def write_series(path, count=5):
    """Separate artificial events in one immutable source, for series UI checks."""
    path = Path(path)
    fs, period = 100000, 4000
    identity = StreamIdentity('synthetic-ringdown-series', 1, 0, fs, 'synthetic')
    writer = StreamWriter.create(path, StreamStart(identity, 0, 'synthetic-ringdown-series'))
    for event in range(count):
        codes, _ = sample_codes(fs=fs, tau=.0012*(1+.02*event), seed=21+event)
        values = codes + (2048,)*(period-len(codes))
        writer.append(StreamBlock(identity, event*period, struct.pack('<'+str(period)+'H', *values)))
    end = count*period
    writer.finish(StreamTerminal(identity, end, 'stopped', True, end, end, 0, stop_requested=True))
    return path
