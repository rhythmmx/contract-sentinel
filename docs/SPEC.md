# Acceptance specification

Problem: a producer may silently change event types or ranges and break downstream consumers.
Users: data engineers who version contracts with pipeline code and need local diagnostics.

Acceptance: stream flat NDJSON within explicit bounds; fail incomplete scans; distinguish bool from
integer; detect backward incompatible contract narrowing; avoid raw data in reports; persist
aggregate history; provide reproducible CLI exit codes and a desktop inspection workflow.

Scope deliberately excludes JSON Schema compatibility and model-based schema inference.
Tests use adversarial malformed input, boundary limits and actual CLI subprocess calls.
