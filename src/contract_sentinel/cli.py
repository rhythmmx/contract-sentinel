import argparse
import json
from pathlib import Path
from .core import (
    compatibility,
    contract_from,
    diagnostic_format,
    record_history,
    report_dict,
    scan,
)


def main():
    parser = argparse.ArgumentParser(
        description="Bounded streaming data contract checks"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("contract", type=Path)
    check.add_argument("data", type=Path)
    check.add_argument("--history", type=Path)
    check.add_argument("--error-budget", type=float, default=0)
    check.add_argument("--max-records", type=int, default=100_000)
    diff = sub.add_parser("diff")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "diff":
            old, new = contract_from(args.old), contract_from(args.new)
            changes = compatibility(old, new)
            field_format = (
                "json_pointer"
                if "json_pointer" in (diagnostic_format(old), diagnostic_format(new))
                else "name"
            )
            print(
                json.dumps(
                    {"breaking_changes": changes, "field_format": field_format},
                    indent=2,
                )
            )
            return 1 if changes else 0
        report = scan(
            args.data,
            contract_from(args.contract),
            error_budget=args.error_budget,
            max_records=args.max_records,
        )
        if args.history:
            record_history(args.history, report)
        print(json.dumps(report_dict(report), indent=2))
        return 0 if report.passed else 1
    except (ValueError, OSError, RecursionError):
        # Never echo dataset content or local private paths into CI logs.
        print(
            json.dumps(
                {"error": "Invalid contract, limits, input, or inaccessible file"}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
