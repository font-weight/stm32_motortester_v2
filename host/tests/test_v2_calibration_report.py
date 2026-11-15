"""PDF projection and exclusive publication; no physical acquisition."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6 import QtGui, QtWidgets

from motortester.v2.calibration import fit_dc, fit_ac, validate_control
from motortester.v2.calibration_report import _report_html, export_calibration_report
from test_v2_calibration import plan, window, dc_record


class CalibrationReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def plain(self, record):
        doc = QtGui.QTextDocument()
        doc.setHtml(_report_html(record))
        return doc.toPlainText()

    def test_pending_failed_and_ac_synthetic_scope(self):
        p = plan(instrument='<b>RM102 & другое</b>', conditions='условия <не HTML>')
        draft = fit_dc(p, window(p, 1500, 'first'), -5., window(p, 2500, 'second'), 5.)
        text = self.plain(draft)
        self.assertIn('Независимый контроль ещё не выполнен', text)
        self.assertIn('<b>RM102 & другое</b>', text)
        self.assertIn('НЕ ПРИМЕНЯТЬ К РЕАЛЬНОМУ ВХОДУ', text)
        self.assertIn('0,01 В/код; b = -20 В', text)
        failed = dc_record(plan(reference_uncertainty_v=.04, tolerance_v=.05))
        self.assertIn('КОНТРОЛЬ НЕ ПРОЙДЕН', self.plain(failed))
        declared = self.plain(dc_record(plan(origin='device')))
        self.assertIn('ПРОИСХОЖДЕНИЕ НЕ АТТЕСТОВАНО', declared)
        self.assertIn('Контроль по данным оператора пройден в указанных условиях', declared)
        p = plan('AC_WIDE', bits=10, amplitude_kind='Vpp', polarity=-1)
        ac = validate_control(fit_ac(p, window(p, 2048, 'zero'),
            window(p, 2100, 'sine', sine_amplitude=400), 4.),
            window(p, 2000, 'control', sine_amplitude=200), 2.)
        text = self.plain(ac)
        self.assertIn('сохранено 10 бит', text)
        self.assertIn('коды ADC12 0…4092, шаг 4', text)
        self.assertIn('ИСКУССТВЕННЫЕ ДАННЫЕ - НЕ КАЛИБРОВКА ПРИБОРА', text)
        self.assertIn('Постоянная составляющая CH1 не измеряется', text)
        self.assertIn('Время подготовки участка и расчёта не является временем физического измерения', text)
        for summary in ac.summaries:
            self.assertIn(summary.raw_sha256[:32], text)

    def test_pdf_atomic_new_name_preserves_record_and_cleans_failure(self):
        record = dc_record()
        before = record.to_dict()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'Протокол CH1.pdf'
            self.assertEqual(export_calibration_report(path, record), path)
            original = path.read_bytes()
            self.assertTrue(original.startswith(b'%PDF-'))
            self.assertIn(b'%%EOF', original[-256:])
            with self.assertRaises(FileExistsError):
                export_calibration_report(path, record)
            self.assertEqual(path.read_bytes(), original)
            with patch('motortester.v2.calibration_report._write_pdf', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    export_calibration_report(Path(folder)/'failed.pdf', record)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ['Протокол CH1.pdf'])
            # Simulate a file appearing while the report was being rendered.
            competing = Path(folder)/'race.pdf'
            def race(source, destination):
                Path(destination).write_bytes(b'other owner')
                raise FileExistsError('new owner')
            with patch('motortester.v2.calibration_report.os.link', side_effect=race):
                with self.assertRaises(FileExistsError):
                    export_calibration_report(competing, record)
            self.assertEqual(competing.read_bytes(), b'other owner')
            self.assertFalse(list(Path(folder).glob('.motortester-report-*')))
        self.assertEqual(record.to_dict(), before)


if __name__ == '__main__':
    unittest.main()
