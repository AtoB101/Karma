# TrustChain Ecosystem API Roadmap V0.1 (M5)

## Goal

Turn TrustChain's internal capabilities (policy control, evidence/proof verification, and safety guardian operations) into ecosystem-facing APIs with stable contracts.

## Scope (M5.0)

1. Payment Intent API
   - Create/query intent
   - Idempotent creation via `Idempotency-Key`
2. Evidence API
   - Query evidence by ID
   - Verify evidence digest/schema marker
3. Risk API
   - Query risk alerts and guardian-derived alarm feed
4. API baseline governance
   - Bearer auth
   - Unified error code model
   - OpenAPI v3.1 contract

## API Principles

- Contract-first: OpenAPI is the integration source of truth.
- Compatible versioning: `/v1` path versioning; additive changes only within v1.
- Auditability by default: evidence and verify endpoints are first-class API objects.
- Ops-safe by default: every endpoint returns machine-readable error codes and request IDs.

## Data Objects

- `PaymentIntent`
  - `intentId`, `merchantRef`, `status`, `payer`, `payee`, `token`, `amount`, `chainId`, `policyId`, `expiresAt`
- `EvidenceObject`
  - `evidenceId`, `schemaVersion`, `evidenceVersion`, `digestSha256`, `payload`
- `RiskAlert`
  - `id`, `severity`, `code`, `title`, `detail`, `source`, `createdAt`

## Security Baseline

- Bearer token required for `/v1/*` except `/v1/health`
- Token configured by `TRUSTCHAIN_API_TOKEN`
- All errors include `requestId`

## Error Code Baseline

- `AUTH_UNAUTHORIZED`
- `INVALID_JSON`
- `INVALID_REQUEST`
- `IDEMPOTENCY_KEY_REQUIRED`
- `PAYMENT_INTENT_NOT_FOUND`
- `EVIDENCE_NOT_FOUND`
- `ROUTE_NOT_FOUND`

## M5.1 Next (SDK + Webhook)

- Webhook events:
  - `payment.intent.created`
  - `evidence.verified`
  - `risk.alert.raised`
- HMAC signature for callbacks
- TS/Python SDK + Postman collection

## M5.2 Next (Production Hardening)

- Tenant-scoped API credentials
- Per-endpoint rate limiting
- SLO metrics and alert routing
- Version negotiation (`v1`, `v2`) policy
