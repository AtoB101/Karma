# Evidence bundle standard (public)

## JSON Schema

Canonical public schema: `packages/evidence-schema/evidence.schema.json`

## Relationship to runtime code

Python reference implementation and hashing rules:

- `evidence_runtime/schemas.py`
- `evidence_runtime/evidence_adapter.py`
- `evidence_runtime/hashing.py`

## On-chain mapping

Evidence integrity is surfaced to Karma bills via existing `proofHash` string semantics — see `docs/SETTLEMENT_FLOW_PUBLIC.md`
and `KarmaBilateral` ABI in `evidence_runtime/abis/non_custodial_agent_payment_min.json`.

## Non-goals (public)

- No private scoring weights  
- No fraud rule tables  
- No internal dispute reason codes  
