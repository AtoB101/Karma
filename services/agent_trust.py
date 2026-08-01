"""Trust signals for Karma agent discovery ranking.

After capability match, prefer agents with higher reputation, success rate,
settlement volume, and fewer disputes. User reviews are not a first-class table
yet — successful settlements proxy “好评”.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import ReputationModel, SettlementModel


SUCCESS_STATUSES = ("settled", "partially_settled")
DISPUTE_STATUSES = ("disputed",)


@dataclass
class AgentTrustStats:
    agent_id: str
    reputation_score: float = 100.0
    total_tasks: int = 0
    successful_tasks: int = 0
    disputed_tasks: int = 0
    success_rate: float = 0.5
    settled_count: int = 0
    settled_volume: float = 0.0
    dispute_rate: float = 0.0
    cold_start: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "reputation_score": round(self.reputation_score, 3),
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "disputed_tasks": self.disputed_tasks,
            "success_rate": round(self.success_rate, 4),
            "settled_count": self.settled_count,
            "settled_volume": round(self.settled_volume, 4),
            "dispute_rate": round(self.dispute_rate, 4),
            "cold_start": self.cold_start,
            # “好评” proxy until a reviews table exists
            "positive_feedback_proxy": round(self.success_rate * max(self.settled_count, 0), 4),
        }


def compute_trust_bonus(stats: AgentTrustStats) -> tuple[float, list[str]]:
    """Additive bonus used after capability match. Higher is better."""
    reasons: list[str] = []
    # Normalize reputation.score (cold start 100; strong agents grow)
    rep_norm = min(max(stats.reputation_score, 0.0) / 200.0, 1.5)  # 200 → 1.0
    bonus = 4.0 * rep_norm
    reasons.append(f"reputation:{stats.reputation_score:.1f}")

    sr = stats.success_rate if stats.total_tasks or stats.settled_count else 0.5
    bonus += 3.5 * sr
    reasons.append(f"success_rate:{sr:.2f}")

    vol_term = math.log1p(stats.settled_count) * 1.2 + math.log1p(stats.settled_volume) * 0.15
    bonus += min(vol_term, 4.0)
    if stats.settled_count:
        reasons.append(f"settled_count:{stats.settled_count}")
    if stats.settled_volume:
        reasons.append(f"settled_volume:{stats.settled_volume:.2f}")

    if stats.dispute_rate > 0:
        penalty = min(stats.dispute_rate * 6.0, 4.0)
        bonus -= penalty
        reasons.append(f"dispute_penalty:{penalty:.2f}")

    if stats.cold_start:
        bonus -= 0.5  # slight preference for proven agents
        reasons.append("cold_start")

    return round(bonus, 3), reasons


async def load_trust_stats_batch(
    db: AsyncSession,
    agent_ids: list[str],
) -> dict[str, AgentTrustStats]:
    ids = [a for a in agent_ids if a]
    out: dict[str, AgentTrustStats] = {i: AgentTrustStats(agent_id=i) for i in ids}
    if not ids:
        return out

    # Reputation table
    result = await db.execute(select(ReputationModel).where(ReputationModel.agent_id.in_(ids)))
    for row in result.scalars().all():
        sr = (row.successful_tasks / row.total_tasks) if row.total_tasks > 0 else 0.5
        dr = (row.disputed_tasks / row.total_tasks) if row.total_tasks > 0 else 0.0
        out[row.agent_id] = AgentTrustStats(
            agent_id=row.agent_id,
            reputation_score=float(row.score or 100.0),
            total_tasks=int(row.total_tasks or 0),
            successful_tasks=int(row.successful_tasks or 0),
            disputed_tasks=int(row.disputed_tasks or 0),
            success_rate=sr,
            dispute_rate=dr,
            cold_start=int(row.total_tasks or 0) == 0,
        )

    # Settlement aggregates as volume / fallback success
    settled = await db.execute(
        select(
            SettlementModel.worker_agent_id,
            func.count(SettlementModel.settlement_id),
            func.coalesce(func.sum(SettlementModel.released_amount), 0.0),
        )
        .where(
            SettlementModel.worker_agent_id.in_(ids),
            SettlementModel.status.in_(list(SUCCESS_STATUSES)),
        )
        .group_by(SettlementModel.worker_agent_id)
    )
    for worker_id, cnt, vol in settled.all():
        if not worker_id or worker_id not in out:
            continue
        st = out[worker_id]
        st.settled_count = int(cnt or 0)
        st.settled_volume = float(vol or 0.0)
        if st.cold_start and st.settled_count > 0:
            # Derive proxy reputation from settlements when reputation row missing/empty
            st.cold_start = False
            st.total_tasks = max(st.total_tasks, st.settled_count)
            st.successful_tasks = max(st.successful_tasks, st.settled_count)
            st.success_rate = st.successful_tasks / max(st.total_tasks, 1)

    disputed = await db.execute(
        select(
            SettlementModel.worker_agent_id,
            func.count(SettlementModel.settlement_id),
        )
        .where(
            SettlementModel.worker_agent_id.in_(ids),
            SettlementModel.status.in_(list(DISPUTE_STATUSES)),
        )
        .group_by(SettlementModel.worker_agent_id)
    )
    for worker_id, cnt in disputed.all():
        if not worker_id or worker_id not in out:
            continue
        st = out[worker_id]
        st.disputed_tasks = max(st.disputed_tasks, int(cnt or 0))
        denom = max(st.total_tasks, st.settled_count + st.disputed_tasks, 1)
        st.dispute_rate = st.disputed_tasks / denom

    return out


async def apply_trust_rerank(
    db: AsyncSession,
    candidates: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Rerank capability-matched candidates by trust (reputation × success × volume)."""
    if not candidates:
        return []
    ids = [str(c.get("agent_id") or "") for c in candidates]
    stats_map = await load_trust_stats_batch(db, ids)
    enriched: list[dict[str, Any]] = []
    for c in candidates:
        aid = str(c.get("agent_id") or "")
        stats = stats_map.get(aid) or AgentTrustStats(agent_id=aid)
        bonus, trust_reasons = compute_trust_bonus(stats)
        # Soft-penalize agents that have not published complete capability/confirm boundaries
        if c.get("boundary_complete") is False:
            bonus = round(bonus - 1.5, 3)
            trust_reasons = list(trust_reasons) + ["boundary_incomplete"]
        # P1 readiness: identity/owner/capability/responsibility verified against records
        if c.get("p1_ready") is True:
            bonus = round(bonus + 2.0, 3)
            trust_reasons = list(trust_reasons) + ["p1_ready"]
        elif c.get("p1_ready") is False:
            bonus = round(bonus - 2.0, 3)
            trust_reasons = list(trust_reasons) + ["p1_not_ready"]
        capability_score = float(c.get("score") or 0.0)
        final = round(capability_score + bonus, 3)
        item = dict(c)
        item["capability_score"] = capability_score
        item["trust_bonus"] = bonus
        item["trust"] = stats.to_dict()
        item["score"] = final
        item["match_reasons"] = list(c.get("match_reasons") or []) + trust_reasons
        enriched.append(item)
    enriched.sort(
        key=lambda x: (
            -float(x["score"]),
            -float((x.get("trust") or {}).get("settled_volume") or 0),
            -float((x.get("trust") or {}).get("reputation_score") or 0),
            x.get("agent_id") or "",
        )
    )
    if limit is not None:
        return enriched[:limit]
    return enriched


async def ensure_reputation_row(
    db: AsyncSession,
    agent_id: str,
    *,
    role: str = "worker",
) -> ReputationModel:
    row = await db.get(ReputationModel, agent_id)
    if row:
        return row
    row = ReputationModel(
        agent_id=agent_id,
        role=role,
        score=100.0,
        total_tasks=0,
        successful_tasks=0,
        disputed_tasks=0,
        last_updated=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


async def record_worker_settlement_outcome(
    db: AsyncSession,
    *,
    worker_agent_id: str,
    success: bool,
    disputed: bool = False,
    volume: float = 0.0,
) -> ReputationModel:
    """Update public reputation after a settlement outcome (好评/差评 proxy)."""
    row = await ensure_reputation_row(db, worker_agent_id, role="worker")
    row.total_tasks = int(row.total_tasks or 0) + 1
    if disputed:
        row.disputed_tasks = int(row.disputed_tasks or 0) + 1
        row.consecutive_successes = 0
        row.score = max(0.0, float(row.score) - 15.0)
    elif success:
        row.successful_tasks = int(row.successful_tasks or 0) + 1
        row.consecutive_successes = int(row.consecutive_successes or 0) + 1
        bump = 5.0 + min(max(volume, 0.0), 100.0) * 0.05
        row.score = min(1000.0, float(row.score) + bump)
    else:
        row.consecutive_successes = 0
        row.score = max(0.0, float(row.score) - 8.0)
    row.last_updated = datetime.utcnow()
    await db.flush()
    return row
