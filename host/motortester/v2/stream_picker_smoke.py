"""Actual Qt save-picker regression; synthetic data only, no native automation."""
import hashlib
import json
from pathlib import Path
import time

from PySide6 import QtCore, QtGui, QtWidgets


HOLD_SECONDS = 2.1
PREVIEW_SECONDS = 70.0
RECORD_SECONDS = 12.0


def write_receipt(output, receipt):
    (Path(output) / "stream-picker-result.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")


def _wait(dialog, flush, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate():
        flush()
        if time.monotonic() >= deadline:
            state = dialog.bridge.state
            raise AssertionError(
                f"Picker wait timed out: phase={state.phase}, revision={state.revision}, "
                f"samples={state.validated_samples}, error={dialog.error_label.text()}")
        time.sleep(.005)
    flush()


def _picker(dialog, flush):
    _wait(dialog, flush, lambda: dialog.record_button.isEnabled())
    dialog.record_button.click()
    _wait(dialog, flush, lambda: dialog._record_picker is not None)
    picker = dialog._record_picker
    assert isinstance(picker, QtWidgets.QFileDialog)
    picker.setWindowTitle("Автоматическая проверка · окно закроется само")
    assert picker.testOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog)
    assert picker.windowModality() == QtCore.Qt.WindowModality.WindowModal
    assert picker.isVisible()
    return picker


def _assert_selected_path(picker, path):
    editor = picker.findChild(QtWidgets.QLineEdit, "fileNameEdit")
    assert editor is not None and editor.text().strip(), "Picker filename field is empty"
    selected = picker.selectedFiles()
    assert len(selected) == 1 and Path(selected[0]).resolve() == Path(path).resolve(), (
        f"Picker path differs: field={editor.text()!r}, selected={selected!r}, expected={str(path)!r}")
    buttons = picker.findChild(QtWidgets.QDialogButtonBox, "buttonBox")
    assert buttons is not None
    begin = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
    assert begin is not None and begin.isEnabled(), "Picker Begin button is disabled"


def _enter_path(picker, path, flush):
    # selectFile() on an already visible QFileDialog may change its directory
    # without populating the editor. Exercise the real filename field instead.
    editor = picker.findChild(QtWidgets.QLineEdit, "fileNameEdit")
    assert editor is not None, "Qt QFileDialog filename editor was not found"
    editor.setFocus()
    editor.setText(str(Path(path).resolve()))
    flush()
    _assert_selected_path(picker, path)


def exercise_record_picker(dialog, path, output, flush):
    """Cancel then Save through the real Record button; leave the writer running.

    The enclosing stream smoke subsequently performs Stop, strict reopen and
    raw/CSV comparison for this exact selected path.
    """
    path, output = Path(path).resolve(), Path(output)
    receipt = {"status": "RUNNING", "source": "paced synthetic wire 0.2",
               "hold_seconds_minimum": HOLD_SECONDS, "selected_path": str(path),
               "save_picker_seconds_minimum": PREVIEW_SECONDS,
               "record_seconds_minimum": RECORD_SECONDS,
               "qt_widget_picker": True, "physical_stream_verified": False}
    plot_updates = [0]

    def changed(*unused):
        plot_updates[0] += 1

    def snapshot():
        state = dialog.bridge.state
        session = None if state.bridge is None else state.bridge.session
        return {"revision": state.revision, "phase": state.phase,
                "samples": state.validated_samples,
                "viewer_sequence": dialog.viewer._latest_live_sequence,
                "plot_updates": plot_updates[0],
                "record_start": None if session is None else session.selected_start_sample_index,
                "writer_accepted_end": None if session is None else session.accepted_end_sample_index,
                "writer_checkpointed_end": None if session is None else session.checkpointed_end_sample_index,
                "failure_code": None if session is None or session.first_failure is None
                                else session.first_failure.code}

    def hold(picker, phase, seconds=HOLD_SECONDS):
        before = snapshot()
        assert before["phase"] == "preview"
        started = previous_poll = last_advance = time.monotonic()
        last_count = before["samples"]
        max_poll_gap = max_sample_gap = 0.
        next_checkpoint = 10.
        checkpoints = []
        previous_sequence = before["viewer_sequence"]
        previous_plot_updates = before["plot_updates"]
        evidence = {"before": before, "checkpoints": checkpoints, "finished_events": []}
        receipt[phase] = evidence

        def finished(result):
            if len(evidence["finished_events"]) < 4:
                evidence["finished_events"].append({
                    "result": int(result), "elapsed_seconds": time.monotonic() - started,
                    "wall_time_unix_seconds": time.time(), "state": snapshot()})
                write_receipt(output, receipt)

        picker.finished.connect(finished)
        write_receipt(output, receipt)
        # The observed Preview failure was near 61 s. The Save picker remains
        # visible for 70 s, while the normal main-window timer is also active.
        while time.monotonic() - started < seconds:
            flush()
            now = time.monotonic()
            max_poll_gap = max(max_poll_gap, now - previous_poll)
            previous_poll = now
            state = dialog.bridge.state
            assert state.revision == before["revision"], "Picker changed source revision"
            assert state.phase == "preview", f"Preview stopped in picker: {state.phase}"
            assert state.validated_samples >= last_count
            assert picker.isVisible()
            max_sample_gap = max(max_sample_gap, now - last_advance)
            if state.validated_samples > last_count:
                last_advance = now
                last_count = state.validated_samples
            elapsed = now - started
            evidence.update(elapsed_seconds=elapsed, max_poll_gap_seconds=max_poll_gap,
                            max_sample_update_gap_seconds=max_sample_gap,
                            controller_max_service_gap_ms=state.max_service_gap_ms)
            if elapsed >= next_checkpoint:
                checkpoint = snapshot()
                checkpoint["elapsed_seconds"] = elapsed
                assert checkpoint["viewer_sequence"] > previous_sequence
                assert checkpoint["plot_updates"] > previous_plot_updates
                previous_sequence = checkpoint["viewer_sequence"]
                previous_plot_updates = checkpoint["plot_updates"]
                checkpoints.append(checkpoint)
                write_receipt(output, receipt)
                next_checkpoint += 10.
            time.sleep(.005)
        after = snapshot()
        elapsed = time.monotonic() - started
        assert after["phase"] == "preview" and after["revision"] == before["revision"]
        assert after["samples"] > before["samples"]
        assert after["viewer_sequence"] > before["viewer_sequence"]
        assert after["plot_updates"] > before["plot_updates"]
        assert dialog.viewer.curve.getData()[0] is not None
        evidence.update(after=after, elapsed_seconds=elapsed,
                        samples_per_wall_second=(after["samples"] - before["samples"]) / elapsed)
        write_receipt(output, receipt)
        return after

    dialog.viewer.curve.sigPlotChanged.connect(changed)
    try:
        _wait(dialog, flush, lambda: dialog.bridge.state.phase == "preview"
              and dialog.viewer.curve.getData()[0] is not None)
        cancelled = _picker(dialog, flush)
        cancel_after = hold(cancelled, "cancel_picker")
        cancelled.reject()
        _wait(dialog, flush, lambda: dialog._record_picker is None)
        assert dialog.bridge.state.phase == "preview"
        assert dialog.bridge.state.revision == cancel_after["revision"]
        assert dialog.saved_path is None and not path.exists()

        selected = _picker(dialog, flush)
        _enter_path(selected, path, flush)
        save_after = hold(selected, "save_picker", PREVIEW_SECONDS)
        _assert_selected_path(selected, path)
        flush()
        image = output / "stream-record-picker.png"
        assert selected.grab().save(str(image))
        assert not QtGui.QImage(str(image)).isNull()
        selected.accept()
        _wait(dialog, flush, lambda: dialog._record_picker is None
              and dialog.bridge.state.phase == "recording")
        started = snapshot()
        assert started["revision"] == save_after["revision"]
        began = previous_poll = time.monotonic()
        last_count = started["samples"]
        last_writer_end = started["writer_accepted_end"] or started["record_start"]
        last_plot_updates = started["plot_updates"]
        next_checkpoint = 2.
        writer_evidence = {"before": started, "checkpoints": [], "max_poll_gap_seconds": 0.}
        receipt["sustained_record"] = writer_evidence
        # The reported storage-capacity failure occurred about 2.6 s after R.
        # Twelve seconds also crosses the 1 MiB periodic writer checkpoint.
        # Verify actual writer progress, not only Preview counters.
        while time.monotonic() - began < RECORD_SECONDS:
            flush()
            now = time.monotonic()
            writer_evidence["max_poll_gap_seconds"] = max(
                writer_evidence["max_poll_gap_seconds"], now - previous_poll)
            previous_poll = now
            current = snapshot()
            assert current["phase"] == "recording", f"Recording stopped: {current}"
            assert current["revision"] == started["revision"]
            assert current["failure_code"] is None
            assert current["samples"] >= last_count
            last_count = current["samples"]
            elapsed = now - began
            writer_evidence["elapsed_seconds"] = elapsed
            if elapsed >= next_checkpoint:
                assert current["writer_accepted_end"] is not None
                assert current["writer_accepted_end"] > last_writer_end
                assert current["plot_updates"] > last_plot_updates
                last_writer_end = current["writer_accepted_end"]
                last_plot_updates = current["plot_updates"]
                current["elapsed_seconds"] = elapsed
                writer_evidence["checkpoints"].append(current)
                write_receipt(output, receipt)
                next_checkpoint += 2.
            time.sleep(.005)
        running = snapshot()
        assert running["phase"] == "recording"
        assert running["revision"] == save_after["revision"]
        assert running["samples"] > started["samples"]
        assert running["plot_updates"] > started["plot_updates"]
        assert running["writer_accepted_end"] - running["record_start"] > 131072
        assert running["writer_checkpointed_end"] is not None
        assert running["writer_checkpointed_end"] > running["record_start"]
        assert not dialog.error_label.text(), dialog.error_label.text()
        elapsed = time.monotonic() - began
        writer_evidence.update(after=running, elapsed_seconds=elapsed,
                               samples_per_wall_second=(running["samples"] - started["samples"]) / elapsed)
        receipt.update(status="RECORDING", after_accept=started, recording_continues=running)
        return receipt
    except BaseException as exc:
        receipt.update(status="FAIL", error=f"{type(exc).__name__}: {exc}",
                       failure_state=snapshot())
        raise
    finally:
        if dialog._record_picker is not None:
            dialog._record_picker.reject()
        dialog.viewer.curve.sigPlotChanged.disconnect(changed)
        write_receipt(output, receipt)


def exercise_stopped_source_picker(dialog, path, output, flush, receipt):
    """A choice made for a stopped preview must not silently start another one."""
    path = Path(path).resolve()
    try:
        assert dialog.start_live()
        assert dialog.viewer.curve.getData()[0] is None
        _wait(dialog, flush, lambda: dialog.bridge.state.phase == "preview")
        picker = _picker(dialog, flush)
        _enter_path(picker, path, flush)
        revision = dialog.bridge.state.revision
        assert dialog.stop()
        _wait(dialog, flush, lambda: dialog.bridge.state.can_open)
        stopped = dialog.bridge.state.validated_samples
        _assert_selected_path(picker, path)
        picker.accept()
        _wait(dialog, flush, lambda: dialog._record_picker is None)
        # Drain the asynchronous callback without allowing an unobserved new
        # admission to hide behind the previous published stopped state.
        until = time.monotonic() + .15
        while time.monotonic() < until:
            flush()
            state = dialog.bridge.state
            assert state.can_open and state.revision == revision
            assert state.validated_samples == stopped
            assert not state.command_pending
            time.sleep(.005)
        assert dialog.error_label.text(), "Stale file choice must explain its rejection"
        assert not path.exists()
        assert not path.with_name(path.name + ".v2.json").exists()
        receipt["stopped_source_choice"] = {
            "revision": revision, "samples": stopped, "new_file_created": False,
            "message": dialog.error_label.text(), "new_source_admitted": False}
        receipt["status"] = "PASS"
    except BaseException as exc:
        receipt.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if dialog._record_picker is not None:
            dialog._record_picker.reject()
        write_receipt(output, receipt)


def exercise_existing_path_picker(path, output, flush):
    """Attempt a real picker save over a completed fixture; retain both files."""
    from .stream_device import companion_path
    from .stream_ui import StreamDialog

    path, output = Path(path).resolve(), Path(output)
    files = (path, companion_path(path))

    def hashes():
        result = {}
        for file in files:
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(256 * 1024), b""):
                    digest.update(chunk)
            result[file.name] = {"sha256": digest.hexdigest(), "bytes": file.stat().st_size}
        return result

    def save():
        (output / "stream-existing-path-result.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    receipt = {"status": "RUNNING", "selected_existing_path": str(path),
               "before": hashes(), "physical_stream_verified": False}
    dialog = StreamDialog()
    dialog.show()
    save()
    try:
        assert dialog.start_live()
        _wait(dialog, flush, lambda: dialog.bridge.state.phase == "preview")
        picker = _picker(dialog, flush)
        _enter_path(picker, path, flush)
        _assert_selected_path(picker, path)
        picker.accept()
        _wait(dialog, flush, lambda: dialog._record_picker is None
              and dialog.bridge.state.can_open and dialog.bridge.metadata_error is not None)
        state = dialog.bridge.state
        assert state.bridge.session.first_failure.code == "host_io"
        assert dialog.saved_path is None
        assert "Файл уже существует" in dialog.error_label.text()
        assert path.as_posix() in dialog.error_label.text().replace("\\", "/")
        assert "Запись не началась" in dialog.state_label.text()
        receipt.update(error_code=state.bridge.session.first_failure.code,
                       visible_message=dialog.error_label.text(),
                       state_message=dialog.state_label.text(),
                       after=hashes(), recording_reported_saved=False)
        assert receipt["before"] == receipt["after"]
        image = output / "stream-existing-path.png"
        assert dialog.grab().save(str(image))
        assert not QtGui.QImage(str(image)).isNull()
        receipt["status"] = "PASS"
        return receipt
    except BaseException as exc:
        receipt.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        save()
        try:
            if dialog._record_picker is not None:
                dialog._record_picker.reject()
            dialog.stop()
            _wait(dialog, flush, lambda: dialog.bridge.state.can_open
                  and (not dialog.bridge.metadata_pending or dialog.bridge.metadata_error is not None))
            # Only the controlled failed test attempt is abandoned. The original
            # journal and companion were verified above and are never removed.
            failure = dialog.bridge.metadata_error
            if failure is not None:
                assert dialog.bridge.abandon_context(failure)
            dialog.close()
            _wait(dialog, flush, lambda: dialog.closed)
            receipt["test_workspace_closed"] = True
        except BaseException as exc:
            receipt.update(status="FAIL", cleanup_error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            save()
