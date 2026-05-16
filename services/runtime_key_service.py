"""Runtime Key issuance, verification, and lightweight spend / replay tracking."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import RuntimeKeyModel


ALLOWED_PERMISSIONS = frozenset(
    {
        "request_voucher",
        "verify_voucher",
        "submit_receipt",
        "update_progress",
        "request_settlement",
        "sync_task_status",
    }
)

# In-process replay / idempotency (single worker — use Redis in multi-instance production).
_replay: dict[str, deque[tuple[str, float]]] = defaultdict(deque)
_DAILY: dict[str, dict[str, float]] = defaultdict(dict)  # key_id -> iso_date -> cumulative amount


def _server_material() -> bytes:
    return (settings.app_secret_key + ":karma_runtime_key_v1").encode()


def hash_runtime_secret(*, key_id: str, secret: str) -> str:
    return hmac.new(_server_material(), f"{key_id}:{secret}".encode(), hashlib.sha256).hexdigest()


def verify_runtime_secret(*, key_id: str, secret: str, secret_hash: str) -> bool:
    expect = hash_runtime_secret(key_id=key_id, secret=secret)
    return hmac.compare_digest(expect, secret_hash)


def parse_runtime_key_token(token: str) -> tuple[str, str]:
    raw = (token or "").strip()
    if not raw.startswith("KRM_RT_"):
        raise HTTPException(status_code=401, detail="invalid runtime key format")
    rest = raw[len("KRM_RT_") :]
    try:
        sep = rest.index("_")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid runtime key format") from exc
    key_id, secret = rest[:sep], rest[sep + 1 :]
    if len(key_id) != 32 or not all(c in "0123456789abcdef" for c in key_id.lower()):
        raise HTTPException(status_code=401, detail="invalid runtime key id segment")
    if len(secret) != 64 or not all(c in "0123456789abcdef" for c in secret.lower()):
        raise HTTPException(status_code=401, detail="invalid runtime key secret segment")
    return key_id, secret.lower()


def normalize_permissions(perms: Iterable[str]) -> list[str]:
    out = sorted({p.strip() for p in perms if (p or "").strip()})
    for p in out:
        if p not in ALLOWED_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"unknown or disallowed permission: {p}")
    if not out:
        raise HTTPException(status_code=400, detail="permissions must be a non-empty subset of allowed scopes")
    return out


def assert_permission(ctx: "RuntimeKeyContext", permission: str) -> None:
    if permission not in ctx.permissions:
        raise HTTPException(status_code=403, detail=f"runtime key missing permission: {permission}")


def check_replay_nonce(*, key_id: str, endpoint: str, nonce: str, ttl_seconds: int = 600) -> None:
    if not nonce or len(nonce) > 128:
        raise HTTPException(status_code=400, detail="client_nonce is required (max 128 chars)")
    bucket = _replay[key_id]
    now = time.monotonic()
    while bucket and now - bucket[0][1] > ttl_seconds:
        bucket.popleft()
    tag = f"{endpoint}:{nonce}"
    if any(existing == tag for existing, _ in bucket):
        raise HTTPException(status_code=409, detail="duplicate client_nonce (replay protection)")
    bucket.append((tag, now))
    while len(bucket) > 2000:
        bucket.popleft()


def check_single_and_daily_limits(
    *,
    key_id: str,
    amount: float,
    single_limit: float,
    daily_limit: float,
    daily_used: float | None = None,
) -> None:
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if amount > single_limit + 1e-9:
        raise HTTPException(status_code=403, detail="amount exceeds runtime key single_limit")
    today = date.today().isoformat()
    used = float(daily_used) if daily_used is not None else float(_DAILY[key_id].get(today, 0.0))
    if used + amount > daily_limit + 1e-9:
        raise HTTPException(status_code=403, detail="amount exceeds runtime key daily_limit")


def record_daily_spend(*, key_id: str, amount: float) -> None:
    today = date.today().isoformat()
    _DAILY[key_id][today] = _DAILY[key_id].get(today, 0.0) + amount


def get_daily_used(key_id: str) -> float:
    today = date.today().isoformat()
    return float(_DAILY.get(key_id, {}).get(today, 0.0))


@dataclass
class RuntimeKeyContext:
    key_id: str
    karma_identity_id: str
    wallet_address: str
    permissions: list[str]
    single_limit: float
    daily_limit: float
    expire_at: datetime
    agent_name: str
    status: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def load_active_context(*, db: AsyncSession, token: str) -> RuntimeKeyContext:
    key_id, secret = parse_runtime_key_token(token)
    row = await db.get(RuntimeKeyModel, key_id)
    if not row or row.status != "active":
        raise HTTPException(status_code=401, detail="invalid or revoked runtime key")
    if not verify_runtime_secret(key_id=key_id, secret=secret, secret_hash=row.secret_hash):
        raise HTTPException(status_code=401, detail="invalid runtime key")
    exp = _as_utc(row.expire_at)
    if _utcnow() > exp + timedelta(seconds=30):
        raise HTTPException(status_code=401, detail="runtime key expired")
    return RuntimeKeyContext(
        key_id=row.key_id,
        karma_identity_id=row.karma_identity_id,
        wallet_address=row.wallet_address,
        permissions=list(row.permissions or []),
        single_limit=float(row.single_limit),
        daily_limit=float(row.daily_limit),
        expire_at=exp,
        agent_name=row.agent_name,
        status=row.status,
    )


async def create_runtime_key_record(
    *,
    db: AsyncSession,
    wallet_address: str,
    karma_identity_id: str,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
    expire_at: datetime,
    agent_name: str,
    agent_binding: str | None,
) -> tuple[str, RuntimeKeyModel]:
    if single_limit <= 0 or daily_limit <= 0:
        raise HTTPException(status_code=400, detail="single_limit and daily_limit must be > 0")
    if daily_limit + 1e-9 < single_limit:
        raise HTTPException(status_code=400, detail="daily_limit must be >= single_limit")
    perms = normalize_permissions(permissions)
    key_id = secrets.token_hex(16)
    secret = secrets.token_hex(32)
    token = f"KRM_RT_{key_id}_{secret}"
    sh = hash_runtime_secret(key_id=key_id, secret=secret)
    row = RuntimeKeyModel(
        key_id=key_id,
        secret_hash=sh,
        wallet_address=wallet_address.strip(),
        karma_identity_id=karma_identity_id.strip(),
        permissions=perms,
        single_limit=single_limit,
        daily_limit=daily_limit,
        expire_at=expire_at,
        agent_name=agent_name.strip() or "agent",
        agent_binding=(agent_binding or "").strip() or None,
        status="active",
    )
    db.add(row)
    await db.flush()
    return token, row


async def revoke_runtime_key(
    *,
    db: AsyncSession,
    key_id: str,
) -> RuntimeKeyModel | None:
    row = await db.get(RuntimeKeyModel, key_id)
    if not row:
        return None
    if row.status == "active":
        row.status = "revoked"
        row.revoked_at = datetime.utcnow()
        await db.flush()
    return row


async def list_runtime_keys_for_identity(
    *,
    db: AsyncSession,
    karma_identity_id: str,
) -> list[RuntimeKeyModel]:
    res = await db.execute(
        select(RuntimeKeyModel)
        .where(RuntimeKeyModel.karma_identity_id == karma_identity_id)
        .order_by(RuntimeKeyModel.created_at.desc())
    )
    return list(res.scalars().all())
