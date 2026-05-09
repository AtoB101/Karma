# Karma Focus Roadmap

This roadmap re-centers the project around one core capability:

> **Off-chain AI agent intent (EIP-712 signed) -> on-chain verifiable settlement**

The goal is to make the system easy to explain, easy to integrate, and hard to misuse.

## 1) Product Narrative (Single Story)

Karma is a settlement rail for machine-to-machine service payments:

1. Agent (or its operator) signs a typed intent off-chain.
2. On-chain contract verifies signer, nonce, amount, and deadline.
3. Escrowed funds settle to the counterparty under deterministic rules.

Everything else is either:

- **Critical guardrail** (must-have for safe settlement), or
- **Deferred integration** (valuable, but not part of the MVP story).

## 2) Scope Decision Matrix

Use this matrix for all feature decisions:

- Does it directly increase settlement correctness/safety?
- Does it reduce integration friction for off-chain agents?
- Is it required to demonstrate real economic completion (token payout)?

If "no" for all three, defer it.

## 3) Versioned Scope

### V1 (Do one thing well)

Ship only the settlement core:

- EIP-712 typed data verification for settlement-authorized actions.
- Replay protection (nonce/digest consumption).
- Deadline/expiry enforcement.
- Amount and operation binding.
- Escrow accounting + payout path with real ERC20 transfer.
- Minimal emergency pause (global or core-path gate).

Acceptance criteria:

- A single end-to-end scenario proves:
  - signature validity,
  - replay rejection,
  - deadline rejection,
  - deterministic payout,
  - accounting conservation invariant.

### V1.5 (Integration polish, not new protocol breadth)

- Developer-facing payload/schema docs for signing flow.
- Backend/API reference flow for `sign -> submit -> settle`.
- Event schema docs for indexers/analytics.
- CI artifacts for scenario + invariants.

### V2 (Optional capability expansion)

- Rich identity/attestation extensions (KYA as a modular policy layer).
- Advanced pool controls and multi-pool optimization.
- Circuit breaker policy expansion beyond minimal pause.

## 4) Module Posture (Keep / Simplify / Defer)

### Keep as first-class in V1

- `BillManager` settlement lifecycle core.
- `AuthTokenManager` + `EIP712Auth` verification path.
- `LockPoolManager` only for escrow deposit/withdraw/settle accounting.
- Minimal `CircuitBreaker` pause for incident response.

### Simplify in V1

- `KYARegistry`: keep interface and basic checks, avoid expanding policy logic.
- Batch complexity: preserve only what is needed for deterministic settlement demos.

### Defer from primary narrative

- Non-core governance/policy sophistication.
- Broad feature combinations that do not improve core settlement reliability.

## 5) Testing Strategy Aligned to Narrative

Prioritize tests by user trust impact:

1. Signature correctness and replay safety.
2. Settlement accounting invariants.
3. Unauthorized actor rejection on sensitive paths.
4. End-to-end scenario with real ERC20 value transfer.

Only after these are stable should additional module tests expand.

## 6) Demo Script (30-second value proposition)

"An agent signs an EIP-712 intent off-chain. The chain verifies exactly who authorized what, by when, and for how much. If valid, settlement executes from escrow to recipient with on-chain finality."

If the demo cannot be summarized this way, scope is too broad.
