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
  "passed": true
}
```

Use `examples/bad.ndjson` to see required-field, range and type violations (exit 1).
Use `contract-sentinel-gui` to inspect these same fixtures locally.

Hosted verification of the implemented source passed on Linux and Windows:
https://github.com/rhythmmx/contract-sentinel/actions/runs/38943402590
GUI smoke tests were local; no screenshot or manual visual QA is claimed.
