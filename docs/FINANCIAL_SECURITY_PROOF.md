# Karma 资金安全证明报告（A–H）

Date: 2026-08-28  
Contracts: `KarmaBilateral.sol` + `CircuitBreaker.sol`  
Tests: `FinancialInvariants.t.sol`, `FinancialFreeze.t.sol`, `OffchainCompromise.t.sol`

## A. Financial Function Map

See `security/registry/financial_functions.yaml`. CI: `security/registry/check_registry.py` via `scripts/security-baseline-guard.sh`.

## B. Financial State Machine

See `docs/FINANCIAL_STATE_MACHINE.md`.

## C. Financial Trust Boundary

| Party | Can | Cannot |
|-------|-----|--------|
| User | lock/bind/dispute/timeout refund/unlock own MINTED | move others' escrow |
| Verification Engine | produce a result; backend may *submit* settle | authorize payout alone (INV-2, TEE/ZK revert) |
| Backend / DB / Redis | submit txs if it holds a hot key | drain escrow unless it is the bill owner (INV-10) |
| Security Control Plane | alert + request freeze | transfer funds |
| Smart Contract | final payout decision + freeze overlay | — |
| Admin / freezeOperator | freeze, params, large dispute resolve | no `withdrawAll`; freeze auto-expires ≤ 7d |

## D. Attack Surface

Listed in `security/registry/README.md` + red-team `security/redteam/2026-08-27-redteam-assessment.md`.

## E. Security Invariants

INV-1 … INV-10 in YAML; forge tests named `test_INV*`.

## F. Circuit Breaker

- Off-chain: `services/security_control_plane.py` on CRITICAL → freeze record; admin `POST /v1/admin/controls/emergency-freeze`; settlement-denied CRITICAL auto-brake also requests freeze.
- On-chain: `freezeGlobal/Agent/Bill/Binding` + `CircuitBreaker.emergencyPause` hooked in Bilateral payout/bind guards.

## G. Attack test results (forge)

| Scene | Test | Result |
|-------|------|--------|
| Unauthorized payout | `test_INV5`, `test_matrix_unauthorizedPayout` | PASS (expect revert) |
| Double payout | `test_INV4_doubleFinalizeReverts` | PASS |
| Amount manipulation | `test_INV7`, `test_matrix_amountManipulationImpossible` | PASS |
| Recipient manipulation | `test_INV6` | PASS |
| State skip | `test_INV3`, `test_matrix_stateSkipImpossible` | PASS |
| Replay | `test_INV8` | PASS |
| Forged verification / TEE | `test_INV2`, `test_matrix_forgedVerificationDoesNotPay` | PASS |
| Dispute vs settle | `test_INV9` | PASS |
| Backend+verifier+DB keys | `test_INV10`, `OffchainCompromise` | PASS |
| Freeze blocks payout, allows timeout refund | `FinancialFreeze` | PASS |

Dynamic HTTP `scripts/attack_simulation.py` remains a **backend** suite, not a replacement for this chain proof.

## H. Remaining risks

- JWT `APP_SECRET_KEY` / arbitrator session / admin multisig (red-team A1–A3) — keys, not escrow bugs.
- Control Plane freeze **on-chain submit** needs `freezeOperator` key + RPC; default API path records freeze off-chain unless `submit_on_chain=true`.
- TEE/ZK still stubs (must stay revert until formally verified).
- Dashboard locked/pending counts are not yet a live indexer of `totalLocked` (shows Control Plane freeze + alerts).
- Audit ring buffer still in-process memory (restart loses events) unless a store is added later.
