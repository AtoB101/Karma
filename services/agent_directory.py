"""Karma agent directory — connect ⇒ immediately discoverable (P1-hardened)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentModel
from services.agent_trust import ensure_reputation_row
from services.signing import signing_service


class AgentConnectError(ValueError):
    pass


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
    identity_class: str | None = None,
    owner_identity_id: str | None = None,
    onboarding_meta: dict[str, Any] | None = None,
    responsibility_acknowledged: bool = False,
    allow_hijack: bool = False,
) -> AgentModel:
    """
    Upsert an agent into the Karma directory with P1 identity/owner binding.

    Anti-forgery: existing agent_id cannot be overwritten by a different
    owner_identity_id unless ``allow_hijack`` (tests only).
    """
    caps = list(capabilities or [])
    if role in {"worker", "seller", "merchant"} and "karma_settle" not in caps:
        caps.append("karma_settle")

    row: AgentModel | None = None
    if agent_id:
        row = await db.get(AgentModel, agent_id)

    if row is not None and not allow_hijack:
        stored_owner = (getattr(row, "owner_identity_id", None) or "").strip() or None
        incoming_owner = (owner_identity_id or "").strip() or None
        if stored_owner:
            if not incoming_owner:
                raise HTTPException(
                    403,
                    f"agent_id '{row.agent_id}' is owned; owner_identity_id required to update",
                )
            if incoming_owner != stored_owner:
                raise HTTPException(
                    403,
                    f"agent_id '{row.agent_id}' is bound to another owner_identity_id (anti-hijack)",
                )

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
            identity_class=identity_class,
            owner_identity_id=owner_identity_id,
            onboarding_meta=dict(onboarding_meta or {}),
            p1_ready=False,
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
        if identity_class:
            row.identity_class = identity_class
        if owner_identity_id:
            row.owner_identity_id = owner_identity_id
        if onboarding_meta is not None:
            merged = dict(row.onboarding_meta or {})
            merged.update(onboarding_meta)
            row.onboarding_meta = merged

    owner_for_boundary = row.owner_identity_id or owner_identity_id or row.agent_id

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
        from services.agent_p1_readiness import boundary_content_hash

        profile_id = identity_class or (
            (profile_card or {}).get("profile_id") if profile_card else None
        )
        if agent_boundary is not None and profile_card is None and not agent_boundary.get(
            "capability_boundary"
        ):
            boundary = materialize_agent_boundary(
                agent_id=row.agent_id,
                name=row.name,
                karma_role=row.role,
                profile_id=profile_id,
                capabilities=list(row.capabilities or []),
                owner_identity_id=owner_for_boundary,
                responsibility_acknowledged=responsibility_acknowledged,
            )
        elif agent_boundary is not None:
            boundary = materialize_agent_boundary(
                agent_id=row.agent_id,
                name=row.name,
                karma_role=row.role,
                profile_id=agent_boundary.get("profile_id") or profile_id,
                capabilities=list(
                    (agent_boundary.get("capability_boundary") or {}).get("capabilities")
                    or row.capabilities
                    or []
                ),
                scene_ids=list(agent_boundary.get("scene_ids") or []),
                profile_card=profile_card
                or {
                    "profile_id": agent_boundary.get("profile_id"),
                    "industry_ids": agent_boundary.get("scene_ids") or [],
                    "service_specs": (agent_boundary.get("capability_boundary") or {}).get(
                        "service_specs"
                    )
                    or {},
                    "boundaries": (agent_boundary.get("capability_boundary") or {}).get("do_not")
                    or "",
                    "compliance_flags": (agent_boundary.get("responsibility_boundary") or {}).get(
                        "compliance_flags"
                    )
                    or {},
                },
                owner_identity_id=owner_for_boundary,
                responsibility_acknowledged=responsibility_acknowledged,
            )
        else:
            existing_b = get_agent_boundary(row.agent_id)
            if (
                existing_b
                and existing_b.get("boundary_complete")
                and profile_card is None
                and not identity_class
            ):
                boundary = existing_b
            else:
                boundary = materialize_agent_boundary(
                    agent_id=row.agent_id,
                    name=row.name,
                    karma_role=row.role,
                    profile_id=profile_id or (
                        (profile_card or {}).get("profile_id") if profile_card else None
                    ),
                    capabilities=list(row.capabilities or []),
                    scene_ids=list((profile_card or {}).get("industry_ids") or [])
                    if profile_card
                    else None,
                    profile_card=profile_card,
                    owner_identity_id=owner_for_boundary,
                    responsibility_acknowledged=responsibility_acknowledged,
                )
        save_agent_boundary(row.agent_id, boundary)
        bhash = boundary_content_hash(boundary)
        row.boundary_hash = bhash
        meta = dict(row.onboarding_meta or {})
        meta["boundary_hash"] = bhash
        meta["owner_identity_id"] = owner_for_boundary
        if identity_class:
            meta["identity_class"] = identity_class
        row.onboarding_meta = meta

    await db.flush()
    return row


async def refresh_p1_ready(db: AsyncSession, agent_id: str) -> dict[str, Any]:
    """Re-evaluate P1 against records and persist ``p1_ready`` on the agent row."""
    from services.agent_p1_readiness import evaluate_p1_readiness

    status = await evaluate_p1_readiness(db, agent_id)
    row = await db.get(AgentModel, agent_id)
    if row:
        row.p1_ready = bool(status.get("p1_ready"))
        if status.get("boundary_hash"):
            row.boundary_hash = status["boundary_hash"]
        await db.flush()
    return status


async def ensure_directory_merchants(
    db: AsyncSession,
    merchants: list[dict[str, Any]],
) -> list[AgentModel]:
    """Materialize demo/catalog merchants as real directory agents (not P1-ready)."""
    rows: list[AgentModel] = []
    for m in merchants:
        row = await connect_agent(
            db,
            agent_id=str(m["agent_id"]),
            name=str(m.get("name") or m["agent_id"]),
            role="worker",
            endpoint_url=m.get("endpoint") or m.get("endpoint_url"),
            capabilities=list(m.get("capabilities") or []),
            identity_class=None,
            responsibility_acknowledged=False,
            allow_hijack=True,
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
        "identity_class": getattr(row, "identity_class", None),
        "owner_identity_id": getattr(row, "owner_identity_id", None),
        "p1_ready": bool(getattr(row, "p1_ready", False)),
        "boundary_hash": getattr(row, "boundary_hash", None),
    }
    if digest:
        card["boundary"] = digest
        card["scene_ids"] = digest.get("scene_ids") or []
        card["boundary_complete"] = digest.get("boundary_complete")
    return card
