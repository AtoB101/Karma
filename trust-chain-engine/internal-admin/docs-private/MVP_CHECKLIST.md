# TrustChain MVP Checklist

This checklist is the acceptance baseline for a demo-ready TrustChain MVP.

## 1) Protocol Core

- [x] KYA registration, verification, revoke, permission hash update
- [x] Lock pool lifecycle (create, top-up, withdraw)
- [x] Bill lifecycle (create, confirm, cancel)
- [x] Batch lifecycle (open, close, settle) with per-pool active batch
- [x] Circuit breaker controls for transaction gating

## 2) Funds Safety

- [x] Real ERC20 transfer flow in lock pool create/top-up/withdraw
- [x] Settlement payout transfers ERC20 to recipient agent address
- [x] Escrow conservation invariant (`totalLocked == mappingBalance + pendingAmount`)
- [x] Pending release on cancel and pending->settled transition on settle

## 3) Authorization Model

- [x] Owner-only controls for confirm/cancel/close/settle
- [x] EIP-712 domain separation in auth token manager
- [x] Signed auth digest consumption with replay protection
- [x] Deadline enforcement for auth operations
- [x] Operation-type and amount-bound auth checks

## 4) Test Coverage

- [x] Unit tests for all core contracts and major revert paths
- [x] Invariant tests for accounting conservation
- [x] Invariant tests for bill/batch state non-regression
- [x] Invariant tests for bill->batch->pool consistency
- [x] Unauthorized caller tests for sensitive operations

## 5) Deployment Shape

- [x] Deploy script wired to current architecture (no deprecated settlement path)
- [x] Bill manager linked with lock pool + KYA + breaker + auth manager

## 6) Remaining To Reach Production-Grade

- [ ] Integrate auth consumption directly into external app/API command flow
- [ ] Add robust ERC20 handling for non-standard tokens (safe transfer wrappers)
- [ ] Add explicit event schema docs for indexer consumers
- [ ] Add off-chain indexer/risk service minimum runtime package
- [ ] Add end-to-end scripted demo (single command scenario run)
- [ ] Run full forge suite in CI and publish reproducible reports
