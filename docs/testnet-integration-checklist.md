# Karma Guard Testnet Integration Checklist (Public)

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

- [ ] Testnet RPC URL configured
- [ ] Testnet chain ID confirmed in frontend config
- [ ] Public contract addresses pinned in env/config
- [ ] Explorer links verified for each contract
- [ ] `.env.example` remains placeholder-only (no real keys)

## B) Wallet and signature readiness

- [ ] Buyer wallet connect flow works
- [ ] Seller wallet connect flow works
- [ ] Signed payload contains expected public fields only
- [ ] Signature failure path displays clear user-facing message
- [ ] Signature expiry path is handled with retry UX

Reference payload example:

- `apps/agent-service-guard/templates/wallet-signature-payload.example.json`

## C) Public contract integration checks

- [ ] Create/settlement actions map to public contract methods (no ABI changes)
- [ ] Event decoding maps correctly to public order statuses
- [ ] Transaction hash is persisted for user-visible status tracing
- [ ] Reorg/retry-safe polling strategy is defined
- [ ] Non-custodial flow messaging remains accurate in UI

## D) Evidence and dispute flow checks

- [ ] Evidence bundle schema matches public standard:
  - `docs/evidence-bundle-standard.md`
- [ ] `evidence_hash` is generated and persisted
- [ ] Dispute open/resolve status transitions are deterministic
- [ ] Public reason codes are shown, private logic not exposed
- [ ] Reserved private endpoints are treated as external dependencies:
  - `/risk/check`
  - `/dispute/recommend-resolution`
  - `/score/seller`

## E) Dashboard and trust badge checks

- [ ] Dashboard fields update after testnet transactions
- [ ] Badge metrics update from public-safe data only
- [ ] No private risk score internals displayed
- [ ] Embed snippet is stable and copyable

## F) Release readiness gates (public side)

- [ ] Smoke route checks pass
- [ ] Security baseline guard passes
- [ ] Trust-engine public safety guard passes
- [ ] Public docs updated with testnet rollout notes
- [ ] Rollback plan for UI/config only changes documented

## Sign-off template

- Environment owner:
- Wallet integration owner:
- Contract integration owner:
- QA owner:
- Date:
- Notes:
