"""
Runtime Gateway — public standard paths for Agent SDK + Console.

Mounted at ``/runtime`` (not under ``/v1``) per the public Runtime API contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ExecutionReceipt,
    ProgressReceipt,
)
from db.models.orm import ProgressReceiptModel, RuntimeKeyModel, SettlementModel, VoucherModel
from db.session import get_db
from db.stores.receipt_store import PostgresReceiptStore
from db.stores.settlement_store import PostgresSettlementStore
from services.agent_automation_policy import get_automation_policy
from services.intent_fulfillment import fulfill_intent
from services.path_param_safety import validate_public_url_segment
from services.profile_capacity import (
    get_allocations,
    get_profile_capacity,
    master_ceiling_usdc,
    serialize_profile_capacity,
)
from services.receipt_guard import validate_execution_receipt_static, verify_execution_receipt_signature
from services.receipt_templates import validate_extension_vs_task_type
from services.task_contract_guard import ensure_task_contract_exists
from services.runtime_key_service import (
    RuntimeKeyContext,
    assert_permission,
    check_replay_nonce,
    check_single_and_daily_limits,
    create_runtime_key_record,
    list_runtime_keys_for_identity,
    load_active_context,
    revoke_runtime_key,
)
from services.runtime_response_sign import signed_json_response
from services.runtime_synthetic_request import synthetic_request
from services.runtime_wallet import (
    build_create_key_message,
    build_list_keys_message,
    build_revoke_key_message,
    verify_personal_message,
)
from services.identity_wallet_binding import ensure_wallet_authorized_for_runtime_key
from services.openclaw_automation_readiness import (
    assert_task_automation_ready,
    resolve_task_id_for_voucher,
)
from services.runtime_daily_spend import get_daily_used_async, record_daily_spend_async
from services.signing import signing_service

router = APIRouter()


def _dev_api_key(actor_id: str) -> str:
    """Synthetic API key compatible with dev auth fallback (never for production)."""
    return f"karma_{actor_id}_devruntimekey12"


def _utc_iso() -> str:
    """毫秒级 UTC 时间戳，给 agent 判断数据新鲜度用。"""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


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
    profile_id: Optional[str] = None


@router.post("/create-key")
async def runtime_create_key(body: CreateRuntimeKeyBody, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("karma_identity_id", body.karma_identity_id)
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
    return signed_json_response(
        {
            "runtime_key": token,
            "key_id": row.key_id,
            "permissions": row.permissions,
            "expire_time": row.expire_at.isoformat(),
            "status": row.status,
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
        }
        for r in rows
    ]
    return signed_json_response({"keys": out})


# ---------------------------------------------------------------------------
# Runtime Key authenticated agent paths
# ---------------------------------------------------------------------------


async def get_runtime_context(
    db: AsyncSession = Depends(get_db),
    x_karma_runtime_key: Annotated[str | None, Header(alias="X-Karma-Runtime-Key")] = None,
) -> RuntimeKeyContext:
    if not (x_karma_runtime_key or "").strip():
        raise HTTPException(status_code=401, detail="X-Karma-Runtime-Key header is required")
    return await load_active_context(db=db, token=x_karma_runtime_key.strip())


@router.get("/permissions")
async def runtime_permissions(
    ctx: RuntimeKeyContext = Depends(get_runtime_context),
    db: AsyncSession = Depends(get_db),
):
    daily_used = await get_daily_used_async(db, ctx.key_id)
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
        headers={"X-Karma-Api-Key": _dev_api_key(ctx.karma_identity_id)},
        path="/runtime/request-voucher",
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
        headers={"X-Karma-Api-Key": _dev_api_key(ctx.karma_identity_id)},
        path="/runtime/check-voucher",
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

    signed_receipt = receipt.model_copy(
        update={"signature": signing_service.sign_receipt(receipt.model_copy(update={"signature": None}))}
    )
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
        if receipt.started_at < latest.ended_at:
            raise HTTPException(status_code=409, detail="receipt timestamps out of order for task")
    try:
        await store.save(signed_receipt)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return signed_json_response(signed_receipt.model_dump(mode="json"), status_code=201)


@router.post("/update-progress")
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
        headers={"X-Karma-Api-Key": _dev_api_key(ctx.karma_identity_id)},
        path="/runtime/update-progress",
    )
    out = await progress_submit_route(bound, delegate, db)
    await db.commit()
    return signed_json_response(out.model_dump(mode="json"), status_code=201)


class RuntimeRequestSettlementBody(BaseModel):
    task_id: str
    kind: Literal["submit_delivery", "buyer_accept", "partial"]
    client_nonce: str = Field(min_length=8, max_length=128)
    settled_value_percent: Optional[float] = None


@router.post("/request-settlement")
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
            headers={"X-Karma-Api-Key": _dev_api_key(state.worker_agent_id or ctx.karma_identity_id)},
            path="/runtime/request-settlement",
        )
        out = await submit_settlement(body.task_id, req, db)
    elif body.kind == "buyer_accept":
        if ctx.karma_identity_id != state.client_agent_id:
            raise HTTPException(status_code=403, detail="buyer_accept requires buyer identity")
        req = synthetic_request(
            headers={"X-Karma-Api-Key": _dev_api_key(state.client_agent_id)},
            path="/runtime/request-settlement",
        )
        out = await buyer_accept_settlement(body.task_id, req, db)
    else:
        if ctx.karma_identity_id != state.client_agent_id:
            raise HTTPException(status_code=403, detail="partial settlement requires buyer identity")
        if body.settled_value_percent is None:
            raise HTTPException(status_code=400, detail="settled_value_percent required for partial")
        req = synthetic_request(
            headers={"X-Karma-Api-Key": _dev_api_key(state.client_agent_id)},
            path="/runtime/request-settlement",
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

