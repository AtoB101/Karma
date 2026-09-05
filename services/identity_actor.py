"""Resolve the acting identity for role-profile ownership checks.

Bridges the two identity namespaces in Karma:
- identity namespace — ``owner_identity_id`` on ``IdentityRoleProfile``, the
  SIWE / wallet-derived karma identity id the card belongs to;
- agent namespace — the ``agent_id`` from an API key / JWT ``sub``, mapped to
  its owning identity via ``AgentModel.owner_identity_id`` (P1 onboarding).

In dev (auth enforcement off) the ``X-Karma-Identity-Id`` header supplies the
identity directly; in production the API key / JWT supplies the agent id, which
this helper resolves back to the identity id.
"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import resolve_actor_id_with_dev_fallback
from db.models.orm import AgentModel


async def resolve_actor_identity_id(db: AsyncSession, request: Request) -> str | None:
    actor = resolve_actor_id_with_dev_fallback(request)
    if not actor:
        return None
    actor = actor.strip()
    if not actor:
        return None
    # agent namespace → identity namespace
    agent = await db.get(AgentModel, actor)
    if agent is not None and agent.owner_identity_id:
        return agent.owner_identity_id.strip()
    # already identity namespace (dev header / wallet / identity id)
    return actor
