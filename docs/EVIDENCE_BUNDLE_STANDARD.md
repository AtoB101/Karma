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

Note: the bilateral core `core/KarmaBilateral.sol` commits a `bytes32 proofHash`
whose canonical value is `SHA256(canonical_json_bytes(bundle))` — see
`decentralized_verifier/rules/hashing.py::proof_hash_bytes32` and
`docs/TEE_ATTESTATION_SPEC.md` ("Proof object identity"). The `karma-ta:v1/...`
string pointer above is the legacy hybrid-contract form; the bytes32 form is the
current canonical on-chain commitment.

## Non-goals (public)

- No private scoring weights  
- No fraud rule tables  
- No internal dispute reason codes  
