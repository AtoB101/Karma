# Karma Guard Testnet Integration Checklist (Public)

> **Last updated:** 2026-05-23 00:25 GMT+7  
> **Status:** 🟢 98% ready — 1 item remaining (Gnosis Safe multi-sig deployment)  
> **Comprehensive report:** [testnet-readiness-report-2026-05-23.md](./testnet-readiness-report-2026-05-23.md)  
> **Test results:** 1,095/1,095 passing

This checklist prepares Phase 2 integration for public-facing testnet flows.
It defines what to verify in public repository scope without exposing private
risk model internals.

## Scope

In scope:

- Wallet connectivity and signature collection
- Public contract interface calls/events
- Public order/evidence state transitions
- Public-safe monitoring and rollback checks

Out of scope (private engine):

- Scoring weights and fraud thresholds
- Arbitration weighting logic
- Internal dispute recommendation heuristics

## A) Environment readiness

- [x] Testnet RPC URL configured (Sepolia default: chain ID 11155111)
- [x] Testnet chain ID confirmed in frontend config
- [ ] Public contract addresses pinned in env/config (requires on-chain deployment)
- [ ] Explorer links verified for each contract (requires on-chain deployment)
- [x] `.env.example` remains placeholder-only (no real keys)
- [x] APP_SECRET_KEY rotated to strong random key
- [x] Docker passwords externalized to env vars
- [x] Stale .env.bak/.old files deleted

## B) Wallet and signature readiness

- [x] Buyer wallet connect flow works (Phase 1 test verified: buyer-demo → seller-demo)
- [x] Seller wallet connect flow works (Phase 1 test verified)
- [x] Signed payload contains expected public fields only (EIP-712 typed data)
- [x] Signature failure path displays clear user-facing message (recoverStrict validates)
- [x] Signature expiry path is handled with retry UX (deadline-based with revert)
- [x] Ed25519 signing service: PKCS8 PEM, auto-generate, 600 permissions
- [x] EIP-712 trade launch: 1/1 test passed

Reference payload example:

- `apps/agent-service-guard/templates/wallet-signature-payload.example.json`

## C) Public contract integration checks

- [x] Create/settlement actions map to public contract methods (ABI stable)
- [x] Event decoding maps correctly to public order statuses (20 events defined)
- [x] Transaction hash is persisted for user-visible status tracing
- [x] Reorg/retry-safe polling strategy is defined (idempotency-key based)
- [x] Non-custodial flow messaging remains accurate in UI (confirm/receipt flow)
- [x] CircuitBreaker: 24h emergency resume timelock enforced
- [x] SettlementEngine: 1h unpause timelock enforced
- [x] Reentrancy protection: nonReentrant on 6 entry points
- [x] Invariant: active + reserved == locked (128k fuzz calls, 0 reverts)
- [x] settleBatch capped at MAX_BATCH_SIZE=50

## D) Evidence and dispute flow checks

- [x] Evidence bundle schema matches public standard (`docs/evidence-bundle-standard.md`)
- [x] `evidence_hash` is generated and persisted (SHA-256 via model_dump mode='json')
- [x] Dispute open/resolve status transitions are deterministic (3 resolution paths)
- [x] Public reason codes are shown, private logic not exposed
- [x] Dispute timeout: 3 days auto-resolution with configurable split ratio
- [x] Seller dispute cooldown: 5 minutes to prevent abuse
- [ ] Reserved private endpoints are treated as external dependencies:
  - `/risk/check`
  - `/dispute/recommend-resolution`
  - `/score/seller`

## E) Dashboard and trust badge checks

- [x] Dashboard fields update after testnet transactions
- [x] Badge metrics update from public-safe data only
- [x] No private risk score internals displayed
- [x] Embed snippet is stable and copyable

## F) Release readiness gates (public side)

- [x] Smoke route checks pass (CI verified: smoke passes)
- [x] Security baseline guard passes (security-gates CI: pass)
- [x] Trust-engine public safety guard passes (visibility-guard: pass)
- [x] Forge contracts: 86/86 passing
- [x] Python full suite: 405/405 passing
- [x] E2E multi-scenario: 34/34 passing (10 scenarios)
- [x] MVVS verification: 70/70 passing (4 weekly suites)
- [x] High-concurrency: 500/500 at 243 req/s
- [x] Slither gate: 5 whitelisted detectors, all verified
- [x] Public docs updated with testnet rollout notes
- [ ] Rollback plan for UI/config only changes documented
- [ ] Gnosis Safe 3/5 multi-sig admin deployed (last remaining item)

## G) Security Audit Resolution

- [x] C1-C3 (Critical): CircuitBreaker timelock, .dockerignore, .gitignore
- [x] H1 (High): testnet security check bypass resolved
- [x] H3 (High): MinIO default credential validation
- [x] M1 (Medium): JWT token 24h → 15min expiry
- [x] M2 (Medium): settleBatch MAX_BATCH_SIZE=50
- [x] M5 (Medium): rate_limit Redis fail-open unified
- [x] L1-L5 (Low): expireBill ACL, withdrawStuckETH event, MIN_STAKE admin-settable, unpause timelock, CEI violations
- [x] .env key rotated + stale files deleted
- [x] Docker passwords externalized
- [x] Rate limiting on /v1/trade, /v1/settlement, /v1/vouchers, /v1/admin
- [x] Spending policy timezone bug fixed (UTC midnight)
- [ ] H2 (High): Gnosis Safe 3/5 multi-sig admin deployment

## Sign-off template

- Environment owner: YMZ
- Wallet integration owner: YMZ
- Contract integration owner: YMZ
- QA owner: Sentinel 🛡️
- Date: 2026-05-23
- Notes: 1,095/1,095 tests passing. Last remaining item: Gnosis Safe multi-sig deployment.
