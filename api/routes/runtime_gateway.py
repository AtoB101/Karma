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
    CapacityState,
    ExecutionReceipt,
    ProgressReceipt,
)
from db.models.orm import CapacityModel, ProgressReceiptModel, RuntimeKeyModel, SettlementModel, VoucherModel
from db.session import get_db
from db.stores.receipt_store import PostgresReceiptStore
from db.stores.settlement_store import PostgresSettlementStore
from services.path_param_safety import validate_public_url_segment
from services.receipt_guard import validate_execution_receipt_static, verify_execution_receipt_signature
from services.receipt_templates import validate_extension_vs_task_type
from services.task_contract_guard import ensure_task_contract_exists
from services.runtime_key_service import (
    RuntimeKeyContext,
    assert_permission,
    check_replay_nonce,
    check_single_and_daily_limits,
    create_runtime_key_record,
    get_daily_used,
    list_runtime_keys_for_identity,
    load_active_context,
    record_daily_spend,
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
from services.signing import signing_service

router = APIRouter()


def _dev_api_key(actor_id: str) -> str:
    """Synthetic API key compatible with dev auth fallback (never for production)."""
    return f"karma_{actor_id}_devruntimekey12"


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


@router.post("/create-key")
async def runtime_create_key(body: CreateRuntimeKeyBody, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("karma_identity_id", body.karma_identity_id)
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
    token, row = await create_runtime_key_record(
        db=db,
        wallet_address=body.wallet_address,
        karma_identity_id=body.karma_identity_id,
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
async def runtime_permissions(ctx: RuntimeKeyContext = Depends(get_runtime_context)):
    return signed_json_response(
        {
            "key_id": ctx.key_id,
            "karma_identity_id": ctx.karma_identity_id,
            "permissions": ctx.permissions,
            "expire_time": ctx.expire_at.isoformat(),
            "status": ctx.status,
            "single_limit": ctx.single_limit,
            "daily_limit": ctx.daily_limit,
            "daily_used": get_daily_used(ctx.key_id),
            "chain_id": int(settings.testnet_chain_id or 0),
            "runtime_url": (settings.public_runtime_base_url or "").strip(),
        }
    )


@router.get("/capacity")
async def runtime_capacity(ctx: RuntimeKeyContext = Depends(get_runtime_context), db: AsyncSession = Depends(get_db)):
    assert_permission(ctx, "sync_task_status")
    validate_public_url_segment("identity_id", ctx.karma_identity_id)
    row = await db.get(CapacityModel, ctx.karma_identity_id)
    if not row:
        state = CapacityState(identity_id=ctx.karma_identity_id)
    else:
        state = CapacityState(
            identity_id=row.identity_id,
            total_locked_usdc=row.total_locked_usdc,
            total_bill_credits=row.total_bill_credits,
            available_credits=row.available_credits,
            reserved_credits=row.reserved_credits,
            in_progress_credits=row.in_progress_credits,
            confirmed_progress_credits=row.confirmed_progress_credits,
            disputed_credits=row.disputed_credits,
            pending_settlement_credits=row.pending_settlement_credits,
            burned_credits=row.burned_credits,
            released_credits=row.released_credits,
            updated_at=row.updated_at,
        )
    return signed_json_response(state.model_dump(mode="json"))


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
    check_replay_nonce(key_id=ctx.key_id, endpoint="request-voucher", nonce=body.client_nonce)
    check_single_and_daily_limits(
        key_id=ctx.key_id,
        amount=float(v.amount),
        single_limit=ctx.single_limit,
        daily_limit=ctx.daily_limit,
    )
    delegate = synthetic_request(
        headers={"X-Karma-Api-Key": _dev_api_key(ctx.karma_identity_id)},
        path="/runtime/request-voucher",
    )
    out = await vouchers_create_route(v, delegate, db)
    record_daily_spend(key_id=ctx.key_id, amount=float(v.amount))
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

