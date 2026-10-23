"""Scan limits reject unsafe types before touching input and preserve valid bounds."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from contract_sentinel.core import scan


CONTRACT = {
    "version": 1,
    "allow_extra": False,
    "fields": {"n": {"type": "integer", "required": True}},
}


class LimitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "PRIVATE_INPUT.jsonl"

    def assert_invalid_before_io(self, **limits):
        with patch.object(Path, "stat") as stat, patch.object(Path, "open") as opened:
            with self.assertRaises(ValueError) as caught:
                scan(self.path, CONTRACT, **limits)
            stat.assert_not_called()
            opened.assert_not_called()
        self.assertNotIn("PRIVATE_INPUT", str(caught.exception))

    def test_count_limits_require_integers_and_valid_ranges_before_io(self):
        invalid = (
            True,
            False,
            1.5,
            float("nan"),
            float("inf"),
            -float("inf"),
            "2",
            None,
            [],
            -1,
        )
        for field in ("max_records", "max_line_bytes", "max_samples"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    self.assert_invalid_before_io(**{field: value})
        for field in ("max_records", "max_line_bytes"):
            with self.subTest(field=field):
                self.assert_invalid_before_io(**{field: 0})
        self.assert_invalid_before_io(max_line_bytes=sys.maxsize)
        self.assert_invalid_before_io(max_line_bytes=sys.maxsize + 1)

    def test_budget_invalid_values_raise_generic_valueerror_before_io(self):
        for value in (
            True,
            False,
            "0.5",
            None,
            [],
            float("nan"),
            float("inf"),
            -float("inf"),
            -0.1,
            1.1,
            10**1000,
        ):
            with self.subTest(value_type=type(value).__name__):
                self.assert_invalid_before_io(error_budget=value)

    def test_record_limit_exact_end_is_complete_but_additional_record_truncates(self):
        self.path.write_bytes(b'{"n":1}\n')
        exact = scan(self.path, CONTRACT, max_records=1)
        self.assertTrue(exact.passed)
        self.assertTrue(exact.input_complete)
        self.assertFalse(exact.truncated)
        self.path.write_bytes(b'{"n":1}\n{"n":2}\n')
        capped = scan(self.path, CONTRACT, max_records=1)
        self.assertEqual(capped.records, 1)
        self.assertTrue(capped.truncated)
        self.assertFalse(capped.passed)
        self.assertFalse(capped.input_complete)

    def test_zero_samples_preserves_invalid_counts_without_diagnostics(self):
        self.path.write_bytes(b'{"n":"bad"}\n{"n":"bad"}\n')
        report = scan(self.path, CONTRACT, max_samples=0)
        self.assertEqual(
            (report.records, report.invalid_records, report.violations), (2, 2, 2)
        )
        self.assertEqual(report.samples, [])
        self.assertFalse(report.passed)

    def test_line_limit_counts_newline_bytes_and_accepts_largest_supported_value(self):
        payload = b'{"n":1}\n'
        self.path.write_bytes(payload)
        self.assertTrue(scan(self.path, CONTRACT, max_line_bytes=len(payload)).passed)
        smaller = scan(self.path, CONTRACT, max_line_bytes=len(payload) - 1)
        self.assertTrue(smaller.truncated)
        self.assertEqual(smaller.samples[0]["code"], "line_too_large")
        self.assertTrue(
            scan(self.path, CONTRACT, max_line_bytes=sys.maxsize - 1).passed
        )
        self.path.write_bytes(b"0")
        minimum = scan(self.path, CONTRACT, max_line_bytes=1)
        self.assertFalse(minimum.truncated)
        self.assertEqual(minimum.records, 1)
        self.assertEqual(minimum.samples[0]["code"], "not_object")

    def test_finite_error_budget_boundaries_and_fractional_threshold(self):
        self.path.write_bytes(b'{"n":1}\n{"n":"bad"}\n')
        for value, passed in (
            (0, False),
            (0.0, False),
            (0.49, False),
            (0.5, True),
            (1, True),
            (1.0, True),
        ):
            with self.subTest(value=value):
                report = scan(self.path, CONTRACT, error_budget=value)
                self.assertEqual(report.passed, passed)
                self.assertEqual(report.invalid_records, 1)

    def test_cli_invalid_limits_are_private_and_never_write_history(self):
        root = Path(self.directory.name)
        schema = root / "contract.json"
        history = root / "history.sqlite"
        schema.write_text(json.dumps(CONTRACT), encoding="utf-8")
        self.path.write_bytes(b'{"n":1}\n')
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        for option, value in (
            ("--max-records", "0"),
            ("--error-budget", "nan"),
            ("--error-budget", "inf"),
        ):
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "contract_sentinel.cli",
                    "check",
                    str(schema),
                    str(self.path),
                    "--history",
                    str(history),
                    option,
                    value,
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            with self.subTest(option=option, value=value):
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertEqual(set(json.loads(run.stdout)), {"error"})
                self.assertNotIn("Traceback", run.stderr)
                self.assertNotIn("PRIVATE_INPUT", run.stdout + run.stderr)
                self.assertNotIn(str(root), run.stdout + run.stderr)
                self.assertFalse(history.exists())
