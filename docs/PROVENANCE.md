# Input provenance and stability checks

A validation result needs to identify its input, especially when a producer can append to or
replace a file during validation. Reports now include `input_sha256`, `input_bytes`,
`input_complete`, and `input_changed`, alongside the existing contract fingerprint.

Acceptance checks: hash original bytes with no newline/Unicode normalization; make no additional
unbounded pass through the dataset; distinguish bounded prefixes from a complete unchanged scan;
fail validation on detected mutation even if every parsed record is valid; preserve cancellation
and exclude raw input values and local paths from output.

## Interpret the fields together

`input_sha256` is SHA-256 of bytes returned to the scanner by bounded reads. `input_bytes` counts
those bytes, including the bounded lookahead needed to detect an exceeded record limit. That
lookahead can contain bytes not validated as a record. Oversized lines contribute only the bounded
prefix read. A fingerprint alone must never be interpreted as proof of a complete dataset check.

`input_complete=true` means EOF was reached without truncation or a detected input change. Invalid
records may still be present, so check `passed` separately. A stable empty file has the SHA-256
of empty bytes and is complete, but still fails the existing nonempty-dataset quality gate.

`input_changed=true` means the file's device/inode, size or modification/change metadata differed
between the original path, opened descriptor, final descriptor and final path checks, or the final
path became inaccessible. This forces `passed=false` and `input_complete=false`. The desktop status
explains this failure even when `invalid_records=0`.

These are best-effort change checks, not locking or an immutable snapshot. Metadata precision and
filesystem semantics vary. Changes that evade metadata checks, or happen after the final checks,
cannot be ruled out. Use immutable input snapshots for strong consistency. A file replaced under
the same path can differ from the descriptor that was actually scanned; checking both detects
common cases without reopening and hashing the new file.

Reports never include the raw file path or bytes. Hashes can correlate identical datasets and
may reveal membership of predictable, low-entropy inputs; they are not anonymization or encryption.
SQLite history continues to store its original aggregate-only schema; dataset fingerprints are
available in returned/exported reports, not added to historical database rows by this change.

Contract files are separately read through a bounded binary read: at most 1,000,001 bytes to
enforce the existing 1 MB limit without a pre-stat/unbounded-read race.
