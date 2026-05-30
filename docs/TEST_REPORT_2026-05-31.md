# Test Report — 2026-05-31

**Repository:** Karma (karma-core)  
**Test framework:** Foundry (forge)  
**Solidity version:** 0.8.28 (via IR, optimizer runs: 1000)  
**Date:** 2026-05-31

---

## 1. Aggregate Test Summary

| Test Suite | File | Test Functions | Status |
|------------|------|---------------|--------|
| NonCustodialAgentPayment | `NonCustodialAgentPayment.t.sol` | 53 | Results pending |
| NCPA Reentrancy | `NonCustodialAgentPaymentReentrancy.t.sol` | 1 | Results pending |
| NCPA Invariant | `NonCustodialAgentPayment.invariant.t.sol` | invariant-based | Results pending |
| KarmaBilateral | `KarmaBilateral.t.sol` | 44 | Results pending |
| KarmaBilateral Attestation | `KarmaBilateralAttestation.t.sol` | 20 | Results pending |
| KarmaBilateral Advanced | `KarmaBilateralAdvanced.t.sol` | 19 | **[ADVANCED_TESTS_RESULTS]** |
| AuthTokenManager | `AuthTokenManager.t.sol` | 9 | Results pending |
| CircuitBreaker | `CircuitBreaker.t.sol` | 5 | Results pending |
| KYARegistry | `KYARegistry.t.sol` | 6 | Results pending |
| KarmaIdentitySBT | `KarmaIdentitySBT.t.sol` | 3 | Results pending |
| SettlementEngine | `SettlementEngine.t.sol` | 12 | Results pending |
| **Total** | **11 files** | **172** | — |

### Grouped by Module

| Module | Test Files | Test Count |
|--------|-----------|------------|
| **NCPA (legacy)** | 3 (NCPA + Reentrancy + Invariant) | 53 + 1 + invariant |
| **KarmaBilateral (core)** | 1 | 44 |
| **Attestation** | 1 | 20 |
| **Advanced (attack/edge)** | 1 | 19 |
| **Supporting contracts** | 5 | 35 |
| **Total** | **11** | **172** |

---

## 2. Coverage Breakdown by Contract

### 2.1 KarmaBilateral.sol

| Function Group | Functions | Tested In |
|----------------|-----------|-----------|
| `lock()` | 1 | `KarmaBilateral.t.sol` (44 tests), `KarmaBilateralAdvanced.t.sol` |
| `bind()` / `bindWithAttestation()` | 2 | `KarmaBilateral.t.sol`, `KarmaBilateralAttestation.t.sol` |
| `settle()` | 1 | Both test files |
| `finalizeSettle()` | 1 | Both test files |
| `dispute()` | 1 | `KarmaBilateral.t.sol`, `KarmaBilateralAdvanced.t.sol` |
| `submitArbitrationEvidence()` | 1 | Both test files |
| `autoResolveArbitration()` | 1 | `KarmaBilateral.t.sol`, `KarmaBilateralAdvanced.t.sol` |
| `resolveDispute()` (admin) | 1 | `KarmaBilateralAdvanced.t.sol` |
| `refundOnTimeout()` | 1 | `KarmaBilateral.t.sol`, `KarmaBilateralAdvanced.t.sol` |
| `unlock()` | 1 | Both test files |
| SCP (`authorize`/`accept`/`cancel`) | 3 | `KarmaBilateral.t.sol` |
| KarmaIdentity | 4 | `KarmaBilateral.t.sol` |
| Admin setters | 10 | `KarmaBilateral.t.sol` |
| Views | 15+ | All test files |
| Layer 2/3 (TEE/ZK stubs) | 2 | Not yet implemented |
| **Total** | **~45** | — |

### 2.2 NonCustodialAgentPayment.sol

| Function Group | Tests |
|----------------|-------|
| `lockFunds()` / `unlockFunds()` | ~8 |
| `createBill()` | ~12 |
| `confirmBill()` / `confirmBillBySignature()` | ~6 |
| `cancelBill()` / `expireBill()` | ~5 |
| `requestBillPayout()` | ~5 |
| `disputeBill()` | ~3 |
| Arbitration (`resolveDispute*`) | ~6 |
| Batch lifecycle | ~4 |
| Policy / access control | ~4 |
| **Total** | **~53** |

### 2.3 Attestation (KarmaBilateralAttestation.t.sol)

| Area | Tests |
|------|-------|
| Verifier registration / removal | ~5 |
| Evidence publication | ~4 |
| Attestation submission (N of M) | ~6 |
| Challenge flow | ~3 |
| Gateway integration | ~2 |
| **Total** | **20** |

### 2.4 Supporting Contracts

| Contract | Tests | Covers |
|----------|-------|--------|
| `AuthTokenManager` | 9 | KYA auth token lifecycle |
| `CircuitBreaker` | 5 | Pause/unpause + safety mode triggers |
| `KYARegistry` | 6 | Identity registration, attestation, revocation |
| `KarmaIdentitySBT` | 3 | SBT mint, burn, transfer block |
| `SettlementEngine` | 12 | Multi-sig escrow, settlement lifecycle |

---

## 3. Gas Cost Summary

> **Note:** Gas values are estimates based on contract logic analysis + ERC-20 standard costs.
> All values assume `via_ir = true`, `optimizer_runs = 1000`, Base Sepolia (L2).
> Actual values will vary ±15%. Run `forge test --gas-report` for precise measurements.

### 3.1 KarmaBilateral — Key Operations

| Operation | Estimated Gas | Notes |
|-----------|---------------|-------|
| `lock(token, amount)` | **~155,000** | ERC-20 `transferFrom` (~45K) + 5 SSTOREs + invariant checks |
| `bind(buyerBill, agentBill, scopeHash)` | **~130,000** | ~6 SSTOREs + pending amount update + `_moveFreeToBound` |
| `bindWithAttestation(buyer, agent, scope, taskId)` | **~150,000** | Same as `bind()` + attestation storage |
| `settle(bindingId, proofHash)` — optimistic | **~55,000** | State transition ACTIVE→FINALIZING + proofHash store |
| `settle(bindingId, proofHash)` — attested (gateway) | **~220,000** | Full settlement including ERC-20 transfers × 2 |
| `finalizeSettle(bindingId)` | **~195,000** | ERC-20 `transfer` × 2 (~90K) + bill burns + invariant checks |
| `dispute(bindingId, evidenceHash)` | **~90,000** | State transition + `ArbitrationRecord` init (5 SSTOREs) |
| `submitArbitrationEvidence(bindingId, hash)` | **~30,000** | Single SSTORE update |
| `autoResolveArbitration(bindingId)` | **~195,000** | Same as `finalizeSettle`/`_executeRefund`/`_executeSplit` |
| `resolveDispute(bindingId, buyerShareBps)` | **~195,000** | Admin dispute resolution with split payout |
| `refundOnTimeout(bindingId)` | **~195,000** | Full refund execution (×2 transfers) |
| `unlock(billId)` | **~95,000** | ERC-20 `transfer` + bill burn + invariant checks |
| `registerIdentity(masterAgentId)` | **~50,000** | Identity struct write |
| `addSubAgent(subWallet, subAgentId)` | **~75,000** | Sub-agent registration |
| `authorize(token, amount, to, expiresAt)` | **~70,000** | Authorization struct creation |
| `accept(authId)` | **~65,000** | Authorization accept + balance updates |
| `cancelAuthorization(authId)` | **~35,000** | Authorization cancel + free balance restore |

### 3.2 NonCustodialAgentPayment — Key Operations (for comparison)

| Operation | Estimated Gas | Notes |
|-----------|---------------|-------|
| `lockFunds(token, amount)` | **~45,000** | Logical accounting only (no transfer) |
| `createBill(seller, token, amount, ...)` | **~175,000** | Policy checks + reservation + batch assignment |
| `confirmBill(billId)` | **~25,000** | Status transition only |
| `requestBillPayout(billId)` | **~135,000** | ERC-20 `transferFrom` buyer→seller (~45K) + account updates |
| `disputeBill(billId)` | **~30,000** | Status transition only |
| `resolveDisputeBuyer(billId)` | **~130,000** | Seller→buyer penalty transfer + account updates |
| `resolveDisputeSeller(billId)` | **~135,000** | Buyer→seller transfer + seller bond return |
| `settleBatch(batchId, maxBills)` | **~135K × settledCount** | Per-bill payout loop |

### 3.3 Gas Comparison: NCPA vs KarmaBilateral

| Operation | NCPA | KarmaBilateral | Delta |
|-----------|------|----------------|-------|
| Initial lock | ~45K | ~155K | +110K (custody vs logical) |
| Task creation / bind | ~175K (createBill) | ~130K (bind) | −45K |
| Settlement (single bill/pair) | ~135K | ~55K + ~195K = ~250K | +115K (two-step) |
| Dispute | ~30K | ~90K | +60K |
| Total happy path (lock→bind→settle) | ~355K | ~380K | +25K (~7%) |
| Total dispute path | ~385K | ~515K | +130K (~34%) |

**Key takeaway:** KarmaBilateral's gas cost is comparable to NCPA for the happy path
(+7%) and moderately higher for dispute paths (+34%), largely because KarmaBilateral
performs actual token custody (ERC-20 transfers) rather than logical accounting.
The added security of on-chain escrow and bilateral binding justifies the marginal
gas increase.

---

## 4. Advanced Tests (KarmaBilateralAdvanced.t.sol)

**Status:** [ADVANCED_TESTS_RESULTS]

The advanced test suite covers:

| Category | Tests | Description |
|----------|-------|-------------|
| Mixed settlement | 2 | NCPA-style + Bilateral parallel operation; cross-contamination check |
| Reentrancy attacks | 2 | Malicious token `transfer()` reentering `settle()` and `dispute()` |
| Front-running | 1 | Attacker tries `dispute()` before `settle()` lands |
| Double-bind | 1 | Same bill in two bindings — must revert |
| State machine violations | 2 | `settle()` after dispute, `dispute()` after settlement |
| Edge cases | 7 | Zero amount, self-bind, different tokens, BOUND unlock, max lock, zero threshold, rapid cycles |
| Dispute window boundary | 2 | Dispute at t = windowEnd − 1 (pass), t = windowEnd (revert) |
| Full lifecycle exhaustion | 1 | All 9 valid state paths exercised in single test |
| Invalid transition matrix | 1 | All invalid state transitions verified to revert |
| **Total** | **19** | — |

---

## 5. Known Gaps

1. **Layer 2 (TEE)** — Interface stubs present; no implementation or tests
2. **Layer 3 (ZK)** — Interface stubs present; no implementation or tests
3. **Gas benchmarks** — No `.gas-snapshot` file exists; values above are estimates
4. **Coverage report** — Not yet generated (`forge coverage` not run)
5. **Fuzz/invariant campaigns** — Only NCPA has invariant tests; KarmaBilateral invariant fuzzing pending
6. **Cross-chain** — No tests for cross-chain settlement or bridge interactions

---

## See Also

- [KarmaBilateral contract](../karma-core/contracts/core/KarmaBilateral.sol)
- [NCPA contract](../karma-core/contracts/core/NonCustodialAgentPayment.sol)
- [KarmaBilateral test suite](../karma-core/contracts/test/KarmaBilateral.t.sol)
- [Advanced test suite](../karma-core/contracts/test/KarmaBilateralAdvanced.t.sol)
- [Migration NCPA → Bilateral](./MIGRATION_NCPA_TO_BILATERAL.md)
- [foundry.toml](../karma-core/foundry.toml)
