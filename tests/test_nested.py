"""Nested object validation, private diagnostics, and recursive compatibility."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from contract_sentinel.core import (
    check_record,
    compatibility,
    diagnostic_format,
    report_dict,
    scan,
    validate_contract,
)


def contract(fields, allow_extra=False):
    return {"version": 1, "fields": fields, "allow_extra": allow_extra}


def object_rule(fields, **changes):
    return {"type": "object", "fields": fields, "allow_extra": False, **changes}


def nested():
    return contract(
        {
            "profile": object_rule(
                {"age": {"type": "integer", "required": True, "min": 0}}, required=True
            )
        }
    )


class NestedTests(unittest.TestCase):
    def test_valid_nested_values_and_flat_scalar_siblings(self):
        schema = nested()
        schema["fields"]["active"] = {"type": "boolean", "required": True}
        self.assertIs(validate_contract(schema), schema)
        self.assertEqual(
            check_record({"profile": {"age": 20}, "active": True}, schema), []
        )
        self.assertEqual(diagnostic_format(schema), "json_pointer")
        self.assertEqual(
            check_record({"profile": {"age": 20}, "active": 1}, schema),
            [("/active", "type")],
        )

    def test_missing_wrong_type_and_nullable_parent_stop_descent(self):
        schema = nested()
        for record, expected in (
            ({}, [("/profile", "required")]),
            ({"profile": None}, [("/profile", "type")]),
            ({"profile": []}, [("/profile", "type")]),
            ({"profile": "PRIVATE_VALUE"}, [("/profile", "type")]),
            ({"profile": {}}, [("/profile/age", "required")]),
        ):
            with self.subTest(record=record):
                self.assertEqual(check_record(record, schema), expected)
        schema["fields"]["profile"]["nullable"] = True
        self.assertEqual(check_record({"profile": None}, schema), [])
        schema["fields"]["profile"]["required"] = False
        self.assertEqual(check_record({}, schema), [])

    def test_unknown_keys_only_identify_parent_object(self):
        schema = nested()
        errors = check_record(
            {
                "PRIVATE_ROOT": True,
                "profile": {"age": 2, "PRIVATE_CHILD": "PRIVATE_VALUE"},
            },
            schema,
        )
        self.assertEqual(
            errors, [("", "unexpected_field"), ("/profile", "unexpected_field")]
        )
        self.assertNotIn("PRIVATE", json.dumps(errors))
        self.assertEqual(check_record([], schema), [("", "not_object")])

    def test_pointer_escaping_in_root_and_nested_field_names(self):
        schema = contract(
            {"~/root": object_rule({"a/b~c": {"type": "integer", "required": True}})}
        )
        self.assertEqual(
            check_record({"~/root": {"a/b~c": "bad"}}, schema),
            [("/~0~1root/a~1b~0c", "type")],
        )

    def test_depth_eight_accepted_nine_rejected(self):
        def chain(depth):
            rule = {"type": "integer"}
            for _ in range(depth):
                rule = object_rule({"child": rule})
            return contract({"top": rule})

        validate_contract(chain(8))
        with self.assertRaises(ValueError):
            validate_contract(chain(9))

    def test_object_schema_rejects_unsupported_or_missing_constraints(self):
        for rule in (
            {"type": "object", "fields": {"n": {"type": "integer"}}},
            object_rule({}),
            object_rule({"n": {"type": "integer"}}, allow_extra=1),
            object_rule({"n": {"type": "integer"}}, min=0),
            object_rule({"n": {"type": "integer"}}, unknown=True),
            object_rule({"n": {"type": "array"}}),
            object_rule({"n": {"type": "integer"}}, nullable=1),
            {"type": "integer", "fields": {"n": {"type": "integer"}}},
        ):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                validate_contract(contract({"obj": rule}))

    def test_flat_contract_diagnostic_api_remains_unchanged(self):
        schema = contract({"age": {"type": "integer", "required": True}})
        self.assertEqual(diagnostic_format(schema), "name")
        self.assertEqual(check_record([], schema), [("$", "not_object")])
        self.assertEqual(
            check_record({"private": True}, schema),
            [("$", "unexpected_field"), ("age", "required")],
        )

    def test_scan_serializes_format_and_pointer_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text('{"profile":{"age":-1}}\n', encoding="utf-8")
            report = scan(path, nested())
        self.assertEqual(report.field_format, "json_pointer")
        self.assertEqual(report_dict(report)["field_format"], "json_pointer")
        self.assertEqual(
            report.samples, [{"line": 1, "field": "/profile/age", "code": "range"}]
        )

    def test_nested_widening_and_loosening_are_compatible(self):
        old = nested()
        new = copy.deepcopy(old)
        new["fields"]["profile"].update(required=False, nullable=True, allow_extra=True)
        new["fields"]["profile"]["fields"]["age"].update(
            type="number", min=-100, required=False, nullable=True
        )
        self.assertEqual(compatibility(old, new), [])

    def test_nested_breaking_changes_have_exact_child_locations(self):
        for updates, reason in (
            ({"type": "string", "min": None}, "type_narrowed_or_changed"),
            ({"min": 10}, "minimum_tightened"),
            ({"max": 50}, "maximum_tightened"),
        ):
            old = nested()
            new = copy.deepcopy(old)
            child = new["fields"]["profile"]["fields"]["age"]
            child.update(updates)
            if child.get("min") is None:
                child.pop("min")
            self.assertIn(
                {"field": "/profile/age", "reason": reason, "severity": "breaking"},
                compatibility(old, new),
            )

    def test_nested_required_nullable_extra_and_removal_breaks(self):
        old = nested()
        parent = old["fields"]["profile"]
        parent["allow_extra"] = True
        parent["fields"]["age"].update(required=False, nullable=True)
        new = copy.deepcopy(old)
        newparent = new["fields"]["profile"]
        newparent["allow_extra"] = False
        newparent["fields"]["age"].update(required=True, nullable=False)
        found = {(item["field"], item["reason"]) for item in compatibility(old, new)}
        self.assertEqual(
            found,
            {
                ("/profile", "extra_fields_now_rejected"),
                ("/profile/age", "now_required"),
                ("/profile/age", "null_no_longer_allowed"),
            },
        )
        old = nested()
        new = copy.deepcopy(old)
        new["fields"]["profile"]["fields"] = {"name": {"type": "string"}}
        self.assertIn(
            {
                "field": "/profile/age",
                "reason": "removed_field_now_rejected",
                "severity": "breaking",
            },
            compatibility(old, new),
        )

    def test_compatibility_uses_pointers_when_only_one_side_is_nested(self):
        old = contract({"profile": {"type": "integer"}})
        new = nested()
        self.assertTrue(
            all(item["field"].startswith("/") for item in compatibility(old, new))
        )

    def test_nested_scan_parser_errors_use_empty_root_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            for payload, limits, expected in (
                (b"not-json\n", {}, "malformed_json"),
                (b"x" * 30, {"max_line_bytes": 10}, "line_too_large"),
            ):
                path.write_bytes(payload)
                report = scan(path, nested(), **limits)
                self.assertEqual(
                    report.samples, [{"line": 1, "field": "", "code": expected}]
                )
                self.assertEqual(report.field_format, "json_pointer")

    def test_deep_json_contract_is_rejected_as_value_error(self):
        from contract_sentinel.core import contract_from

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deep.json"
            path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
            with self.assertRaises(ValueError):
                contract_from(path)
