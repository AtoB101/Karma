"""Launch guards for preauth trade pipeline (amounts, parties, testnet anchors)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import HTTPException

from config.settings import settings
from db.models.orm import AgentAutomationPolicyModel


PIPELINE_VERSION = "v2"
REQUIREMENT_MAX_LEN = 32_000
CHAIN_ANCHOR_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


def normalize_idempotency_key(key: str | None) -> str | None:
    if key is None:
        return None
    trimmed = key.strip()
    if not trimmed:
        return None
    if len(trimmed) < 8 or len(trimmed) > 256:
        raise HTTPException(400, detail="Idempotency-Key must be 8-256 characters")
    return trimmed


def require_idempotency_key_if_configured(key: str | None) -> str | None:
    normalized = normalize_idempotency_key(key)
    env = (settings.app_env or "").lower()
    if env in ("production", "prod") and not normalized:
        raise HTTPException(400, detail="Idempotency-Key required in production")
    return normalized


def validate_launch_parties(*, buyer_identity_id: str, seller_identity_id: str) -> None:
    if buyer_identity_id == seller_identity_id:
        raise HTTPException(400, detail="buyer and seller must be different identities")
    if len(buyer_identity_id) > 128 or len(seller_identity_id) > 128:
        raise HTTPException(400, detail="identity id too long")


def validate_requirement_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise HTTPException(400, detail="requirement_text is required")
    if len(cleaned) > REQUIREMENT_MAX_LEN:
        raise HTTPException(400, detail=f"requirement_text exceeds {REQUIREMENT_MAX_LEN} characters")
    return cleaned


def validate_chain_anchor_for_mode(chain_anchor_hash: str | None) -> str | None:
    raw = (chain_anchor_hash or "").strip() or None
    mode = (settings.settlement_mode or "offchain").lower()
    if mode in ("testnet", "hybrid") and not raw:
        raise HTTPException(
            400,
            detail="chain_anchor_hash required when SETTLEMENT_MODE is testnet or hybrid",
        )
    if raw and not CHAIN_ANCHOR_RE.match(raw):
        raise HTTPException(400, detail="chain_anchor_hash must be 32-byte hex (0x + 64 hex chars)")
    return raw


def clamp_spec_to_policies(
    spec: dict[str, Any],
    *,
    buyer_policy: AgentAutomationPolicyModel,
    seller_policy: AgentAutomationPolicyModel,
) -> dict[str, Any]:
    amount = float(spec["amount"])
    precision = float(spec["task_precision"])
    task_type = str(spec["task_type"])

    for role, policy in (("buyer", buyer_policy), ("seller", seller_policy)):
        if policy.single_limit and amount > float(policy.single_limit):
            raise HTTPException(
                400,
                detail=f"amount {amount} exceeds {role} automation-policy single_limit",
            )

    if buyer_policy.allowed_task_types and task_type not in (buyer_policy.allowed_task_types or []):
        raise HTTPException(400, detail=f"task_type {task_type} not in buyer allowed_task_types")

    pmin = buyer_policy.task_precision_min
    pmax = buyer_policy.task_precision_max
    if pmin is not None and precision < float(pmin):
        raise HTTPException(400, detail=f"task_precision below buyer minimum ({pmin})")
    if pmax is not None and precision > float(pmax):
        raise HTTPException(400, detail=f"task_precision above buyer maximum ({pmax})")

    escrow_min = float(settings.escrow_min_amount)
    escrow_max = float(settings.escrow_max_amount)
    if amount < escrow_min or amount > escrow_max:
        raise HTTPException(400, detail=f"amount must be between {escrow_min} and {escrow_max}")

    spec["amount"] = amount
    spec["bill_credit_amount"] = amount
    spec["task_precision"] = precision
    return spec


def requirement_fingerprint(
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    amount: float | None,
    task_type: str | None,
) -> str:
    payload = "|".join(
        [
            buyer_identity_id,
            seller_identity_id,
            hashlib.sha256(requirement_text.encode("utf-8")).hexdigest(),
            str(amount if amount is not None else ""),
            (task_type or "").strip(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
