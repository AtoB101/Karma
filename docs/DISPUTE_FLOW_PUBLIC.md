# Dispute flow (public)

## On-chain (KarmaBilateral)

- During `FINALIZING`, a party may call `dispute(bindingId)`.
- Admin / configured resolver may `resolveDispute(bindingId, buyerShareBps)`.
- Timeout recovery: `refundOnTimeout(bindingId)` when settle never completes.

See `karma-core/contracts/core/KarmaBilateral.sol` for exact gates.

## Off-chain

- Capture dispute intents with binding / bill references, evidence digests, and signatures.
- Surface review status and public-facing reasons only.
- Do not expose private classifier weights or fraud features in public SDKs or console.

## API

Public settlement / dispute routes live under `/v1/settlement` (see `docs/API_REFERENCE.md` and OpenAPI).  
Private adjudication engines stay off public hosts.
