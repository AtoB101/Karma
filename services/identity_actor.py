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

from api.middleware.auth import (
    resolve_actor_id_with_dev_fallback,
    resolve_agent_id_from_request,
)
from db.models.orm import AgentModel


async def resolve_actor_identity_id(db: AsyncSession, request: Request) -> str | None:
    # 2026-09-17 复核：这里原先只看 Authorization / API Key / 开发用的身份头，
    # **不认 Runtime Gateway 盖在 request.state 上的 actor** —— 于是任何从
    # /runtime/* 委托进来的写操作（网关已验过 Runtime Key）在归属校验里都拿不到
    # 身份，一律 403。``resolve_agent_id_from_request`` 正是那个认网关 actor 的口径，
    # 这里先走它，再回落到开发用的身份头。
    actor = resolve_agent_id_from_request(request) or resolve_actor_id_with_dev_fallback(request)
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
