"""Expected digests bind successful checks to a complete stable byte stream."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from contract_sentinel.core import record_history, report_dict, scan


CONTRACT = {
    "version": 1,
    "allow_extra": False,
    "fields": {"n": {"type": "integer", "required": True}},
}


class ExpectedDigestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "PRIVATE_DATA.jsonl"
        self.payload = b'{"n":1}\r\n{"n":2}\n'
        self.path.write_bytes(self.payload)
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def test_matching_digest_including_uppercase_passes_and_absent_is_none(self):
        for expected in (self.digest, self.digest.upper()):
            report = scan(self.path, CONTRACT, expected_sha256=expected)
            self.assertTrue(report.input_matches_expected)
            self.assertTrue(report.passed)
            self.assertEqual(report.input_sha256, self.digest)
        self.assertIsNone(scan(self.path, CONTRACT).input_matches_expected)

    def test_mismatch_cannot_be_overridden_by_permissive_error_budget(self):
        expected = "0" * 64
        report = scan(self.path, CONTRACT, expected_sha256=expected, error_budget=1)
        self.assertFalse(report.input_matches_expected)
        self.assertFalse(report.passed)
        self.assertTrue(report.input_complete)
        self.assertEqual(report.invalid_records, 0)
        self.assertNotIn(expected, json.dumps(report_dict(report)))

    def test_matching_consumed_prefix_is_not_a_complete_match(self):
        self.path.write_bytes(b'{"n":1}\n{"n":2}\n{"n":3}\n')
        prefix = b'{"n":1}\n{"n":2}\n'
        report = scan(
            self.path,
            CONTRACT,
            max_records=1,
            expected_sha256=hashlib.sha256(prefix).hexdigest(),
        )
        self.assertEqual(report.input_sha256, hashlib.sha256(prefix).hexdigest())
        self.assertTrue(report.truncated)
        self.assertFalse(report.input_complete)
        self.assertFalse(report.input_matches_expected)
        self.assertFalse(report.passed)

    def test_mutation_during_scan_prevents_match(self):
        calls = 0

        def mutate():
            nonlocal calls
            calls += 1
            if calls == 2:
                with self.path.open("ab") as stream:
                    stream.write(b'{"n":3}\n')
            return False

        report = scan(
            self.path, CONTRACT, expected_sha256=self.digest, should_cancel=mutate
        )
        self.assertTrue(report.input_changed)
        self.assertFalse(report.input_matches_expected)
        self.assertFalse(report.passed)

    def test_empty_digest_can_match_without_passing_validation(self):
        self.path.write_bytes(b"")
        report = scan(
            self.path, CONTRACT, expected_sha256=hashlib.sha256(b"").hexdigest()
        )
        self.assertTrue(report.input_matches_expected)
        self.assertTrue(report.input_complete)
        self.assertFalse(report.passed)

    def test_invalid_expected_digest_is_rejected_before_io(self):
        class DigestSubclass(str):
            pass

        for value in (
            True,
            123,
            b"a" * 64,
            "",
            "a" * 63,
            "a" * 65,
            "g" * 64,
            "a" * 63 + "\n",
            DigestSubclass("a" * 64),
        ):
            with (
                self.subTest(value_type=type(value).__name__),
                patch.object(Path, "stat") as stat,
                patch.object(Path, "open") as opened,
            ):
                with self.assertRaises(ValueError):
                    scan(self.path, CONTRACT, expected_sha256=value)
                stat.assert_not_called()
                opened.assert_not_called()

    def test_history_remains_aggregate_and_records_failed_mismatch(self):
        report = scan(self.path, CONTRACT, expected_sha256="0" * 64)
        database = self.root / "history.db"
        record_history(database, report)
        with closing(sqlite3.connect(database)) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
            self.assertEqual(
                columns, ["id", "at", "contract_sha256", "records", "invalid", "passed"]
            )
            self.assertEqual(
                connection.execute(
                    "SELECT records,invalid,passed FROM runs"
                ).fetchone(),
                (2, 0, 0),
            )

    def test_cli_digest_exit_codes_are_private_and_invalid_input_writes_no_history(
        self,
    ):
        schema = self.root / "contract.json"
        schema.write_text(json.dumps(CONTRACT), encoding="utf-8")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        for expected, exit_code in (
            (self.digest, 0),
            ("0" * 64, 1),
            ("PRIVATE_INVALID_DIGEST", 2),
        ):
            history = self.root / f"history-{exit_code}.db"
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "contract_sentinel.cli",
                    "check",
                    str(schema),
                    str(self.path),
                    "--expected-sha256",
                    expected,
                    "--history",
                    str(history),
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )
            with self.subTest(exit_code=exit_code):
                self.assertEqual(run.returncode, exit_code, run.stderr)
                self.assertNotIn("Traceback", run.stderr)
                self.assertNotIn("PRIVATE_DATA", run.stdout + run.stderr)
                if expected != self.digest:
                    self.assertNotIn(expected, run.stdout + run.stderr)
                result = json.loads(run.stdout)
                if exit_code == 2:
                    self.assertEqual(set(result), {"error"})
                    self.assertFalse(history.exists())
                else:
                    self.assertEqual(result["input_matches_expected"], exit_code == 0)
