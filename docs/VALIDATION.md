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

## 2026-10-23 strict scan-limit milestone

58 tests passed locally, including seven new limit regression tests. Unsafe count/budget types,
nonfinite values and platform-overflowing line sizes fail with ValueError before input stat/open.
Valid exact record/line bounds, zero sample retention and fractional error budgets retain their
behavior. Invalid CLI limits return sanitized JSON with exit 2 and create no history database.
Ruff lint/format and mypy pass. A fresh wheel installation and pip check passed; installed API
rejection and CLI exit codes 0/1/2 were executed. Hosted Linux/Windows CI is checked before merge.
This fixes configured-bound validation, not a global resource quota; callers can choose large caps.

## 2026-10-24 integer-domain compatibility milestone

65 local tests passed, including seven new tests for equivalent positive/negative fractional
bounds, actual rejected integer witnesses, integer-to-number widening, absent bounds, arbitrary-size
integers, escaped nested pointers and unchanged fractional number behavior. A deterministic bounded
acceptance-set comparison covers nonempty old integer intervals against integer/number destinations.
Ruff lint/format and mypy pass. Conservative findings for empty old integer ranges and unreachable
structures remain possible; whole-contract satisfiability is not analyzed.

## Expected dataset digest gate - 2026-10-26

73 local tests passed, including eight new tests for trusted matches, uppercase normalization,
optional-default compatibility, mismatch despite error budget 1, matching bounded prefixes rejected,
source-change rejection, empty-data quality failure, strict pre-I/O validation, CLI privacy/exit codes
and unchanged aggregate history. Ruff lint/format and mypy passed. A fresh wheel installation,
pip check and installed CLI match/uppercase (0), mismatch (1), invalid expectation (2), and omitted
expectation (null) checks passed. Hosted Linux/Windows CI is inspected before merge. This is an
observed-byte acceptance gate; immutable snapshots, locking or producer authentication are not claimed.
