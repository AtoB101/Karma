"""Payment code v1 — QR/deep-link payload for timed buyer payment authorization."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

PAYMENT_CODE_VERSION = "payment_code_v1"


def build_payment_code_payload(
    *,
    voucher_id: str,
    buyer_identity_id: str,
    seller_identity_id: str,
    amount: float,
    bill_credit_amount: float,
    currency: str,
    task_type: str,
    task_precision: float | None,
    expires_at: datetime,
    payment_mode: str,
    chain_anchor_hash: str | None = None,
    responsibility_boundary_id: str | None = None,
) -> dict[str, Any]:
    return {
        "version": PAYMENT_CODE_VERSION,
        "voucher_id": voucher_id,
        "buyer_identity_id": buyer_identity_id,
        "seller_identity_id": seller_identity_id,
        "amount": amount,
        "bill_credit_amount": bill_credit_amount,
        "currency": currency,
        "task_type": task_type,
        "task_precision": task_precision,
        "expires_at": expires_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        if expires_at.tzinfo
        else expires_at.isoformat() + "Z",
        "payment_mode": payment_mode,
        "chain_anchor_hash": chain_anchor_hash,
        "responsibility_boundary_id": responsibility_boundary_id,
        "payload_hash": "",
    }


def finalize_payload_hash(payload: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in payload.items() if k != "payload_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    out = dict(payload)
    out["payload_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return out
