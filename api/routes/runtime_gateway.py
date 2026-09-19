"""
Runtime Gateway — public standard paths for Agent SDK + Console.

Mounted at ``/runtime`` (not under ``/v1``) per the public Runtime API contract.
"""
from __future__ import annotations

import functools
from datetime import datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.bundles import submit_bundle as submit_bundle_route
from api.routes.discovery import DiscoverIntentRequest, discover_for_intent
from api.routes.progress import submit_progress_receipt as progress_submit_route
from api.routes.settlement import (
    PartialSettlementRequest,
    buyer_accept_settlement,
    partial_settlement,
    submit_settlement,
)
from api.routes.vouchers import (
    CreateVoucherRequest,
    VerifyVoucherRequest,
    create_voucher as vouchers_create_route,
    verify_voucher as vouchers_verify_route,
)
from config.settings import settings
from core.schemas import (
    EvidenceBundle,
    ExecutionReceipt,
    ProgressReceipt,
)
from db.models.orm import ProgressReceiptModel, RuntimeKeyModel, SettlementModel, VoucherModel
from db.session import get_db
from db.stores.receipt_store import PostgresReceiptStore
from db.stores.settlement_store import PostgresSettlementStore
from services.agent_automation_policy import get_automation_policy
from services.console_notice import (
    NOTICE_KEY_BOUND,
    NOTICE_KEY_UNBOUND,
    ack_notices,
    add_notice,
    list_notices,
    notice_view,
    unread_notice_count,
)
from services.identity_actor import resolve_actor_identity_id
from services.intent_fulfillment import fulfill_intent
from services.path_param_safety import validate_public_url_segment
from services.profile_capacity import (
    get_allocations,
    get_profile_capacity,
    master_ceiling_usdc,
    serialize_profile_capacity,
)
from services.receipt_canonical import evidence_bundle_signing_bytes
from services.receipt_guard import (
    execution_receipt_starts_before_prior_ended,
    validate_execution_receipt_static,
    verify_execution_receipt_signature,
)
from services.receipt_templates import validate_extension_vs_task_type
from services.task_contract_guard import ensure_task_contract_exists
from services.runtime_key_service import (
    MAX_KEY_LIFETIME_DAYS,
    PENDING_KEY_BINDING,
    PublicKeyError,
    RuntimeKeyContext,
    agent_binding_fingerprint,
    assert_permission,
    BIND_CODE_TTL_SECONDS,
    binding_scope,
    check_replay_nonce,
    check_single_and_daily_limits,
    confirm_key_binding,
    create_runtime_key_record,
    display_activation_code,
    hash_binding_scope,
    list_bound_runtime_keys,
    list_runtime_keys_for_identity,
    load_active_context,
    normalize_activation_code,
    pending_activation_block,
    pending_binding_view,
    reject_key_binding,
    request_key_binding,
    revoke_runtime_key,
    unbind_key_binding,
    verify_signed_request,
)
from services.runtime_response_sign import signed_json_response
from services.runtime_synthetic_request import synthetic_request
from services.runtime_wallet import (
    build_confirm_bind_message,
    build_create_key_message,
    build_list_bind_requests_message,
    build_list_keys_message,
    build_reject_bind_message,
    build_revoke_key_message,
    build_unbind_key_message,
    verify_personal_message,
)
from services.identity_wallet_binding import ensure_wallet_authorized_for_runtime_key
from services.openclaw_automation_readiness import (
    assert_task_automation_ready,
    resolve_task_id_for_voucher,
)
from services.runtime_call_log import call_view, list_key_calls, record_key_call
from services.runtime_daily_spend import get_daily_used_async, record_daily_spend_async
from services.signing import signing_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Agent 动作端的调用留痕（操作台「已绑定钥匙」展开后的「最近调用」）
# ---------------------------------------------------------------------------


def _body_amount(body: object) -> float | None:
    """从请求体里抠金额 —— 只为展示，抠不到就是 None，不参与任何校验。"""
    if body is None:
        return None
    candidate = getattr(body, "amount", None)
    if candidate is None:
        voucher = getattr(body, "voucher", None)
        candidate = getattr(voucher, "amount", None) if voucher is not None else None
    try:
        return float(candidate) if candidate is not None else None
    except (TypeError, ValueError):
        return None


def _detail_text(detail: object) -> str:
    return str(detail or "")[:200]


def _action_name(request: Request) -> str:
    """只给动作端留痕：读路径一律返回空串，调用方据此跳过。"""
    url = getattr(request, "url", None)
    path = str(getattr(url, "path", "") or "")
    if path not in LOGGED_ACTION_PATHS:
        return ""
    return path.rsplit("/", 1)[-1]


async def _log_call_safe(
    db: AsyncSession | None,
    ctx: RuntimeKeyContext | None,
    *,
    endpoint: str,
    outcome: str,
    http_status: int,
    amount: float | None = None,
    detail: str = "",
    rollback_first: bool = False,
) -> None:
    """旁路写一笔调用记录。写不进日志是日志的事，不能连累 agent 的请求。"""
    if db is None or ctx is None or not endpoint:
        return
    try:
        if rollback_first:
            # 失败路径上会话里可能留着半截写入，先丢掉再记 —— 否则这一提交会把
            # 本该回滚的东西一起落库。
            await db.rollback()
        await record_key_call(
            db,
            key_id=ctx.key_id,
            karma_identity_id=ctx.karma_identity_id,
            endpoint=endpoint,
            outcome=outcome,
            http_status=http_status,
            amount=amount,
            detail=detail,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - 留痕是旁路，吞掉
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


def runtime_call_logged(endpoint: str):
    """给动作端记一笔「哪把钥匙、什么时候、做了什么、结果如何」。

    成功 / 被拒 / 异常三类都记：主人展开「最近调用」最想确认的恰恰是「有没有被拒、
    为什么被拒」—— 只记成功等于把最有价值的一半藏起来。
    装饰器写在 ``@router.post`` 下一行：路由注册的是包过一层之后的函数。
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            db = kwargs.get("db")
            ctx = kwargs.get("ctx")
            amount = _body_amount(kwargs.get("body"))
            try:
                out = await fn(*args, **kwargs)
            except HTTPException as exc:
                await _log_call_safe(
                    db,
                    ctx,
                    endpoint=endpoint,
                    outcome="rejected",
                    http_status=int(exc.status_code),
                    amount=amount,
                    detail=_detail_text(exc.detail),
                    rollback_first=True,
                )
                raise
            except Exception as exc:  # noqa: BLE001 - 记一笔再往上抛
                await _log_call_safe(
                    db,
                    ctx,
                    endpoint=endpoint,
                    outcome="failed",
                    http_status=500,
                    amount=amount,
                    detail=type(exc).__name__,
                    rollback_first=True,
                )
                raise
            await _log_call_safe(
                db,
                ctx,
                endpoint=endpoint,
                outcome="ok",
                http_status=int(getattr(out, "status_code", 200) or 200),
                amount=amount,
            )
            return out

        return wrapper

    return decorator


async def _session_owned_identity(db: AsyncSession, request: Request, claimed: str) -> str:
    """会话必须是本人：没登录 403，替别人查也 403。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(
            status_code=403, detail="authentication required: connect a wallet first"
        )
    identity = str(claimed or "").strip()
    if identity and identity != actor:
        raise HTTPException(
            status_code=403, detail="karma_identity_id does not match the authenticated identity"
        )
    return actor


async def _notice_safe(
    db: AsyncSession, *, karma_identity_id: str, kind: str, payload: dict
) -> None:
    """站内提醒是旁路：写不进去也不能让用户看到「动作失败」。"""
    try:
        await add_notice(db, karma_identity_id=karma_identity_id, kind=kind, payload=payload)
        await db.commit()
    except Exception:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


def _utc_iso() -> str:
    """毫秒级 UTC 时间戳，给 agent 判断数据新鲜度用。"""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _binding_receipt(row: RuntimeKeyModel, agent_id: str) -> dict:
    """绑定生效后的平台签收回执 —— agent 自己也能验证「绑的确实是我」。

    agent 拿 binding_scope 原文 + 平台公钥就能验：绑定范围是平台背书的，
    不是它自己嘴上说的。没这个回执，agent 没法证明自己真的绑上了。
    """
    scope = binding_scope(
        key_id=row.key_id,
        karma_identity_id=row.karma_identity_id,
        agent_id=agent_id,
    )
    return {
        "binding_scope": scope,
        "binding_scope_fingerprint": hash_binding_scope(scope),
        "binding_scope_signature": signing_service.sign_bytes(scope.encode("utf-8")),
        "service_public_key": signing_service.get_public_key_b64(),
        "required_headers": [
            "X-Karma-Runtime-Key",
            "X-Karma-Agent-Signature",
            "X-Karma-Runtime-Timestamp",
            "X-Karma-Runtime-Nonce",
        ],
    }


# ---------------------------------------------------------------------------
# Wallet-bound Console operations (no Runtime Key yet)
# ---------------------------------------------------------------------------


class CreateRuntimeKeyBody(BaseModel):
    wallet_address: str
    karma_identity_id: str
    wallet_signature: str
    permissions: list[str]
    single_limit: float = Field(gt=0)
    daily_limit: float = Field(gt=0)
    expire_time: datetime
    agent_name: str
    agent_binding: Optional[str] = None
    # agent 自己声明的 id（操作台铸造时提交）。它必须与 agent_binding 一致 ——
    # agent_binding 是写进钱包签名消息的那个字段，两个不一致就等于用户没授权过这个 agent。
    agent_id: Optional[str] = None
    profile_id: Optional[str] = None


@router.post("/create-key")
async def runtime_create_key(body: CreateRuntimeKeyBody, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("karma_identity_id", body.karma_identity_id)
    agent_id = (body.agent_id or "").strip() or None
    bound_agent = (body.agent_binding or "").strip() or None
    if agent_id and not bound_agent:
        raise HTTPException(
            status_code=400,
            detail="agent_id requires agent_binding (agent_binding is the wallet-signed field)",
        )
    if agent_id and bound_agent and agent_id != bound_agent:
        # 同一个东西写了两个值，说明调用方拼错了 —— 在铸造前就失败，
        # 别铸出一把「声明与授权对象不一致」的钥匙。
        raise HTTPException(status_code=403, detail="agent_id must match agent_binding")
    if body.profile_id:
        validate_public_url_segment("profile_id", body.profile_id)
    msg = build_create_key_message(
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
        permissions=body.permissions,
        single_limit=body.single_limit,
        daily_limit=body.daily_limit,
        expire_time=body.expire_time,
        agent_name=body.agent_name,
        agent_binding=body.agent_binding,
    )
    verify_personal_message(
        message=msg,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    from config.settings import settings
    from services.agent_automation_policy import assert_runtime_key_matches_policy, get_automation_policy

    if settings.runtime_require_saved_automation_policy:
        policy = await get_automation_policy(db, body.karma_identity_id)
        if not policy:
            raise HTTPException(
                status_code=403,
                detail="automation policy not saved — configure fund limits and permissions in Console first",
            )
        assert_runtime_key_matches_policy(
            policy=policy,
            permissions=body.permissions,
            single_limit=body.single_limit,
            daily_limit=body.daily_limit,
        )
    await ensure_wallet_authorized_for_runtime_key(
        db,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
    )
    token, row = await create_runtime_key_record(
        db=db,
        wallet_address=body.wallet_address,
        karma_identity_id=body.karma_identity_id,
        profile_id=body.profile_id,
        permissions=body.permissions,
        single_limit=body.single_limit,
        daily_limit=body.daily_limit,
        expire_at=body.expire_time,
        agent_name=body.agent_name,
        agent_binding=body.agent_binding,
    )
    await db.commit()
    # 绑定声明是给 agent 的回执：告诉它这把 key 到底授权给谁。
    # 服务端用平台 Ed25519 私钥签名，agent 侧拿 service_public_key 就能核对。
    effective_agent_id = (body.agent_id or "").strip() or (row.agent_binding or "")
    scope = ""
    scope_signature = ""
    if effective_agent_id:
        scope = binding_scope(
            key_id=row.key_id,
            karma_identity_id=row.karma_identity_id,
            agent_id=effective_agent_id,
        )
        scope_signature = signing_service.sign_bytes(scope.encode("utf-8"))
    return signed_json_response(
        {
            "runtime_key": token,
            "key_id": row.key_id,
            "permissions": row.permissions,
            "expire_time": row.expire_at.isoformat(),
            "status": row.status,
            "agent_binding": row.agent_binding,
            "key_binding": row.key_binding,
            "nonce_required": row.nonce_required,
            "max_key_lifetime_days": MAX_KEY_LIFETIME_DAYS,
            "activation_required": bool(
                (row.key_binding or "") == PENDING_KEY_BINDING and not row.agent_public_key
            ),
            # 时间只作用在匹配码上：agent 申请那一刻起 3 分钟内要输码完成激活。
            "activation_code_ttl_seconds": BIND_CODE_TTL_SECONDS,
            "binding_scope": scope,
            "binding_scope_fingerprint": hash_binding_scope(scope) if scope else "",
            "binding_scope_signature": scope_signature,
            "service_public_key": signing_service.get_public_key_b64(),
            "next_step": (
                "agent 用 POST /runtime/bind-key 绑定自己的 Ed25519 公钥，"
                "主人拿匹配码在操作台确认（码 3 分钟内有效）；"
                "激活之前这把钥匙的付款类调用一律 403"
                if effective_agent_id
                else "未指定 agent：这把 key 走服务端托管路径（认 key 不认人）"
            ),
        },
        status_code=201,
    )


class RevokeRuntimeKeyBody(BaseModel):
    key_id: str
    wallet_address: str
    karma_identity_id: str
    wallet_signature: str


@router.post("/revoke-key")
async def runtime_revoke_key(body: RevokeRuntimeKeyBody, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("key_id", body.key_id)
    validate_public_url_segment("karma_identity_id", body.karma_identity_id)
    msg = build_revoke_key_message(
        key_id=body.key_id,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
    )
    verify_personal_message(
        message=msg,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    row = await db.get(RuntimeKeyModel, body.key_id)
    if not row or row.karma_identity_id != body.karma_identity_id:
        raise HTTPException(status_code=404, detail="runtime key not found for identity")
    if row.wallet_address.lower() != body.wallet_address.strip().lower():
        raise HTTPException(status_code=403, detail="wallet does not own this runtime key")
    await revoke_runtime_key(db=db, key_id=body.key_id)
    await db.commit()
    return signed_json_response({"key_id": body.key_id, "status": "revoked"})


class ListRuntimeKeysBody(BaseModel):
    wallet_address: str
    karma_identity_id: str
    wallet_signature: str
    client_nonce: str


@router.post("/list-keys")
async def runtime_list_keys(body: ListRuntimeKeysBody, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("karma_identity_id", body.karma_identity_id)
    validate_public_url_segment("client_nonce", body.client_nonce)
    msg = build_list_keys_message(
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
        client_nonce=body.client_nonce,
    )
    verify_personal_message(
        message=msg,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    rows = await list_runtime_keys_for_identity(db=db, karma_identity_id=body.karma_identity_id)
    out = [
        {
            "key_id": r.key_id,
            "profile_id": r.profile_id,
            "permissions": r.permissions,
            "expire_time": r.expire_at.isoformat(),
            "status": r.status,
            "agent_name": r.agent_name,
            "single_limit": r.single_limit,
            "daily_limit": r.daily_limit,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            # 绑定状态要给用户看：绑了 agent 公钥以后，光有钥匙字符串花不了钱。
            "agent_binding": r.agent_binding,
            "key_binding": r.key_binding,
            "agent_fingerprint": (
                agent_binding_fingerprint(r.agent_public_key) if r.agent_public_key else ""
            ),
            # 有没有「agent 申请了、等用户输匹配码」的待确认请求。
            "pending_binding": pending_binding_view(r),
            # 铸造时指给了 agent、但还没完成匹配码激活：这个状态下动钱的
            # 调用一律 403，操作台据此标「未激活」。
            "activation_required": bool(
                (r.key_binding or "") == PENDING_KEY_BINDING and not r.agent_public_key
            ),
        }
        for r in rows
    ]
    return signed_json_response({"keys": out})


# ---------------------------------------------------------------------------
# Agent 自助绑定公钥 —— 「使用时刻硬校验」的开关
# ---------------------------------------------------------------------------


class BindKeyBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    agent_public_key: str = Field(min_length=32, max_length=128)
    client_nonce: str = Field(min_length=8, max_length=128)


@router.post("/bind-key")
async def runtime_bind_key(
    body: BindKeyBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_karma_runtime_key: Annotated[str | None, Header(alias="X-Karma-Runtime-Key")] = None,
    x_karma_agent_signature: Annotated[str | None, Header(alias="X-Karma-Agent-Signature")] = None,
    x_karma_runtime_timestamp: Annotated[str | None, Header(alias="X-Karma-Runtime-Timestamp")] = None,
    x_karma_runtime_nonce: Annotated[str | None, Header(alias="X-Karma-Runtime-Nonce")] = None,
):
    """申请把 agent 的 Ed25519 公钥钉在这把 Runtime Key 上 —— 第一步。

    申请之后绑定**还没生效**：服务端只在待确认位存下公钥，回一串 8 位匹配码。
    agent 必须把这串码交回主人，主人在操作台手输并签名确认
    （``POST /runtime/confirm-bind-key``）之后，绑定才真正落库。

    为什么这么绕：Runtime Key 是不记名令牌。以前「谁先调 bind-key 谁就绑上」——
    偷到 key 的人抢先绑自己的公钥，主人反而被挡在外面。现在码在 agent 手里、
    在主人手里各一份，偷 key 的人两样都没有。

    已经绑在同一把公钥上的重复申请是幂等的：不再发新码，直接回 status=active。
    绑定生效后每个请求都必须带 X-Karma-Agent-Signature。

    换绑不做静默替换：已经绑过别的公钥时一律 409，先吊销再铸新的。
    """
    token = (x_karma_runtime_key or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Karma-Runtime-Key header is required")
    validate_public_url_segment("agent_id", body.agent_id)
    ctx = await load_active_context(db=db, token=token)
    check_replay_nonce(key_id=ctx.key_id, endpoint="bind-key", nonce=body.client_nonce)
    if ctx.agent_public_key:
        verify_signed_request(
            ctx=ctx,
            method=request.method,
            path=request.url.path,
            body=await request.body(),
            signature_b64=x_karma_agent_signature,
            timestamp_header=x_karma_runtime_timestamp,
            nonce_header=x_karma_runtime_nonce,
        )
    try:
        row, activation_code, status = await request_key_binding(
            db=db,
            key_id=ctx.key_id,
            agent_id=body.agent_id,
            agent_public_key=body.agent_public_key,
        )
    except PublicKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    bound_agent = (row.agent_binding or body.agent_id).strip()
    payload = {
        "key_id": row.key_id,
        "agent_id": bound_agent,
        "status": status,
        "key_binding": row.key_binding,
        "agent_fingerprint": (
            agent_binding_fingerprint(row.agent_public_key) if row.agent_public_key else ""
        ),
        "nonce_required": row.nonce_required,
        "pending_binding": pending_binding_view(row),
    }
    if status == "active":
        payload.update(_binding_receipt(row, bound_agent))
    else:
        pending = pending_binding_view(row) or {}
        payload.update(
            {
                "activation_code": activation_code,
                "activation_expires_at": pending.get("expires_at"),
                "activation_attempts_left": pending.get("attempts_left"),
                "activation_code_hint": (
                    "把这串匹配码交给这把 key 的主人，让他在 Karma 操作台输入并签名确认；"
                    "在他确认之前绑定不生效，你调用接口会一直是服务端托管状态。"
                ),
                "confirm_endpoint": "/runtime/confirm-bind-key",
            }
        )
    return signed_json_response(payload)


# ---------------------------------------------------------------------------
# 操作台侧：确认 / 拒绝 agent 的接入申请（一律要钱包签名）
# ---------------------------------------------------------------------------


class ConfirmBindKeyBody(BaseModel):
    key_id: str
    karma_identity_id: str
    wallet_address: str
    wallet_signature: str
    activation_code: str = Field(min_length=1, max_length=32)
    client_nonce: str = Field(min_length=8, max_length=128)


class RejectBindKeyBody(BaseModel):
    key_id: str
    karma_identity_id: str
    wallet_address: str
    wallet_signature: str
    client_nonce: str = Field(min_length=8, max_length=128)


class ListBindRequestsBody(BaseModel):
    karma_identity_id: str
    wallet_address: str
    wallet_signature: str
    client_nonce: str


class ListPendingBindsBody(BaseModel):
    """操作台侧轮询用：只要会话身份，不要钱包签名。"""

    karma_identity_id: str


async def _owned_identity_key(
    db: AsyncSession, *, key_id: str, karma_identity_id: str, wallet_address: str
) -> RuntimeKeyModel:
    """这把 key 必须属于这个身份、并且是这个钱包的。"""
    validate_public_url_segment("key_id", key_id)
    validate_public_url_segment("karma_identity_id", karma_identity_id)
    row = await db.get(RuntimeKeyModel, key_id)
    if not row or row.karma_identity_id != karma_identity_id:
        raise HTTPException(status_code=404, detail="runtime key not found for identity")
    if row.wallet_address.lower() != wallet_address.strip().lower():
        raise HTTPException(status_code=403, detail="wallet does not own this runtime key")
    return row


def _confirm_bind_signature_ok(
    *,
    key_id: str,
    karma_identity_id: str,
    wallet_address: str,
    wallet_signature: str,
    client_nonce: str,
    candidates: list[str],
) -> None:
    """验「确认绑定」的钱包签名。

    默认签的是显示形式 XXXX-XXXX；客户端要是签了紧凑形式（没有连字符），或者把用户
    原样输入的字串（小写、带空格）拿去签，这里也会接着试 —— 用户不该为了一个连字符
    看到莫名其妙的 401。
    """
    last: HTTPException | None = None
    for candidate in candidates:
        msg = build_confirm_bind_message(
            key_id=key_id,
            karma_identity_id=karma_identity_id,
            wallet_address=wallet_address,
            activation_code=candidate,
            client_nonce=client_nonce,
        )
        try:
            verify_personal_message(
                message=msg,
                wallet_address=wallet_address,
                wallet_signature=wallet_signature,
            )
            return
        except HTTPException as exc:
            last = exc
    if last is not None:
        raise last


@router.post("/confirm-bind-key")
async def runtime_confirm_bind_key(
    body: ConfirmBindKeyBody, db: AsyncSession = Depends(get_db)
):
    """主人在操作台敲下匹配码 + 钱包签名 —— 到这一步 agent 绑定才生效。"""
    await _owned_identity_key(
        db,
        key_id=body.key_id,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
    )
    validate_public_url_segment("client_nonce", body.client_nonce)
    normalized = normalize_activation_code(body.activation_code)
    candidates: list[str] = []
    for candidate in (
        display_activation_code(normalized),
        normalized,
        (body.activation_code or "").strip(),
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    _confirm_bind_signature_ok(
        key_id=body.key_id,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
        client_nonce=body.client_nonce,
        candidates=candidates,
    )
    row = await confirm_key_binding(db=db, key_id=body.key_id, code=normalized)
    await db.commit()
    bound_agent = (row.agent_binding or "").strip()
    payload = {
        "key_id": row.key_id,
        "agent_id": bound_agent,
        "status": "active",
        "key_binding": row.key_binding,
        "agent_fingerprint": (
            agent_binding_fingerprint(row.agent_public_key) if row.agent_public_key else ""
        ),
        "nonce_required": row.nonce_required,
        "pending_binding": None,
    }
    await _notice_safe(
        db,
        karma_identity_id=body.karma_identity_id,
        kind=NOTICE_KEY_BOUND,
        payload={
            "key_id": row.key_id,
            "agent_id": bound_agent,
            "agent_name": row.agent_name or "",
        },
    )
    payload.update(_binding_receipt(row, bound_agent))
    return signed_json_response(payload)


@router.post("/reject-bind-key")
async def runtime_reject_bind_key(
    body: RejectBindKeyBody, db: AsyncSession = Depends(get_db)
):
    """主人拒绝这次接入：清掉待确认请求。key 本身不动，agent 也没被吊销。"""
    await _owned_identity_key(
        db,
        key_id=body.key_id,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
    )
    validate_public_url_segment("client_nonce", body.client_nonce)
    msg = build_reject_bind_message(
        key_id=body.key_id,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
        client_nonce=body.client_nonce,
    )
    verify_personal_message(
        message=msg,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    row = await reject_key_binding(db=db, key_id=body.key_id)
    await db.commit()
    return signed_json_response(
        {
            "key_id": row.key_id,
            "status": "rejected",
            "key_binding": row.key_binding,
            "pending_binding": pending_binding_view(row),
        }
    )


@router.post("/list-bind-requests")
async def runtime_list_bind_requests(
    body: ListBindRequestsBody, db: AsyncSession = Depends(get_db)
):
    """操作台拉「agent 已申请、还没输码确认」的接入请求。"""
    validate_public_url_segment("karma_identity_id", body.karma_identity_id)
    validate_public_url_segment("client_nonce", body.client_nonce)
    msg = build_list_bind_requests_message(
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
        client_nonce=body.client_nonce,
    )
    verify_personal_message(
        message=msg,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    rows = await list_runtime_keys_for_identity(db=db, karma_identity_id=body.karma_identity_id)
    requests = []
    for r in rows:
        if r.wallet_address.lower() != body.wallet_address.strip().lower():
            continue
        view = pending_binding_view(r)
        if not view:
            continue
        view["agent_name"] = r.agent_name
        view["key_binding"] = r.key_binding
        requests.append(view)
    requests.sort(key=lambda v: v.get("expires_at") or "")
    return signed_json_response({"requests": requests})


@router.post("/list-pending-binds")
async def runtime_list_pending_binds(
    body: ListPendingBindsBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """操作台进页面时拉「待确认接入请求」——用会话身份，不打钱包签名弹窗。

    和 ``/runtime/list-bind-requests`` 的分工：那条要求钱包签名，身份不可辩驳，
    适合用户主动发起的动作；这条只认会话（SIWE bearer / X-Karma-Identity-Id），
    好让主人一进操作台就能看见「有 agent 在申请接入」。

    只回当前会话身份名下的 key，且只给指纹 / 有效期这类展示信息 ——
    匹配码本身在服务端只有 HMAC，这里也拿不到。
    """
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(
            status_code=403, detail="authentication required: connect a wallet first"
        )
    identity = (body.karma_identity_id or "").strip()
    if identity and identity != actor:
        raise HTTPException(
            status_code=403, detail="karma_identity_id does not match the authenticated identity"
        )
    rows = await list_runtime_keys_for_identity(db=db, karma_identity_id=actor)
    requests = []
    for r in rows:
        view = pending_binding_view(r)
        if not view:
            continue
        view["agent_name"] = r.agent_name
        view["key_binding"] = r.key_binding
        requests.append(view)
    requests.sort(key=lambda v: v.get("expires_at") or "")
    return signed_json_response({"requests": requests})


class UnbindKeyBody(BaseModel):
    key_id: str
    karma_identity_id: str
    wallet_address: str
    wallet_signature: str
    client_nonce: str = Field(min_length=8, max_length=128)


class ListBoundKeysBody(BaseModel):
    """设置页列「已绑 agent 的钥匙」——只认会话，不打钱包签名弹窗。"""

    karma_identity_id: str


@router.post("/list-bound-keys")
async def runtime_list_bound_keys(
    body: ListBoundKeysBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """设置页「取消绑定」那一栏的数据源：当前会话身份名下、已绑公钥的钥匙。

    和 ``/runtime/list-keys`` 的分工：那条要钱包签名，适合用户主动发起的动作；
    这条只认会话（SIWE bearer / X-Karma-Identity-Id），进设置页就能看见
    「现在哪把钥匙在代表我花钱」。公钥原文不回传，只给指纹 —— 页面不需要原文。
    """
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(
            status_code=403, detail="authentication required: connect a wallet first"
        )
    identity = (body.karma_identity_id or "").strip()
    if identity and identity != actor:
        raise HTTPException(
            status_code=403, detail="karma_identity_id does not match the authenticated identity"
        )
    rows = await list_bound_runtime_keys(db=db, karma_identity_id=actor)
    keys = [
        {
            "key_id": r.key_id,
            "agent_id": (r.agent_binding or "").strip(),
            "agent_name": r.agent_name,
            "agent_fingerprint": agent_binding_fingerprint(r.agent_public_key),
            "key_binding": r.key_binding,
            "permissions": r.permissions,
            "single_limit": r.single_limit,
            "daily_limit": r.daily_limit,
            "expire_time": r.expire_at.isoformat() if r.expire_at else "",
            "nonce_required": bool(r.nonce_required),
        }
        for r in rows
        if (r.status or "").strip().lower() == "active"
    ]
    keys.sort(key=lambda v: ((v.get("agent_name") or ""), (v.get("key_id") or "")))
    return signed_json_response({"keys": keys})


@router.post("/unbind-key")
async def runtime_unbind_key(body: UnbindKeyBody, db: AsyncSession = Depends(get_db)):
    """主人在设置页点「取消绑定」：钱包签名一次，钥匙立刻回到「未激活」。

    为什么不顺手续成托管（service）状态：那等于把钥匙变回不记名令牌 —— 谁抄到
    谁花，而用户点这个按钮的意思恰恰是「别再让那个 agent 代表我花钱」。摘掉公钥
    之后这把钥匙谁都花不了；要用就重新走一次激活（agent 再申请、主人再输码）。
    """
    await _owned_identity_key(
        db,
        key_id=body.key_id,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
    )
    validate_public_url_segment("client_nonce", body.client_nonce)
    msg = build_unbind_key_message(
        key_id=body.key_id,
        karma_identity_id=body.karma_identity_id,
        wallet_address=body.wallet_address,
        client_nonce=body.client_nonce,
    )
    verify_personal_message(
        message=msg,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    row = await unbind_key_binding(db=db, key_id=body.key_id)
    await db.commit()
    # 取消绑定是不可逆动作：落一条站内提醒，主人下次进操作台仍然看得见，点过才消。
    await _notice_safe(
        db,
        karma_identity_id=body.karma_identity_id,
        kind=NOTICE_KEY_UNBOUND,
        payload={
            "key_id": row.key_id,
            "agent_id": (row.agent_binding or "").strip(),
            "agent_name": row.agent_name or "",
        },
    )
    return signed_json_response(
        {
            "key_id": row.key_id,
            "status": "unbound",
            "key_binding": row.key_binding,
            "agent_id": (row.agent_binding or "").strip(),
            "agent_fingerprint": "",
            "activation_required": True,
            "activation_code_ttl_seconds": BIND_CODE_TTL_SECONDS,
            "pending_binding": pending_binding_view(row),
        }
    )


# ---------------------------------------------------------------------------
# 操作台侧（会话鉴权）：最近调用 + 站内提醒
# ---------------------------------------------------------------------------


class ListKeyCallsBody(BaseModel):
    """「已绑定钥匙」卡片展开后看最近调用 —— 只认会话，不惊动钱包。"""

    karma_identity_id: str
    key_id: str
    limit: int = 20


@router.post("/key-calls")
async def runtime_key_calls(
    body: ListKeyCallsBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """这把钥匙最近替我做了什么（成功 / 被拒 / 异常都记）。

    只认会话：展开一张卡片看历史，不该弹钱包签名。别人的钥匙一律 404 ——
    连「存在与否」都不给非本人看。
    """
    actor = await _session_owned_identity(db, request, body.karma_identity_id)
    validate_public_url_segment("key_id", body.key_id)
    row = await db.get(RuntimeKeyModel, body.key_id)
    if not row or row.karma_identity_id != actor:
        raise HTTPException(status_code=404, detail="runtime key not found for identity")
    rows = await list_key_calls(db, key_id=row.key_id, limit=body.limit)
    return signed_json_response({"key_id": row.key_id, "calls": [call_view(r) for r in rows]})


class ListNoticesBody(BaseModel):
    """站内提醒：主人自己的钥匙发生了什么事。"""

    karma_identity_id: str
    limit: int = 20
    unread_only: bool = False


@router.post("/list-notices")
async def runtime_list_notices(
    body: ListNoticesBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """操作台站内提醒（只给本人）。"""
    actor = await _session_owned_identity(db, request, body.karma_identity_id)
    rows = await list_notices(
        db, karma_identity_id=actor, limit=body.limit, unread_only=body.unread_only
    )
    unread = await unread_notice_count(db, karma_identity_id=actor)
    return signed_json_response({"notices": [notice_view(r) for r in rows], "unread": unread})


class AckNoticeBody(BaseModel):
    karma_identity_id: str
    notice_ids: Optional[list[int]] = None


@router.post("/ack-notice")
async def runtime_ack_notice(
    body: AckNoticeBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """点过就算读过；不给 id 就是「全部标记已读」。"""
    actor = await _session_owned_identity(db, request, body.karma_identity_id)
    acked = await ack_notices(db, karma_identity_id=actor, notice_ids=body.notice_ids)
    await db.commit()
    unread = await unread_notice_count(db, karma_identity_id=actor)
    return signed_json_response({"acked": acked, "unread": unread})


# ---------------------------------------------------------------------------
# Runtime Key authenticated agent paths
# ---------------------------------------------------------------------------


# 还没激活的钥匙也允许调这几个端点：agent 需要能读到「我还没激活」，
# 而不是只看到一句 403 去猜。真正的动作端不在这里 —— 那些一律拒。
PENDING_ACTIVATION_ALLOWED_PATHS = {"/runtime/permissions"}

# 会写调用记录的动作端。故意只列这六个：读路径（permissions / task-status）
# 不记，否则「最近调用」会被自己刷屏。
LOGGED_ACTION_PATHS = {
    "/runtime/place-order",
    "/runtime/request-voucher",
    "/runtime/submit-receipt",
    "/runtime/update-progress",
    "/runtime/submit-bundle",
    "/runtime/request-settlement",
}


async def get_runtime_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_karma_runtime_key: Annotated[str | None, Header(alias="X-Karma-Runtime-Key")] = None,
    x_karma_agent_signature: Annotated[str | None, Header(alias="X-Karma-Agent-Signature")] = None,
    x_karma_runtime_timestamp: Annotated[str | None, Header(alias="X-Karma-Runtime-Timestamp")] = None,
    x_karma_runtime_nonce: Annotated[str | None, Header(alias="X-Karma-Runtime-Nonce")] = None,
) -> RuntimeKeyContext:
    """校验 Runtime Key；已绑定 agent 公钥的 key 还要逐请求验签。

    老 key（没绑公钥）走原路径：只认 key 本身，行为与升级前一致 ——
    升级不会把已经在跑的 agent 打掉。绑过的 key 少了签名 / 时间戳 / nonce 一律 401。
    """
    token = (x_karma_runtime_key or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Karma-Runtime-Key header is required")
    ctx = await load_active_context(db=db, token=token)
    if request.url.path not in PENDING_ACTIVATION_ALLOWED_PATHS:
        blocked = pending_activation_block(
            key_binding=ctx.key_binding,
            agent_public_key=ctx.agent_public_key,
        )
        if blocked:
            # 「未激活就想花钱」是最值得主人看见的一条记录：他手里的 403 不是网络问题。
            await _log_call_safe(
                db,
                ctx,
                endpoint=_action_name(request),
                outcome="rejected",
                http_status=403,
                detail=_detail_text(blocked),
                rollback_first=True,
            )
            raise HTTPException(status_code=403, detail=blocked)
    try:
        verify_signed_request(
            ctx=ctx,
            method=request.method,
            path=request.url.path,
            body=await request.body(),
            signature_b64=x_karma_agent_signature,
            timestamp_header=x_karma_runtime_timestamp,
            nonce_header=x_karma_runtime_nonce,
        )
    except HTTPException as exc:
        # 验签失败发生在路由函数之前（依赖先跑），装饰器那层看不见它 —— 在这里补记。
        await _log_call_safe(
            db,
            ctx,
            endpoint=_action_name(request),
            outcome="rejected",
            http_status=int(exc.status_code),
            detail=_detail_text(exc.detail),
            rollback_first=True,
        )
        raise
    return ctx


@router.get("/permissions")
async def runtime_permissions(
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    daily_used = await get_daily_used_async(db, ctx.key_id)
    ctx_row = await db.get(RuntimeKeyModel, ctx.key_id)
    return signed_json_response(
        {
            "key_id": ctx.key_id,
            "karma_identity_id": ctx.karma_identity_id,
            "permissions": ctx.permissions,
            "expire_time": ctx.expire_at.isoformat(),
            "status": ctx.status,
            "single_limit": ctx.single_limit,
            "daily_limit": ctx.daily_limit,
            "daily_used": daily_used,
            "agent_binding": ctx.agent_binding,
            "key_binding": ctx.key_binding,
            "agent_fingerprint": (
                agent_binding_fingerprint(ctx.agent_public_key) if ctx.agent_public_key else ""
            ),
            "nonce_required": ctx.nonce_required,
            "pending_binding": pending_binding_view(ctx_row) if ctx_row else None,
            # 未激活的钥匙只能读到这里：告诉调用方还差哪一步。
            "activation_required": bool(
                (ctx.key_binding or "") == PENDING_KEY_BINDING and not ctx.agent_public_key
            ),
            "activation_code_ttl_seconds": BIND_CODE_TTL_SECONDS,
            "chain_id": int(settings.testnet_chain_id or 0),
            "runtime_url": (settings.public_runtime_base_url or "").strip(),
        }
    )


@router.get("/capacity")
async def runtime_capacity(
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    """这张身份卡（或这个子身份）现在还剩多少额度可用。

    与操作台同一口径（``services.profile_capacity``）：

    * 主身份上限 = ``capacity.total_locked_usdc``；为 0 时回退到链上有效 commit
      之和（非托管 v2 —— 钱在用户自己钱包里，只给了合约额度）。
    * 子身份看 ``profile_capacity`` 的分配与占用。

    旧实现直读 ``capacity`` 表：线上这张表是空的，所以 agent 读到的永远是 0。
    """
    assert_permission(ctx, "sync_task_status")
    validate_public_url_segment("identity_id", ctx.karma_identity_id)

    locked = await master_ceiling_usdc(db, identity_id=ctx.karma_identity_id)
    allocations = await get_allocations(db, identity_id=ctx.karma_identity_id)
    allocated = round(sum(float(a.get("allocated_credits") or 0.0) for a in allocations), 6)
    identity_in_use = round(
        sum(
            float(a.get("in_progress_credits") or 0.0)
            + float(a.get("pending_settlement_credits") or 0.0)
            + float(a.get("disputed_credits") or 0.0)
            for a in allocations
        ),
        6,
    )

    profile_row: dict | None = None
    if ctx.profile_id:
        row = await get_profile_capacity(db, profile_id=ctx.profile_id)
        if row is not None and row.owner_identity_id == ctx.karma_identity_id:
            profile_row = serialize_profile_capacity(row)

    if profile_row is not None:
        scope = "profile"
        available = round(float(profile_row.get("available_credits") or 0.0), 6)
        in_use = round(
            float(profile_row.get("in_progress_credits") or 0.0)
            + float(profile_row.get("pending_settlement_credits") or 0.0)
            + float(profile_row.get("disputed_credits") or 0.0),
            6,
        )
    else:
        scope = "identity"
        available = round(max(0.0, locked - allocated), 6)
        in_use = identity_in_use

    return signed_json_response(
        {
            "identity_id": ctx.karma_identity_id,
            "profile_id": ctx.profile_id,
            "scope": scope,
            "total_locked_usdc": locked,
            "allocated_usdc": allocated,
            "unallocated_usdc": round(max(0.0, locked - allocated), 6),
            "available_usdc": available,
            "in_use_usdc": in_use,
            "allocations": allocations,
            "profile_capacity": profile_row,
            "checked_at": _utc_iso(),
        }
    )


@router.get("/policy")
async def runtime_policy(
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    """agent 读到的「边界」：这件事我能自己拍板到什么程度。

    只读调用者自己（同一把 Runtime Key）的策略，不返回任何其他身份的数据。金额口有两个：

    * ``per_order_hard_cap_usdc`` —— 超过它连付款凭证都开不出来（Runtime Key 硬上限）。
    * ``per_order_auto_approve_usdc`` —— 不超过它，agent 可以自己下单；超过就必须回
      操作台由主人确认（``high_risk_mode`` 决定要不要每笔都确认）。
    """
    policy = await get_automation_policy(db, ctx.karma_identity_id)
    daily_used = await get_daily_used_async(db, ctx.key_id)

    policy_single = float(policy.single_limit) if policy else 0.0
    policy_daily = float(policy.daily_limit) if policy else 0.0
    policy_auto = bool(
        policy
        and policy.auto_enabled
        and policy.responsibility_acknowledged
        # 主人选了「每一笔都找我确认」就没有自动额度可言。
        and str(policy.high_risk_mode or "") != "always"
    )
    auto_single = min(float(ctx.single_limit), policy_single) if policy_auto else 0.0
    auto_daily = min(float(ctx.daily_limit), policy_daily) if policy_auto else 0.0

    rules: list[str] = []
    if auto_single > 0:
        rules.append(f"单笔 ≤ {auto_single:g} USDC：我可以自己挑商家、自己下单，不用问你")
        rules.append("取消 / 退款 / 改价 / 换商家 我永远不会自己做，必须等你确认")
    else:
        rules.append("自动下单未开启：每一笔都要主人在操作台确认")
    rules.append(f"单笔 > {float(ctx.single_limit):g} USDC 会被直接拒绝（Runtime Key 硬上限）")
    rules.append(
        f"每天累计上限 {float(ctx.daily_limit):g} USDC，今天已用 {daily_used:g} USDC"
    )
    if policy and policy.high_risk_mode == "always":
        rules.append("主人要求每一笔都人工确认")
    if not policy:
        rules.append("还没保存自动授权策略：只能读状态，不能自动花钱")

    return signed_json_response(
        {
            "key_id": ctx.key_id,
            "karma_identity_id": ctx.karma_identity_id,
            "profile_id": ctx.profile_id,
            "agent_name": ctx.agent_name,
            "configured": policy is not None,
            "permissions": list(ctx.permissions),
            "auto_enabled": bool(policy.auto_enabled) if policy else False,
            "responsibility_acknowledged": bool(policy.responsibility_acknowledged) if policy else False,
            "policy_version": int(policy.policy_version) if policy else 0,
            "limits": {
                "per_order_auto_approve_usdc": auto_single,
                "per_order_hard_cap_usdc": float(ctx.single_limit),
                "daily_auto_usdc": auto_daily,
                "daily_hard_cap_usdc": float(ctx.daily_limit),
                "daily_used_usdc": daily_used,
            },
            "boundaries": {
                "high_risk_mode": policy.high_risk_mode if policy else None,
                "allowed_task_types": list(getattr(policy, "allowed_task_types", None) or [])
                if policy
                else [],
                "trusted_counterparty_ids": list(
                    getattr(policy, "trusted_counterparty_ids", None) or []
                )
                if policy
                else [],
                "auto_accept_incoming": bool(getattr(policy, "auto_accept_incoming", False))
                if policy
                else False,
                "auto_execute_pipeline": bool(getattr(policy, "auto_execute_pipeline", False))
                if policy
                else False,
                "human_not_present_allowed": bool(
                    getattr(policy, "human_not_present_allowed", False)
                )
                if policy
                else False,
            },
            "rules_zh": rules,
            "expire_time": ctx.expire_at.isoformat(),
            "chain_id": int(settings.testnet_chain_id or 0),
            "runtime_url": (settings.public_runtime_base_url or "").strip(),
        }
    )


class RuntimeDiscoverBody(BaseModel):
    requirement_text: str = Field(min_length=1, max_length=32000)
    amount: Optional[float] = Field(default=None, gt=0)
    limit: int = Field(default=10, ge=1, le=50)
    client_nonce: str = Field(min_length=8, max_length=128)


@router.post("/discover")
async def runtime_discover(
    body: RuntimeDiscoverBody,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    """agent 找活干 / 找人干活：按一句话需求发现可结算的 agent 与商家。"""
    assert_permission(ctx, "discover_agents")
    check_replay_nonce(key_id=ctx.key_id, endpoint="discover", nonce=body.client_nonce)
    out = await discover_for_intent(
        DiscoverIntentRequest(
            requirement_text=body.requirement_text,
            buyer_identity_id=ctx.karma_identity_id,
            amount=body.amount,
            limit=body.limit,
        ),
        db,
    )
    payload = dict(out) if isinstance(out, dict) else {"plan": out}
    payload["requested_by_identity_id"] = ctx.karma_identity_id
    payload["profile_id"] = ctx.profile_id
    return signed_json_response(payload)


class RuntimePlaceOrderBody(BaseModel):
    requirement_text: str = Field(min_length=1, max_length=32000)
    amount: float = Field(gt=0)
    seller_identity_id: Optional[str] = None
    client_nonce: str = Field(min_length=8, max_length=128)
    negotiate_a2a: bool = True
    auto_complete: bool = False
    confirmation_session_id: Optional[str] = Field(default=None, max_length=128)
    # 已经和卖方做完 Important Fields 双签的 capture（真实商业场景必须过这一关）。
    important_fields_capture_id: Optional[str] = Field(default=None, max_length=128)


@router.post("/place-order")
@runtime_call_logged("place-order")
async def runtime_place_order(
    body: RuntimePlaceOrderBody,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    """agent 按主人划的边界自己下单。

    边界在服务端算，客户端说了不算：

    * 单笔 > Runtime Key 上限 → 403（先用 ``/runtime/policy`` 读清楚再下单）。
    * 超过已保存策略的自动额度 → 不建单、不扣钱，返回 ``awaiting_owner_confirmation``，
      等主人在操作台点确认。
    * 单笔 ≤ 自动额度 → 正常建单出凭证；钱依然要验收通过才真正划转。
    """
    assert_permission(ctx, "place_order")
    if body.seller_identity_id:
        validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    check_replay_nonce(key_id=ctx.key_id, endpoint="place-order", nonce=body.client_nonce)
    daily_used = await get_daily_used_async(db, ctx.key_id)
    check_single_and_daily_limits(
        key_id=ctx.key_id,
        amount=float(body.amount),
        single_limit=ctx.single_limit,
        daily_limit=ctx.daily_limit,
        daily_used=daily_used,
    )
    out = await fulfill_intent(
        db,
        requirement_text=body.requirement_text,
        buyer_identity_id=ctx.karma_identity_id,
        amount=float(body.amount),
        seller_identity_id=body.seller_identity_id,
        auto_fund_capacity=True,
        negotiate_a2a=body.negotiate_a2a,
        auto_complete=body.auto_complete,
        buyer_signature=f"runtime:{ctx.key_id}",
        require_owner_confirmation=True,
        confirmation_session_id=body.confirmation_session_id,
        important_fields_capture_id=body.important_fields_capture_id,
        policy_auto_allowed=False,
    )
    payload = dict(out) if isinstance(out, dict) else {"result": out}
    if payload.get("voucher_id"):
        # 真出了凭证才算这笔钱动用过额度（和 /runtime/request-voucher 同一本账）。
        await record_daily_spend_async(db, key_id=ctx.key_id, amount=float(body.amount))
    await db.commit()
    payload["requested_by_identity_id"] = ctx.karma_identity_id
    payload["profile_id"] = ctx.profile_id
    payload["awaiting_owner_confirmation"] = payload.get("status") == "awaiting_owner_confirmation"
    return signed_json_response(payload)


class RuntimeRequestVoucherEnvelope(BaseModel):
    """Voucher fields plus anti-replay metadata for the Runtime Gateway."""

    client_nonce: str = Field(min_length=8, max_length=128)
    voucher: CreateVoucherRequest


@router.post("/request-voucher")
@runtime_call_logged("request-voucher")
async def runtime_request_voucher(
    body: RuntimeRequestVoucherEnvelope,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    assert_permission(ctx, "request_voucher")
    v = body.voucher
    if v.buyer_identity_id != ctx.karma_identity_id:
        raise HTTPException(status_code=403, detail="voucher buyer_identity_id must match runtime key identity")
    if ctx.profile_id and not v.profile_id:
        v = v.model_copy(update={"profile_id": ctx.profile_id})
    check_replay_nonce(key_id=ctx.key_id, endpoint="request-voucher", nonce=body.client_nonce)
    daily_used = await get_daily_used_async(db, ctx.key_id)
    check_single_and_daily_limits(
        key_id=ctx.key_id,
        amount=float(v.amount),
        single_limit=ctx.single_limit,
        daily_limit=ctx.daily_limit,
        daily_used=daily_used,
    )
    delegate = synthetic_request(
        path="/runtime/request-voucher",
        actor_id=ctx.karma_identity_id,
    )
    out = await vouchers_create_route(v, delegate, db)
    await record_daily_spend_async(db, key_id=ctx.key_id, amount=float(v.amount))
    await db.commit()
    return signed_json_response(out.model_dump(mode="json"), status_code=201)


class RuntimeCheckVoucherBody(BaseModel):
    """Read-only voucher verify for seller Runtime Key (does not accept)."""

    voucher_id: str
    client_nonce: str = Field(min_length=8, max_length=128)
    expected_amount: Optional[float] = None


@router.post("/check-voucher")
async def runtime_check_voucher(
    body: RuntimeCheckVoucherBody,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    assert_permission(ctx, "verify_voucher")
    validate_public_url_segment("voucher_id", body.voucher_id)
    check_replay_nonce(key_id=ctx.key_id, endpoint="check-voucher", nonce=body.client_nonce)
    task_id = await resolve_task_id_for_voucher(db, body.voucher_id)
    if task_id:
        await assert_task_automation_ready(
            db, task_id=task_id, karma_identity_id=ctx.karma_identity_id
        )
    delegate = synthetic_request(
        path="/runtime/check-voucher",
        actor_id=ctx.karma_identity_id,
    )
    out = await vouchers_verify_route(
        body.voucher_id,
        VerifyVoucherRequest(seller_identity_id=ctx.karma_identity_id, expected_amount=body.expected_amount),
        delegate,
        db,
    )
    await db.commit()
    return signed_json_response(out.model_dump(mode="json"))


@router.post("/submit-receipt")
@runtime_call_logged("submit-receipt")
async def runtime_submit_receipt(
    receipt: ExecutionReceipt,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    assert_permission(ctx, "submit_receipt")
    validate_public_url_segment("task_id", receipt.task_id)
    validate_public_url_segment("receipt_id", receipt.receipt_id)
    if receipt.agent_id != ctx.karma_identity_id:
        raise HTTPException(status_code=403, detail="receipt agent_id must match runtime key identity")
    if ctx.profile_id and not receipt.profile_id:
        receipt = receipt.model_copy(update={"profile_id": ctx.profile_id})

    await assert_task_automation_ready(
        db, task_id=receipt.task_id, karma_identity_id=ctx.karma_identity_id
    )
    await ensure_task_contract_exists(db, receipt.task_id)

    # The agent holds a Runtime Key, never the platform signing key, so the receipt it
    # sends is unsigned. The gateway signs on its behalf ? exactly like the progress path
    # above ? and that signature is what satisfies the RECEIPT_REQUIRE_SIGNATURE gate.
    # Validating first would reject every agent receipt in production with
    # "receipt signature is required".
    receipt = receipt.model_copy(
        update={
            "signature": signing_service.sign_receipt(
                receipt.model_copy(update={"signature": None})
            )
        }
    )

    store = PostgresReceiptStore(db)
    try:
        validate_execution_receipt_static(receipt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if settings.receipt_template_voucher_binding:
        res = await db.execute(select(SettlementModel).where(SettlementModel.task_id == receipt.task_id))
        sm = res.scalar_one_or_none()
        if sm is not None and sm.voucher_id:
            vm = await db.get(VoucherModel, sm.voucher_id)
            task_type = vm.task_type if vm is not None else None
            try:
                validate_extension_vs_task_type(task_type=task_type, receipt=receipt)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    signed_receipt = receipt
    if not verify_execution_receipt_signature(signed_receipt):
        raise HTTPException(status_code=500, detail="runtime receipt signing invariant failed")

    latest = await store.get_latest_by_task(receipt.task_id)
    if latest is None:
        if receipt.step_index != 1:
            raise HTTPException(status_code=409, detail="first receipt step_index must be 1")
    else:
        if receipt.step_index != latest.step_index + 1:
            raise HTTPException(
                status_code=409,
                detail=f"receipt step_index must be sequential: expected {latest.step_index + 1}",
            )
        # The stored ended_at comes back from the database timezone-naive while the
        # incoming receipt is UTC-aware; compare through the shared normalizer. A raw
        # less-than raises TypeError ("can't compare offset-naive and offset-aware
        # datetimes") and every receipt after the first 500s.
        if execution_receipt_starts_before_prior_ended(
            started_at=receipt.started_at, prior_ended_at=latest.ended_at
        ):
            raise HTTPException(status_code=409, detail="receipt timestamps out of order for task")
    try:
        await store.save(signed_receipt)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return signed_json_response(signed_receipt.model_dump(mode="json"), status_code=201)


@router.post("/update-progress")
@runtime_call_logged("update-progress")
async def runtime_update_progress(
    progress: ProgressReceipt,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    assert_permission(ctx, "update_progress")
    if progress.seller_identity_id != ctx.karma_identity_id:
        raise HTTPException(status_code=403, detail="seller_identity_id must match runtime key identity")
    await assert_task_automation_ready(
        db, task_id=progress.task_id, karma_identity_id=ctx.karma_identity_id
    )
    sig = signing_service.sign_dict(
        {
            "runtime_progress_binding": ctx.key_id,
            "progress_receipt_id": progress.progress_receipt_id,
            "task_id": progress.task_id,
            "evidence_hash": progress.evidence_hash,
            "runtime_log_hash": progress.runtime_log_hash,
        }
    )
    bound = progress.model_copy(update={"seller_signature": f"runtime:{sig}"})
    delegate = synthetic_request(
        path="/runtime/update-progress",
        actor_id=ctx.karma_identity_id,
    )
    out = await progress_submit_route(bound, delegate, db)
    await db.commit()
    return signed_json_response(out.model_dump(mode="json"), status_code=201)


@router.post("/submit-bundle")
@runtime_call_logged("submit-bundle")
async def runtime_submit_bundle(
    bundle: EvidenceBundle,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    """Agent 提交证据包（P0-5）。

    Agent 手里只有 Runtime Key、没有平台签名私钥，而 ``/v1/bundles`` 从
    2026-09-17 起要求签名必须验得通。所以与 ``submit-receipt`` /
    ``update-progress`` 同一套做法：**网关确认调用者身份后代签**，再委托给
    ``/v1/bundles`` —— 归属校验（必须是该任务的买方/卖方本人）与验签都在那
    一条路径上完成，只有一份实现。
    """
    assert_permission(ctx, "submit_receipt")
    validate_public_url_segment("bundle_id", bundle.bundle_id)
    validate_public_url_segment("task_id", bundle.task_id)

    signed = bundle.model_copy(
        update={
            "agent_signature": signing_service.sign_bytes(
                evidence_bundle_signing_bytes(bundle)
            )
        }
    )
    delegate = synthetic_request(
        path="/runtime/submit-bundle",
        actor_id=ctx.karma_identity_id,
    )
    out = await submit_bundle_route(signed, delegate, db)
    await db.commit()
    return signed_json_response(out.model_dump(mode="json"), status_code=201)


class RuntimeRequestSettlementBody(BaseModel):
    task_id: str
    kind: Literal["submit_delivery", "buyer_accept", "partial"]
    client_nonce: str = Field(min_length=8, max_length=128)
    settled_value_percent: Optional[float] = None


@router.post("/request-settlement")
@runtime_call_logged("request-settlement")
async def runtime_request_settlement(
    body: RuntimeRequestSettlementBody,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    assert_permission(ctx, "request_settlement")
    validate_public_url_segment("task_id", body.task_id)
    check_replay_nonce(key_id=ctx.key_id, endpoint="request-settlement", nonce=body.client_nonce)
    await assert_task_automation_ready(
        db, task_id=body.task_id, karma_identity_id=ctx.karma_identity_id
    )

    store = PostgresSettlementStore(db)
    state = await store.get(body.task_id)
    if not state:
        raise HTTPException(status_code=404, detail="settlement not found")

    if body.kind == "submit_delivery":
        if ctx.karma_identity_id != (state.worker_agent_id or ""):
            raise HTTPException(status_code=403, detail="submit_delivery requires worker identity")
        req = synthetic_request(
            path="/runtime/request-settlement",
            actor_id=state.worker_agent_id or ctx.karma_identity_id,
        )
        out = await submit_settlement(body.task_id, req, db)
    elif body.kind == "buyer_accept":
        if ctx.karma_identity_id != state.client_agent_id:
            raise HTTPException(status_code=403, detail="buyer_accept requires buyer identity")
        req = synthetic_request(
            path="/runtime/request-settlement",
            actor_id=state.client_agent_id,
        )
        out = await buyer_accept_settlement(body.task_id, req, db)
    else:
        if ctx.karma_identity_id != state.client_agent_id:
            raise HTTPException(status_code=403, detail="partial settlement requires buyer identity")
        if body.settled_value_percent is None:
            raise HTTPException(status_code=400, detail="settled_value_percent required for partial")
        req = synthetic_request(
            path="/runtime/request-settlement",
            actor_id=state.client_agent_id,
        )
        out = await partial_settlement(
            body.task_id,
            PartialSettlementRequest(settled_value_percent=body.settled_value_percent),
            req,
            db,
        )
    await db.commit()
    return signed_json_response(out.model_dump(mode="json"))


@router.get("/task-status/{task_id}")
async def runtime_task_status(
    task_id: str,
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    assert_permission(ctx, "sync_task_status")
    validate_public_url_segment("task_id", task_id)
    settlement_store = PostgresSettlementStore(db)
    settlement = await settlement_store.get(task_id)
    if not settlement:
        raise HTTPException(status_code=404, detail="settlement not found for task")
    allowed = {settlement.client_agent_id, settlement.worker_agent_id}
    allowed.discard(None)
    if ctx.karma_identity_id not in allowed:
        raise HTTPException(status_code=403, detail="runtime key identity is not a party on this task")

    rstore = PostgresReceiptStore(db)
    receipts = await rstore.list_by_task(task_id)
    prog_result = await db.execute(
        select(ProgressReceiptModel)
        .where(ProgressReceiptModel.task_id == task_id)
        .order_by(ProgressReceiptModel.timestamp.asc())
    )
    prog_rows = list(prog_result.scalars().all())
    payload = {
        "task_id": task_id,
        "settlement": settlement.model_dump(mode="json"),
        "execution_receipts": [r.model_dump(mode="json") for r in receipts],
        "progress_receipts": [
            {
                "progress_receipt_id": p.progress_receipt_id,
                "progress_percent": p.progress_percent,
                "claimed_value_percent": p.claimed_value_percent,
                "confirmation_status": p.confirmation_status,
                "timestamp": p.timestamp.isoformat() if p.timestamp else None,
            }
            for p in prog_rows
        ],
    }
    return signed_json_response(payload)

