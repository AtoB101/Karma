# Evidence bundle standard (public)

## JSON Schema

Canonical public schema: `packages/evidence-schema/evidence.schema.json`

## Relationship to runtime code

Python reference implementation and hashing rules:

- `trusted_agent_runtime/schemas.py`
- `trusted_agent_runtime/evidence_adapter.py`
- `trusted_agent_runtime/hashing.py`

## On-chain mapping

Evidence integrity is surfaced to Karma bills via existing `proofHash` string semantics — see `docs/PUBLIC_ALIGNMENT_REPORT.md`
and `NonCustodialAgentPayment` ABI in `trusted_agent_runtime/abis/non_custodial_agent_payment_min.json`.

## Non-goals (public)

- No private scoring weights  
- No fraud rule tables  
- No internal dispute reason codes  
