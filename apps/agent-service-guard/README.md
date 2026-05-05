# Karma Guard for Agent Services (Public MVP)

Karma Guard is the first public scenario product in the Karma public repository.
It demonstrates a clear, open, and integrator-friendly flow for protected AI
service payments:

- Buyer protection
- Seller bond
- Evidence settlement
- Non-custodial payment flow
- Karma Protected badge

This public demo **does not** expose private scoring weights, anti-fraud
parameters, or arbitration internals.

## Run locally

From repository root:

```bash
python3 -m http.server 8790
```

Then open:

`http://127.0.0.1:8790/apps/agent-service-guard/frontend/index.html`

### Local smoke check (Python-only)

```bash
python3 ./scripts/agent-service-guard-smoke.py
```

This validates required pages, paths, and key public-safe strings.

Optional Node.js-based run + smoke:

```bash
npm install
npm run guard:dev
npm run guard:smoke
```

## Pages

- Home: `/apps/agent-service-guard/frontend/index.html`
- Create service: `/apps/agent-service-guard/frontend/service-create.html`
- Pay with protection: `/apps/agent-service-guard/frontend/pay.html?service_id=<id>`
- Order detail: `/apps/agent-service-guard/frontend/order.html?order_id=<id>`
- Dashboard: `/apps/agent-service-guard/frontend/dashboard.html`
- Trust badge: `/apps/agent-service-guard/frontend/badge.html?seller_wallet=<wallet>`

## Current mock scope

- Storage: browser localStorage (mock store)
- Payment lock/bond lock: mock statuses only
- Evidence hash: mock deterministic hash helper
- Dispute decision: admin mock buttons (`BUYER_WINS`, `SELLER_WINS`, `PARTIAL_REFUND`)
- Dashboard and badge metrics: computed from mock orders

## Future real integrations

Phase 2/3 targets are documented in `ROADMAP.md`:

- Real wallet signature and settlement calls
- Contract/testnet integration
- x402 and agent API integration

## Private engine boundary

Public repo can reserve interface contracts only. Private logic remains private.
Reserved endpoints:

- `/risk/check`
- `/dispute/recommend-resolution`
- `/score/seller`

These endpoints are provided by the private risk engine.
