"""Identity card is the start of the reputation ledger (user / merchant / enterprise)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentModel, ReputationModel
from services.agent_trust import ensure_reputation_row
from services.reputation_pack import evaluate_pack_eligibility

LEDGER_META_SOURCE = "identity_card_ledger"
STUB_PUBLIC_KEY = "identity-card-ledger"


def role_for_identity_class(identity_class: str | None) -> str:
    cls = (identity_class or "user").strip().lower()
    if cls in {"user", "client", "buyer"}:
        return "client"
    return "worker"


def _stub_name(identity_id: str, identity_class: str | None) -> str:
    cls = (identity_class or "user").strip().lower() or "user"
    tail = identity_id[-8:] if len(identity_id) > 8 else identity_id
    return f"karma-{cls}-{tail}"


async def open_identity_ledger(
    db: AsyncSession,
    identity_id: str,
    *,
    identity_class: str | None = None,
) -> ReputationModel:
    """Open (or reuse) the reputation book the moment a Karma identity exists.

    Reputation rows FK to ``agents``, so a directory stub is created when needed.
    Existing agents/scores are never reset.
    """
    iid = (identity_id or "").strip()
    if not iid:
        raise ValueError("identity_id required")
    role = role_for_identity_class(identity_class)
    agent = await db.get(AgentModel, iid)
    if agent is None:
        agent = AgentModel(
            agent_id=iid,
            name=_stub_name(iid, identity_class),
            role=role,
            public_key=STUB_PUBLIC_KEY,
            endpoint_url=None,
            capabilities=["karma_settle"] if role == "worker" else [],
            is_active=True,
            registered_at=datetime.utcnow(),
            identity_class=(identity_class or "user"),
            owner_identity_id=iid,
            p1_ready=False,
            onboarding_meta={"source": LEDGER_META_SOURCE},
        )
        db.add(agent)
        await db.flush()
    else:
        if identity_class and not agent.identity_class:
            agent.identity_class = identity_class
        if not agent.owner_identity_id:
            agent.owner_identity_id = iid
        await db.flush()
    return await ensure_reputation_row(db, iid, role=role)


def reputation_card_view(row: ReputationModel) -> dict[str, Any]:
    elig = evaluate_pack_eligibility(
        score=float(row.score or 0),
        successful_tasks=int(row.successful_tasks or 0),
        disputed_tasks=int(row.disputed_tasks or 0),
        last_incident_at=row.last_incident_at,
        last_incident_kind=row.last_incident_kind,
        wash_trade_flags=int(row.wash_trade_flags or 0),
    )
    return {
        "agent_id": row.agent_id,
        "profile_id": row.profile_id,
        "score": float(row.score or 0),
        "role": row.role,
        "total_tasks": int(row.total_tasks or 0),
        "successful_tasks": int(row.successful_tasks or 0),
        "disputed_tasks": int(row.disputed_tasks or 0),
        "wash_trade_flags": int(row.wash_trade_flags or 0),
        "pack_eligible": elig.eligible,
        "pack_path": elig.path,
        "dividend_eligible_offchain": elig.dividend_eligible_offchain,
        "fee_waiver": False,
        "ledger_opened": True,
        "note_zh": (
            "领取 Karma 身份卡即开立信誉账本；成交、违约、刷量都记在这本账上，"
            "达标可打包上链。不减免交易手续费。"
        ),
    }


async def attach_card_reputation(
    db: AsyncSession,
    card: dict[str, Any],
    *,
    identity_id: str,
    identity_class: str | None = None,
) -> dict[str, Any]:
    row = await open_identity_ledger(
        db,
        identity_id,
        identity_class=identity_class or card.get("identity_class"),
    )
    out = dict(card)
    out["reputation"] = reputation_card_view(row)
    return out


async def ensure_profile_reputation(
    db: AsyncSession,
    *,
    profile_id: str,
    owner_identity_id: str,
    identity_class: str | None = None,
) -> ReputationModel:
    """Open a per-profile reputation book (每个身份的独立历史/成功率/违约)."""
    pid = (profile_id or "").strip()
    if not pid:
        raise ValueError("profile_id required")
    role = role_for_identity_class(identity_class)
    agent = await db.get(AgentModel, pid)
    if agent is None:
        agent = AgentModel(
            agent_id=pid,
            name=_stub_name(pid, identity_class),
            role=role,
            public_key=STUB_PUBLIC_KEY,
            endpoint_url=None,
            capabilities=["karma_settle"] if role == "worker" else [],
            is_active=True,
            registered_at=datetime.utcnow(),
            identity_class=(identity_class or "user"),
            owner_identity_id=owner_identity_id,
            p1_ready=False,
            onboarding_meta={"source": "profile_reputation"},
        )
        db.add(agent)
        await db.flush()
    row = await ensure_reputation_row(db, pid, role=role)
    if row.profile_id != pid:
        row.profile_id = pid
        await db.flush()
    return row


async def attach_profile_reputation(
    db: AsyncSession,
    profile: dict[str, Any],
) -> dict[str, Any]:
    row = await ensure_profile_reputation(
        db,
        profile_id=profile["profile_id"],
        owner_identity_id=profile.get("owner_identity_id", ""),
        identity_class=profile.get("class"),
    )
    out = dict(profile)
    out["reputation"] = reputation_card_view(row)
    return out


async def record_profile_settlement_outcome(
    db: AsyncSession,
    *,
    profile_id: str,
    owner_identity_id: str,
    identity_class: str | None = None,
    success: bool = True,
    disputed: bool = False,
    volume: float = 0.0,
) -> ReputationModel | None:
    """最后一环：结算后把成交/违约回写到该档案的声誉账本。"""
    pid = (profile_id or "").strip()
    if not pid:
        return None
    row = await ensure_profile_reputation(
        db,
        profile_id=pid,
        owner_identity_id=owner_identity_id,
        identity_class=identity_class,
    )
    row.total_tasks = int(row.total_tasks or 0) + 1
    if disputed:
        row.disputed_tasks = int(row.disputed_tasks or 0) + 1
        row.consecutive_successes = 0
        row.score = max(0.0, float(row.score or 0) - 15.0)
        row.last_incident_at = datetime.utcnow()
        row.last_incident_kind = "dispute"
    elif success:
        row.successful_tasks = int(row.successful_tasks or 0) + 1
        row.consecutive_successes = int(row.consecutive_successes or 0) + 1
        bump = 5.0 + min(max(volume, 0.0), 100.0) * 0.05
        row.score = min(1000.0, float(row.score or 0) + bump)
    else:
        row.consecutive_successes = 0
        row.score = max(0.0, float(row.score or 0) - 8.0)
        row.last_incident_at = datetime.utcnow()
        row.last_incident_kind = "default"
    row.last_updated = datetime.utcnow()
    await db.flush()
    return row
