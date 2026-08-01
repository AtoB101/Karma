"""Intent → discover agents/merchants in Karma (assistant orchestration entrypoint)."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentModel, IdentityProfileModel
from db.session import get_db
from services.intent_discovery import (
    build_discovery_plan,
    parse_intent_for_discovery,
    rank_candidates,
)

router = APIRouter()


class DiscoverIntentRequest(BaseModel):
    requirement_text: str = Field(min_length=1, max_length=32000)
    buyer_identity_id: str | None = None
    amount: float | None = Field(default=None, gt=0)
    limit: int = Field(default=10, ge=1, le=50)
    # Optional external A2A registry; empty → skip
    registry_url: str | None = None
    include_local_agents: bool = True
    include_did_projections: bool = True


def _agent_row_to_card(row: AgentModel) -> dict[str, Any]:
    return {
        "agent_id": row.agent_id,
        "name": row.name,
        "description": f"Karma {row.role} agent",
        "capabilities": row.capabilities or [],
        "skills": [{"id": c, "name": c} for c in (row.capabilities or [])],
        "endpoint": row.endpoint_url,
        "karma": {
            "supports_voucher": True,
            "supports_evidence": True,
            "accepted_tokens": ["USDC"],
        },
        "_source": "karma_agents",
    }


def _identity_to_card(row: IdentityProfileModel) -> dict[str, Any]:
    return {
        "agent_id": row.identity_id,
        "name": row.display_id,
        "description": "DID-projected identity (merchant/worker)",
        "capabilities": ["karma_settle"],
        "skills": [],
        "endpoint": None,
        "karma": {
            "supports_voucher": True,
            "did_agent_address": row.did_agent_address,
            "on_chain_did": row.on_chain_did,
            "accepted_tokens": ["USDC"],
        },
        "_source": "identity_projection",
    }


async def _fetch_registry_cards(registry_url: str, capabilities: list[str], limit: int) -> list[dict]:
    try:
        params = {"limit": limit, "capabilities": ",".join(capabilities)}
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{registry_url.rstrip('/')}/api/agents", params=params)
            if not resp.is_success:
                return []
            data = resp.json()
            cards = data if isinstance(data, list) else data.get("agents", [])
            for c in cards:
                c["_source"] = "a2a_registry"
            return cards
    except httpx.HTTPError:
        return []


@router.post("/intent")
async def discover_for_intent(
    body: DiscoverIntentRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Assistant entrypoint: understand user requirement → find Karma agents/merchants.

    Returns ranked candidates + a trade_launch_hint so the assistant can continue into
    A2A negotiate → voucher → evidence → settle without the user naming a seller.
    """
    try:
        query = parse_intent_for_discovery(body.requirement_text, amount=body.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    cards: list[dict[str, Any]] = []

    if body.include_local_agents:
        result = await db.execute(select(AgentModel).where(AgentModel.is_active == True))  # noqa: E712
        for row in result.scalars().all():
            cards.append(_agent_row_to_card(row))

    if body.include_did_projections:
        result = await db.execute(
            select(IdentityProfileModel).where(
                IdentityProfileModel.status == "active",
                IdentityProfileModel.projection_readonly == True,  # noqa: E712
            )
        )
        for row in result.scalars().all():
            cards.append(_identity_to_card(row))

    import os
    registry_url = (body.registry_url or "").strip() or os.getenv("A2A_REGISTRY_URL", "")
    if registry_url:
        cards.extend(await _fetch_registry_cards(registry_url, query.capabilities, body.limit * 2))

    # Dedupe by agent_id
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in cards:
        aid = str(c.get("agent_id") or "")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        unique.append(c)

    ranked = rank_candidates(unique, query, limit=body.limit)
    plan = build_discovery_plan(
        query=query,
        candidates=ranked,
        buyer_identity_id=body.buyer_identity_id,
    )
    return plan
