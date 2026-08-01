"""Karma agent directory — connect ⇒ immediately discoverable."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentModel
from services.agent_trust import ensure_reputation_row
from services.signing import signing_service


async def connect_agent(
    db: AsyncSession,
    *,
    agent_id: str | None = None,
    name: str,
    role: str,
    endpoint_url: str | None = None,
    capabilities: list[str] | None = None,
    public_key: str | None = None,
    profile_card: dict[str, Any] | None = None,
    agent_boundary: dict[str, Any] | None = None,
    ensure_boundary: bool = True,
) -> AgentModel:
    """
    Upsert an agent into the Karma directory.

    After connect, the agent appears in GET /v1/agents and discovery ranking.
    Initializes a cold-start reputation row so trust filters have a baseline.
    Always persists an agent boundary card (capability / responsibility /
    confirmation) so counterparties know what can be automated vs owner-confirmed.
    """
    caps = list(capabilities or [])
    # Settlement-capable agents should advertise karma_settle for discovery
    if role in {"worker", "seller", "merchant"} and "karma_settle" not in caps:
        caps.append("karma_settle")

    row: AgentModel | None = None
    if agent_id:
        row = await db.get(AgentModel, agent_id)

    if row is None:
        from core.schemas import AgentIdentity, AgentRole

        try:
            agent_role = AgentRole(role)
        except ValueError:
            agent_role = AgentRole.WORKER
        identity = AgentIdentity(
            name=name,
            role=agent_role,
            public_key=public_key or signing_service.get_public_key_b64(),
            endpoint_url=endpoint_url,
            capabilities=caps,
        )
        if agent_id:
            identity.agent_id = agent_id
        row = AgentModel(
            agent_id=identity.agent_id,
            name=identity.name,
            role=identity.role.value,
            public_key=identity.public_key,
            endpoint_url=identity.endpoint_url,
            capabilities=identity.capabilities,
            is_active=True,
            registered_at=identity.registered_at,
        )
        db.add(row)
    else:
        row.name = name or row.name
        if role:
            row.role = role
        if endpoint_url is not None:
            row.endpoint_url = endpoint_url
        existing = list(row.capabilities or [])
        for c in caps:
            if c not in existing:
                existing.append(c)
        row.capabilities = existing
        row.is_active = True
        if public_key:
            row.public_key = public_key

    await db.flush()
    await ensure_reputation_row(
        db,
        row.agent_id,
        role="client" if row.role == "client" else "worker",
    )
    if profile_card is not None:
        from services.agent_profile_store import save_profile_card

        save_profile_card(row.agent_id, profile_card)

    if agent_boundary is not None or ensure_boundary:
        from services.agent_boundary import (
            get_agent_boundary,
            materialize_agent_boundary,
            save_agent_boundary,
        )

        boundary = agent_boundary
        if boundary is None:
            # Keep a richer existing boundary if present; else build from caps/card
            existing_b = get_agent_boundary(row.agent_id)
            if existing_b and existing_b.get("boundary_complete") and profile_card is None:
                boundary = existing_b
            else:
                boundary = materialize_agent_boundary(
                    agent_id=row.agent_id,
                    name=row.name,
                    karma_role=row.role,
                    profile_id=(profile_card or {}).get("profile_id") if profile_card else None,
                    capabilities=list(row.capabilities or []),
                    scene_ids=list((profile_card or {}).get("industry_ids") or [])
                    if profile_card
                    else None,
                    profile_card=profile_card,
                    owner_identity_id=row.agent_id,
                )
        else:
            boundary = {**boundary, "agent_id": row.agent_id}
        save_agent_boundary(row.agent_id, boundary)
    return row


async def ensure_directory_merchants(
    db: AsyncSession,
    merchants: list[dict[str, Any]],
) -> list[AgentModel]:
    """Materialize demo/catalog merchants as real directory agents."""
    rows: list[AgentModel] = []
    for m in merchants:
        row = await connect_agent(
            db,
            agent_id=str(m["agent_id"]),
            name=str(m.get("name") or m["agent_id"]),
            role="worker",
            endpoint_url=m.get("endpoint") or m.get("endpoint_url"),
            capabilities=list(m.get("capabilities") or []),
        )
        rows.append(row)
    return rows


def agent_row_to_card(row: AgentModel) -> dict[str, Any]:
    from services.agent_boundary import boundary_digest, get_agent_boundary
    from services.agent_profile_store import get_profile_card

    boundary = get_agent_boundary(row.agent_id)
    digest = boundary_digest(boundary)
    profile = get_profile_card(row.agent_id)
    description = (
        (profile or {}).get("description")
        or (boundary or {}).get("capability_boundary", {}).get("capability_summary")
        or f"Karma {row.role} agent"
    )
    card: dict[str, Any] = {
        "agent_id": row.agent_id,
        "name": row.name,
        "description": description,
        "capabilities": row.capabilities or [],
        "skills": [{"id": c, "name": c} for c in (row.capabilities or [])],
        "endpoint": row.endpoint_url,
        "karma": {
            "supports_voucher": True,
            "supports_evidence": True,
            "accepted_tokens": ["USDC"],
        },
        "_source": "karma_directory",
        "is_active": bool(row.is_active),
        "registered_at": (row.registered_at or datetime.utcnow()).isoformat(),
    }
    if digest:
        card["boundary"] = digest
        card["scene_ids"] = digest.get("scene_ids") or []
        card["boundary_complete"] = digest.get("boundary_complete")
    return card
