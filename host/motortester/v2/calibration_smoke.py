"""Focused Windows/frozen wizard witness; all measurements are artificial."""
from dataclasses import replace
import json
from pathlib import Path
import platform
import sys
import traceback
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets


def run(output):
    from .calibration_ui import CalibrationWizard, ImportWindowDialog
    from .calibration import load_calibration, save_calibration, calibrated_selection, CalibrationRecord
    from .analog_ui import AnalogInputDialog
    from .unified_gui import MainWindow

    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["Calibration-check"])
    app.setStyle("Fusion")
    report = dict(status="RUNNING", platform=platform.platform(), qt_platform=app.platformName(),
        frozen=bool(getattr(sys, "frozen", False)), executable=sys.executable,
        origin="artificial only; device declarations below are serialization fixtures",
        physical_measurements=False, real_serial_open_calls=0, checks=[], callback_errors=[])
    old_hook = sys.excepthook
    sys.excepthook = lambda typ, val, tb: report["callback_errors"].append("".join(traceback.format_exception(typ, val, tb)))
    windows = []
    def pump():
        app.processEvents()
        if report["callback_errors"]: raise AssertionError(report["callback_errors"][-1])
    def shot(widget, name):
        pump(); assert widget.grab().save(str(output / name))
    def forbid_serial(*a, **k):
        report["real_serial_open_calls"] += 1
        raise AssertionError("No physical serial allowed")
    try:
        with patch("serial.Serial", side_effect=forbid_serial), patch("serial.tools.list_ports.comports", return_value=[]):
            main = MainWindow(); windows.append(main); main.show(); pump()
            action = next(a for a in main.service_menu.actions() if a.text() == "Калибровка входа DC / AC…")
            def close_entry():
                try:
                    dialog = app.activeModalWidget()
                    assert isinstance(dialog, CalibrationWizard)
                    dialog.reject()
                except Exception:
                    report["callback_errors"].append(traceback.format_exc())
                    if app.activeModalWidget(): app.activeModalWidget().reject()
            QtCore.QTimer.singleShot(0, close_entry); action.trigger(); pump()
            report["checks"].append("Main Service menu opens offline wizard without STM32")
            main.close(); pump()
            records = []
            for index, (mode, rate) in enumerate((("DC_WIDE", 50000), ("AC_WIDE", 100000), ("AC_SENSITIVE", 150000))):
                wizard = CalibrationWizard(); windows.append(wizard); wizard.show(); pump()
                wizard.plan_page.mode.setCurrentIndex(index)
                wizard.plan_page.rate.setCurrentIndex(index)
                if index == 0: shot(wizard, "01-plan.png")
                wizard.next(); pump(); assert wizard.currentId() == 1, wizard.plan_page.error.text()
                wizard.fit_page.first.button.click(); wizard.fit_page.second.button.click(); pump()
                if index == 0: shot(wizard, "02-dc-fit.png")
                wizard.next(); pump(); assert wizard.currentId() == 2, wizard.fit_page.error.text()
                draft = wizard.draft
                draft_path = output / f"{mode}-draft.mtcal.json"
                save_calibration(draft_path, draft)
                assert load_calibration(draft_path) == draft
                wizard.control_page.control.button.click()
                wizard.next(); pump(); assert wizard.currentId() == 3, wizard.control_page.error.text()
                record = wizard.record
                assert record.state == "synthetic_verified", (record.state, record.control_bound_v)
                assert not record.can_apply
                expected_a = .02 if index == 0 else .005
                assert abs(record.a - expected_a) < .00002
                assert abs(record.b + (40 if index == 0 else 10)) < .04
                shot(wizard, f"0{index+3}-{mode}-result.png")
                path = output / f"{mode}.mtcal.json"
                with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")), \
                     patch.object(QtWidgets.QMessageBox, "information", return_value=QtWidgets.QMessageBox.StandardButton.Ok):
                    assert wizard.save_record(record)
                assert load_calibration(path) == record
                records.append(record)
                wizard.accept(); pump()
                report["checks"].append(f"{mode}/{rate}: wizard fit, independent control, raw save/reopen; cannot apply synthetic")
            # A stored draft resumes exactly at independent control, retaining
            # the prior criteria and fit timestamp (no refitting to the check).
            saved = load_calibration(output / "DC_WIDE-draft.mtcal.json")
            resumed = CalibrationWizard(resume_record=saved); windows.append(resumed); resumed.show(); pump()
            assert resumed.currentId() == 2 and resumed.draft == saved
            resumed.control_page.control.button.click(); resumed.next(); pump()
            assert resumed.record.fit_at_utc == saved.fit_at_utc
            first_control = resumed.record
            resumed.back(); pump(); resumed.control_page.control.button.click()
            with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Cancel):
                resumed.next(); pump()
                assert resumed.currentId() == 2 and resumed.record is first_control
            with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Cancel):
                resumed.reject(); assert resumed.isVisible()
            with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Discard): resumed.reject()
            report["checks"].append("Resume draft; unsaved control Cancel retains result on replacement and close")
            # This path deliberately labels a generated object device to check
            # local UI acceptance; it is never a real measurement or default.
            sample = records[0]
            device = CalibrationRecord(replace(sample.plan, origin="device"),
                tuple(replace(w, origin="device") for w in sample.windows), sample.reference_values,
                sample.fit_at_utc, sample.control_checked_at_utc)
            device_path = output / "DECLARED-DEVICE-FIXTURE-NOT-MEASUREMENT.mtcal.json"
            save_calibration(device_path, device)
            selection = AnalogInputDialog(identity=device.plan.raw_format); windows.append(selection); selection.show(); pump()
            selection.mode.setCurrentIndex(1); selection.instance.setText(device.plan.hardware_instance_id)
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(output / "DC_WIDE.mtcal.json"), "")):
                selection.load_calibration()
            assert selection.measured_pair is None and "реальных данных" in selection.error.text()
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(device_path), "")): selection.load_calibration()
            assert selection.measured_pair is not None and not selection.confirm.isChecked()
            shot(selection, "06-measured-selection-fixture.png")
            selection.confirm.setChecked(True); selection.accept()
            profile, snapshot = selection.profile, selection.snapshot
            assert profile.state == "calibrated" and snapshot.calibration is not None
            again = AnalogInputDialog(identity=device.plan.raw_format, current_profile=profile, current_snapshot=snapshot)
            windows.append(again); again.show(); pump()
            assert again.measured_pair is not None and not again.confirm.isChecked()
            again.instance.setText("other-board"); assert again.measured_pair is None
            again.reject()
            report["checks"].append("Synthetic load rejected; declared-device fixture needs exact mode/instance/Fs + switches; editing instance clears calibration")
            # Worker UI is inert while its request is in flight; only the
            # returned request can supply the selected raw window.
            from concurrent.futures import Future
            pending = Future()
            imp = ImportWindowDialog(records[0].plan); windows.append(imp); imp.show(); pump()
            with patch.object(imp.pool, "submit", return_value=pending): imp.load()
            assert not imp.pick_button.isEnabled() and not imp.settled.isEnabled()
            imp.reject(); assert imp.isVisible()
            pending.set_result(records[0].windows[0]); imp.poll(); pump()
            assert not imp.ok.isEnabled() and not imp.settled.isChecked()
            imp.settled.setChecked(True); assert imp.ok.isEnabled(); imp.accept()
            report["checks"].append("Importer in-flight change/close blocked; settled confirmation required after result")
        report["status"] = "PASS"
    except Exception:
        report["error"] = traceback.format_exc(); report["status"] = "FAIL"
    finally:
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Discard):
            for w in reversed(windows):
                w.close()
        pump()
        sys.excepthook = old_hook
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
