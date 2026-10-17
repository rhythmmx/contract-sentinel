"""Provenance describes consumed bytes, and never certifies a changing input."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from contract_sentinel.core import ScanCancelled, report_dict, scan


CONTRACT = {
    "version": 1,
    "allow_extra": False,
    "fields": {"name": {"type": "string", "required": True}},
}


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "records.jsonl"

    def test_complete_fingerprint_preserves_utf8_and_original_newlines(self):
        payload = '{"name":"café"}\r\n{"name":"東京"}\n{"name":"last"}'.encode("utf-8")
        self.path.write_bytes(payload)
        report = scan(self.path, CONTRACT)
        self.assertTrue(report.passed)
        self.assertEqual(report.records, 3)
        self.assertEqual(report.input_sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(report.input_bytes, len(payload))
        self.assertTrue(report.input_complete)
        self.assertFalse(report.input_changed)
        self.assertEqual(report_dict(report)["input_sha256"], report.input_sha256)

    def test_record_limit_hash_includes_consumed_lookahead_only(self):
        lines = [b'{"name":"one"}\n', b'{"name":"two"}\n', b'{"name":"three"}\n']
        self.path.write_bytes(b"".join(lines))
        report = scan(self.path, CONTRACT, max_records=1)
        consumed = b"".join(lines[:2])
        self.assertEqual(report.records, 1)
        self.assertEqual(report.input_bytes, len(consumed))
        self.assertEqual(report.input_sha256, hashlib.sha256(consumed).hexdigest())
        self.assertTrue(report.truncated)
        self.assertFalse(report.input_complete)
        self.assertFalse(report.input_changed)
        self.assertFalse(report.passed)

    def test_oversized_line_fingerprint_is_bounded_and_incomplete(self):
        payload = b'{"name":"' + b"x" * 1000 + b'"}\n'
        self.path.write_bytes(payload)
        report = scan(self.path, CONTRACT, max_line_bytes=20)
        self.assertEqual(report.input_bytes, 21)
        self.assertEqual(report.input_sha256, hashlib.sha256(payload[:21]).hexdigest())
        self.assertTrue(report.truncated)
        self.assertFalse(report.input_complete)
        self.assertFalse(report.passed)
        self.assertEqual(report.samples[0]["code"], "line_too_large")

    def test_mutation_during_scan_fails_closed_even_for_valid_records(self):
        self.path.write_bytes(b'{"name":"original"}\n')
        calls = 0

        def mutate_after_first_record():
            nonlocal calls
            calls += 1
            if calls == 2:
                with self.path.open("ab") as stream:
                    stream.write(b'{"name":"added"}\n')
            return False

        report = scan(self.path, CONTRACT, should_cancel=mutate_after_first_record)
        self.assertGreaterEqual(calls, 2)
        self.assertEqual(report.invalid_records, 0)
        self.assertFalse(report.truncated)
        self.assertTrue(report.input_changed)
        self.assertFalse(report.input_complete)
        self.assertFalse(report.passed)

    def test_empty_file_has_complete_empty_fingerprint_but_does_not_pass(self):
        self.path.write_bytes(b"")
        report = scan(self.path, CONTRACT)
        self.assertEqual(report.input_sha256, hashlib.sha256(b"").hexdigest())
        self.assertEqual(report.input_bytes, 0)
        self.assertTrue(report.input_complete)
        self.assertFalse(report.input_changed)
        self.assertFalse(report.passed)

    def test_cancellation_never_returns_partial_provenance(self):
        self.path.write_bytes(b'{"name":"one"}\n{"name":"two"}\n')
        calls = 0

        def cancel_after_first_record():
            nonlocal calls
            calls += 1
            return calls == 2

        with self.assertRaises(ScanCancelled):
            scan(self.path, CONTRACT, should_cancel=cancel_after_first_record)
        self.assertEqual(calls, 2)

    def test_cancellation_after_eof_still_raises(self):
        self.path.write_bytes(b"")
        calls = 0

        def cancel_before_return():
            nonlocal calls
            calls += 1
            return calls == 2

        with self.assertRaises(ScanCancelled):
            scan(self.path, CONTRACT, should_cancel=cancel_before_return)

    def test_contract_size_limit_uses_actual_bytes_even_with_stale_metadata(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import json

        from contract_sentinel.core import contract_from

        encoded = json.dumps(CONTRACT).encode("utf-8")
        self.path.write_bytes(encoded + b" " * (1_000_001 - len(encoded)))
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=0)):
            with self.assertRaisesRegex(ValueError, "Contract exceeds 1 MB"):
                contract_from(self.path)

    def test_contract_exact_byte_limit_is_accepted(self):
        import json

        from contract_sentinel.core import contract_from

        encoded = json.dumps(CONTRACT).encode("utf-8")
        self.path.write_bytes(encoded + b" " * (1_000_000 - len(encoded)))
        self.assertEqual(contract_from(self.path), CONTRACT)

    def test_stable_path_and_descriptor_ctime_can_have_different_semantics(self):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch

        self.path.write_bytes(b'{"name":"one"}\n')
        actual_fstat = os.fstat

        def descriptor_stat(fd):
            info = actual_fstat(fd)
            return SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns,
                st_ctime_ns=123,
            )

        with patch("contract_sentinel.core.os.fstat", side_effect=descriptor_stat):
            report = scan(self.path, CONTRACT)
        self.assertTrue(report.passed)
        self.assertTrue(report.input_complete)
        self.assertFalse(report.input_changed)

    def test_descriptor_ctime_change_detected_without_size_or_mtime_change(self):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch

        self.path.write_bytes(b'{"name":"one"}\n')
        actual_fstat = os.fstat
        calls = 0

        def changing_descriptor_stat(fd):
            nonlocal calls
            calls += 1
            info = actual_fstat(fd)
            return SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns,
                st_ctime_ns=calls,
            )

        with patch(
            "contract_sentinel.core.os.fstat", side_effect=changing_descriptor_stat
        ):
            report = scan(self.path, CONTRACT)
        self.assertEqual(calls, 2)
        self.assertTrue(report.input_changed)
        self.assertFalse(report.input_complete)
        self.assertFalse(report.passed)
