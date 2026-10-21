"""Worker lifecycle checks without creating a display or Tk event loop."""

from concurrent.futures import Future
from threading import Event
import unittest
from unittest.mock import Mock

from contract_sentinel.core import Report, ScanCancelled
from contract_sentinel.gui import Inspector


class InspectorLifecycle(unittest.TestCase):
    def setUp(self):
        self.inspector = Inspector.__new__(Inspector)
        gui = self.inspector
        gui.root = Mock()
        gui.executor = Mock()
        gui.contract = "contract.json"
        gui.dataset = "data.ndjson"
        gui.report = {"stale": True}
        gui.cancel_event = Event()
        gui.running = False
        gui.closed = False
        gui.run_button = Mock()
        gui.cancel_button = Mock()
        gui.export_button = Mock()
        gui.status = Mock()
        gui.table = Mock()
        gui.table.get_children.return_value = ()
        self.future = Future()
        gui.executor.submit.return_value = self.future

    def finish_poll(self):
        self.inspector.root.after.call_args.args[1]()

    def test_cancel_discards_stale_and_racing_completed_reports(self):
        gui = self.inspector
        gui.run()
        self.assertIsNone(gui.report)
        gui.run()  # Re-entry cannot queue another job.
        self.assertEqual(gui.executor.submit.call_count, 1)
        self.future.set_result(Report(1, 0, 0, [], False, "hash", True))
        gui.cancel()
        self.finish_poll()
        self.assertIsNone(gui.report)
        self.assertFalse(gui.running)
        self.assertIn("cancelled", gui.status.set.call_args.args[0])

    def test_worker_cancellation_is_handled(self):
        self.inspector.run()
        self.future.set_exception(ScanCancelled())
        self.finish_poll()
        self.assertFalse(self.inspector.running)
        self.assertIsNone(self.inspector.report)

    def test_changed_input_failure_explained_even_with_valid_records(self):
        self.inspector.run()
        self.future.set_result(
            Report(
                2,
                0,
                0,
                [],
                False,
                "contract",
                False,
                input_sha256="bytes",
                input_changed=True,
            )
        )
        self.finish_poll()
        self.assertIn(
            "source changed during scan", self.inspector.status.set.call_args.args[0]
        )
        self.assertFalse(self.inspector.report["passed"])

    def test_nested_root_diagnostic_has_readable_label(self):
        self.inspector.run()
        self.future.set_result(
            Report(
                1,
                1,
                1,
                [{"line": 1, "field": "", "code": "not_object"}],
                False,
                "contract",
                False,
                field_format="json_pointer",
            )
        )
        self.finish_poll()
        self.assertEqual(
            self.inspector.table.insert.call_args.kwargs["values"],
            (1, "(root)", "not_object"),
        )
        self.assertEqual(self.inspector.report["samples"][0]["field"], "")

    def test_input_change_invalidates_previous_report(self):
        from unittest.mock import patch

        with patch(
            "contract_sentinel.gui.filedialog.askopenfilename", return_value="new.json"
        ):
            self.inspector.choose_contract()
        self.assertIsNone(self.inspector.report)
        self.inspector.export_button.configure.assert_called_with(state="disabled")

    def test_failed_rerun_cannot_export_previous_pass(self):
        self.inspector.run()
        self.future.set_exception(ValueError("bad contract"))
        self.finish_poll()
        self.assertIsNone(self.inspector.report)
        self.inspector.export_button.configure.assert_called_with(state="disabled")

    def test_close_signals_worker_and_poll_never_touches_destroyed_widgets(self):
        gui = self.inspector
        gui.run()
        gui.close()
        self.assertTrue(gui.cancel_event.is_set())
        gui.status.reset_mock()
        self.finish_poll()
        gui.status.set.assert_not_called()
        gui.root.destroy.assert_called_once()
        gui.executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
