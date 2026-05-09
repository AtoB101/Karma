// Karma Guard SDK example (public-safe)
// This file intentionally exposes only public fields and flow contracts.

export function buildEvidenceBundle(input) {
  return {
    evidence_id: input.evidence_id,
    order_id: input.order_id,
    buyer_wallet: input.buyer_wallet,
    seller_wallet: input.seller_wallet,
    service_type: input.service_type,
    price: input.price,
    currency: input.currency,
    input_summary: input.input_summary,
    output_summary: input.output_summary,
    output_hash: input.output_hash,
    execution_status: input.execution_status || "DELIVERED",
    failure_reason: input.failure_reason || "",
    started_at: input.started_at,
    completed_at: input.completed_at,
    buyer_signature: input.buyer_signature || "",
    seller_signature: input.seller_signature || "",
    evidence_hash: input.evidence_hash,
    settlement_status: input.settlement_status || "UNSETTLED",
    dispute_status: input.dispute_status || "NONE",
    created_at: input.created_at,
  };
}

export function buildRiskCheckInput(order) {
  return {
    order_id: order.order_id,
    buyer_wallet: order.buyer_wallet,
    seller_wallet: order.seller_wallet,
    amount: order.price,
    currency: order.currency,
    service_type: order.service_type,
    evidence_hash: order.evidence_hash || "",
  };
}

export function parseRiskCheckResult(result) {
  return {
    risk_level: result.risk_level, // LOW | MEDIUM | HIGH
    public_reason_code: result.public_reason_code,
    action: result.action, // ALLOW | REVIEW | FREEZE
  };
}

