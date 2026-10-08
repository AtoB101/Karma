"""Identity ownership binding — 谁能对某个身份档案 / 凭证 / 额度动手。

背景（2026-10-08 边界盘点）：``/v1/identities/*``、``/v1/identity/{id}/credentials`` 与
``/v1/identity/{id}/class``、``GET /v1/capacity/{id}`` 此前只要求「已登录」，``identity_id``
取自路径、无人校验 —— 任何登录身份都能改**别人**的自动化资金边界、代他人签发 / 吊销凭证、
改身份类别、读他人额度。

与 ``services/ledger_party_access`` / ``services/settlement_party_access`` 同一套路：
``identity_require_owner_binding`` 与 ``auth_enforce_protected_routes`` 同时为真时才强制，
否则保持本地开发 / 联调可用（生产两条都是 fail-closed 必须为真）。

强制时，调用者必须落在该身份的**任一命名空间**里（agent→owner_identity 映射后的身份，
或原始 actor id），或者属于平台运维岗（``ADMIN_ACTOR_IDS``）。
"""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from services.actor_guards import admin_actor_ids, caller_actor_id
from services.identity_actor import resolve_actor_identity_id


def identity_owner_binding_active() -> bool:
    return bool(settings.identity_require_owner_binding and settings.auth_enforce_protected_routes)


async def require_identity_owner(
    db: AsyncSession,
    request: Request,
    identity_id: str,
    *,
    what: str = "this identity",
    also_ids: Iterable[str] = (),
) -> None:
    """调用者必须是该身份本人，或平台运维岗；否则 403。

    ``also_ids`` 允许同时认一串等价 id（例如 DID 投影的 agent 地址），
    避免「同一个主体的两种写法」被误判成第三方。
    """
    if not identity_owner_binding_active():
        return
    target = (identity_id or "").strip()
    resolved = await resolve_actor_identity_id(db, request)
    raw = caller_actor_id(request)
    candidates = {target} | {str(x).strip() for x in also_ids if x}
    candidates.discard("")
    for actor in (resolved, raw):
        if actor and actor.strip() in candidates:
            return
    if raw and raw.strip() in admin_actor_ids():
        return
    raise HTTPException(403, "only the owner of %s may perform this action" % what)
