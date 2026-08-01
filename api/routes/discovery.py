"""Intent → discover agents/merchants in Karma (assistant orchestration entrypoint)."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import AgentModel, IdentityProfileModel
from db.session import get_db
from services.agent_directory import agent_row_to_card, ensure_directory_merchants
from services.agent_trust import apply_trust_rerank
from services.discovery_priority import (
    get_scene_priority_policy,
    ranking_metadata,
    resolve_scene_id,
)
from services.intent_discovery import (
    build_discovery_plan,
    parse_intent_for_discovery,
    rank_candidates,
)


def _demo_merchants_default() -> bool:
    env = (settings.app_env or "").lower()
    return env in ("development", "dev", "local", "test")

router = APIRouter()

_DEMO_MERCHANTS = [
    {
        "agent_id": "merchant-food-demo",
        "name": "Demo Food Merchant",
        "capabilities": ["order_food", "karma_settle"],
        "endpoint": "",
    },
    {
        "agent_id": "merchant-flight-demo",
        "name": "Demo Flight Merchant",
        "capabilities": ["book_flight", "karma_settle"],
        "endpoint": "",
    },
    {
        "agent_id": "merchant-hotel-demo",
        "name": "Demo Hotel Merchant",
        "capabilities": ["book_hotel", "karma_settle"],
        "endpoint": "",
    },
    {
        "agent_id": "merchant-data-demo",
        "name": "Demo Data Worker",
        "capabilities": [
            "data_processing",
            "karma_settle",
            "api.translate",
            "api.caption",
            "api.labeling",
        ],
        "endpoint": "",
    },
]


class DiscoverIntentRequest(BaseModel):
    requirement_text: str = Field(min_length=1, max_length=32000)
    buyer_identity_id: str | None = None
    amount: float | None = Field(default=None, gt=0)
    limit: int = Field(default=10, ge=1, le=50)
    registry_url: str | None = None
    include_local_agents: bool = True
    include_did_projections: bool = True
    include_demo_merchants: bool | None = None  # default: only in dev/test
    require_p1_ready: bool | None = None  # default: scene policy / False
    require_scene_coverage: bool | None = None  # default: scene policy
    apply_trust_ranking: bool = True
    enforce_scene_policy: bool | None = None  # default: True for high-risk / B2B scenes
    drop_ineligible: bool | None = None  # default: follow enforce_scene_policy
    scene_id: str | None = None  # optional override; must match intent-inferred when set


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
    Discover agents that can solve the requirement, ranked by P3 priority:
    P1 readiness → boundary complete → scene coverage → verifiable trust tier → score.
    """
    try:
        query = parse_intent_for_discovery(body.requirement_text, amount=body.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    inferred_scene = query.scene_id
    if body.scene_id and body.scene_id.strip() and body.scene_id.strip() != inferred_scene:
        raise HTTPException(
            400,
            f"scene_id '{body.scene_id}' does not match intent-inferred scene '{inferred_scene}'",
        )
    scene_id = resolve_scene_id(scene_id=body.scene_id, task_type=query.task_type)
    query.scene_id = scene_id
    scene_policy = get_scene_priority_policy(scene_id)

    # Scene-aware defaults: high-risk / B2B enforce policy; daily commerce soft-prefer
    enforce_default = bool(
        scene_policy.get("high_risk")
        or scene_policy.get("require_p1_ready")
        or scene_policy.get("require_boundary_complete")
    )
    enforce_scene_policy = (
        enforce_default if body.enforce_scene_policy is None else bool(body.enforce_scene_policy)
    )
    drop_ineligible = (
        enforce_scene_policy if body.drop_ineligible is None else bool(body.drop_ineligible)
    )
    require_p1 = (
        bool(scene_policy.get("require_p1_ready"))
        if body.require_p1_ready is None
        else bool(body.require_p1_ready)
    )

    cards: list[dict[str, Any]] = []
    include_demo = (
        _demo_merchants_default() if body.include_demo_merchants is None else body.include_demo_merchants
    )

    if include_demo:
        await ensure_directory_merchants(db, _DEMO_MERCHANTS)

    if body.include_local_agents:
        result = await db.execute(select(AgentModel).where(AgentModel.is_active == True))  # noqa: E712
        for row in result.scalars().all():
            cards.append(agent_row_to_card(row))

    if body.include_did_projections and not require_p1:
        # DID-only projections lack service_specs — exclude when requiring P1
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

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in cards:
        aid = str(c.get("agent_id") or "")
        if not aid or aid in seen:
            continue
        if require_p1 and not c.get("p1_ready"):
            # Buyers (identity_class=user) may still appear; filter seller-like
            ic = c.get("identity_class")
            if ic in {None, "merchant", "enterprise"} or "karma_settle" in (c.get("capabilities") or []):
                if ic != "user":
                    continue
        seen.add(aid)
        unique.append(c)

    ranked = rank_candidates(unique, query, limit=max(body.limit * 3, 30))
    if body.apply_trust_ranking:
        ranked = await apply_trust_rerank(
            db,
            ranked,
            limit=body.limit,
            scene_id=scene_id,
            task_type=query.task_type,
            drop_ineligible=drop_ineligible,
            enforce_scene_policy=enforce_scene_policy,
        )
    else:
        ranked = ranked[: body.limit]

    plan = build_discovery_plan(
        query=query,
        candidates=ranked,
        buyer_identity_id=body.buyer_identity_id,
    )
    meta = ranking_metadata(
        scene_id=scene_id,
        apply_priority=body.apply_trust_ranking,
        enforce_scene_policy=enforce_scene_policy,
        require_p1_ready=require_p1,
        drop_ineligible=drop_ineligible,
    )
    meta["include_demo_merchants"] = include_demo
    if body.require_scene_coverage is True:
        meta["scene_policy"]["require_scene_coverage"] = True
    plan["ranking"] = meta
    await db.commit()
    return plan
