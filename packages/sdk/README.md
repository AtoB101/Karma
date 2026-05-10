# @karma-network/sdk (scaffold)

TypeScript SDK for public KARMA HTTP APIs and wallet helpers.

**Status:** scaffold only — implement `registerAgent`, `enableSettlement`, `createBill`, `submitEvidence`,
`getSettlementStatus`, `openDispute`, `verifyEvidence`, `connectWallet`, and `getAgentReputation` against
`openapi/karma-public-console-api.yaml`.

Rules:

- Every mutating HTTP call must support **request signing** (HMAC or wallet-signed payload per deployment).
- Evidence bundles must include **integrity hashes** compatible with the public schema.
- **No private scoring** in this package.
