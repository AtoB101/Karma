"""Karma API — Reputation (public read + pack-to-chain)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import make_rate_limit_dep
from api.routes.admin_controls import require_admin_actor
from core.schemas import AgentRole, ReputationSnapshot
from db.models.orm import ReputationModel
from db.session import get_db
from services.reputation_pack import (
    KIND_DEFAULT,
    KIND_DISPUTE,
    KIND_FRAUD,
    KIND_WASH,
    dividend_points_for_pack,
    evaluate_pack_eligibility,
    evidence_hash,
    score_to_e2,
)

router = APIRouter()


class PackReputationBody(BaseModel):
    wallet_address: str
    submit_on_chain: bool = False


class SlashReputationBody(BaseModel):
    wallet_address: str
    kind: str = Field(default=KIND_DEFAULT)
    submit_on_chain: bool = False


def _elig_payload(agent_id: str, row: ReputationModel) -> dict:
    elig = evaluate_pack_eligibility(
        score=float(row.score or 0),
        successful_tasks=int(row.successful_tasks or 0),
        disputed_tasks=int(row.disputed_tasks or 0),
        last_incident_at=row.last_incident_at,
        last_incident_kind=row.last_incident_kind,
        wash_trade_flags=int(row.wash_trade_flags or 0),
    )
    digest = evidence_hash(
        agent_id=agent_id,
        score=float(row.score or 0),
        successful_tasks=int(row.successful_tasks or 0),
        disputed_tasks=int(row.disputed_tasks or 0),
        last_incident_at=row.last_incident_at,
        last_incident_kind=row.last_incident_kind,
    )
    return {
        "agent_id": agent_id,
        "onchain_packed_at": row.onchain_packed_at.isoformat() if row.onchain_packed_at else None,
        "onchain_packed_score": row.onchain_packed_score,
        "dividend_weight": float(row.dividend_weight or 0),
        "evidence_hash": digest,
        "score_e2": score_to_e2(float(row.score or 0)),
        "wash_trade_flags": int(row.wash_trade_flags or 0),
        **elig.to_dict(),
    }


@router.get("/{agent_id}/pack-eligibility")
async def get_pack_eligibility(agent_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(ReputationModel, agent_id)
    if not row:
        raise HTTPException(404, f"No reputation record for agent {agent_id}")
    return _elig_payload(agent_id, row)


@router.get("/{agent_id}/rewards")
async def get_reputation_rewards(agent_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(ReputationModel, agent_id)
    if not row:
        raise HTTPException(404, f"No reputation record for agent {agent_id}")
    elig = evaluate_pack_eligibility(
        score=float(row.score or 0),
        successful_tasks=int(row.successful_tasks or 0),
        disputed_tasks=int(row.disputed_tasks or 0),
        last_incident_at=row.last_incident_at,
        last_incident_kind=row.last_incident_kind,
        wash_trade_flags=int(row.wash_trade_flags or 0),
    )
    return {
        "agent_id": agent_id,
        "dividend_weight": float(row.dividend_weight or 0),
        "fee_waiver": False,
        "dividend_eligible": elig.dividend_eligible_offchain and bool(row.onchain_packed_at),
        "wash_trade_flags": int(row.wash_trade_flags or 0),
        "note_zh": "高信誉获得平台分红权重，不减免交易手续费。",
    }


@router.post("/{agent_id}/slash", dependencies=[Depends(make_rate_limit_dep("write_sensitive"))])
async def slash_reputation(
    agent_id: str,
    body: SlashReputationBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_actor),
):
    """Mark default/fraud/dispute. Freeze dividend until 90-day same-class rehab. No fee change."""
    row = await db.get(ReputationModel, agent_id)
    if not row:
        raise HTTPException(404, f"No reputation record for agent {agent_id}")
    kind = (body.kind or KIND_DEFAULT).strip().lower()
    if kind not in {KIND_DEFAULT, KIND_DISPUTE, KIND_FRAUD, KIND_WASH}:
        raise HTTPException(400, "kind must be dispute, default, fraud, or wash")
    row.last_incident_at = datetime.utcnow()
    row.last_incident_kind = kind
    if kind == KIND_DISPUTE:
        row.disputed_tasks = int(row.disputed_tasks or 0) + 1
        row.score = max(0.0, float(row.score or 0) - 15.0)
    elif kind == KIND_WASH:
        row.wash_trade_flags = int(row.wash_trade_flags or 0) + 1
        row.score = max(0.0, float(row.score or 0) - 8.0)
    else:
        row.score = max(0.0, float(row.score or 0) - 8.0)
    row.consecutive_successes = 0
    row.last_updated = datetime.utcnow()

    tx_hash = None
    if body.submit_on_chain and row.onchain_packed_at:
        try:
            from services.chain.reputation_adapter import submit_slash

            tx_hash = submit_slash(
                wallet=body.wallet_address,
                score_e2=score_to_e2(float(row.score or 0)),
                kind=kind,
            )
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=502, detail=f"on-chain slash failed: {exc}") from exc
    await db.flush()
    return {
        "agent_id": agent_id,
        "slashed": True,
        "kind": kind,
        "score": float(row.score or 0),
        "rehab_days": 90,
        "tx_hash": tx_hash,
        "fee_waiver": False,
        "note_zh": "违约/欺诈降分；90 天内不再出现同类问题且积分回阈值后可再次打包上链。不减免手续费。",
    }


@router.post("/{agent_id}/pack", dependencies=[Depends(make_rate_limit_dep("write_sensitive"))])
async def pack_reputation(
    agent_id: str,
    body: PackReputationBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_actor),
):
    """Anchor eligible off-chain score. Does not waive Bilateral fees."""
    row = await db.get(ReputationModel, agent_id)
    if not row:
        raise HTTPException(404, f"No reputation record for agent {agent_id}")
    payload = _elig_payload(agent_id, row)
    if not payload["eligible"]:
        raise HTTPException(status_code=409, detail={"reason": "not_eligible", **payload})

    tx_hash = None
    if body.submit_on_chain:
        try:
            from services.chain.reputation_adapter import submit_pack

            tx_hash = submit_pack(
                wallet=body.wallet_address,
                score_e2=int(payload["score_e2"]),
                success_count=int(row.successful_tasks or 0),
                evidence_hash=str(payload["evidence_hash"]),
            )
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=502, detail=f"on-chain pack failed: {exc}") from exc

    row.onchain_packed_at = datetime.utcnow()
    row.onchain_packed_score = float(row.score or 0)
    row.onchain_pack_tx = tx_hash
    pts = dividend_points_for_pack(float(row.score or 0))
    if pts:
        row.dividend_weight = float(row.dividend_weight or 0) + pts
    await db.flush()
    return {
        "agent_id": agent_id,
        "packed": True,
        "path": payload["path"],
        "score": row.onchain_packed_score,
        "evidence_hash": payload["evidence_hash"],
        "tx_hash": tx_hash,
        "dividend_weight": float(row.dividend_weight or 0),
        "fee_waiver": False,
    }


@router.get("/{agent_id}", response_model=ReputationSnapshot)
async def get_reputation(agent_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(ReputationModel, agent_id)
    if not row:
        raise HTTPException(404, f"No reputation record for agent {agent_id}")
    return _from_row(row)


@router.get("", response_model=list[ReputationSnapshot])
async def leaderboard(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ReputationModel).order_by(desc(ReputationModel.score)).limit(limit)
    )
    return [_from_row(r) for r in result.scalars().all()]


def _from_row(row: ReputationModel) -> ReputationSnapshot:
    success_rate = (
        row.successful_tasks / row.total_tasks if row.total_tasks > 0 else 0.0
    )
    return ReputationSnapshot(
        agent_id=row.agent_id,
        role=AgentRole(row.role),
        score=row.score,
        total_tasks=row.total_tasks,
        successful_tasks=row.successful_tasks,
        disputed_tasks=row.disputed_tasks,
        success_rate=success_rate,
        last_updated=row.last_updated,
    )
