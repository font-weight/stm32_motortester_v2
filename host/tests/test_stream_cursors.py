"""Focused cursor invariants: exact samples, view rebasing, bounded stale reads."""
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6 import QtWidgets
from motortester.gui_stream import StreamViewerPanel
from motortester.stream_model import StreamIdentity, StreamStart, StreamBlock, StreamTerminal
from motortester.stream_recording import StreamWriter, recover
from motortester.stream_wire import mode_revision
from motortester.v2.stream_cursors import StreamCursorTool, read_cursor_pair


class CursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.panel = StreamViewerPanel()
        self.tool = StreamCursorTool(self.panel)
        self.releases = []

    def wait(self, predicate):
        limit = time.monotonic() + 8
        while not predicate():
            self.app.processEvents()
            if time.monotonic() > limit:
                self.fail('Cursor wait timeout')
            time.sleep(.003)
        self.app.processEvents()

    def tearDown(self):
        for release in self.releases:
            release.set()
        self.tool.shutdown(); self.panel.shutdown()
        self.wait(lambda: not self.tool._mailbox.running and not self.panel._mailbox.running)
        self.tool.close(); self.panel.close()
        self.temp.cleanup()

    def recording(self, name, first=0, count=80000):
        identity = StreamIdentity(name, 0, 7, 50000, 'synthetic')
        path = Path(self.temp.name) / name
        writer = StreamWriter.create(path, StreamStart(identity, first, name))
        for at in range(0, count, 8192):
            values = [(i * 37) % 4096 for i in range(at, min(count, at+8192))]
            writer.append(StreamBlock(identity, first+at, struct.pack(f'<{len(values)}H', *values)))
        end = first+count
        writer.finish(StreamTerminal(identity, end, 'stopped', True, end, end, 0, stop_requested=True))
        return recover(path)

    def load(self, recording):
        self.panel.load_recording(recording)
        self.wait(lambda: not self.panel.busy)

    def test_two_samples_signed_150k_large_index_and_missing(self):
        class Reader:
            identity = StreamIdentity('cursor150', 0, 5, 150000, 'synthetic',
                protocol_revision=mode_revision(5), acquisition_mode=5,
                retained_bits=10, discarded_lsb=2, wire_sample_encoding='u10packed_le',
                normalization='left_shift_2', quantization='truncate_lsb')
            first_sample_index = 2**53+17
            end_sample_index = first_sample_index+80000
            calls = []
            missing = False
            def iter_raw(self, a, b, chunk_samples):
                self.calls.append((a,b,chunk_samples))
                if not self.missing:
                    yield StreamBlock(self.identity, a, struct.pack('<H', (a-self.first_sample_index)*4 % 4096))
        reader = Reader()
        a, b = reader.first_sample_index+123, reader.first_sample_index+7
        values = read_cursor_pair(reader, a, b)
        self.assertEqual((values.code_a, values.code_b), (492, 28))
        self.assertEqual(values.delta_s, -116/150000)
        self.assertEqual(reader.calls, [(a,a+1,1),(b,b+1,1)])
        self.assertEqual(read_cursor_pair(reader, b, b).delta_s, 0)
        reader.missing = True
        with self.assertRaisesRegex(ValueError, 'отсутствует'):
            read_cursor_pair(reader, a, b)
        with self.assertRaises(ValueError):
            read_cursor_pair(reader, reader.end_sample_index, b)

    def test_overview_uses_raw_and_keeps_indices_on_rebase(self):
        first = 2**53+17
        rec = self.recording('large.mtstream', first)
        self.load(rec)
        self.panel.show_whole_recording(); self.wait(lambda: not self.panel.busy)
        self.tool.enabled.setChecked(True)
        self.tool.set_indices(first+123, first+70001)
        self.wait(lambda: self.tool.values is not None and not self.tool.busy)
        values = self.tool.values
        self.assertEqual((values.code_a, values.code_b), (123*37%4096,70001*37%4096))
        self.panel.select_range(first+65000, first+75000)
        self.wait(lambda: not self.panel.busy)
        self.assertEqual(self.tool.values, values)
        self.assertFalse(self.tool.lines[0].isVisible())
        self.assertAlmostEqual(self.tool.lines[1].value(),5001/50000)
        self.assertIn('вне экрана', self.tool.readout.text())
        self.load(self.recording('new.mtstream', count=500))
        self.assertIsNone(self.tool.values)
        self.assertFalse(self.tool.enabled.isChecked())

    def test_coalescing_stale_source_and_stale_integrity_failure(self):
        rec = self.recording('pending.mtstream', count=1000)
        self.load(rec)
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        calls = []
        def slow(reader,a,b):
            calls.append((a,b)); started.set(); release.wait(5)
            return read_cursor_pair(reader,a,b)
        with patch('motortester.v2.stream_cursors.read_cursor_pair', slow):
            self.tool.enabled.setChecked(True)
            self.wait(started.is_set)
            self.tool.set_indices(10,20); self.tool.set_indices(30,40)
            self.assertIsNone(self.tool.values)
            self.assertEqual(len(calls),1)
            self.panel.select_range(0,200); self.wait(lambda:not self.panel.busy)
            release.set()
            self.wait(lambda:not self.tool.busy)
            self.assertEqual(calls[-1],(30,40)); self.assertEqual(len(calls),2)
            self.assertEqual(self.tool.values.a,30)
            # Old-source result cannot revive values on a new recording.
            started.clear(); release.clear(); self.tool.set_indices(50,60)
            self.wait(started.is_set)
            self.load(self.recording('replacement.mtstream',count=1000))
            release.set(); self.wait(lambda:not self.tool.busy)
            self.assertIsNone(self.tool.values)
            # A changed-file error stays visible even if the pair became stale.
            started.clear(); release.clear(); self.tool.enabled.setChecked(True)
            self.wait(started.is_set)
            self.tool.set_indices(70,80)
            current=self.panel._recording
            with current.path.open('r+b') as file:
                file.seek(-1,2); byte=file.read(1); file.seek(-1,2); file.write(bytes([byte[0]^1]))
            release.set(); self.wait(lambda:not self.tool.busy)
            self.assertIsNotNone(self.panel._source_failure)
            self.assertIsNone(self.tool.values)
            self.assertFalse(self.tool.enabled.isChecked())
