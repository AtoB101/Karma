# Migration: NonCustodialAgentPayment → KarmaBilateral

**Status:** Draft  
**Target network:** Base Sepolia  
**Last updated:** 2026-05-31

## Overview

`NonCustodialAgentPayment` (NCPA) and `KarmaBilateral` serve the same purpose — facilitating
agent-to-agent task payments — but differ fundamentally in architecture. NCPA uses logical
accounting (no token custody); KarmaBilateral escrows tokens and enforces bilateral binding
before any settlement can occur.

This document maps the migration path for integrators moving from the NCPA contract to
KarmaBilateral.

---

## 1. State Mapping

### 1.1 NCPA Bill → KarmaBilateral Bill Token

| NCPA `BillStatus`       | KarmaBilateral `BillState` | Notes |
|--------------------------|----------------------------|-------|
| `Pending`               | `MINTED`                    | Newly created, available to bind |
| `Confirmed`             | `BOUND`                     | Committed to an active binding |
| `Settled`               | `BURNED`                    | Terminal — tokens released |
| `Cancelled` / `Expired` | `BURNED` (via `unlock`)     | Pre-bind cancellation only |
| `Disputed`              | `DISPUTED` (binding-level)  | KarmaBilateral moves dispute to binding |

### 1.2 NCPA Batch → KarmaBilateral Batch Threshold

NCPA batches are explicit, user-owned aggregation buckets. KarmaBilateral does not have
explicit batch objects. Instead, an optional `batchThreshold` triggers `PENDING` state on
bindings when the cumulative pending amount for a token exceeds the threshold.

| NCPA Concept                  | KarmaBilateral Equivalent                                   |
|-------------------------------|-------------------------------------------------------------|
| `createBatch` / `closeBatch`  | None — threshold is global per token                        |
| `settleBatch()`               | Individual `settle(bindingId)` after bind                   |
| `batchCircuitBreakerPaused`   | Not yet implemented                                         |

---

## 2. Contract Addresses

| Contract                      | Network      | Address | Status    |
|-------------------------------|--------------|---------|-----------|
| `NonCustodialAgentPayment`    | Sepolia      | (existing deployment) | Deprecating |
| `KarmaBilateral`              | Base Sepolia | (see `DeployKarmaBilateral.s.sol`) | Active |
| `KarmaAttestationGateway`     | Base Sepolia | (deployed after Bilateral) | Active |
| `VerifierRegistry`            | Base Sepolia | (deployed first) | Active |

**Base Sepolia USDC:** `0x036CbD53842c5426634e7929541eC2318f3dCF7e`

> **Note:** NCPA was deployed to Sepolia (Ethereum L1 testnet). KarmaBilateral targets
> Base Sepolia (L2, lower gas). A fresh USDC token on Base Sepolia is required.

---

## 3. Step-by-Step Migration

### 3.1 Prerequisites

- USDC balance on Base Sepolia
- USDC approval for the `KarmaBilateral` contract (`approve()` with `type(uint256).max` recommended)
- Updated SDK / contract ABI (see `karma-core/out/KarmaBilateral.sol/KarmaBilateral.json`)

### 3.2 Phase 1: Lock (replace `lockFunds`)

**NCPA (old):**
```solidity
// Logical lock — funds stay in wallet, balance+allowance checked at settlement
ncp.lockFunds(usdc, 100_000_000);
ncp.createBill(seller, usdc, 100_000_000, scopeHash, proofHash, deadline);
```

**KarmaBilateral (new):**
```solidity
// Physical lock — USDC transferred into contract escrow
usdc.approve(address(karma), 100_000_000);
uint256 billId = karma.lock(usdc, 100_000_000);
```

**Key difference:** `lock()` actually transfers tokens. Ensure the ERC-20 `approve` is set before calling.

### 3.3 Phase 2: Bind (replace `confirmBill`)

**NCPA (old):**
```solidity
// Buyer confirms their side; seller separately confirms theirs
ncp.confirmBill(buyerBillId);  // buyer calls
// Settlement can proceed with just buyer confirmation
```

**KarmaBilateral (new):**
```solidity
// Buyer calls bind() — requires both party billIds + scope hash
// Both bills must be MINTED; both move to BOUND atomically
uint256 bindingId = karma.bind(buyerBillId, agentBillId, scopeHash);
```

**Key difference:** Bilateral binding requires both parties have minted Bill Tokens.
Single-party confirmation is not supported. The `scopeHash` encodes the task agreement.

### 3.4 Phase 3: Settle (new dispute window flow)

**NCPA (old):**
```solidity
// Direct settlement — buyer→seller transfer, no dispute window
bool ok = ncp.requestBillPayout(billId);
```

**KarmaBilateral (new):**
```solidity
// Step 1: Submit settlement proof → starts 24h dispute window
karma.settle(bindingId, proofHash);

// Step 2: After dispute window closes (24h), finalize
// (anyone can call, timer-based gate)
karma.finalizeSettle(bindingId);
```

**Key difference:** Settlement is a two-step process. The `settle()` call does NOT
release funds; `finalizeSettle()` does, after the dispute window expires.

### 3.5 Phase 4: Dispute (replaces NCPA dispute flow)

**NCPA (old):**
```solidity
ncp.disputeBill(billId);
// Arbitrator resolves with resolveDisputeBuyer / resolveDisputeSeller / resolveDisputeSplit
```

**KarmaBilateral (new):**
```solidity
// During dispute window (after settle(), before finalizeSettle())
karma.dispute(bindingId, evidenceHash);

// Both parties submit evidence within 72h evidence window
karma.submitArbitrationEvidence(bindingId, agentEvidenceHash);

// After evidence window: auto-resolve (small disputes) or admin resolve (large)
karma.autoResolveArbitration(bindingId);
// OR for large disputes:
// karma.resolveDispute(bindingId, buyerShareBps);  // admin only
```

### 3.6 Timeout Refund (new)

**NCPA:** `expireBill()` + `cancelBill()`

**KarmaBilateral:**
```solidity
// If settle() is never called within 7 days of bind():
karma.refundOnTimeout(bindingId);
```

---

## 4. Breaking Changes

### 4.1 `settle()` Now Requires Both Sides

NCPA could settle a bill with only the buyer's confirmation. KarmaBilateral requires
both buyer and agent Bill Tokens to be in `BOUND` state before `settle()` is callable.

**Mitigation:** Agent must call `lock()` + approve the binding before any settlement.

### 4.2 Dispute Window Added (24h default)

NCPA had no mandatory waiting period. KarmaBilateral inserts a 24-hour dispute window
between `settle()` and `finalizeSettle()`.

**Impact:** Settlement is not instant in the standard path. Immediate settlement is
available only via the attestation gateway path (`bindWithAttestation`).

### 4.3 Physical Token Custody

NCPA relied on balance+allowance checks at settlement time. KarmaBilateral holds USDC
in the contract. The invariant `totalBillSupply[token] == totalLocked[token]` is
enforced on every mutation.

**Impact:** Integrators must ensure their wallet has sufficient USDC balance *and*
approval before calling `lock()`. Failed transfers revert the entire transaction.

### 4.4 No Seller Bond

NCPA required sellers to lock a bond (`sellerBondBps`). KarmaBilateral has no seller
bond — both parties lock their respective escrow amounts symmetrically.

**Impact:** Sellers no longer post collateral beyond their own service value.

### 4.5 Batch Mode Removed

NCPA's explicit batch lifecycle (`Open → Closed → Settled`) is replaced by a simple
global `pendingBatchAmount` threshold per token.

**Impact:** No `closeBatch()` or `settleBatch()` calls. Each binding settles individually.
The `PENDING` state is informational only (triggers when threshold is reached).

### 4.6 EIP-712 Confirmation-by-Signature Removed

NCPA supported `confirmBillBySignature` for relayed confirmation. KarmaBilateral does
not implement this — the buyer must call `bind()` directly.

---

## 5. Attestation Gateway Path (New)

KarmaBilateral supports an accelerated settlement path via `KarmaAttestationGateway`:

```solidity
// Bind with N-of-M attestation requirement
uint256 bindingId = karma.bindWithAttestation(buyerBillId, agentBillId, scopeHash, taskId);

// Gateway verifiers attest; once quorum met:
// → Gateway calls karma.settle(bindingId, proofHash)
// → Bypasses dispute window, immediate settlement
```

This path is recommended for high-value or time-sensitive tasks where N-of-M verifier
consensus replaces the optimistic dispute window.

---

## 6. Recommended Timeline

| Phase | Duration | Actions |
|-------|----------|---------|
| **P0 — Deploy** | Week 1 | Deploy `KarmaBilateral` + `VerifierRegistry` + `KarmaAttestationGateway` to Base Sepolia |
| **P1 — SDK Update** | Week 1-2 | Update `karma-core/sdk/` with KarmaBilateral ABI + adapters |
| **P2 — Integrator Migration** | Week 2-4 | Existing integrators update to new `lock()/bind()/settle()/finalizeSettle()` flow |
| **P3 — Attestation** | Week 3-4 | Register verifier nodes; test attestation path end-to-end |
| **P4 — NCPA Freeze** | Week 4+ | Freeze NCPA Sepolia deployment (no new bills); maintain read access for 90 days |
| **P5 — NCPA Deprecation** | Month 3 | Announce NCPA deprecation; all active bills resolved or migrated |

---

## 7. Verification Checklist

- [ ] USDC approved on KarmaBilateral contract
- [ ] `lock()` succeeds and mints Bill Token
- [ ] Agent has own `lock()` call before `bind()`
- [ ] `bind()` creates binding with correct `scopeHash`
- [ ] `settle()` transitions binding to `FINALIZING`
- [ ] `finalizeSettle()` releases USDC after dispute window
- [ ] `dispute()` + `autoResolveArbitration()` flow works
- [ ] Invariant `totalBillSupply == totalLocked` holds after every operation

---

## See Also

- [KarmaBilateral contract](../karma-core/contracts/core/KarmaBilateral.sol)
- [Deploy script](../karma-core/contracts/script/DeployKarmaBilateral.s.sol)
- [Execution Receipt Standard V2](./EXECUTION_RECEIPT_STANDARD_V2.md)
- [KarmaBilateral test suite](../karma-core/contracts/test/KarmaBilateral.t.sol)
