"""Persistent workspace ownership; encoded fake serial only, never real COM."""
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtWidgets

from motortester.v2.stream_device import SerialStreamSelection, StreamDeviceBridge
from motortester.v2.unified_panel import UnifiedStreamPanel
from motortester.v2.stream_ui import StreamDialog
from qt_test_support import pump_events
from test_v2_stream_serial import FakeSerialFactory
from test_v2_analog_profile import context as nominal_context


class UnifiedPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.errors = []
        self.old_hook = sys.excepthook
        sys.excepthook = lambda kind, value, traceback: self.errors.append(str(value))
        self.guard = patch('motortester.transport._serial_factory',
                           side_effect=AssertionError('Real COM forbidden'))
        self.guard.start()
        self.factory = FakeSerialFactory()
        def bridge_factory(parent, **options):
            if options.get('selection') is not None:
                options['fake_backend_factory'] = self.factory
            return StreamDeviceBridge(parent, **options)
        self.panel = UnifiedStreamPanel(bridge_factory=bridge_factory)

    def wait(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            pump_events(5)
        self.assertEqual(self.errors, [])
        self.assertTrue(predicate(), str(self.panel.bridge.state))

    def tearDown(self):
        for backend in self.factory.backends:
            backend.fail_close = False
        self.panel.bridge.retry_close()
        self.panel.close()
        self.wait(lambda: self.panel.closed)
        self.panel.deleteLater()
        pump_events(10)
        self.guard.stop()
        sys.excepthook = self.old_hook

    def selection(self, name='TEST-CH1'):
        return SerialStreamSelection(name, requested_sample_rate_hz=50_000)

    def test_inert_start_connect_no_start_and_guard_live_owner(self):
        panel = self.panel
        pump_events(30)
        self.assertIsNone(panel.selection)
        self.assertFalse(panel.demo_enabled)
        self.assertFalse(panel.start_live())
        self.assertFalse(panel.live_button.isEnabled())
        self.assertFalse(panel.record_button.isEnabled())
        self.assertTrue(panel.raw_view.isChecked())
        self.assertFalse(panel.raw_view.isEnabled())
        self.assertFalse(panel.viewer.voltage_display)
        self.assertFalse(panel.viewer.plot.isHidden())
        self.assertFalse(panel.cursors.isHidden())
        self.assertFalse(panel.cursors.enabled.isEnabled())
        self.assertEqual(self.factory.backends, [])
        self.assertIsNone(panel.viewer.scroll_area.widget())
        self.assertIs(panel.viewer.content.parent(), panel)
        self.assertTrue(panel.connect_selection(self.selection()))
        self.wait(lambda: panel.bridge.state.ready and panel.bridge.connection is not None)
        backend = self.factory.backends[0]
        self.assertNotIn(8, [c[0] for c in backend.peer.commands])
        self.assertEqual(panel.bridge.input_format.retained_bits, 12)
        self.assertTrue(panel.start_live())
        self.wait(lambda: panel.bridge.state.phase == 'preview')
        current = panel.bridge
        self.assertFalse(panel.connect_selection(self.selection('OTHER')))
        self.assertFalse(panel.start_demo())
        self.assertIs(current, panel.bridge)
        panel.stop()
        self.wait(lambda: panel.can_select_connection())
        self.assertTrue(panel.connect_selection(self.selection('OTHER')))
        self.wait(lambda: panel.bridge is not current and panel.bridge.state.ready
                  and panel.bridge.connection is not None)
        self.assertFalse(backend.is_open)
        self.assertEqual(panel.selection.port, 'OTHER')
        self.assertEqual(len(self.factory.backends), 2)

    def test_file_view_is_kept_until_ready_and_demo_is_explicit(self):
        panel = self.panel
        panel._opening = True
        panel.viewer.origin_label.setText('Сохранённая запись')
        self.factory.incompatible = 'version'
        self.assertTrue(panel.connect_selection(self.selection()))
        self.wait(lambda: panel.bridge.state.phase == 'fault')
        self.assertTrue(panel._opening)
        self.assertEqual(panel.viewer.origin_label.text(), 'Сохранённая запись')
        self.wait(panel.can_select_connection)
        self.factory.incompatible = None
        self.assertTrue(panel.connect_selection(self.selection()))
        self.wait(lambda: panel.bridge.state.ready and panel.bridge.connection is not None)
        self.assertFalse(panel._opening)
        panel.disconnect_device()
        self.wait(panel.can_change_source)
        self.assertTrue(panel.start_demo('ignition'))
        self.wait(lambda: panel.demo_enabled and panel.bridge.state.phase == 'preview')
        self.assertIsNone(panel.selection)
        self.assertFalse(panel.active_input_profile.configured)
        self.assertTrue(panel.raw_view.isChecked())
        self.assertEqual(panel.context.ui_profile, 'ignition')

    def test_dirty_cancel_and_unconfirmed_close_keep_old_owner(self):
        panel = self.panel
        previous = panel.bridge
        panel.capture.dirty = True
        # Cancel means that the asynchronous prompt never invokes its callback.
        with patch.object(panel.capture, 'confirm_discard', Mock()) as prompt:
            self.assertFalse(panel.connect_selection(self.selection()))
            prompt.assert_called_once()
            self.assertIs(panel.bridge, previous)
            self.assertEqual(self.factory.backends, [])
        panel.capture.dirty = False
        self.assertTrue(panel.connect_selection(self.selection()))
        self.wait(lambda: panel.bridge.state.ready and panel.bridge.connection is not None)
        previous = panel.bridge
        self.factory.backends[0].fail_close = True
        panel.disconnect_device()
        self.wait(lambda: panel.bridge.state.can_retry_close)
        self.assertFalse(panel.can_select_connection())
        self.assertFalse(panel.connect_selection(self.selection('OTHER')))
        self.assertFalse(panel.start_demo())
        self.assertIs(panel.bridge, previous)
        self.assertEqual(len(self.factory.backends), 1)

    def test_ready_can_change_port_and_open_without_start(self):
        panel = self.panel
        self.assertTrue(panel.connect_selection(self.selection()))
        self.wait(lambda: panel.bridge.state.ready and panel.bridge.connection is not None)
        self.assertTrue(panel.can_select_connection())
        previous = panel.bridge
        self.assertTrue(panel.connect_selection(self.selection('SECOND')))
        self.wait(lambda: panel.bridge is not previous and panel.bridge.state.ready
                  and panel.bridge.connection is not None)
        self.assertTrue(panel.open_button.isEnabled())
        backend = self.factory.backends[-1]
        backend.fail_close = True
        with patch.object(StreamDialog, 'open_path', return_value=True) as open_file:
            self.assertTrue(panel.open_path('chosen.mtstream'))
            self.assertFalse(panel.open_path('duplicate.mtstream'))
            self.wait(lambda: panel.bridge.state.can_retry_close and
                      panel.disconnect_button.text() == 'Повторить закрытие порта')
            self.assertTrue(panel.disconnect_button.isEnabled())
            self.assertEqual(panel.disconnect_button.text(), 'Повторить закрытие порта')
            open_file.assert_not_called()
            self.assertTrue(backend.is_open)
            backend.fail_close = False
            self.assertTrue(panel.disconnect_device())
            self.wait(lambda: open_file.called)
            open_file.assert_called_once_with('chosen.mtstream')
            self.assertFalse(backend.is_open)
        for backend in self.factory.backends:
            self.assertNotIn(8, [c[0] for c in backend.peer.commands])

    def test_close_cancels_queued_open(self):
        panel = self.panel
        self.assertTrue(panel.connect_selection(self.selection()))
        self.wait(lambda: panel.bridge.state.ready and panel.bridge.connection is not None)
        with patch.object(panel.bridge, 'disconnect_source', return_value=True), \
                patch.object(StreamDialog, 'open_path', return_value=True) as open_file:
            self.assertTrue(panel.open_path('cancelled.mtstream'))
            self.assertTrue(panel.busy)
            panel.close()
            self.wait(lambda: panel.closed)
            self.assertIsNone(panel._pending_open)
            open_file.assert_not_called()

    def test_loaded_file_defaults_to_its_voltage_profile_once(self):
        panel = self.panel
        panel._opening = True
        panel._refresh_input_display()
        self.assertTrue(panel.raw_view.isChecked())
        panel.archive = object()
        panel.verified_context = SimpleNamespace(context=nominal_context())
        panel._refresh_input_display()
        self.assertFalse(panel.raw_view.isChecked())
        self.assertTrue(panel.viewer.voltage_display)
        # An explicit later raw choice and unit edit survive refreshes.
        panel.raw_view.setChecked(True)
        panel.set_voltage_unit('мВ')
        self.assertTrue(panel.raw_view.isChecked())
        self.assertFalse(panel.viewer.voltage_display)
        panel.archive = None
        panel.verified_context = None
        panel._refresh_input_display()
        panel.archive = object()
        panel.verified_context = SimpleNamespace(context=nominal_context('AC_WIDE'))
        panel._refresh_input_display()
        self.assertFalse(panel.raw_view.isChecked())
        self.assertTrue(panel.viewer.voltage_display)
        # Clear the stand-in before normal lifecycle/status processing.
        panel.archive = panel.verified_context = None
        panel._opening = False


if __name__ == '__main__':
    unittest.main()
