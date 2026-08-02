# Trust Engine V1 Public Schema (Public-Safe)

Public contract-level fields and status markers only.

Does **not** include private scoring weights, anti-fraud thresholds, evidence
weighting internals, or arbitration tie-break constants.

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

- Public repo: field presence, API contract, interoperability shape, Bilateral settle mapping.
- Private systems (if any): scoring formulas, anti-cheat thresholds, dispute policy tuning.

See also: `docs/EVIDENCE_BUNDLE_STANDARD.md`, `docs/SETTLEMENT_FLOW_PUBLIC.md`.
