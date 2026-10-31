"""Owner-facing spending grant approval (device-flow style handshake).

An agent wants a budgeted spending grant. It opens an approval request; the
server returns a short confirmation code plus an official-domain approval URI.
The owner opens the URI, cross-checks the confirmation code against the one the
agent showed in the chat, reviews the grant terms, connects a wallet, signs the
canonical grant message, and the grant is created only after the signature and
the code both verify.

Nothing alone is enough:

``challenge_id``       unguessable capability carried in the approval URI.
``confirmation_code``  human-typed 8-char code the agent shows and the owner
                       retypes on the official page - proves both sides are in
                       the same conversation.
``wallet_signature``   EIP-191 over the exact grant terms - proves the owner
                       really approved *these* terms with *this* wallet.

The challenge record is persisted to ``.karma_data/grant_approval.json`` in the
same shape as ``agent_pairing`` persists its records; the confirmation code is
stored only as a SHA-256 digest, and the owner's identity is resolved from the
signing wallet via ``identity_wallet_binding`` - never self-asserted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from services import spending_grant as grants
from services.identity_wallet_binding import resolve_identity_id_by_wallet
from services.runtime_wallet import verify_personal_message

_STORE_PATH = Path(__file__).resolve().parents[1] / ".karma_data" / "grant_approval.json"

#: How long the owner has to approve before the challenge dies on its own.
DEFAULT_TTL_SECONDS = 900
#: Wrong confirmation code or wrong wallet signature both burn one attempt.
MAX_ATTEMPTS = 5
#: Hard cap on the store; oldest finished records are dropped first.
MAX_RECORDS = 500
#: No I/L/O/0/1: the owner may be reading this off a chat and typing it.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8

_DEFAULT_BASE_URL = "https://karma-network.ai"

_LOCK = threading.Lock()
_LOADED = False
_RECORDS: dict[str, dict[str, Any]] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _public_base_url() -> str:
    try:
        from config.settings import settings

        base = (getattr(settings, "public_runtime_base_url", "") or "").strip()
    except Exception:  # noqa: BLE001
        base = ""
    return (base or _DEFAULT_BASE_URL).rstrip("/")


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        if _STORE_PATH.is_file():
            try:
                raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _RECORDS.update(
                        {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
                    )
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(_RECORDS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(tmp, 0o600)
    except Exception:  # noqa: BLE001
        pass
    tmp.replace(_STORE_PATH)


def _purge_expired_unlocked() -> None:
    now = _utcnow()
    for row in _RECORDS.values():
        if str(row.get("status") or "") != "pending":
            continue
        exp = _parse_iso(str(row.get("expires_at") or ""))
        if exp and exp <= now:
            row["status"] = "expired"
    if len(_RECORDS) > MAX_RECORDS:
        ordered = sorted(
            _RECORDS.values(),
            key=lambda r: _parse_iso(str(r.get("created_at") or "")) or _utcnow(),
            reverse=True,
        )
        keep = {str(r["challenge_id"]) for r in ordered[:MAX_RECORDS]}
        for key in list(_RECORDS.keys()):
            if key not in keep:
                _RECORDS.pop(key, None)


def reset_grant_approvals() -> None:
    """Test hook: forget every challenge, in memory and on disk."""
    global _LOADED
    with _LOCK:
        _RECORDS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def normalize_confirmation_code(value: str) -> str:
    """``k4qp-3m2x`` / ``K4QP 3M2X`` / ``K4QP3M2X`` all mean the same code."""
    raw = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if len(raw) != _CODE_LEN:
        return ""
    if any(ch not in _CODE_ALPHABET for ch in raw):
        return ""
    return raw[:4] + "-" + raw[4:]


def _confirmation_key(value: str) -> str:
    return normalize_confirmation_code(value).replace("-", "")


def _new_confirmation_code() -> str:
    while True:
        body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
        code = body[:4] + "-" + body[4:]
        if not any(
            _confirmation_key(r.get("confirmation_code", "")) == _confirmation_key(code)
            for r in _RECORDS.values()
        ):
            return code


def _find_by_challenge_id(challenge_id: str) -> dict[str, Any] | None:
    return _RECORDS.get((challenge_id or "").strip())


def _public_view(row: dict[str, Any]) -> dict[str, Any]:
    exp = _parse_iso(str(row.get("expires_at") or ""))
    now = _utcnow()
    attempts = int(row.get("attempts") or 0)
    return {
        "schema_version": "karma-spending-grant-approval-v1",
        "challenge_id": row.get("challenge_id"),
        "status": row.get("status"),
        "expires_at": row.get("expires_at"),
        "expires_in_seconds": max(0, int((exp - now).total_seconds())) if exp else 0,
        "attempts_left": max(0, MAX_ATTEMPTS - attempts),
        "agent_id": row.get("agent_id"),
        "agent_name": row.get("agent_name"),
        "agent_public_key_fingerprint": row.get("agent_public_key_fingerprint"),
        "currency": row.get("currency") or "USDC",
        "token_address": row.get("token_address"),
        "total_limit": row.get("total_limit"),
        "per_tx_limit": row.get("per_tx_limit"),
        "purpose_scope": list(row.get("purpose_scope") or []),
        "grant_expires_at": row.get("grant_expires_at"),
    }




def _grant_terms_unlocked(row: dict[str, Any], wallet_address: str) -> dict[str, Any]:
    """Rebuild the canonical grant terms exactly as ``create_grant`` will see them.

    One single source for both the sign-message endpoint and the approve step, so
    the message the owner signs is byte-for-byte the message the server verifies.
    """
    return dict(
        grant_id=str(row.get("grant_id") or ""),
        wallet_address=wallet_address,
        agent_id=str(row.get("agent_id") or ""),
        agent_public_key=str(row.get("agent_public_key") or "") or None,
        currency=str(row.get("currency") or "USDC"),
        token_address=row.get("token_address"),
        total_limit=float(row.get("total_limit") or 0),
        per_tx_limit=float(row.get("per_tx_limit") or 0),
        purpose_scope=list(row.get("purpose_scope") or []),
        expires_at=row.get("grant_expires_at"),
        nonce=str(row.get("nonce") or ""),
    )


def _require_pending_unlocked(row: dict[str, Any]) -> None:
    exp = _parse_iso(str(row.get("expires_at") or ""))
    if exp and exp <= _utcnow():
        row["status"] = "expired"
        _persist_unlocked()
        raise HTTPException(410, "approval request has expired")
    if str(row.get("status") or "") != "pending":
        raise HTTPException(409, f"approval request is already {row.get('status')}")


def sign_message_for(challenge_id: str, wallet_address: str) -> str:
    """The exact EIP-191 text the owner must sign for this wallet address."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_challenge_id(challenge_id)
        if row is None:
            raise HTTPException(404, "approval request not found — check the link with the agent")
        _require_pending_unlocked(row)
        return grants.build_grant_message(**_grant_terms_unlocked(row, wallet_address))


def _record_failed_attempt_unlocked(row: dict[str, Any]) -> None:
    row["attempts"] = int(row.get("attempts") or 0) + 1
    if int(row["attempts"]) >= MAX_ATTEMPTS:
        row["status"] = "expired"
        row["deny_reason"] = "too many failed attempts"


def issue_grant_approval(
    *,
    agent_id: str,
    agent_name: str,
    agent_public_key: str | None,
    currency: str,
    token_address: str | None,
    total_limit: float,
    per_tx_limit: float,
    purpose_scope: list[str],
    expires_at: str | None,
) -> dict[str, Any]:
    """Open an approval request. The confirmation code is returned exactly once."""
    name = (agent_name or "").strip()
    if not name:
        raise HTTPException(400, "agent_name is required")
    if total_limit <= 0:
        raise HTTPException(400, "total_limit must be positive")
    if per_tx_limit <= 0:
        raise HTTPException(400, "per_tx_limit must be positive")
    if per_tx_limit > total_limit:
        raise HTTPException(400, "per_tx_limit cannot exceed total_limit")

    from services.runtime_key_service import agent_binding_fingerprint

    fingerprint = ""
    if agent_public_key:
        try:
            fingerprint = agent_binding_fingerprint(agent_public_key)
        except Exception:  # noqa: BLE001
            fingerprint = ""

    challenge_id = secrets.token_hex(16)
    confirmation_code = _new_confirmation_code()
    grant_id = "grant_" + secrets.token_hex(8)
    nonce = secrets.token_urlsafe(12)
    now = _utcnow()

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        _RECORDS[challenge_id] = {
            "challenge_id": challenge_id,
            "confirmation_code_sha256": _sha256_hex(_confirmation_key(confirmation_code)),
            "status": "pending",
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=DEFAULT_TTL_SECONDS)),
            "attempts": 0,
            "grant_id": grant_id,
            "nonce": nonce,
            "agent_id": (agent_id or "").strip(),
            "agent_name": name,
            "agent_public_key": (agent_public_key or "").strip(),
            "agent_public_key_fingerprint": fingerprint,
            "currency": (currency or "USDC").strip() or "USDC",
            "token_address": (token_address or "").strip() or None,
            "total_limit": float(total_limit),
            "per_tx_limit": float(per_tx_limit),
            "purpose_scope": [str(p).strip() for p in (purpose_scope or []) if str(p).strip()],
            "grant_expires_at": (expires_at or "").strip() or None,
            "owner_wallet_address": None,
            "owner_identity_id": None,
            "approved_at": None,
            "grant_created": False,
            "deny_reason": "",
        }
        _persist_unlocked()

    return {
        "schema_version": "karma-spending-grant-approval-v1",
        "challenge_id": challenge_id,
        "confirmation_code": confirmation_code,
        "approval_uri": f"{_public_base_url()}/console/pages/grant-approval/?challenge={challenge_id}",
        "expires_at": _iso(now + timedelta(seconds=DEFAULT_TTL_SECONDS)),
        "expires_in_seconds": DEFAULT_TTL_SECONDS,
        "instructions_zh": (
            "① 把 confirmation_code 展示给你的主人；"
            "② 请他在官方域审批页打开 approval_uri，核对 agent 名称、公钥指纹与额度；"
            "③ 主人在页面输入同一串核对码、连接钱包签名，签名通过后授权才生效。"
        ),
        "instructions_en": (
            "1) Show confirmation_code to your owner. 2) Ask them to open approval_uri "
            "on the official domain and review the agent name, public-key fingerprint "
            "and limits. 3) The owner retypes the same code and signs with their wallet; "
            "the grant only takes effect once the signature verifies."
        ),
    }


def public_view(challenge_id: str) -> dict[str, Any]:
    """Owner-side read of a pending request, for the official approval page."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_challenge_id(challenge_id)
        if row is None:
            raise HTTPException(404, "approval request not found — check the link with the agent")
        return _public_view(row)


async def approve_grant_approval(
    db: AsyncSession,
    *,
    challenge_id: str,
    confirmation_code: str,
    wallet_address: str,
    wallet_signature: str,
) -> dict[str, Any]:
    """Verify the owner's code + wallet signature, then create the grant."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_challenge_id(challenge_id)
        if row is None:
            raise HTTPException(404, "approval request not found — check the link with the agent")
        _require_pending_unlocked(row)

        given = _confirmation_key(confirmation_code or "")
        expected = str(row.get("confirmation_code_sha256") or "")
        if not given or not hmac.compare_digest(_sha256_hex(given), expected):
            _record_failed_attempt_unlocked(row)
            _persist_unlocked()
            raise HTTPException(403, "confirmation code does not match the one shown by the agent")

        terms = _grant_terms_unlocked(row, wallet_address)
        message = grants.build_grant_message(**terms)
        try:
            verify_personal_message(
                message=message,
                wallet_address=wallet_address,
                wallet_signature=wallet_signature,
            )
        except HTTPException:
            _record_failed_attempt_unlocked(row)
            _persist_unlocked()
            raise

    owner_identity_id = await resolve_identity_id_by_wallet(db, wallet_address)
    if not owner_identity_id:
        raise HTTPException(
            403,
            "wallet is not bound to a Karma identity — connect this wallet in the console first",
        )

    grant = await grants.create_grant(
        db,
        owner_identity_id=owner_identity_id,
        wallet_signature=wallet_signature,
        agent_name=(str(row.get("agent_name") or "").strip() or None),
        **terms,
    )

    with _LOCK:
        row["status"] = "approved"
        row["owner_wallet_address"] = (wallet_address or "").strip().lower()
        row["owner_identity_id"] = owner_identity_id
        row["approved_at"] = _iso(_utcnow())
        row["grant_created"] = True
        _persist_unlocked()

    return grants._grant_to_dict(grant)