# Dispute flow (public)

## On-chain (KarmaBilateral)

- During `FINALIZING`, a party may call `dispute(bindingId)`.
- Admin / configured resolver may `resolveDispute(bindingId, buyerShareBps)`.
- Timeout recovery: `refundOnTimeout(bindingId)` when settle never completes.

See `karma-core/contracts/core/KarmaBilateral.sol` for exact gates.

## API (bilateral on-chain dispute)

Role-gated (`ADMIN_ACTOR_IDS` ∪ `ARBITRATOR_ACTOR_IDS`) endpoints on `/v1/bilateral`:

- `POST /v1/bilateral/resolve` — relay `resolveDispute(bindingId, buyerShareBps)`. The chain
  enforces the split against submitted evidence and the evidence window, so this is not an override.
- `POST /v1/bilateral/auto-resolve` — relay `autoResolveArbitration(bindingId)` (conservative
  auto-resolution after the evidence window closes).
- `GET /v1/bilateral/dispute/{binding_id}` — ruling view: binding state + arbitration record
  (evidence hashes, submitted timestamps, resolved flag) + the anchored order contract
  (terms, signatures, `anchored` scopeHash comparison).

The on-chain contract already bounds `resolveDispute` (evidence window + split range /
evidence-consistency) and replaces the single-EOA admin with an `AdminTimelock` on non-testnet
deploys; see `karma-core/contracts/script/DeployKarmaBilateral.s.sol`.

## Off-chain

- Capture dispute intents with binding / bill references, evidence digests, and signatures.
- Surface review status and public-facing reasons only.
- Do not expose private classifier weights or fraud features in public SDKs or console.

## API

Public settlement / dispute routes live under `/v1/settlement` (see `docs/API_REFERENCE.md` and OpenAPI).  
Private adjudication engines stay off public hosts.
