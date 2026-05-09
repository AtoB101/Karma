# Karma Guard for Agent Services - DATA CONTRACT (Public)

This file publishes **public-safe field contracts and state enums only**.
It does not expose private scoring weights, fraud thresholds, or arbitration
decision internals.

## Service

- `service_id`
- `seller_wallet`
- `service_name`
- `service_type`
- `description`
- `price`
- `currency`
- `delivery_time`
- `refund_policy`
- `seller_bond_rate`
- `created_at`
- `status`

## Order

- `order_id`
- `service_id`
- `buyer_wallet`
- `seller_wallet`
- `service_name`
- `service_type`
- `price`
- `currency`
- `seller_bond_amount`
- `payment_status`
- `delivery_status`
- `dispute_status`
- `settlement_status`
- `seller_bond_status`
- `created_at`
- `updated_at`

## EvidenceBundle

- `evidence_id`
- `order_id`
- `buyer_wallet`
- `seller_wallet`
- `service_type`
- `price`
- `currency`
- `input_summary`
- `output_summary`
- `output_hash`
- `execution_status`
- `failure_reason`
- `started_at`
- `completed_at`
- `buyer_signature`
- `seller_signature`
- `evidence_hash`
- `settlement_status`
- `dispute_status`
- `created_at`

## Dispute

- `dispute_id`
- `order_id`
- `opened_by`
- `reason_code`
- `reason_text`
- `evidence_hash`
- `status`
- `resolution`
- `refund_amount`
- `seller_penalty_amount`
- `created_at`
- `resolved_at`

## SellerStats

- `seller_wallet`
- `total_protected_volume`
- `verified_orders`
- `settled_orders`
- `disputed_orders`
- `refunded_orders`
- `success_rate`
- `dispute_rate`
- `active_bond_amount`
- `total_bond_locked`
- `average_settlement_time`

## Public State Enums

### PaymentStatus

- `MOCK_LOCKED`
- `LOCKED`
- `RELEASED`
- `REFUNDED`
- `PARTIAL_RELEASED`

### DeliveryStatus

- `PENDING`
- `DELIVERED`
- `CONFIRMED`
- `FAILED`

### DisputeStatus

- `NONE`
- `OPEN`
- `RESOLVED`
- `REJECTED`

### SettlementStatus

- `UNSETTLED`
- `SETTLED`
- `FROZEN`
- `REFUNDED`
- `PARTIALLY_SETTLED`

### SellerBondStatus

- `NONE`
- `MOCK_LOCKED`
- `LOCKED`
- `RELEASED`
- `FROZEN`
- `SLASHED`
- `PARTIAL_RELEASED`

### Mock Arbitration Outcomes (Public Demo Only)

- `BUYER_WINS`
- `SELLER_WINS`
- `PARTIAL_REFUND`

## Private Engine Reserved Endpoints (Interface Only)

The public repo may call these endpoints in future, but must not implement
private logic:

- `/risk/check`
- `/dispute/recommend-resolution`
- `/score/seller`

Public-safe structures:

```ts
type RiskCheckInput = {
  order_id: string;
  service_type: string;
  price: number;
  currency: string;
  seller_wallet: string;
  buyer_wallet: string;
};

type RiskCheckResult = {
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  public_reason_code: string;
  action: "ALLOW" | "REVIEW" | "FREEZE";
};
```

```ts
type DisputeReviewInput = {
  dispute_id: string;
  order_id: string;
  evidence_hash: string;
  reason_code: string;
};

type DisputeReviewResult = {
  recommendation: "BUYER_WINS" | "SELLER_WINS" | "PARTIAL_REFUND";
  public_reason_code: string;
};
```

```ts
type SellerScoreInput = {
  seller_wallet: string;
  period_days: number;
};

type SellerScoreResult = {
  score_band: "A" | "B" | "C";
  public_reason_code: string;
};
```
