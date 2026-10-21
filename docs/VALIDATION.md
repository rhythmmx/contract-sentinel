# Validation — 2026-10-16

Verified locally on Python 3.12 / Windows:

- Package built and installed into the clean verification environment.
- 16 tests passed: actual CLI exit codes, malformed/duplicate/non-finite JSON, bool vs integer,
  very large integers, exact/truncated record limits, oversized lines, bounded diagnostics,
  aggregate history privacy and compatibility narrowing/widening.
- Ruff lint and format checks passed; mypy passed on all four source files.
- Good example dataset executed successfully and produced a genuine JSON report.
- Tk window construction, event-loop update and close passed.
- GUI background-worker validation and result-table population passed in a local smoke test.

Testing caught a SQLite connection lifecycle bug on Windows; connections now explicitly close.
GUI visual layout, file dialogs and manual usability have not received visual QA.
No performance benchmark, measured coverage, production deployment or third-party adoption claimed.
Hosted CI results are recorded separately after actual execution.

## 2026-10-17 input-provenance milestone

36 local tests passed, including exact-byte hashes, bounded incomplete prefixes, deterministic
mutation during scanning, empty input, cancellation and contract-size bounds. Ruff lint/format and
mypy passed. The GUI explains source-change failures even when all parsed records are valid.
Metadata checks remain best effort; immutable-snapshot guarantees are not claimed.

## 2026-10-21 nested-object milestone

51 tests passed locally, including the existing 36, 14 nested-object regressions and one desktop
root-label regression. Ruff lint/format and mypy passed. Independent review found no blocker.
A fresh package installation verified flat and nested checks, recursive compatibility output,
exit codes 0/1/2 and rejection beyond the depth limit. An installed real Tk smoke verified readable
root diagnostics while retaining the actual empty pointer in export data. Full visual QA remains
unverified. Hosted Linux/Windows CI is inspected before merge; no arrays/full JSON Schema claimed.
