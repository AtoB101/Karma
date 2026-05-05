# Evidence Bundle Standard (Public)

This document defines the **public** evidence bundle contract for Karma Guard.
It defines field names and state surfaces only.

Private scoring, anti-fraud thresholds, and arbitration weighting remain in the
private risk engine and are intentionally not published.

## EvidenceBundle fields

Required fields:

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

## Public rules

1. `evidence_hash` is a deterministic pointer to delivery evidence content.
2. `output_hash` allows integrity checks without exposing raw private data.
3. `settlement_status` and `dispute_status` map to public state machine enums.
4. Public repositories should store only mock or redacted evidence summaries.
5. Raw private prompts, responses, and risk-model internals are not public data.

## State compatibility

`settlement_status` must be one of:

- `UNSETTLED`
- `SETTLED`
- `FROZEN`
- `REFUNDED`
- `PARTIALLY_SETTLED`

`dispute_status` must be one of:

- `NONE`
- `OPEN`
- `RESOLVED`
- `REJECTED`

## Private engine extension boundary

If private review is needed, public code may call:

- `/risk/check`
- `/dispute/recommend-resolution`
- `/score/seller`

These endpoints are provided by the private risk engine.
