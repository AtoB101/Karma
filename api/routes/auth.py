"""
Karma API — Auth Routes
Token issuance for agents.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import create_access_token, validate_api_key_for_agent
from api.middleware.rate_limit import register_rate_limit
from db.session import get_db
from db.models.orm import AgentModel

router = APIRouter()


class TokenRequest(BaseModel):
    agent_id: str
    api_key: str   # pre-issued static API key


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    agent_id: str


@router.post("/token", response_model=TokenResponse)
async def issue_token(
    body: TokenRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_rate_limit),
):
    """
    Exchange a static API key for a short-lived JWT.
    In production: verify api_key hash against DB record.
    """
    agent = await db.get(AgentModel, body.agent_id)
    if not agent or not agent.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not validate_api_key_for_agent(body.agent_id, body.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=body.agent_id)
    return TokenResponse(access_token=token, agent_id=body.agent_id)
