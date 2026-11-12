"""
Settlement party authorization — shared by settlement and progress routes.

When ``settlement_require_party_actor`` and ``auth_enforce_protected_routes`` are both enabled,
mutations must be performed by the correct economic party (buyer = ``client_agent_id``,
worker = ``worker_agent_id``) to prevent cross-tenant rule abuse.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from api.middleware.auth import resolve_agent_id_from_auth_headers
from config.settings import settings
from core.schemas import SettlementState


def party_binding_active() -> bool:
    return bool(settings.settlement_require_party_actor and settings.auth_enforce_protected_routes)


def resolve_actor(request: Request) -> str | None:
    return resolve_agent_id_from_auth_headers(
        authorization=request.headers.get("authorization"),
        api_key=request.headers.get("x-karma-api-key"),
    )


def require_actor(request: Request) -> str:
    actor = resolve_actor(request)
    if not actor:
        raise HTTPException(401, "authentication required for this operation")
    return actor


def require_buyer(request: Request, state: SettlementState) -> None:
    if not party_binding_active():
        return
    actor = require_actor(request)
    if actor != state.client_agent_id:
        raise HTTPException(403, "only the settlement buyer may perform this action")


def require_worker(request: Request, state: SettlementState) -> None:
    if not party_binding_active():
        return
    actor = require_actor(request)
    if not state.worker_agent_id:
        raise HTTPException(409, "settlement has no assigned worker")
    if actor != state.worker_agent_id:
        raise HTTPException(403, "only the assigned worker may perform this action")


def require_buyer_or_worker(request: Request, state: SettlementState) -> None:
    if not party_binding_active():
        return
    actor = require_actor(request)
    allowed = {state.client_agent_id}
    if state.worker_agent_id:
        allowed.add(state.worker_agent_id)
    if actor not in allowed:
        raise HTTPException(403, "only the settlement buyer or assigned worker may perform this action")


def require_buyer_on_create(request: Request, client_agent_id: str) -> None:
    if not party_binding_active():
        return
    actor = require_actor(request)
    if actor != client_agent_id:
        raise HTTPException(403, "authenticated actor must match client_agent_id when creating settlement")


def require_actor_matches_identity(request: Request, identity_id: str) -> None:
    """Bind the caller to an asserted agent id (e.g. progress seller_identity_id)."""
    if not party_binding_active():
        return
    actor = require_actor(request)
    if actor != identity_id:
        raise HTTPException(
            403,
            "authenticated actor must match the asserted identity for this operation",
        )
