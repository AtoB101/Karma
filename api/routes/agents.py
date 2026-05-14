"""Karma API — Agents"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import register_rate_limit

from core.schemas import AgentIdentity, AgentRole
from db.session import get_db
from db.models.orm import AgentModel
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


@router.post("", response_model=AgentIdentity, status_code=201)
async def register_agent(
    body: RegisterAgentRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_rate_limit),
):
    agent = AgentIdentity(
        name=body.name,
        role=body.role,
        public_key=signing_service.get_public_key_b64(),
        endpoint_url=body.endpoint_url,
        capabilities=body.capabilities,
    )
    db.add(AgentModel(
        agent_id=agent.agent_id,
        name=agent.name,
        role=agent.role.value,
        public_key=agent.public_key,
        endpoint_url=agent.endpoint_url,
        capabilities=agent.capabilities,
        registered_at=agent.registered_at,
    ))
    return agent


@router.get("/{agent_id}", response_model=AgentIdentity)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
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


@router.get("", response_model=list[AgentIdentity])
async def list_agents(
    role: AgentRole | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(AgentModel).where(AgentModel.is_active == True)
    if role:
        q = q.where(AgentModel.role == role.value)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        AgentIdentity(
            agent_id=r.agent_id,
            name=r.name,
            role=AgentRole(r.role),
            public_key=r.public_key,
            endpoint_url=r.endpoint_url,
            capabilities=r.capabilities or [],
            registered_at=r.registered_at,
            is_active=r.is_active,
        )
        for r in rows
    ]
