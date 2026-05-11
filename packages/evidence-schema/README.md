# Evidence bundle schema (public)

`evidence.schema.json` is a **public, structural** JSON Schema. It intentionally **does not** encode private scoring,
fraud rules, or dispute weighting — those belong in the private risk engine repository.

Align runtime tooling with:

- `trusted_agent_runtime/` (hashing + structural verification)
- On-chain `proofHash` / bill semantics in `karma-core/contracts/core/NonCustodialAgentPayment.sol`
