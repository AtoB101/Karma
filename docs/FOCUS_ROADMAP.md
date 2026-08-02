# Karma Focus Roadmap

This roadmap re-centers the project around one core capability:

> **Off-chain AI agent intent (EIP-712 signed) → on-chain verifiable settlement (KarmaBilateral)**

The goal is to make the system easy to explain, easy to integrate, and hard to misuse.

## 1) Product Narrative (Single Story)

Karma is a settlement rail for machine-to-machine service payments:

1. Buyer and agent each `lock` USDC and mint Bill Tokens.
2. `bind` pairs bills under a scope hash (optional IntentPackage).
3. Delivery evidence yields a `proofHash`; `settle` opens the dispute window.
4. After the window, `finalizeSettle` burns bills and releases USDC.

Everything else is either:

- **Critical guardrail** (must-have for safe settlement), or
- **Deferred integration** (valuable, but not part of the MVP story).

Canonical builder path: [`PILOT_E2E_PATH.md`](./PILOT_E2E_PATH.md).

## 2) Scope Decision Matrix

Use this matrix for all feature decisions:

- Does it directly increase settlement correctness/safety?
- Does it reduce integration friction for off-chain agents?
- Is it required to demonstrate real economic completion (token payout)?

If "no" for all three, defer it.

## 3) Versioned Scope

### V1 (Do one thing well)

Ship the Bilateral settlement core:

- EIP-712 typed data verification for settlement-authorized actions (HTTP trade path).
- On-chain `lock → bind → settle → finalizeSettle` with dispute window.
- Replay protection (nonce/digest consumption) on signed HTTP surfaces.
- Escrow accounting invariant: bill supply == locked.
- Minimal emergency pause (`CircuitBreaker`).

Acceptance criteria:

- A single end-to-end scenario proves signature validity (HTTP), on-chain finalize,
  dispute/refund branches, and accounting conservation.

### V1.5 (Integration polish, not new protocol breadth)

- Developer-facing payload/schema docs for signing + Bilateral flows.
- Console live HTTP writes + public API OpenAPI.
- Ecosystem adapters already in-tree: Open Wallet, x402, AP2 evidence interop
  (see [`INTEGRATIONS.md`](./INTEGRATIONS.md)).

### V2 (Optional capability expansion)

- Rich identity/attestation extensions (KYA as a modular policy layer).
- TEE / ZK settle paths (`settleWithTEE` / `settleWithZKProof`).
- Solana / multi-chain anchoring (`packages/karma_solana` — out of pilot).
- P7 ticket issuer APIs beyond digital/hash POD scenes.

## 4) Module Posture (Keep / Simplify / Defer)

### Keep as first-class in V1

- `KarmaBilateral` settlement lifecycle core.
- `AuthTokenManager` + EIP-712 verification path.
- Supporting registries: `KYARegistry`, `EvidenceChain`, `ScoringEngine`, `VerifierRegistry`.
- Minimal `CircuitBreaker` pause for incident response.

### Simplify in V1

- `KYARegistry`: keep interface and basic checks, avoid expanding policy logic.
- Batch complexity: preserve only what is needed for deterministic settlement demos.

### Defer from primary narrative

- Non-core governance/policy sophistication.
- Broad feature combinations that do not improve core settlement reliability.
- Solana billing bridge and hollow multi-chain packages.

## 5) Testing Strategy Aligned to Narrative

Prioritize tests by user trust impact:

1. Signature correctness and replay safety.
2. Settlement accounting invariants (forge + invariant checks).
3. Unauthorized actor rejection on sensitive paths.
4. End-to-end scenario with real ERC20 value transfer on Sepolia.
5. Console HTTP live-write smoke (`tests/unit/test_console_live_write_smoke.py`).

Only after these are stable should additional module tests expand.

## 6) Demo Script (30-second value proposition)

"Both sides lock USDC as Bill Tokens. Bind freezes the pair. Settle opens a short
dispute window; finalize burns the bills and releases funds. Math settles, not humans."

If the demo cannot be summarized this way, scope is too broad.
