# Dispute flow (public)

## Public responsibilities

- Capture **dispute intents** with references to `bill_id`, evidence URIs, and signatures suitable for audit.  
- Surface **review status** and **public-facing reasons** returned by operator services.  
- Never expose private classifier weights, internal codes, or proprietary fraud features in static frontends or public SDKs.

## On-chain vs off-chain

On-chain dispute transitions are enforced by `NonCustodialAgentPayment` (see contract source).  
Off-chain review and reputation updates must be performed by **private services** behind authenticated internal APIs.

## API sketch

`POST /api/public/disputes/create` in `openapi/karma-public-console-api.yaml` describes a public-safe create call.  
Private adjudication endpoints must **not** be mounted on public hosts.
