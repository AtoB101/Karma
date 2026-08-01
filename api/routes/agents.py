"""Karma API — Agents"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import register_agent_rate_limit

from core.schemas import AgentIdentity, AgentRole
from db.session import get_db
from db.models.orm import AgentModel
from services.agent_directory import connect_agent
from services.agent_trust import ensure_reputation_row, load_trust_stats_batch
from services.signing import signing_service
from services.text_safety import validate_safe_storage_text, validate_safe_storage_text_optional

router = APIRouter()


class RegisterAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    role: AgentRole
    endpoint_url: str | None = Field(default=None, max_length=2048)
    capabilities: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="name")

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def _safe_endpoint(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="endpoint_url")

    @field_validator("capabilities")
    @classmethod
    def _capability_item_length(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 128:
                raise ValueError("each capability string must be at most 128 characters")
            validate_safe_storage_text(item, field="capabilities[]")
        return v


class ConnectAgentRequest(BaseModel):
    """Upsert path: agent connects to Karma ⇒ immediately discoverable."""
    agent_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    role: AgentRole = AgentRole.WORKER
    endpoint_url: str | None = Field(default=None, max_length=2048)
    capabilities: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="name")

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def _safe_endpoint(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="endpoint_url")

    @field_validator("capabilities")
    @classmethod
    def _capability_item_length(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 128:
                raise ValueError("each capability string must be at most 128 characters")
            validate_safe_storage_text(item, field="capabilities[]")
        return v


def _to_identity(row: AgentModel) -> AgentIdentity:
    return AgentIdentity(
        agent_id=row.agent_id,
        name=row.name,
        role=AgentRole(row.role),
        public_key=row.public_key,
        endpoint_url=row.endpoint_url,
        capabilities=row.capabilities or [],
        registered_at=row.registered_at,
        is_active=row.is_active,
    )


@router.post("/connect", response_model=AgentIdentity)
async def connect_agent_route(
    body: ConnectAgentRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_agent_rate_limit),
):
    """
    Connect (upsert) an agent into the Karma directory.

    After this call, other agents can discover it via /v1/discovery/intent and
    rank it by reputation / settlement history.
    """
    row = await connect_agent(
        db,
        agent_id=body.agent_id,
        name=body.name,
        role=body.role.value,
        endpoint_url=body.endpoint_url,
        capabilities=body.capabilities,
    )
    await db.commit()
    return _to_identity(row)


@router.post("", response_model=AgentIdentity, status_code=201)
async def register_agent(
    body: RegisterAgentRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_agent_rate_limit),
):
    row = await connect_agent(
        db,
        name=body.name,
        role=body.role.value,
        endpoint_url=body.endpoint_url,
        capabilities=body.capabilities,
        public_key=signing_service.get_public_key_b64(),
    )
    await db.commit()
    return _to_identity(row)


@router.get("/{agent_id}", response_model=AgentIdentity)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return _to_identity(row)


@router.get("/{agent_id}/trust")
async def get_agent_trust(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Reputation + settlement volume used by discovery ranking."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    await ensure_reputation_row(db, agent_id, role="client" if row.role == "client" else "worker")
    stats = await load_trust_stats_batch(db, [agent_id])
    return {
        "agent_id": agent_id,
        "agent": _to_identity(row),
        "trust": (stats.get(agent_id).to_dict() if stats.get(agent_id) else {}),
    }


@router.get("", response_model=list[AgentIdentity])
async def list_agents(
    role: AgentRole | None = None,
    capability: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(AgentModel).where(AgentModel.is_active == True)  # noqa: E712
    if role:
        q = q.where(AgentModel.role == role.value)
    result = await db.execute(q)
    rows = result.scalars().all()
    out = [_to_identity(r) for r in rows]
    if capability:
        cap = capability.lower()
        out = [a for a in out if any(str(c).lower() == cap for c in (a.capabilities or []))]
    return out
