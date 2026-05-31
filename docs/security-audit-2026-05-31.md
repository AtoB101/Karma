# Security Audit Report — KarmaBilateral.sol

**Date:** 2026-05-31  
**Auditor:** KT (Karma Operations Director), automated via Slither + manual review  
**Contract:** `KarmaBilateral.sol` (Solidity ^0.8.24)  
**Scope:** Full contract — all external, public, and internal functions  
**Tooling:** Slither 0.11.0 (25 contracts, 101 detectors)

---

## Executive Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH     | 0 |
| MEDIUM   | 3 |
| LOW      | 4 |
| INFO     | 6 |

**Bottom line:** No critical or high-severity vulnerabilities found in KarmaBilateral.sol. The contract's `nonReentrant` guard covers all functions that make external calls. State machines are well-guarded. The main issues are missing events on admin setters, defense-in-depth gaps (missing `nonReentrant` on identity functions), and a zero-address validation gap.

---

## Detailed Findings

### [M-01] Missing `nonReentrant` modifier on KarmaIdentity functions

**Severity:** MEDIUM  
**Location:** Lines ~898–971

**Description:** Four external KarmaIdentity management functions lack the `nonReentrant` modifier:

- `registerIdentity(bytes32 masterAgentId)` — line 898
- `addSubAgent(address subWallet, bytes32 subAgentId)` — line 906
- `removeSubAgent(address subWallet)` — line 925
- `setSubAgentAllowance(address subWallet, uint256 allowance)` — line 942

While these functions currently make **no external calls**, they write to storage (`identities`, `subAgentById`, `subAgentMaster`, `activeSubAgents`, `_masterSubAgentIds`). Every other state-changing external function in this contract uses `nonReentrant` — these four break the pattern.

**Risk:** If any of these functions is extended in a future upgrade to make an external call (e.g., to verify an on-chain identity registry), the missing guard becomes a reentrancy vector.

**Recommendation:** Add `nonReentrant` modifier to all four functions for defense-in-depth consistency.

```diff
- function registerIdentity(bytes32 masterAgentId) external {
+ function registerIdentity(bytes32 masterAgentId) external nonReentrant {
```

---

### [M-02] Critical admin setters missing event emissions

**Severity:** MEDIUM  
**Location:** Lines 1073–1094

**Description:** Five admin-only setter functions change core protocol parameters without emitting events:

| Function | Variable Set | Value Changed |
|----------|-------------|---------------|
| `setDisputeWindow(uint256)` | `disputeWindowSeconds` | Settle delay after bind |
| `setOptimisticDisputeWindow(uint256)` | `disputeWindow` | Layer 1 dispute window |
| `setEvidenceWindow(uint256)` | `evidenceWindow` | Arbitration evidence deadline |
| `setAutoArbitrationThreshold(uint256)` | `autoArbitrationThreshold` | Auto-resolve pool cap |
| `setSettleTimeout(uint256)` | `settleTimeoutSeconds` | Timeout refund deadline |

**Confirmed by Slither** for 3 of 5 (the first two were not auto-flagged by Slither, manually confirmed missing).

**Risk:** Off-chain monitoring systems (indexers, dashboards, alert bots) cannot detect parameter changes without events. An admin key compromise changing the dispute window from 24h to 1 second would go undetected in event logs — only storage diffs would show it.

**Recommendation:** Add events for all five setters.

```solidity
event DisputeWindowSecondsUpdated(uint256 newValue);
event OptimisticDisputeWindowUpdated(uint256 newValue);
event EvidenceWindowUpdated(uint256 newValue);
event AutoArbitrationThresholdUpdated(uint256 newValue);
event SettleTimeoutUpdated(uint256 newValue);
```

---

### [M-03] `setAttestationGateway()` lacks zero-address validation

**Severity:** MEDIUM  
**Location:** Line 1097

**Description:** 
```solidity
function setAttestationGateway(address gateway) external onlyAdmin {
    attestationGateway = gateway;
    emit AttestationGatewayUpdated(gateway);
}
```

There is no `require(gateway != address(0))` check. Setting the gateway to `address(0)` would:

1. Permanently break `bindWithAttestation()` — it reverts with `GatewayNotSet()` when `attestationGateway == address(0)`.
2. Prevent attested settlement — `settle()` reverts with `AttestationRequired()` for attested bindings.
3. There is **no recovery path** — no separate function exists to re-set the gateway AND re-link existing attested bindings.

**Confirmed by Slither.**

**Risk:** A fat-finger admin transaction setting the gateway to zero permanently bricks all attested binding flows. While admin is a trusted role, operational errors are the most common class of on-chain incidents.

**Recommendation:** Add zero-address validation and consider a two-step transfer pattern:

```solidity
function setAttestationGateway(address gateway) external onlyAdmin {
    require(gateway != address(0), "ZeroAddress");
    attestationGateway = gateway;
    emit AttestationGatewayUpdated(gateway);
}
```

---

### [L-01] Misleading setter function naming — `setDisputeWindow` vs `setOptimisticDisputeWindow`

**Severity:** LOW  
**Location:** Lines 1073, 1079

**Description:** 
- `setDisputeWindow(seconds_)` sets `disputeWindowSeconds` (the **settle delay** — minimum time after `bind()` before `settle()` can be called).
- `setOptimisticDisputeWindow(seconds_)` sets `disputeWindow` (the **actual dispute window** — time after `settle()` during which buyer can dispute).

The naming is semantically inverted: the function called "setDisputeWindow" does NOT set the dispute window. This is a UX trap for the admin.

**Recommendation:** Rename for clarity:
- `setDisputeWindow()` → `setSettleDelaySeconds()`
- `setOptimisticDisputeWindow()` → `setDisputeWindowSeconds()`

---

### [L-02] `Authorization.accepted` field semantically overloaded

**Severity:** LOW  
**Location:** Lines 861–893

**Description:** The `accepted` boolean in the `Authorization` struct serves double duty:

- `accept()` sets `accepted = true` (authorization claimed by recipient)
- `cancelAuthorization()` also sets `accepted = true` (authorization resolved by cancellation)

This means `accepted = true` actually means "resolved (accepted OR cancelled)." Off-chain systems querying `authorizations[authId].accepted` will see `true` for cancelled authorizations and may incorrectly interpret them as accepted.

**Recommendation:** Use a dedicated `resolved` flag or an enum (`PENDING`, `ACCEPTED`, `CANCELLED`).

---

### [L-03] Redundant variable references in stub functions

**Severity:** LOW  
**Location:** Lines 699–738

**Description:** `settleWithTEE()` and `settleWithZKProof()` contain bare variable references to suppress unused-variable compiler warnings:

```solidity
bindingId;
proofHash;
teeAttestation;
```

**Confirmed by Slither** as "redundant-statements."

**Recommendation:** Use inline assembly blocks or structured comments to suppress warnings cleanly. These will be removed when Layer 2/3 are implemented.

---

### [L-04] Global invariant checks use `revert` not `assert` — gas refund edge case

**Severity:** LOW  
**Location:** Lines 1171–1177, 1179–1183

**Description:** `_checkInvariant()` and `_checkPerAddressInvariant()` use custom error `revert` instead of `assert()`. While `revert` is appropriate (it refunds unused gas), it means invariant violations are indistinguishable from regular application-level errors in transaction traces. Using `assert()` would signal to tooling that this should NEVER happen — a true invariant violation.

**Recommendation:** Consider using `assert()` for truly invariant conditions (as Solidity docs recommend) to distinguish invariants from business-logic errors.

---

### [I-01] Reentrancy analysis — all guarded paths confirmed

**Finding:** All 16 external/public functions that make external calls are protected by the `nonReentrant` modifier. Internal helpers (`_executeSettle`, `_executeRefund`, `_executeSplit`, `_transfer`) are only called through protected paths.

**Slither-note:** Slither flagged `lock()` as "reentrancy-benign" — state writes occur after `transferFrom()`. This is safe because:
1. The `nonReentrant` modifier prevents re-entry.
2. For the intended token (USDC), the ERC20 implementation does not call back.
3. Even with a malicious token that calls back, `nonReentrant` blocks re-entrant calls to other protected functions.

The four KarmaIdentity functions (M-01) are the only unprotected state-changing paths.

---

### [I-02] Integer overflow/underflow — no exploitable vectors

**Finding:** Solidity ^0.8.24 provides built-in overflow protection. All arithmetic operations use default checked math. No `unchecked` blocks exist in the contract. The `_executeSplit()` calculation `(totalPool * buyerShareBps) / 10_000` is bounded by realistic USDC amounts and validated `buyerShareBps <= 10000`.

---

### [I-03] Bill Token SBT property — verified non-transferable

**Finding:** Bill Tokens are **truly non-transferable** within the contract:
- No `transfer()` / `transferFrom()` / `approve()` functions exist for bills.
- `bill.owner` is set at mint and never modified.
- `_burnBill()` does not reset `owner` (only `state` changes to `BURNED`).
- BURNED bills cannot be re-bound (state check in `bind()` requires `MINTED`).

The only way to "transfer" bill value is to `unlock()` a MINTED bill (releasing USDC to the owner) and then transfer USDC directly — which is normal ERC20 behavior and not a bill token bypass.

---

### [I-04] State machine transitions — all properly guarded

**Bills:** MINTED → BOUND → BURNED
- `bind()` requires MINTED state → transitions to BOUND. Verified: no double-bind possible.
- `unlock()` requires MINTED state → transitions to BURNED via `_burnBill()`. Verified: only MINTED (unbound) bills can be unlocked.
- No path to skip from MINTED directly to BURNED through settlement functions (those require bindings to exist).
- BURNED bills cannot be re-minted or re-bound. Terminal state. ✅

**Bindings:** ACTIVE/PENDING → FINALIZING → SETTLED / DISPUTED → SETTLED/REFUNDED
- All transitions are guarded by explicit state checks.
- Terminal states (SETTLED, REFUNDED) have no exit paths.
- `_executeSettle()`, `_executeRefund()`, `_executeSplit()` all burn bills and transition bindings to terminal states in one atomic internal call. No intermediate inconsistent state. ✅

---

### [I-05] Front-running analysis — no exploitable vectors

**Scenario 1 (buyer calls settle, agent front-runs dispute):** Not possible — only buyer can call `dispute()`, and only during FINALIZING state (after settle).

**Scenario 2 (agent calls settle, buyer disputes within window):** By design — the `disputeWindow` (24h) exists for exactly this purpose.

**Scenario 3 (MEV on bind):** `bind()` requires the caller to own the buyer bill. No race condition possible — bill ownership is deterministic.

**Scenario 4 (MEV on finalizeSettle):** Anyone can call `finalizeSettle()` after the dispute window. Outcome is deterministic — no incentive to front-run.

**Scenario 5 (MEV on autoResolveArbitration):** Anyone can call after evidence window. Deterministic outcome based on evidence submission. No profit from front-running.

---

### [I-06] USDC approval abuse — no contract-level risk

**Finding:** The contract uses `transferFrom` only in `lock()`, and only for the exact `amount` the caller specifies. No function allows arbitrary `transferFrom` from a user's address. Settlement payouts use `transfer()` (sending from the contract's own balance). No infinite approval risk exists at the contract level.

**Note for users:** Standard ERC20 approval hygiene applies — users should approve specific amounts rather than `type(uint256).max`, but this is a wallet-level concern, not a contract vulnerability.

---

## Certora Specs Completeness

### Existing coverage

| Contract | Spec File | Status |
|----------|-----------|--------|
| `SettlementEngine.sol` | `certora/specs/SettlementEngine.spec` | ✅ light coverage (admin, domain) |
| `NonCustodialAgentPayment.sol` | `certora/specs/NonCustodialAgentPayment.spec` | ✅ light coverage (arbitrator, zero-token) |
| `CircuitBreaker.sol` | `certora/specs/CircuitBreaker.spec` | ✅ good coverage (pause/resume cycles) |
| `AuthTokenManager.sol` | `certora/specs/AuthTokenManager.spec` | ✅ exists |
| `KYARegistry.sol` | `certora/specs/KYARegistry.spec` | ✅ exists |
| **`KarmaBilateral.sol`** | **❌ MISSING** | **No spec file** |

### Missing KarmaBilateral invariants for Certora

The following invariants are enforced in Solidity (via `_checkInvariant`, `_checkPerAddressInvariant`, state checks) but have **no Certora formal verification coverage**:

1. **Global token invariant:** `∀ token: totalBillSupply[token] == totalLocked[token]`
2. **Per-address invariant:** `∀ address: freeBalance[a] + boundBalance[a] == totalMintedByAddr[a]`
3. **Bill state machine:** MINTED → {BOUND, BURNED}; BOUND → BURNED; BURNED is terminal
4. **Binding state machine:** ACTIVE/PENDING → FINALIZING → {SETTLED, DISPUTED} → {SETTLED, REFUNDED}
5. **Access control:** All `onlyAdmin` functions revert for non-admin callers
6. **NonReentrant:** No function with `nonReentrant` modifier can be re-entered
7. **Bill ownership:** `bill.owner` never changes after mint
8. **Token allowlist:** `lock()` reverts for non-allowed tokens
9. **Attestation gate:** Only gateway can settle attested bindings
10. **Dispute access:** Only buyer can call `dispute()`

**Recommendation:** Create `certora/specs/KarmaBilateral.spec` covering at minimum invariants 1–5. The per-address invariant (#2) is especially critical — a violation means internal accounting is silently corrupted.

---

## Slither Findings (Full Output)

### KarmaBilateral-specific

| Detector | Finding | Severity |
|----------|---------|----------|
| `events-maths` | `setOptimisticDisputeWindow`, `setEvidenceWindow`, `setAutoArbitrationThreshold` missing events | MEDIUM |
| `missing-zero-check` | `setAttestationGateway` lacks zero-address check | MEDIUM |
| `reentrancy-benign` | `lock()` writes state after `transferFrom` (guarded by nonReentrant) | INFO |
| `timestamp` | Multiple functions use `block.timestamp` for comparisons (expected) | INFO |
| `redundant-statements` | Bare variable refs in `settleWithTEE` and `settleWithZKProof` | INFO |

### Related contracts (for awareness)

| Detector | Contract | Finding |
|----------|----------|---------|
| `reentrancy-no-eth` | `NonCustodialAgentPayment` | State writes after external calls in `_resolveDisputeSplitInternal`, `resolveDisputeSplit`, `settleBatch` |
| `reentrancy-benign` | `NonCustodialAgentPayment` | State writes after external calls in `_settleConfirmedBill`, `_settleDisputedBillSellerWins` |
| `arbitrary-send-erc20` | `SettlementEngine` | Arbitrary `from` in `transferFrom` |
| `dead-code` | `NonCustodialAgentPayment` | `_enforceSettlementGuard` unused |
| `calls-loop` | `NonCustodialAgentPayment`, `SettlementEngine` | External calls inside loops |

---

## Recommendations (Priority-Ordered)

1. **CRITICAL — None**
2. **HIGH — None**
3. **MEDIUM — Fix before mainnet:**
   - [ ] Add events to all 5 parameter setter functions (M-02)
   - [ ] Add zero-address check to `setAttestationGateway()` (M-03)
   - [ ] Add `nonReentrant` to 4 KarmaIdentity functions (M-01)
4. **LOW — Fix in next sprint:**
   - [ ] Rename setters for clarity (L-01)
   - [ ] Use enum for Authorization resolution state (L-02)
   - [ ] Clean up redundant statements in stubs (L-03)
   - [ ] Consider `assert()` for true invariants (L-04)
5. **PROCESS:**
   - [ ] Create `certora/specs/KarmaBilateral.spec` covering 10 missing invariants
   - [ ] Fix reentrancy findings in `NonCustodialAgentPayment.sol` (separate audit)

---

## Methodology

1. **Automated:** Ran Slither 0.11.0 on the full contracts directory with forge-std, test, mocks, and `_legacy` paths filtered out.
2. **Manual line-by-line review** of all state-changing functions in KarmaBilateral.sol.
3. **State machine analysis** — traced every possible transition for BillToken and Binding states.
4. **Access control audit** — verified every `onlyAdmin`, owner-check, and gateway-gated path.
5. **Reentrancy coverage** — mapped every external call to its `nonReentrant` guard.
6. **Certora gap analysis** — compared existing specs against the KarmaBilateral invariant surface.

---

*Report generated by KT (🧊) — Mission Control security audit workflow.*
