"""Trade launch signing orchestration — preview, verify, optional server-side sign."""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from sdk.signing_backend import TradeLaunchSignContext, get_signing_backend
from services.identity_wallet_binding import get_bound_wallet
from services.trade_launch_eip712 import (
    default_launch_deadline_unix,
    verify_trade_launch_buyer_signature,
)
from services.agent_automation_policy import get_automation_policy
from services.requirement_decomposer import decompose_buyer_requirement
from services.trade_pipeline_security import (
    clamp_spec_to_policies,
    requirement_fingerprint,
    validate_requirement_text,
)


def resolve_launch_nonce(*, launch_idempotency_key: str | None, requirement_fp: str) -> str:
    if launch_idempotency_key:
        return launch_idempotency_key.strip()
    return f"ephemeral-{hashlib.sha256(requirement_fp.encode()).hexdigest()[:24]}"


def build_sign_context(
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    amount: float,
    task_type: str,
    task_precision: float,
    launch_idempotency_key: str | None,
    chain_anchor_hash: str | None,
) -> TradeLaunchSignContext:
    fp = requirement_fingerprint(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=requirement_text,
        amount=amount,
        task_type=task_type,
    )
    chain_id = int(settings.trade_launch_eip712_chain_id or settings.testnet_chain_id or 11155111)
    vc = (
        settings.trade_launch_eip712_verifying_contract
        or settings.voucher_eip712_verifying_contract
        or "0x0000000000000000000000000000000000000000"
    )
    return TradeLaunchSignContext(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_fingerprint=fp,
        amount=float(amount),
        task_type=task_type,
        task_precision=float(task_precision),
        launch_nonce=resolve_launch_nonce(
            launch_idempotency_key=launch_idempotency_key,
            requirement_fp=fp,
        ),
        deadline_unix=default_launch_deadline_unix(),
        chain_id=chain_id,
        verifying_contract=vc,
        chain_anchor_hash=chain_anchor_hash,
    )


async def resolve_clamped_launch_spec(
    db: AsyncSession,
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    amount: float | None,
    task_precision: float | None,
    task_type: str | None,
) -> dict[str, Any]:
    cleaned = validate_requirement_text(requirement_text)
    buyer_policy = await get_automation_policy(db, buyer_identity_id)
    seller_policy = await get_automation_policy(db, seller_identity_id)
    if not buyer_policy or not seller_policy:
        raise HTTPException(status_code=403, detail="both parties need saved automation-policy before signing")
    spec = decompose_buyer_requirement(
        requirement_text=cleaned,
        seller_identity_id=seller_identity_id,
        buyer_identity_id=buyer_identity_id,
        amount=amount,
        task_precision=task_precision,
        task_type=task_type,
    )
    return clamp_spec_to_policies(spec, buyer_policy=buyer_policy, seller_policy=seller_policy)


async def build_signing_preview(
    db: AsyncSession,
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    amount: float | None,
    task_type: str | None,
    task_precision: float | None,
    launch_idempotency_key: str | None,
    chain_anchor_hash: str | None,
) -> dict[str, Any]:
    spec = await resolve_clamped_launch_spec(
        db,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=requirement_text,
        amount=amount,
        task_precision=task_precision,
        task_type=task_type,
    )
    ctx = build_sign_context(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=validate_requirement_text(requirement_text),
        amount=float(spec["amount"]),
        task_type=str(spec["task_type"]),
        task_precision=float(spec["task_precision"]),
        launch_idempotency_key=launch_idempotency_key,
        chain_anchor_hash=chain_anchor_hash,
    )
    wallet = await get_bound_wallet(db, buyer_identity_id)
    return {
        "signing_backend": settings.karma_signing_backend,
        "buyer_wallet_address": wallet,
        "launch_nonce": ctx.launch_nonce,
        "deadline_unix": ctx.deadline_unix,
        "requirement_fingerprint": ctx.requirement_fingerprint,
        "typed_data": ctx.to_typed_data(),
        "eip712_primary_type": "TradeLaunchIntent",
    }


async def sign_trade_launch_with_configured_backend(
    db: AsyncSession,
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    amount: float | None,
    task_type: str | None,
    task_precision: float | None,
    launch_idempotency_key: str | None,
    chain_anchor_hash: str | None,
) -> dict[str, Any]:
    bid = (settings.karma_signing_backend or "client_only").lower()
    if bid in ("client_only", "external"):
        raise HTTPException(
            status_code=400,
            detail="server-side signing disabled (KARMA_SIGNING_BACKEND=client_only|external); sign typed_data locally",
        )
    spec = await resolve_clamped_launch_spec(
        db,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=requirement_text,
        amount=amount,
        task_precision=task_precision,
        task_type=task_type,
    )
    ctx = build_sign_context(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=validate_requirement_text(requirement_text),
        amount=float(spec["amount"]),
        task_type=str(spec["task_type"]),
        task_precision=float(spec["task_precision"]),
        launch_idempotency_key=launch_idempotency_key,
        chain_anchor_hash=chain_anchor_hash,
    )
    backend = get_signing_backend()
    try:
        signature = backend.sign_trade_launch(ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    wallet = await get_bound_wallet(db, buyer_identity_id)
    preview = {
        "buyer_signature": signature,
        "signing_backend": backend.backend_id,
        "buyer_wallet_address": wallet,
        "launch_nonce": ctx.launch_nonce,
        "deadline_unix": ctx.deadline_unix,
    }
    return preview


def build_trade_launch_attestation(
    *,
    ctx: TradeLaunchSignContext,
    buyer_wallet_address: str,
) -> dict[str, Any]:
    """Embedded in voucher ``progress_rule_spec`` — links TradeLaunch signature to voucher row."""
    return {
        "schema": "karma-trade-launch-attestation-v1",
        "eip712_primary_type": "TradeLaunchIntent",
        "requirement_fingerprint": ctx.requirement_fingerprint,
        "launch_nonce": ctx.launch_nonce,
        "deadline_unix": ctx.deadline_unix,
        "buyer_wallet_address": buyer_wallet_address.strip().lower(),
        "buyer_identity_id": ctx.buyer_identity_id,
        "seller_identity_id": ctx.seller_identity_id,
        "amount": ctx.amount,
        "task_type": ctx.task_type,
        "task_precision": ctx.task_precision,
        "chain_anchor_hash": ctx.chain_anchor_hash,
    }


def verify_trade_launch_attestation_signature(
    *,
    attestation: dict[str, Any],
    buyer_signature: str,
) -> None:
    """Re-verify TradeLaunchIntent from attestation embedded at pipeline launch."""
    if attestation.get("schema") != "karma-trade-launch-attestation-v1":
        raise ValueError("invalid trade_launch_attestation schema")
    ctx = TradeLaunchSignContext(
        buyer_identity_id=str(attestation["buyer_identity_id"]),
        seller_identity_id=str(attestation["seller_identity_id"]),
        requirement_fingerprint=str(attestation["requirement_fingerprint"]),
        amount=float(attestation["amount"]),
        task_type=str(attestation["task_type"]),
        task_precision=float(attestation["task_precision"]),
        launch_nonce=str(attestation["launch_nonce"]),
        deadline_unix=int(attestation["deadline_unix"]),
        chain_id=int(
            settings.trade_launch_eip712_chain_id or settings.testnet_chain_id or 11155111
        ),
        verifying_contract=(
            settings.trade_launch_eip712_verifying_contract
            or settings.voucher_eip712_verifying_contract
            or "0x0000000000000000000000000000000000000000"
        ),
        chain_anchor_hash=attestation.get("chain_anchor_hash"),
    )
    verify_trade_launch_buyer_signature(
        buyer_wallet_address=str(attestation["buyer_wallet_address"]),
        buyer_signature=buyer_signature,
        typed_data=ctx.to_typed_data(),
    )
    now = int(__import__("time").time())
    if now > ctx.deadline_unix:
        raise ValueError("trade launch signature expired (deadline_unix passed)")


async def verify_trade_launch_commitment(
    db: AsyncSession,
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    amount: float,
    task_type: str,
    task_precision: float,
    buyer_signature: str,
    launch_idempotency_key: str | None,
    chain_anchor_hash: str | None,
) -> tuple[TradeLaunchSignContext, str, dict[str, Any]] | None:
    """
    Verify TradeLaunch EIP-712 when enabled.

    Returns (context, wallet, attestation) or None when EIP-712 not required.
    """
    if not settings.trade_launch_require_eip712:
        return None

    ctx = build_sign_context(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=requirement_text,
        amount=amount,
        task_type=task_type,
        task_precision=task_precision,
        launch_idempotency_key=launch_idempotency_key,
        chain_anchor_hash=chain_anchor_hash,
    )
    wallet = await get_bound_wallet(db, buyer_identity_id)
    if not wallet:
        raise HTTPException(
            status_code=403,
            detail="trade launch EIP-712 requires a bound buyer wallet on the identity profile",
        )
    try:
        verify_trade_launch_buyer_signature(
            buyer_wallet_address=wallet,
            buyer_signature=buyer_signature,
            typed_data=ctx.to_typed_data(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    now = int(__import__("time").time())
    if now > ctx.deadline_unix:
        raise HTTPException(status_code=403, detail="trade launch signature expired (deadline_unix passed)")

    att = build_trade_launch_attestation(ctx=ctx, buyer_wallet_address=wallet)
    return ctx, wallet, att


async def assert_buyer_signature_for_launch(
    db: AsyncSession,
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    amount: float,
    task_type: str,
    task_precision: float,
    buyer_signature: str,
    launch_idempotency_key: str | None,
    chain_anchor_hash: str | None,
) -> dict[str, Any] | None:
    """Backward-compatible wrapper; returns attestation dict when EIP-712 enforced."""
    result = await verify_trade_launch_commitment(
        db,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=requirement_text,
        amount=amount,
        task_type=task_type,
        task_precision=task_precision,
        buyer_signature=buyer_signature,
        launch_idempotency_key=launch_idempotency_key,
        chain_anchor_hash=chain_anchor_hash,
    )
    if result is None:
        return None
    _ctx, _wallet, att = result
    return att
