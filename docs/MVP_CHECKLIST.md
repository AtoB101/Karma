# TrustChain MVP Checklist (Focused Narrative)

This checklist aligns the MVP to one job:

> **EIP-712 signed off-chain agent intent -> on-chain settlement with safe accounting**

If an item does not improve this flow's correctness, safety, or integration clarity, it should be deferred.

## 1) Core Settlement Path (Must Pass)

- [x] Agent/operator can sign EIP-712 typed intent for settlement-related operations
- [x] Contract verifies signer identity, operation type, amount binding, and deadline
- [x] Replay protection prevents digest/token reuse
- [x] Bill lifecycle reaches deterministic settlement end-state
- [x] Real ERC20 payout reaches recipient from escrow path

## 2) Safety Invariants (Must Hold)

- [x] Escrow conservation invariant (`totalLocked == mappingBalance + pendingAmount`)
- [x] Pending accounting transitions are valid on cancel/settle
- [x] Unauthorized callers are blocked on sensitive flows
- [x] Minimal emergency pause exists for incident response

## 3) Demo Acceptance (Must Be Explainable in <1 min)

- [x] Scenario test shows: register context -> lock funds -> sign -> verify -> settle
- [x] Scenario asserts exact payout amount and conservation invariant
- [x] Scenario includes at least one rejection case (replay or deadline)

## 4) Integration Readiness (V1.5)

- [x] Publish signing payload/schema reference for backend integration (`docs/SIGNING_PAYLOAD_SPEC.md`)
- [ ] Add event schema docs for indexer consumers
- [x] Provide a single-command demo run wrapper around scenario flow (`scripts/run_focus_demo.sh`)
- [ ] Run scenario + invariants in CI and publish reproducible output

## 5) Explicitly Deferred (Do Not Expand in V1)

- [ ] Rich KYA policy expansion beyond minimal gating
- [ ] Advanced lock/batch strategy optimizations not required by core settlement proof
- [ ] Circuit breaker policy breadth beyond minimal stop mechanism
