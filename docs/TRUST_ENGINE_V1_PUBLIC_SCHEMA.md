# Trust Engine V1 Public Schema (Public-Safe)

This document defines only public contract-level fields and status markers.

It intentionally does **not** include private scoring weights, anti-fraud
thresholds, evidence weighting internals, or arbitration tie-break constants.

## Evidence fields (required)

- `caller_authorization_signature`: signature proving caller authorization exists
- `provider_execution_signature`: signature proving provider execution exists
- `request_hash`: hash pointer to the request payload
- `response_hash`: hash pointer to the response payload
- `dispute_status`: dispute state marker (`none|opened|under_review|resolved`)
- `settlement_status`: settlement state marker (`pending|settled|cancelled|disputed`)

## Evidence fields (optional)

- `execution_trace_hash`: execution trace hash pointer (presence-only in public schema)

## Public boundary

- Public repo defines field presence, API contract, and interoperability shape.
- Private repo owns internal scoring formulas, anti-cheat thresholds, and dispute policy tuning.
