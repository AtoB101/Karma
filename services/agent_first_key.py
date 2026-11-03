"""Self-serve "first key": one-time challenge, device/IP binding, grant-gated upgrade.

A brand-new agent has no credential yet, so this flow is unauthenticated by
design. It mints a *restricted* bootstrap key (``scope=["grant:apply"]``) that can
only open the owner-approval handshake - it cannot spend, settle or mutate
anything. After the owner approves a spending grant, the agent calls ``upgrade``
with that restricted key to exchange it for a full-scope key, but only while an
active (non-expired) grant exists for that agent.

Three independent locks on the unauthenticated mint:

``device_id``   client-generated stable id; the claim must present the same one.
``ip``          server-observed address (``real_client_ip``); claim must match.
``challenge``   one-time nonce issued by the server and consumed on claim.

The challenge record is persisted to ``.karma_data/agent_first_key.json`` in the
same shape as ``agent_pairing`` / ``grant_approval``; only a SHA-256 digest of the
challenge is stored.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from services.agent_bootstrap_credentials import mint_agent_api_key, mint_restricted_api_key

_STORE_PATH = Path(__file__).resolve().parents[1] / ".karma_data" / "agent_first_key.json"

CHALLENGE_TTL_SECONDS = 300
FIRST_KEY_TTL_SECONDS = 86400
MAX_ATTEMPTS = 5
MAX_PENDING_PER_IP = 5
MAX_PENDING_PER_DEVICE = 3
MAX_RECORDS = 1000

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
    tmp.write_text(json.dumps(_RECORDS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(_STORE_PATH)


def reset_first_keys() -> None:
    """Test hook: forget every challenge, in memory and on disk."""
    global _LOADED
    with _LOCK:
        _RECORDS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


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


def _pending_count(field: str, value: str) -> int:
    return sum(
        1
        for row in _RECORDS.values()
        if str(row.get("status") or "") == "pending" and str(row.get(field) or "") == value
    )


def issue_challenge(*, device_id: str, ip: str, agent_name: str | None = None) -> dict[str, Any]:
    device = (device_id or "").strip()
    if not device:
        raise HTTPException(400, "device_id is required")
    if len(device) > 128:
        raise HTTPException(400, "device_id is too long")
    client_ip = (ip or "").strip()
    if not client_ip:
        raise HTTPException(400, "client address is required")

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        if _pending_count("device_id", device) >= MAX_PENDING_PER_DEVICE:
            raise HTTPException(429, "too many pending challenges for this device")
        if _pending_count("request_ip", client_ip) >= MAX_PENDING_PER_IP:
            raise HTTPException(429, "too many pending challenges from this address")

        challenge_id = secrets.token_hex(16)
        challenge = secrets.token_urlsafe(24)
        now = _utcnow()
        _RECORDS[challenge_id] = {
            "challenge_id": challenge_id,
            "challenge_sha256": _sha256_hex(challenge),
            "status": "pending",
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=CHALLENGE_TTL_SECONDS)),
            "attempts": 0,
            "device_id": device,
            "request_ip": client_ip,
            "agent_name": (agent_name or "").strip() or None,
            "agent_id": None,
            "claimed_at": None,
        }
        _persist_unlocked()

    return {
        "schema_version": "karma-agent-first-key-v1",
        "challenge_id": challenge_id,
        "challenge": challenge,
        "expires_in_seconds": CHALLENGE_TTL_SECONDS,
        "next_step": "POST /v1/agents/first-key/claim with challenge_id + challenge + device_id",
    }


def _require_pending_unlocked(row: dict[str, Any]) -> None:
    exp = _parse_iso(str(row.get("expires_at") or ""))
    if exp and exp <= _utcnow():
        row["status"] = "expired"
        _persist_unlocked()
        raise HTTPException(410, "challenge has expired")
    if str(row.get("status") or "") != "pending":
        raise HTTPException(409, f"challenge is already {row.get('status')}")


def _record_failed_attempt_unlocked(row: dict[str, Any]) -> None:
    row["attempts"] = int(row.get("attempts") or 0) + 1
    if int(row["attempts"]) >= MAX_ATTEMPTS:
        row["status"] = "expired"


def claim(*, challenge_id: str, challenge: str, device_id: str, ip: str) -> dict[str, Any]:
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _RECORDS.get((challenge_id or "").strip())
        if row is None:
            raise HTTPException(404, "challenge not found")
        _require_pending_unlocked(row)

        given = (challenge or "").strip()
        expected = str(row.get("challenge_sha256") or "")
        if not given or not hmac.compare_digest(_sha256_hex(given), expected):
            _record_failed_attempt_unlocked(row)
            _persist_unlocked()
            raise HTTPException(403, "challenge does not match")

        if (device_id or "").strip() != str(row.get("device_id") or ""):
            _record_failed_attempt_unlocked(row)
            _persist_unlocked()
            raise HTTPException(403, "device_id does not match the challenge")
        if (ip or "").strip() != str(row.get("request_ip") or ""):
            _record_failed_attempt_unlocked(row)
            _persist_unlocked()
            raise HTTPException(403, "client address does not match the challenge")

        agent_id = f"agent-{secrets.token_hex(6)}"
        issued = mint_restricted_api_key(
            agent_id,
            scope=["grant:apply"],
            ttl_seconds=FIRST_KEY_TTL_SECONDS,
        )

        row["status"] = "claimed"
        row["agent_id"] = agent_id
        row["claimed_at"] = _iso(_utcnow())
        _persist_unlocked()

    return {
        "schema_version": "karma-agent-first-key-v1",
        "agent_id": agent_id,
        "api_key": issued["api_key"],
        "api_key_hint": "store now; plaintext is not re-shown; TTL applies",
        "scope": issued["scope"],
        "expires_at": issued["expires_at"],
        "next_step": (
            "POST /v1/spending-grants/approval-request to ask your owner for a "
            "spending grant; once approved, POST /v1/agents/first-key/upgrade to "
            "exchange this key for full scope."
        ),
    }


async def upgrade(db, *, agent_id: str) -> dict[str, Any]:
    """Exchange a restricted first key for a full-scope key, grant-gated.

    The caller must already hold an *active* (non-expired) spending grant for
    ``agent_id``. On success the restricted key record is overwritten with a new
    full-scope secret, so the old restricted secret stops working immediately.
    """
    aid = (agent_id or "").strip()
    if not aid:
        raise HTTPException(401, "agent identity required")
    from services import spending_grant as grants

    rows = await grants.list_grants(db, agent_id=aid)
    active = [g for g in rows if g.status == "active" and not grants._expired(g)]
    if not active:
        raise HTTPException(403, "no active spending grant — ask your owner to approve one first")
    issued = mint_agent_api_key(aid)
    return {
        "schema_version": "karma-agent-first-key-v1",
        "agent_id": aid,
        "api_key": issued["api_key"],
        "api_key_hint": "store now; plaintext is not re-shown; this key has full scope",
        "scope": ["*"],
        "expires_at": None,
        "active_grants": len(active),
    }


def public_view(challenge_id: str) -> dict[str, Any]:
    """Read-only status for the claiming client (never leaks the challenge)."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _RECORDS.get((challenge_id or "").strip())
        if row is None:
            raise HTTPException(404, "challenge not found")
        return {
            "challenge_id": row.get("challenge_id"),
            "status": row.get("status"),
            "expires_in_seconds": max(
                0,
                int((_parse_iso(str(row.get("expires_at") or "")) - _utcnow()).total_seconds())
                if _parse_iso(str(row.get("expires_at") or "")) else 0,
            ),
            "attempts_left": max(0, MAX_ATTEMPTS - int(row.get("attempts") or 0)),
        }
