"""
Settlement party authorization — shared by settlement and progress routes.

When ``settlement_require_party_actor`` and ``auth_enforce_protected_routes`` are both enabled,
mutations must be performed by the correct economic party (buyer = ``client_agent_id``,
worker = ``worker_agent_id``) to prevent cross-tenant rule abuse.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from api.middleware.auth import resolve_agent_id_from_request
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import SettlementState
from services.actor_guards import caller_actor_id, caller_is_privileged


def party_binding_active() -> bool:
    return bool(settings.settlement_require_party_actor and settings.auth_enforce_protected_routes)


def resolve_actor(request: Request) -> str | None:
    """调用者身份。

    ``resolve_agent_id_from_request`` 只认 Authorization / API Key，**不认**未强制
    鉴权环境下用来声明身份的开发头（``X-Karma-Identity-Id``）。读权限闸门需要
    那个口径 —— 否则本地/联调时「声明了自己是谁」的第三方反而被当成匿名放行。
    写入侧的 ``require_*`` 只在强制鉴权时生效，所以这里放宽不会削弱写路径。
    """
    return caller_actor_id(request) or resolve_agent_id_from_request(request)


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


async def actor_identity_ids(db: AsyncSession, request: Request) -> set[str]:
    """调用者可能对应的全部 id。

    同一个调用者会因为凭证不同落在两个命名空间里：API key / JWT 给的是 **agent**
    维度，而结算的 ``client_agent_id`` / ``worker_agent_id`` 用的是 **身份**（kid_）
    维度。两者都要认，否则「用 API key 读自己那单」会被误判成第三方。
    """
    from services.identity_actor import resolve_actor_identity_id

    ids: set[str] = set()
    raw = caller_actor_id(request)
    if raw:
        ids.add(raw)
    mapped = await resolve_actor_identity_id(db, request)
    if mapped:
        ids.add(mapped)
    return ids


async def require_party_read(
    db: AsyncSession,
    request: Request,
    party_ids: set[str],
    *,
    public_read: bool,
) -> None:
    """当事人才能读的交易明细（P1-7）。

    2026-09-17 复核实测：k2 能读到 k1 的合同（对手方、金额、标题、完整需求描述）
    与结算流转（含争议理由），而这两样都属于交易内部信息。

    口径（**故意与写路径不同**，避免把本地开发/公开市场读流打挂）：

    * ``public_read`` 打开时完全放行（产品决策要「公开可审计」时用这个开关）；
    * 调用者未表明身份时放行 —— 生产环境里 ``auth_enforce_protected_routes``
      已经在中间件层把匿名挡掉了，这里不重复判 401；
    * 调用者身份明确时：必须是当事人本人或平台运维岗，否则 403。
    """
    if public_read:
        return
    ids = await actor_identity_ids(db, request)
    if not ids:
        return
    if ids & {i for i in party_ids if i}:
        return
    if caller_is_privileged(request):
        return
    raise HTTPException(
        403,
        "only the buyer, the assigned worker, or platform operations may read this record",
    )
