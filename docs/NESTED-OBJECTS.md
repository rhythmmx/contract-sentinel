# Nested object contracts

API/webhook records commonly place values inside objects such as `payload.user.id`. Contracts
can now validate those objects without flattening records or treating them as unchecked extras.
This remains a deliberately small dialect, not a JSON Schema implementation.

## Reproduce the synthetic examples

```sh
contract-sentinel check examples/nested.contract.json examples/nested-good.ndjson
contract-sentinel check examples/nested.contract.json examples/nested-bad.ndjson
contract-sentinel diff examples/nested.contract.json examples/nested-breaking.contract.json
```

The first exits 0. The bad dataset exits 1 with findings at `/payload`, `/payload/latency_ms`
and `/payload/user/id`. The last exits 1 because a nested numeric maximum is tightened and a
previously optional object becomes required. These are synthetic records, not production data.

## Object rules

An object rule contains `type: object`, a nonempty `fields` mapping, and explicit boolean
`allow_extra`. Optional `required` and `nullable` flags default to false, just as for scalars.
Numeric bounds are forbidden on objects; unknown constraints and array types are rejected.
Each nested object declares its own extra-field policy independently of its parent.

A missing optional object is accepted. If present, it must be an object unless null is explicitly
allowed. Missing required parents, wrong parent types and accepted null parents stop checks below
that parent, so diagnostics do not fabricate missing children. Present objects validate their
declared children recursively. Unknown extras are allowed only where explicitly configured.

The contract's `version` remains positive-integer metadata, not an automatic migration gate.
The example version-2 contract is a changed specification; nesting also works with version 1.
Version changes alone do not establish compatibility or prevent downgrades.

## Unambiguous diagnostics

Flat-only contracts keep their existing field names and `$` root marker. If a contract contains
an object rule, all field locations use JSON Pointer encoding and reports mark
`field_format: json_pointer`. `/payload/user/id` locates a nested field; names containing `~` or
`/` escape those characters as `~0` and `~1`. For example a field named `a/b~c` at the root is
`/a~1b~0c`, not a path to multiple children.

The root pointer is the empty string. The desktop table renders it as `(root)` while exported
JSON preserves the actual empty pointer. Extra-field findings point to the containing object,
never to the unknown input key or value. Configured field names remain visible and can be sensitive.

Compatibility findings use pointers if either contract contains an object rule, and the diff
command exposes `field_format` to disambiguate them. Otherwise flat diff locations stay unchanged.
This metadata is additive; report consumers should tolerate and read the new format field.

## Compatibility and bounds

Within corresponding objects, the analyzer checks required additions, type narrowing, numeric
bounds, revoked nullability, stricter extra-field policy and removed fields rejected by the new
policy. Integer-to-number widening and constraint loosening remain compatible. Differences are
reported at the relevant nested location, not as a blanket rewrite of the parent object.

At most eight object levels beneath the root are accepted; depth nine is rejected. The existing
1 MB contract/line read limits, record/sample caps, cancellation and input-provenance checks remain.
Deep malformed contract JSON is returned as a generic input error rather than exposing a traceback.
Only declared rules are checked: allowing extra fields leaves those extra values unconstrained.

No array schemas, references, unions, regexes, automatic inference or semantic validation are added.
Compatibility is a structural rule analysis, not a formal proof for every possible dataset. The
existing best-effort input-change and fingerprint privacy limitations still apply.
