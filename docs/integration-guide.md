# Karma Guard Integration Guide (Public)

This guide describes how external developers integrate with the public
Karma Guard surface for agent-service payments.

## Version markers

- Payload examples version: `v1-public-testnet-prep`
- Contract template version: `1.0.0`
- Changelog: `docs/agent-service-guard-changelog.md`

## Integration model

Karma Guard protects agent-service payments with:

- buyer-side protection signaling
- seller bond signaling
- evidence settlement workflow
- dispute lifecycle status

Karma Guard public repo exposes:

- frontend demo pages
- public data contract fields
- public status machine
- public-safe API placeholders

Karma Guard does not expose private risk-scoring logic.

## Demo routes

Under `apps/agent-service-guard/frontend/`:

- `index.html` - product entry page
- `service-create.html` - seller creates protected service
- `pay.html?service_id=<id>` - buyer creates protected order
- `order.html?order_id=<id>` - delivery/evidence/dispute flow
- `dashboard.html` - aggregate stats
- `badge.html?seller_wallet=<wallet>` - trust badge view

## Service creation flow

Seller submits:

- service metadata
- price/currency
- refund policy
- seller wallet
- seller bond rate (default 30%)

System returns:

- `service_id`
- `payment_link = /pay/{service_id}`

## Buyer payment flow

Buyer opens payment link and creates order.
Initial order state:

- `payment_status = MOCK_LOCKED`
- `delivery_status = PENDING`
- `dispute_status = NONE`
- `settlement_status = UNSETTLED`
- `seller_bond_status = MOCK_LOCKED`

## Evidence + settlement flow

Seller submits delivery summary.
System generates `evidence_hash` and updates delivery state.

Buyer can:

- confirm completion
- open dispute

Admin can mock-resolve dispute:

- `BUYER_WINS`
- `SELLER_WINS`
- `PARTIAL_REFUND`

## Private engine placeholders

Public repo supports placeholder interfaces only:

- `POST /risk/check`
- `POST /dispute/recommend-resolution`
- `POST /score/seller`

These endpoints are implemented by private risk engine.

## Phase 2 public preparation package

For testnet integration preparation, use:

- Payload Version: `v1-public-testnet-prep`
- `docs/testnet-integration-checklist.md`
- `docs/wallet-signature-payload-examples.json`
- `apps/agent-service-guard/templates/wallet-signature-payload-template.json`

These are public-safe templates and checklists only. Private decision engines
remain out of scope for this repository.

