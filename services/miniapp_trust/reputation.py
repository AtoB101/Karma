"""Execution history + reputation updates for MiniApp settle path."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any

from services.miniapp_registry import store as registry
from services.wash_trade import TradeEdge, evaluate_wash_signals


@dataclass
class ExecutionRecord:
    record_id: str
    order_id: str
    buyer_identity_id: str
    seller_identity_id: str | None
    agent_id: str | None
    amount_usdc: str
    status: str
    verification_run_id: str | None = None
    created_at: int = 0
    public_proof: dict = field(default_factory=dict)


_LOCK = Lock()
_HISTORY: list[ExecutionRecord] = []
_REP: dict[str, float] = {}  # identity_id -> score


def _amount(raw: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def record_settlement(
    *,
    order_id: str,
    buyer_identity_id: str,
    seller_identity_id: str | None,
    agent_id: str | None,
    amount_usdc: str,
    verification_run_id: str | None,
    public_proof: dict | None = None,
    buyer_wallet: str | None = None,
    seller_wallet: str | None = None,
) -> ExecutionRecord:
    proof = dict(public_proof or {})
    with _LOCK:
        edges = [
            TradeEdge(
                buyer_id=h.buyer_identity_id,
                seller_id=h.seller_identity_id or "",
                amount=_amount(h.amount_usdc),
                at=datetime.utcfromtimestamp(h.created_at),
            )
            for h in _HISTORY
        ]
    verdict = evaluate_wash_signals(
        buyer_id=buyer_identity_id,
        seller_id=seller_identity_id,
        amount=_amount(amount_usdc),
        history=edges,
        buyer_wallet=buyer_wallet,
        seller_wallet=seller_wallet,
    )
    proof["wash"] = verdict.to_dict()
    rec = ExecutionRecord(
        record_id="exe_" + secrets.token_hex(6),
        order_id=order_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        agent_id=agent_id,
        amount_usdc=str(amount_usdc),
        status="SETTLED",
        verification_run_id=verification_run_id,
        created_at=int(time.time()),
        public_proof=proof,
    )
    with _LOCK:
        _HISTORY.append(rec)
        if verdict.credit:
            for iid, delta in ((buyer_identity_id, 1.0), (seller_identity_id, 2.0)):
                if not iid:
                    continue
                _REP[iid] = float(_REP.get(iid, 50.0) + delta)
    if verdict.credit and agent_id:
        registry.bump_agent_reputation(agent_id, delta=2.0, settled=True)
    return rec


def reputation_of(identity_id: str) -> dict[str, Any]:
    with _LOCK:
        score = _REP.get(identity_id, 50.0)
        hist = [h for h in _HISTORY if identity_id in (h.buyer_identity_id, h.seller_identity_id)]
    return {
        "identity_id": identity_id,
        "reputation_score": score,
        "settled_count": len([h for h in hist if h.status == "SETTLED"]),
        "recent": [
            {
                "order_id": h.order_id,
                "amount_usdc": h.amount_usdc,
                "status": h.status,
                "at": h.created_at,
                "public_proof": h.public_proof,
            }
            for h in hist[-10:]
        ],
    }


def list_history(*, identity_id: str | None = None, limit: int = 50) -> list[ExecutionRecord]:
    with _LOCK:
        vals = list(_HISTORY)
    if identity_id:
        vals = [h for h in vals if identity_id in (h.buyer_identity_id, h.seller_identity_id)]
    return vals[-limit:]


def reset_for_tests() -> None:
    with _LOCK:
        _HISTORY.clear()
        _REP.clear()
