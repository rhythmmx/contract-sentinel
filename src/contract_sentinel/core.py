"""A deliberately small contract dialect, not a JSON Schema implementation."""

from dataclasses import asdict, dataclass
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Callable

TYPES = {"string", "integer", "number", "boolean", "object"}


def load_json(text: str):
    def reject(value):
        raise ValueError("Non-finite JSON numbers are not supported")

    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Non-finite JSON numbers are not supported")
        return parsed

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        text, parse_constant=reject, parse_float=finite_float, object_pairs_hook=pairs
    )


def validate_contract(contract: dict) -> dict:
    if not isinstance(contract, dict) or set(contract) != {
        "version",
        "fields",
        "allow_extra",
    }:
        raise ValueError("Contract requires exactly version, fields and allow_extra")
    if type(contract["version"]) is not int or contract["version"] < 1:
        raise ValueError("Version must be a positive integer")

    def validate_object(node, depth):
        if depth > 8:
            raise ValueError("Object nesting exceeds 8 levels")
        if type(node.get("allow_extra")) is not bool or not isinstance(
            node.get("fields"), dict
        ):
            raise ValueError("Invalid object fields")
        if not node["fields"]:
            raise ValueError("At least one field is required")
        for name, rule in node["fields"].items():
            if not isinstance(name, str) or not name or not isinstance(rule, dict):
                raise ValueError("Invalid field rule")
            kind = rule.get("type")
            if not isinstance(kind, str) or kind not in TYPES:
                raise ValueError("Unsupported field type")
            allowed = {"type", "required", "nullable"}
            allowed |= {"fields", "allow_extra"} if kind == "object" else {"min", "max"}
            if set(rule) - allowed:
                raise ValueError("Unsupported field constraint")
            for flag in ("required", "nullable"):
                if type(rule.get(flag, False)) is not bool:
                    raise ValueError("Flags must be boolean")
            if kind == "object":
                validate_object(rule, depth + 1)
                continue
            for bound in ("min", "max"):
                if bound in rule:
                    value = rule[bound]
                    if kind not in {"integer", "number"} or type(value) not in {
                        int,
                        float,
                    }:
                        raise ValueError(
                            "Bounds require numeric fields and numeric values"
                        )
                    if type(value) is float and not math.isfinite(value):
                        raise ValueError("Bounds must be finite")
            if rule.get("min", -math.inf) > rule.get("max", math.inf):
                raise ValueError("Minimum exceeds maximum")

    validate_object(contract, 0)
    return contract


def diagnostic_format(contract: dict) -> str:
    """Identify how contract field locations are encoded in diagnostics."""
    return (
        "json_pointer"
        if any(r["type"] == "object" for r in contract["fields"].values())
        else "name"
    )


def _field_location(parent: str, name: str, pointers: bool) -> str:
    if pointers:
        return parent + "/" + name.replace("~", "~0").replace("/", "~1")
    return name


def contract_from(path: Path) -> dict:
    # Bound the actual read: metadata checked before opening could become stale.
    with path.open("rb") as stream:
        content = stream.read(1_000_001)
    if len(content) > 1_000_000:
        raise ValueError("Contract exceeds 1 MB")
    try:
        return validate_contract(load_json(content.decode("utf-8")))
    except RecursionError:
        raise ValueError("Contract nesting exceeds supported limits") from None


def check_record(record, contract: dict) -> list[tuple[str, str]]:
    pointers = diagnostic_format(contract) == "json_pointer"
    errors = []

    def check_object(value, node, location):
        if not isinstance(value, dict):
            errors.append((location, "not_object"))
            return
        fields = node["fields"]
        if not node["allow_extra"] and value.keys() - fields.keys():
            # Do not disclose unknown input key names.
            errors.append((location, "unexpected_field"))
        for name, rule in fields.items():
            field = _field_location(location, name, pointers)
            if name not in value:
                if rule.get("required", False):
                    errors.append((field, "required"))
                continue
            item = value[name]
            if item is None and rule.get("nullable", False):
                continue
            kind = rule["type"]
            correct = (
                (kind == "integer" and type(item) is int)
                or (kind == "number" and type(item) in {int, float})
                or (kind == "string" and isinstance(item, str))
                or (kind == "boolean" and type(item) is bool)
                or (kind == "object" and isinstance(item, dict))
            )
            if not correct:
                errors.append((field, "type"))
                continue
            if kind == "object":
                check_object(item, rule, field)
            elif kind in {"integer", "number"}:
                if type(item) is float and not math.isfinite(item):
                    errors.append((field, "non_finite"))
                elif item < rule.get("min", -math.inf) or item > rule.get(
                    "max", math.inf
                ):
                    errors.append((field, "range"))

    check_object(record, contract, "" if pointers else "$")
    return errors


@dataclass
class Report:
    records: int
    invalid_records: int
    violations: int
    samples: list[dict]
    truncated: bool
    contract_sha256: str
    passed: bool
    input_sha256: str = ""
    input_bytes: int = 0
    input_complete: bool = False
    input_changed: bool = False
    field_format: str = "name"


class ScanCancelled(Exception):
    """A scan stopped cooperatively; no complete report is available."""


def scan(
    path: Path,
    contract: dict,
    *,
    max_records: int = 100_000,
    max_line_bytes: int = 1_000_000,
    max_samples: int = 50,
    error_budget: float = 0,
    should_cancel: Callable[[], bool] | None = None,
) -> Report:
    """Scan bounded lines, checking cancellation between reads and before return.

    Cancellation cannot interrupt an operating-system read already in progress.
    A cancelled scan raises ScanCancelled instead of returning a partial report.
    Input hashes cover bytes returned by bounded reads, including record-limit
    lookahead. Only input_complete identifies a complete, unchanged input hash.
    Metadata checks detect common modifications, not an immutable snapshot.
    """
    validate_contract(contract)
    field_format = diagnostic_format(contract)
    root_location = "" if field_format == "json_pointer" else "$"
    if (
        not 0 <= error_budget <= 1
        or max_records < 1
        or max_line_bytes < 1
        or max_samples < 0
    ):
        raise ValueError("Invalid scan limits")
    records = invalid = violations = 0
    samples: list[dict] = []
    truncated = False
    input_digest = hashlib.sha256()
    input_bytes = 0
    reached_eof = False

    def identity(stat):
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    before = identity(path.stat())
    with path.open("rb") as stream:
        opened = identity(os.fstat(stream.fileno()))
        while True:
            if should_cancel is not None and should_cancel():
                raise ScanCancelled()
            line = stream.readline(max_line_bytes + 1)
            if not line:
                reached_eof = True
                break
            input_digest.update(line)
            input_bytes += len(line)
            if records >= max_records:
                truncated = True
                break
            records += 1
            if len(line) > max_line_bytes:
                # Stop rather than consuming an unbounded hostile line.
                errors = [(root_location, "line_too_large")]
                truncated = True
            else:
                try:
                    record = load_json(line.decode("utf-8"))
                    errors = check_record(record, contract)
                except (ValueError, UnicodeError, RecursionError):
                    errors = [(root_location, "malformed_json")]
            if errors:
                invalid += 1
                violations += len(errors)
                for field, code in errors:
                    if len(samples) < max_samples:
                        samples.append({"line": records, "field": field, "code": code})
            if truncated:
                break
        finished = identity(os.fstat(stream.fileno()))
        try:
            after = identity(path.stat())
        except OSError:
            # A disappeared or inaccessible source cannot certify a stable input.
            after = None
    # On Windows/Python 3.12 path stat and descriptor stat expose different
    # ctime semantics. Compare ctime within each API, never across the APIs.
    input_changed = (
        after is None
        or not (before[:4] == opened[:4] == finished[:4] == after[:4])
        or before[4] != after[4]
        or opened[4] != finished[4]
    )
    if should_cancel is not None and should_cancel():
        raise ScanCancelled()
    digest = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    input_complete = reached_eof and not truncated and not input_changed
    passed = records > 0 and input_complete and invalid / records <= error_budget
    return Report(
        records,
        invalid,
        violations,
        samples,
        truncated,
        digest,
        passed,
        input_digest.hexdigest(),
        input_bytes,
        input_complete,
        input_changed,
        field_format,
    )


def compatibility(old: dict, new: dict) -> list[dict]:
    """Find changes that reject records accepted by the old contract."""
    validate_contract(old)
    validate_contract(new)
    findings = []

    def add(field, reason):
        findings.append({"field": field, "reason": reason, "severity": "breaking"})

    pointers = (
        diagnostic_format(old) == "json_pointer"
        or diagnostic_format(new) == "json_pointer"
    )

    def compare_objects(before, after, location):
        if before["allow_extra"] and not after["allow_extra"]:
            add(location, "extra_fields_now_rejected")
        for name, rule in after["fields"].items():
            field = _field_location(location, name, pointers)
            previous = before["fields"].get(name)
            if previous is None:
                if rule.get("required", False):
                    add(field, "new_required_field")
                # Previously unconstrained values may now be rejected, even for optional fields.
                if before["allow_extra"]:
                    add(field, "previously_unconstrained_field")
                continue
            if rule["type"] != previous["type"] and not (
                previous["type"] == "integer" and rule["type"] == "number"
            ):
                add(field, "type_narrowed_or_changed")
            if rule.get("required", False) and not previous.get("required", False):
                add(field, "now_required")
            if previous.get("nullable", False) and not rule.get("nullable", False):
                add(field, "null_no_longer_allowed")
            if rule["type"] == previous["type"] == "object":
                compare_objects(previous, rule, field)
            if rule.get("min", -math.inf) > previous.get("min", -math.inf):
                add(field, "minimum_tightened")
            if rule.get("max", math.inf) < previous.get("max", math.inf):
                add(field, "maximum_tightened")
        if not after["allow_extra"]:
            for name in before["fields"].keys() - after["fields"].keys():
                add(
                    _field_location(location, name, pointers),
                    "removed_field_now_rejected",
                )

    compare_objects(old, new, "" if pointers else "$")
    return sorted(findings, key=lambda x: (x["field"], x["reason"]))


def record_history(database: Path, report: Report) -> int:
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
          id INTEGER PRIMARY KEY, at TEXT NOT NULL, contract_sha256 TEXT NOT NULL,
          records INTEGER NOT NULL, invalid INTEGER NOT NULL, passed INTEGER NOT NULL)""")
        cursor = db.execute(
            "INSERT INTO runs(at,contract_sha256,records,invalid,passed) "
            "VALUES (?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                report.contract_sha256,
                report.records,
                report.invalid_records,
                int(report.passed),
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("History insert did not return an identifier")
        return cursor.lastrowid


def report_dict(report: Report) -> dict:
    return asdict(report)
