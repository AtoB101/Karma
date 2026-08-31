"""Detect wash volume and fake settles so they cannot farm reputation or pack-to-chain."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import SettlementModel

_SUCCESS = ("settled", "partially_settled")


@dataclass
class TradeEdge:
    buyer_id: str
    seller_id: str
    amount: float
    at: datetime | None = None
    buyer_wallet: str | None = None
    seller_wallet: str | None = None


@dataclass
class WashVerdict:
    credit: bool
    flags_delta: int
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit": self.credit,
            "flags_delta": self.flags_delta,
            "signals": list(self.signals),
        }


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _in_window(edge: TradeEdge, *, now: datetime, window: timedelta) -> bool:
    if edge.at is None:
        return True
    at = edge.at.replace(tzinfo=None) if edge.at.tzinfo else edge.at
    return (now - at) <= window


def evaluate_wash_signals(
    *,
    buyer_id: str | None,
    seller_id: str | None,
    amount: float,
    history: Iterable[TradeEdge] = (),
    buyer_wallet: str | None = None,
    seller_wallet: str | None = None,
    now: datetime | None = None,
) -> WashVerdict:
    """Heuristic v1: self-deal, same wallet, dust, A↔B ping-pong, pair spam, burst."""
    now = now or datetime.utcnow()
    pair_window = timedelta(hours=int(settings.reputation_wash_pair_window_hours))
    burst_window = timedelta(minutes=int(settings.reputation_wash_burst_window_minutes))
    min_amt = float(settings.reputation_wash_min_amount)
    pair_max = int(settings.reputation_wash_pair_max)
    burst_max = int(settings.reputation_wash_burst_max)

    buyer = _norm(buyer_id)
    seller = _norm(seller_id)
    bw = _norm(buyer_wallet)
    sw = _norm(seller_wallet)
    rows = list(history)
    signals: list[str] = []
    flags = 0
    deny_credit = False

    if buyer and seller and buyer == seller:
        signals.append("self_deal")
        deny_credit = True
        flags = max(flags, 2)
    if bw and sw and bw == sw:
        signals.append("same_wallet")
        deny_credit = True
        flags = max(flags, 2)

    if float(amount) < min_amt:
        signals.append("dust")
        deny_credit = True

    pair_n = 1
    reverse_n = 0
    burst_n = 1
    if seller:
        for edge in rows:
            if _in_window(edge, now=now, window=burst_window) and _norm(edge.seller_id) == seller:
                burst_n += 1
            if not _in_window(edge, now=now, window=pair_window):
                continue
            eb, es = _norm(edge.buyer_id), _norm(edge.seller_id)
            if buyer and eb == buyer and es == seller:
                pair_n += 1
            if buyer and eb == seller and es == buyer:
                reverse_n += 1

    if reverse_n >= 1:
        signals.append("circular")
        deny_credit = True
        flags = max(flags, 1)
    if pair_n >= pair_max:
        signals.append("pair_velocity")
        deny_credit = True
        flags = max(flags, 1)
    if burst_n >= burst_max:
        signals.append("burst")
        deny_credit = True
        flags = max(flags, 1)
    if "dust" in signals and pair_n >= 2:
        flags = max(flags, 1)

    return WashVerdict(credit=not deny_credit, flags_delta=flags, signals=signals)


async def load_recent_edges(
    db: AsyncSession,
    *,
    buyer_id: str | None,
    seller_id: str | None,
    exclude_task_id: str | None = None,
    now: datetime | None = None,
) -> list[TradeEdge]:
    now = now or datetime.utcnow()
    hours = int(settings.reputation_wash_pair_window_hours)
    burst_h = max(1, int(settings.reputation_wash_burst_window_minutes) // 60 + 1)
    since = now - timedelta(hours=max(hours, burst_h))
    clauses = [
        SettlementModel.status.in_(list(_SUCCESS)),
        SettlementModel.created_at >= since,
    ]
    party = []
    if seller_id:
        party.append(SettlementModel.worker_agent_id == seller_id)
    if buyer_id and seller_id:
        party.append(
            (SettlementModel.worker_agent_id == buyer_id)
            & (SettlementModel.client_agent_id == seller_id)
        )
    if party:
        clauses.append(or_(*party))
    else:
        return []
    if exclude_task_id:
        clauses.append(SettlementModel.task_id != exclude_task_id)
    result = await db.execute(select(SettlementModel).where(*clauses))
    out: list[TradeEdge] = []
    for row in result.scalars().all():
        amt = float(row.released_amount if row.released_amount is not None else row.escrow_amount or 0)
        out.append(
            TradeEdge(
                buyer_id=str(row.client_agent_id or ""),
                seller_id=str(row.worker_agent_id or ""),
                amount=amt,
                at=row.created_at,
            )
        )
    return out


async def inspect_settlement_wash(
    db: AsyncSession,
    *,
    buyer_id: str | None,
    seller_id: str | None,
    amount: float,
    exclude_task_id: str | None = None,
    buyer_wallet: str | None = None,
    seller_wallet: str | None = None,
) -> WashVerdict:
    history = await load_recent_edges(
        db, buyer_id=buyer_id, seller_id=seller_id, exclude_task_id=exclude_task_id
    )
    return evaluate_wash_signals(
        buyer_id=buyer_id,
        seller_id=seller_id,
        amount=amount,
        history=history,
        buyer_wallet=buyer_wallet,
        seller_wallet=seller_wallet,
    )
