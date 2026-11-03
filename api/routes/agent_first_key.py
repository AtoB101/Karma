"""Public self-serve first-key router (unauthenticated by design)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_agent_id
from api.middleware.rate_limit import agent_pairing_rate_limit, real_client_ip
from db.session import get_db
from services import agent_first_key

router = APIRouter(prefix="/v1/agents/first-key", tags=["AgentFirstKey"])


class ChallengeBody(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)
    agent_name: str | None = Field(default=None, max_length=128)


class ClaimBody(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=128)
    challenge: str = Field(min_length=8, max_length=128)
    device_id: str = Field(min_length=8, max_length=128)


@router.post("/challenge", status_code=201)
async def first_key_challenge(
    body: ChallengeBody,
    request: Request,
    _rl: None = Depends(agent_pairing_rate_limit),
):
    """Issue a one-time challenge bound to the caller's device and address."""
    return agent_first_key.issue_challenge(
        device_id=body.device_id,
        ip=real_client_ip(request),
        agent_name=body.agent_name,
    )


@router.post("/claim")
async def first_key_claim(
    body: ClaimBody,
    request: Request,
    _rl: None = Depends(agent_pairing_rate_limit),
):
    """Consume the one-time challenge and mint a restricted first key (once)."""
    return agent_first_key.claim(
        challenge_id=body.challenge_id,
        challenge=body.challenge,
        device_id=body.device_id,
        ip=real_client_ip(request),
    )


@router.get("/status/{challenge_id}")
async def first_key_status(challenge_id: str):
    """Read-only status for a pending challenge (never leaks the challenge)."""
    return agent_first_key.public_view(challenge_id)


@router.post("/upgrade")
async def first_key_upgrade(
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(get_current_agent_id),
    _rl: None = Depends(agent_pairing_rate_limit),
):
    """Exchange a restricted first key for full scope, while an active grant exists."""
    return await agent_first_key.upgrade(db, agent_id=actor)
