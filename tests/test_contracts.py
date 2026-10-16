import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from contract_sentinel.core import (
    check_record,
    compatibility,
    load_json,
    record_history,
    scan,
    validate_contract,
)


class Contracts(unittest.TestCase):
    def setUp(self):
        self.contract = {
            "version": 1,
            "allow_extra": False,
            "fields": {"count": {"type": "integer", "required": True, "min": 0}},
        }
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "data.ndjson"

    def tearDown(self):
        self.temp.cleanup()

    def test_bool_not_integer(self):
        self.assertEqual(
            check_record({"count": True}, self.contract), [("count", "type")]
        )

    def test_required_and_range(self):
        self.assertEqual(check_record({}, self.contract), [("count", "required")])
        self.assertEqual(
            check_record({"count": -1}, self.contract), [("count", "range")]
        )

    def test_unknown_key_privacy(self):
        errors = check_record({"count": 1, "private-person": "secret"}, self.contract)
        self.assertNotIn("private-person", repr(errors))

    def test_duplicate_and_nan(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}'):
            with self.assertRaises(ValueError):
                load_json(text)

    def test_large_integer_does_not_overflow_float_conversion(self):
        self.assertEqual(check_record({"count": 10**1000}, self.contract), [])

    def test_malformed_private_input(self):
        self.path.write_text('private secret\n{"count": 2}\n')
        report = scan(self.path, self.contract)
        self.assertEqual(report.invalid_records, 1)
        self.assertNotIn("secret", repr(report))
        self.assertFalse(report.passed)
        self.assertTrue(scan(self.path, self.contract, error_budget=0.5).passed)

    def test_record_limit_fails_closed(self):
        self.path.write_text('{"count":1}\n' * 3)
        report = scan(self.path, self.contract, max_records=2)
        self.assertTrue(report.truncated)
        self.assertFalse(report.passed)
        self.assertEqual(report.records, 2)

    def test_exact_limit_is_complete(self):
        self.path.write_text('{"count":1}\n' * 2)
        self.assertTrue(scan(self.path, self.contract, max_records=2).passed)

    def test_oversized_line(self):
        self.path.write_bytes(b"x" * 100)
        report = scan(self.path, self.contract, max_line_bytes=10)
        self.assertTrue(report.truncated)
        self.assertEqual(report.samples[0]["code"], "line_too_large")

    def test_empty_fails(self):
        self.path.write_text("")
        self.assertFalse(scan(self.path, self.contract).passed)

    def test_contract_rejects_bad_constraints(self):
        for changes in ({"min": 5, "max": 2}, {"nullable": 1}, {"pattern": "x"}):
            contract = copy.deepcopy(self.contract)
            contract["fields"]["count"].update(changes)
            with self.assertRaises(ValueError):
                validate_contract(contract)

    def test_numeric_widening(self):
        new = copy.deepcopy(self.contract)
        new["fields"]["count"]["type"] = "number"
        self.assertEqual(compatibility(self.contract, new), [])
        self.assertEqual(
            compatibility(new, self.contract)[0]["reason"], "type_narrowed_or_changed"
        )

    def test_added_required(self):
        new = copy.deepcopy(self.contract)
        new["fields"]["id"] = {"type": "string", "required": True}
        self.assertEqual(
            compatibility(self.contract, new)[0]["reason"], "new_required_field"
        )

    def test_new_optional_constrains_previous_extra(self):
        old = copy.deepcopy(self.contract)
        old["allow_extra"] = True
        new = copy.deepcopy(old)
        new["fields"]["id"] = {"type": "string"}
        self.assertEqual(
            compatibility(old, new)[0]["reason"], "previously_unconstrained_field"
        )

    def test_samples_bounded_and_history_private(self):
        self.path.write_text('{"count":"private-value"}\n' * 100)
        report = scan(self.path, self.contract, max_samples=2)
        self.assertEqual(len(report.samples), 2)
        db = Path(self.temp.name) / "history.db"
        self.assertEqual(record_history(db, report), 1)
        with closing(sqlite3.connect(db)) as conn:
            rows = conn.execute("SELECT * FROM runs").fetchall()
        self.assertNotIn("private-value", repr(rows))

    def test_cli_exit_codes(self):
        contract_path = Path(self.temp.name) / "contract.json"
        contract_path.write_text(json.dumps(self.contract))
        self.path.write_text('{"count":1}\n')
        command = [
            sys.executable,
            "-m",
            "contract_sentinel.cli",
            "check",
            str(contract_path),
            str(self.path),
        ]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.path.write_text("{}\n")
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
        contract_path.write_text("{}")
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
