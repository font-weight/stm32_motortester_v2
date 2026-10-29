"""Single capture checks within the one existing native/frozen GUI witness."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib
import json
import struct

from ..stream_model import StreamIdentity
from ..stream_view import EventConfig, EventEntry
from ..stream_wire import BATCH1024_REVISION
from .stream_device import StreamContext
from .stream_capture import CaptureAttempt, HEADER, load_capture, save_capture


def check_boundaries(folder):
    cfg = EventConfig(2000, 1800, 'above', 5, 3, 2, 0, 30, 0, 4092)
    identity = StreamIdentity('capture-boundaries-synthetic', 1, 5, 150_000, 'synthetic',
        protocol_revision=BATCH1024_REVISION, acquisition_mode=5, retained_bits=10,
        discarded_lsb=2, wire_sample_encoding='u10packed_le', normalization='left_shift_2',
        quantization='truncate_lsb')
    old = EventEntry(3, 12, 7, 18, 10, 12, 15, ())
    first = EventEntry(4, 22, 17, 28, 20, 22, 25, ())
    later = EventEntry(5, 40, 35, 46, 38, 40, 43, ())
    codes = [1000] * 60
    for start in (12, 22, 40):
        codes[start:start + 3] = [2400] * 3
    raw = struct.pack('<60H', *codes)
    status = NS(phase='recording', stop_pending=False, close_requested=False,
        revision=8, config=cfg, config_revision=3, bridge=NS(identity=identity),
        detector_status=NS(outcome='running', processed_until=15, next_ordinal=3,
                           pending=replace(old, end_index=15, flags=('pending',))))
    source = NS(revision=8, identity=identity, config=cfg, config_revision=3, first=0,
        end=60, raw_first=0, raw=raw, events=(old, first, later), flags=(),
        loss_samples=None, tail_state='running', detector=NS(outcome='running', processed_until=60,
            next_ordinal=6, first_retained_ordinal=3, pending=None))
    shot = CaptureAttempt(status, StreamContext()).consume(source)
    assert shot.event == first and shot.identity.retained_bits == 10
    assert shot.raw_u16le == raw[34:56]  # First post-arm event, not old or latest.
    target = folder / 'boundary150.mtshot'
    save_capture(target, shot)
    assert load_capture(target) == shot
    altered = bytearray(target.read_bytes()); altered[-40] ^= 1
    bad = folder / 'corrupt.mtshot'; bad.write_bytes(altered)
    try:
        load_capture(bad)
        raise AssertionError('Повреждённый захват был принят')
    except ValueError:
        pass
    # A valid digest is not enough: the saved search rails must match ADC10.
    data = target.read_bytes()
    magic, meta_size, samples = HEADER.unpack_from(data)
    metadata = json.loads(data[HEADER.size:HEADER.size + meta_size])
    metadata['config']['rail_high'] = 4095
    encoded = json.dumps(metadata).encode('utf-8')
    body = HEADER.pack(magic, len(encoded), samples) + encoded + data[HEADER.size + meta_size:-32]
    invalid = folder / 'invalid-config.mtshot'
    invalid.write_bytes(body + hashlib.sha256(body).digest())
    try:
        load_capture(invalid)
        raise AssertionError('Несогласованные границы ADC10 были приняты')
    except ValueError:
        pass
    try:
        save_capture(target, shot)
        raise AssertionError('Существующий файл был заменён')
    except FileExistsError:
        pass
    assert load_capture(target) == shot
    assert CaptureAttempt(status, StreamContext()).consume(NS(**(vars(source) | {'revision': 9}))) is None
    attempt = CaptureAttempt(status, StreamContext())
    evicted = NS(**(vars(source) | {'raw_first': 25, 'raw': raw[50:]}))
    assert attempt.consume(evicted) is None and attempt.done
    attempt = CaptureAttempt(status, StreamContext())
    pending = replace(first, end_index=26, flags=('pending',))
    early = NS(**(vars(source) | {'end': 26, 'raw': raw[:52], 'events': (old,),
        'detector': NS(outcome='running', processed_until=26, next_ordinal=4,
                       first_retained_ordinal=3, pending=pending)}))
    assert attempt.consume(early) is None and attempt.partial is not None
    incomplete = attempt.finish('host_stop_before_context')
    assert incomplete.completion == 'interrupted' and 'right_truncated' in incomplete.event.flags
    assert incomplete.end_sample_index == 26 and incomplete.raw_u16le == raw[34:52]
    truncated = folder / 'incomplete.mtshot'
    save_capture(truncated, incomplete)
    assert load_capture(truncated) == incomplete
    return {'first_ordinal': shot.event.ordinal, 'pre_arm_ordinal': old.ordinal,
            'later_ordinal': later.ordinal, 'retained_bits': shot.identity.retained_bits,
            'sample_rate_hz': shot.identity.nominal_fs_hz, 'interrupted_end': incomplete.end_sample_index}


def check_capture_live(app, window, panel, output, wait):
    tool = panel.capture
    assert wait(app, tool.arm_button.isEnabled)
    # Explicit cancellation never calls Stop and does not create a frame.
    tool.arm_button.click()
    assert tool.attempt is not None
    tool.arm_button.click()
    assert tool.attempt is None and panel.bridge.state.phase == 'recording'
    tool.arm_button.click()
    request = tool.attempt
    assert request is not None and not panel.viewer.event_sync
    boundary, ordinal = request.boundary, request.ordinal
    assert wait(app, lambda: tool.shot is not None and tool.attempt is None)
    shot = tool.shot
    assert shot.event.trigger_index >= boundary and shot.event.ordinal == ordinal
    viewer = panel.viewer
    assert wait(app, lambda: viewer._display_origin == shot.first_sample_index and
                viewer.curve.getData()[1] is not None)
    frozen_selection = viewer.selection
    before = panel.bridge.state.validated_samples
    assert wait(app, lambda: panel.bridge.state.validated_samples > before + 3000)
    assert viewer.selection == frozen_selection and viewer._held_live is shot and tool.dirty
    assert panel.bridge.state.phase == 'recording'
    panel.cursors.enabled.setChecked(True)
    assert wait(app, lambda: panel.cursors.values is not None)
    assert viewer._held_live is shot
    # Cancelling close must also cancel the main window's pending-close intent.
    window.close()
    assert tool.prompt is not None
    tool.prompt.reject()
    assert wait(app, lambda: tool.prompt is None)
    assert not window._stream_close_pending and not panel._closing and tool.shot is shot
    tool.toggle()  # New capture must not silently replace this unsaved one.
    assert tool.prompt is not None and tool.shot is shot
    tool.prompt.reject()
    assert wait(app, lambda: tool.prompt is None)
    tool.save_dialog()
    assert tool.picker is not None
    before = panel.bridge.state.validated_samples
    assert wait(app, lambda: panel.bridge.state.validated_samples > before + 3000)
    tool.picker.reject()
    assert wait(app, lambda: tool.picker is None)
    assert tool.dirty and tool.shot is shot
    target = Path(output).with_name(Path(output).stem + '-capture.mtshot')
    # A genuine failed file operation must retain the exact in-memory capture.
    occupied = target.with_name(target.stem + '-occupied.mtshot')
    occupied.write_bytes(b'existing user file fixture')
    assert tool.save_path(occupied)
    assert wait(app, lambda: not panel.busy)
    assert tool.dirty and tool.shot is shot and occupied.read_bytes() == b'existing user file fixture'
    assert tool.save_path(target)
    assert wait(app, lambda: not panel.busy and not tool.dirty)
    assert load_capture(target) == shot
    window.yscale.set_value(512, emit=True)
    assert window.grab().save(str(Path(output).with_name(Path(output).stem + '-capture.png')))
    bounds = check_boundaries(Path(output).parent)
    return target, shot, {'arm_end_index': boundary, 'expected_ordinal': ordinal,
        'captured_ordinal': shot.event.ordinal, 'trigger_index': shot.event.trigger_index,
        'start_index': shot.first_sample_index, 'end_index': shot.end_sample_index,
        'raw_sha256': hashlib.sha256(shot.raw_u16le).hexdigest(),
        'artifact': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'boundaries': bounds}


def check_capture_open(app, window, panel, path, shot, output, wait):
    assert panel.capture.shot is shot  # Stop did not discard the capture.
    assert panel.open_path(path)
    assert wait(app, lambda: not panel.busy and panel.archive is not None)
    assert panel.archive == shot and panel.viewer._recording == shot
    assert panel.search_config() == shot.config and not panel.search_editable()
    assert not panel.capture.dirty and not panel.capture.arm_button.isEnabled()
    assert wait(app, lambda: panel.viewer.curve.getData()[1] is not None)
    panel.cursors.enabled.setChecked(True)
    assert wait(app, lambda: panel.cursors.values is not None)
    assert window.grab().save(str(Path(output).with_name(Path(output).stem + '-capture-open.png')))
    return True
