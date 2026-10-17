# Reproduce the demo

Run from the repository after installation:

```sh
contract-sentinel check examples/events.contract.json examples/good.ndjson
```

Actual verified output from the committed synthetic fixture:

```json
{
  "records": 2,
  "invalid_records": 0,
  "violations": 0,
  "samples": [],
  "truncated": false,
  "contract_sha256": "016739013ddb167c1a524fcb2afabd05a7b6ba256cc6575405a3e635265b9086",
  "passed": true,
  "input_sha256": "f61846e902b4fc14dea6856546aa85249998450bbc4f7d9e7dd08850822c23b8",
  "input_bytes": 114,
  "input_complete": true,
  "input_changed": false
}
```

Use `examples/bad.ndjson` to see required-field, range and type violations (exit 1).
Use `contract-sentinel-gui` to inspect these same fixtures locally.
Byte counts and input fingerprints can differ with Git checkout newline settings (LF vs CRLF).
The fingerprint describes the bytes actually read; JSON content is not normalized.

Hosted verification of the implemented source passed on Linux and Windows:
https://github.com/rhythmmx/contract-sentinel/actions/runs/38943402590
GUI smoke tests were local; no screenshot or manual visual QA is claimed.
