"""Integer compatibility follows accepted integer values, including widening."""

import unittest

from contract_sentinel.core import check_record, compatibility


def schema(kind="integer", **bounds):
    return {
        "version": 1,
        "allow_extra": False,
        "fields": {"value": {"type": kind, "required": True, **bounds}},
    }


class IntegerCompatibilityTests(unittest.TestCase):
    def test_equivalent_fractional_integer_intervals_are_compatible(self):
        for old_bounds, new_bounds in (
            ({"min": 1.1, "max": 4.9}, {"min": 1.9, "max": 4.1}),
            ({"min": -4.9, "max": -1.1}, {"min": -4.1, "max": -1.9}),
            ({"min": -0.9, "max": 0.9}, {"min": -0.1, "max": 0.1}),
        ):
            for kind in ("integer", "number"):
                with self.subTest(old=old_bounds, new=new_bounds, kind=kind):
                    self.assertEqual(
                        compatibility(schema(**old_bounds), schema(kind, **new_bounds)),
                        [],
                    )

    def test_true_boundary_crossings_have_rejected_integer_witnesses(self):
        for old_bounds, new_bounds, witness, reason in (
            ({"min": 1.1}, {"min": 2.1}, 2, "minimum_tightened"),
            ({"max": 4.9}, {"max": 3.9}, 4, "maximum_tightened"),
            ({"min": -4.9}, {"min": -3.9}, -4, "minimum_tightened"),
            ({"max": -1.1}, {"max": -2.1}, -2, "maximum_tightened"),
        ):
            for kind in ("integer", "number"):
                old, new = schema(**old_bounds), schema(kind, **new_bounds)
                with self.subTest(witness=witness, kind=kind):
                    self.assertEqual(check_record({"value": witness}, old), [])
                    self.assertTrue(check_record({"value": witness}, new))
                    self.assertIn(
                        {"field": "value", "reason": reason, "severity": "breaking"},
                        compatibility(old, new),
                    )

    def test_absent_bounds_widen_and_new_finite_bounds_restrict(self):
        self.assertEqual(compatibility(schema(min=1, max=4), schema()), [])
        self.assertEqual(compatibility(schema(min=1, max=4), schema("number")), [])
        reasons = {
            item["reason"]
            for item in compatibility(schema(), schema(min=-100, max=100))
        }
        self.assertEqual(reasons, {"minimum_tightened", "maximum_tightened"})

    def test_huge_integer_bounds_do_not_require_float_conversion(self):
        huge = 10**1000
        old = schema(min=huge, max=huge + 3)
        for kind in ("integer", "number"):
            self.assertEqual(
                compatibility(old, schema(kind, min=huge, max=huge + 3)), []
            )
            new = schema(kind, min=huge + 1, max=huge + 2)
            self.assertEqual(check_record({"value": huge}, old), [])
            self.assertTrue(check_record({"value": huge}, new))
            self.assertEqual(
                {item["reason"] for item in compatibility(old, new)},
                {"minimum_tightened", "maximum_tightened"},
            )

    def test_number_to_number_preserves_fractional_breaking_changes(self):
        changes = compatibility(
            schema("number", min=1.1, max=4.9), schema("number", min=1.9, max=4.1)
        )
        self.assertEqual(
            {item["reason"] for item in changes},
            {"minimum_tightened", "maximum_tightened"},
        )
        self.assertEqual(check_record({"value": 1.5}, schema("number", min=1.1)), [])
        self.assertTrue(check_record({"value": 1.5}, schema("number", min=1.9)))

    def test_nested_integer_boundary_uses_escaped_json_pointer(self):
        old = {
            "version": 1,
            "allow_extra": False,
            "fields": {
                "a/b": {
                    "type": "object",
                    "allow_extra": False,
                    "fields": {"~value": {"type": "integer", "min": -4.9}},
                }
            },
        }
        new = {
            "version": 1,
            "allow_extra": False,
            "fields": {
                "a/b": {
                    "type": "object",
                    "allow_extra": False,
                    "fields": {"~value": {"type": "number", "min": -3.9}},
                }
            },
        }
        self.assertEqual(
            compatibility(old, new),
            [
                {
                    "field": "/a~1b/~0value",
                    "reason": "minimum_tightened",
                    "severity": "breaking",
                }
            ],
        )

    def test_bounded_acceptance_sets_match_findings_for_nonempty_old_ranges(self):
        bounds = (-2.9, -2, -1.1, -0.1, 0, 0.9, 1.1, 2, 2.9)
        intervals = [(low, high) for low in bounds for high in bounds if low <= high]
        universe = range(-4, 5)
        for old_low, old_high in intervals:
            accepted_old = {value for value in universe if old_low <= value <= old_high}
            if not accepted_old:
                continue
            old = schema(min=old_low, max=old_high)
            for new_low, new_high in intervals:
                accepted_new = {
                    value for value in universe if new_low <= value <= new_high
                }
                expected_break = not accepted_old <= accepted_new
                for kind in ("integer", "number"):
                    actual = bool(
                        compatibility(old, schema(kind, min=new_low, max=new_high))
                    )
                    self.assertEqual(
                        actual,
                        expected_break,
                        (old_low, old_high, new_low, new_high, kind),
                    )
