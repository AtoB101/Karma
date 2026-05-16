"""Bind EVM wallet addresses to Karma identity profiles for Runtime Key mint."""

from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import IdentityProfileModel


def _norm_wallet(addr: str) -> str:
    return (addr or "").strip().lower()


async def _ensure_profile(db: AsyncSession, karma_identity_id: str) -> IdentityProfileModel:
    row = await db.get(IdentityProfileModel, karma_identity_id)
    if row:
        return row
    row = IdentityProfileModel(
        identity_id=karma_identity_id,
        display_id=_new_display_id(),
        legal_identity_status="unbound",
        status="active",
        bound_wallet_address=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    return row


def _new_display_id() -> str:
    return f"Karma-ID-{secrets.token_hex(3).upper()}"


async def ensure_wallet_authorized_for_runtime_key(
    db: AsyncSession,
    *,
    karma_identity_id: str,
    wallet_address: str,
) -> None:
    """
  When wallet binding is enforced, the signing wallet must match the identity's bound address.

  On first mint, ``runtime_auto_bind_wallet_on_create_key`` records the wallet on the profile.
    """
    if not settings.runtime_require_wallet_identity_binding and not settings.runtime_auto_bind_wallet_on_create_key:
        return

    wallet = _norm_wallet(wallet_address)
    if not wallet.startswith("0x") or len(wallet) < 10:
        raise HTTPException(status_code=400, detail="invalid wallet_address")

    profile = await _ensure_profile(db, karma_identity_id.strip())
    bound = _norm_wallet(profile.bound_wallet_address or "")

    if not bound:
        if settings.runtime_auto_bind_wallet_on_create_key:
            profile.bound_wallet_address = wallet
            profile.updated_at = datetime.utcnow()
            await db.flush()
            return
        if settings.runtime_require_wallet_identity_binding:
            raise HTTPException(
                status_code=403,
                detail="identity has no bound wallet — complete wallet binding in Console first",
            )
        return

    if bound != wallet:
        raise HTTPException(
            status_code=403,
            detail="wallet_address does not match bound wallet for this karma_identity_id",
        )


async def get_bound_wallet(db: AsyncSession, karma_identity_id: str) -> str | None:
    profile = await db.get(IdentityProfileModel, karma_identity_id)
    if not profile or not profile.bound_wallet_address:
        return None
    return profile.bound_wallet_address
