# Karma Guard for Agent Services - Acceptance Checklist

This checklist validates the public mock MVP flow.

## Core flow checks

- [ ] Open home page at `frontend/index.html`.
- [ ] See the four entry actions:
  - Create Protected Service
  - Pay with Protection
  - View Dashboard
  - View Trust Badge

## Service creation

- [ ] Create service with fields:
  - `service_name`
  - `service_type`
  - `description`
  - `price`
  - `currency`
  - `delivery_time`
  - `refund_policy`
  - `seller_wallet`
  - `seller_bond_rate` (default 30%)
- [ ] Confirm generated:
  - `service_id`
  - `payment_link` (`/pay/{service_id}`)
- [ ] Confirm data is persisted in local mock storage.

## Buyer payment

- [ ] Open payment page for a service (`/pay/{service_id}` pattern via query mapping).
- [ ] Confirm service card shows:
  - service name/description/price
  - seller wallet
  - seller bond rate
  - Karma Protected
  - buyer protection note
- [ ] Click payment action and create an order.
- [ ] Confirm initial order state:
  - `payment_status = MOCK_LOCKED`
  - `delivery_status = PENDING`
  - `dispute_status = NONE`
  - `settlement_status = UNSETTLED`
  - `seller_bond_status = MOCK_LOCKED`

## Order detail flow

- [ ] Open order detail page and verify required fields displayed:
  - `order_id`
  - `buyer_wallet`
  - `seller_wallet`
  - `price`
  - `payment_status`
  - `delivery_status`
  - `dispute_status`
  - `settlement_status`
  - `seller_bond_status`
  - `evidence_hash`
- [ ] Seller submits delivery and system generates `evidence_hash`.
- [ ] Buyer confirms completion.
- [ ] Buyer opens dispute.
- [ ] Admin resolves dispute with mock options:
  - `BUYER_WINS`
  - `SELLER_WINS`
  - `PARTIAL_REFUND`

## Dashboard and badge

- [ ] Dashboard metrics change after new orders / confirmations / disputes:
  - `total_protected_volume`
  - `verified_orders`
  - `settled_orders`
  - `disputed_orders`
  - `refunded_orders`
  - `active_seller_bond`
  - `average_settlement_time`
  - `seller_success_rate`
  - `dispute_rate`
- [ ] Badge page (`/badge/{seller_wallet}` pattern via query mapping) shows:
  - Karma Protected
  - Seller Wallet
  - Total Protected Volume
  - Verified Orders
  - Success Rate
  - Dispute Rate
  - Active Bond
  - Copy Embed Code action

## Public/private boundary checks

- [ ] No private scoring weights are exposed.
- [ ] No anti-cheat threshold constants are exposed.
- [ ] No arbitration tie-break weighting internals are exposed.
- [ ] Only field contracts and public state-machine data are published.
