# TrustChain Settlement Core (MVP Focus)

TrustChain focuses on one core capability:

> **Off-chain AI agent intent (EIP-712 signed) -> on-chain verifiable settlement**

This repo is intentionally centered on proving that core flow end-to-end:

1. Off-chain actor signs typed intent.
2. Contract verifies signer, amount, nonce/replay, and deadline.
3. Escrowed funds settle to recipient with deterministic accounting.

For roadmap and scope discipline, see: `docs/FOCUS_ROADMAP.md`

## Security Verification Matrix (Latest Audit Baseline)

TrustChain maintains a layered evidence chain from unit testing to formal proofs:

| Layer | Tool | Type | Result |
| --- | --- | --- | --- |
| 1 | `forge test` | Unit tests | 55/55 passed |
| 2 | `forge invariant` | Invariant fuzzing | 256 runs, 0 revert |
| 3 | Slither | Static analysis | 22 warnings, no fund-loss class issue |
| 4 | Echidna | Adversarial fuzzing | 100,000 runs, 0 violation |
| 5 | Certora | Formal verification | 6/6 rules verified |

Formal verification scope and rule-level details are tracked in `SECURITY.md`.
Investor/partner ready one-page bilingual summary: `docs/SECURITY_SUMMARY_CN_EN.md`.

## Current Module Posture

Primary (V1 first-class):

- auth verification (`AuthTokenManager`, `EIP712Auth`)
- settlement lifecycle (`BillManager`)
- escrow accounting + payout (`LockPoolManager`)
- minimal emergency stop (`CircuitBreaker`)

Secondary/deferred in narrative:

- richer identity/policy expansion (`KYARegistry` beyond minimal checks)
- broader feature combinations not required for signature-to-settlement proof

## Prerequisites

Install Foundry (macOS/Linux):

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

Verify installation:

```bash
forge --version
```

Install `forge-std` test library:

```bash
forge install foundry-rs/forge-std
```

## Build

From project root:

```bash
forge build
```

## Test

Run core narrative demo first (recommended):

```bash
forge test --match-path "contracts/test/ScenarioFlow.t.sol" -vv
```

Single-command demo wrapper:

```bash
./scripts/run_focus_demo.sh
```

Run all tests:

```bash
forge test -vv
```

Run a single test file:

```bash
forge test --match-path "contracts/test/KYARegistry.t.sol" -vv
```

Run invariant/fuzz tests:

```bash
forge test --match-path "contracts/test/LockPoolManager.invariant.t.sol" -vv
forge test --match-path "contracts/test/CrossModuleAccounting.invariant.t.sol" -vv
forge test --match-path "contracts/test/BillStateMachine.invariant.t.sol" -vv
```

## Notes

- Demo-first message: prove signed-intent settlement correctness before adding breadth.
- Keep decisions tied to settlement reliability and integration simplicity.
- `BatchSettlement` is a deprecated compatibility wrapper; use `BillManager` directly.
- Signing payload details for backend integration: `docs/SIGNING_PAYLOAD_SPEC.md`
