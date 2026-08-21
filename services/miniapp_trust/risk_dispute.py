"""MiniApp risk + dispute helpers (Sprint 7 remaining)."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class RiskAssessment:
    assessment_id: str
    order_id: str
    score: float  # 0..100 higher = riskier
    flags: list[str] = field(default_factory=list)
    hold: bool = False
    created_at: int = 0


@dataclass
class DisputeCase:
    dispute_id: str
    order_id: str
    opened_by: str
    reason: str
    status: str = "open"  # open|resolved|rejected
    resolution: dict = field(default_factory=dict)
    created_at: int = 0


_LOCK = Lock()
_RISK: dict[str, RiskAssessment] = {}
_DISPUTES: dict[str, DisputeCase] = {}


def assess_risk(*, order_id: str, intent: dict, evidence: dict | None = None, self_deal: bool = False) -> RiskAssessment:
    flags: list[str] = []
    score = 0.0
    scene = (intent or {}).get("scene_id") or (intent or {}).get("category") or ""
    if scene == "high_risk":
        flags.append("high_risk_scene")
        score += 40
    if self_deal:
        flags.append("self_deal")
        score += 50
    amount = float((intent or {}).get("amount_usdc") or (evidence or {}).get("amount_usdc") or 0)
    if amount >= 1000:
        flags.append("high_amount")
        score += 20
    if evidence and evidence.get("merchant_self_only"):
        flags.append("merchant_self_only")
        score += 30
    hold = score >= 50 or "high_risk_scene" in flags and amount >= 300
    a = RiskAssessment(
        assessment_id="risk_" + secrets.token_hex(6),
        order_id=order_id,
        score=score,
        flags=flags,
        hold=hold,
        created_at=int(time.time()),
    )
    with _LOCK:
        _RISK[order_id] = a
    return a


def open_dispute(*, order_id: str, opened_by: str, reason: str) -> DisputeCase:
    d = DisputeCase(
        dispute_id="dsp_" + secrets.token_hex(6),
        order_id=order_id,
        opened_by=opened_by,
        reason=reason,
        created_at=int(time.time()),
    )
    with _LOCK:
        _DISPUTES[d.dispute_id] = d
    return d


def resolve_dispute(dispute_id: str, *, resolution: dict) -> DisputeCase:
    with _LOCK:
        d = _DISPUTES[dispute_id]
        d.status = "resolved"
        d.resolution = dict(resolution)
        return d


def latest_risk(order_id: str) -> RiskAssessment | None:
    with _LOCK:
        return _RISK.get(order_id)


def list_disputes(order_id: str | None = None) -> list[DisputeCase]:
    with _LOCK:
        vals = list(_DISPUTES.values())
        if order_id:
            vals = [d for d in vals if d.order_id == order_id]
        return vals


def reset_for_tests() -> None:
    with _LOCK:
        _RISK.clear()
        _DISPUTES.clear()
