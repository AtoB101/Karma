"""Agent self-service pairing (device-code style handshake).

A foreign agent asks to be connected, the wallet owner approves it in the
console, and the agent picks its credentials up by polling with the code it was
handed. Nobody copies a secret between two windows by hand.

Three codes live in a pairing record and they are **not** interchangeable:

``pairing_code``  held by the agent only; proves the poller is the same process
                  that opened the request. Returned once, at request time, and
                  persisted only as a SHA-256 hash.
``user_code``     short and human-typed (``K4QP-3M2X``) so the owner can match
                  the request on screen. Alone it grants nothing.
``delivery``      minted credentials, held server-side until the agent claims
                  them and wiped on claim — the one-shot rule the rest of the
                  platform already follows for bootstrap keys.

Escrow of the pending payload is deliberate: Karma already custodies the
agent's Ed25519 signer server-side (``services/agent_key_store.py``), so a
short-lived, single-claim secret store is not a new class of custody.
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

_STORE_PATH = Path(__file__).resolve().parents[1] / ".karma_data" / "agent_pairing.json"

#: How long the owner has to approve before the code dies on its own.
DEFAULT_TTL_SECONDS = 900
#: Console polls while waiting for approval.
POLL_INTERVAL_SECONDS = 3
#: One IP can have this many requests open at once (unauthenticated endpoint).
MAX_PENDING_PER_IP = 10
#: Hard cap on the store; oldest finished records are dropped first.
MAX_RECORDS = 500
#: No I/L/O/0/1: the owner may be reading this off a screen and typing it.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_USER_CODE_LEN = 8
_DEFAULT_BASE_URL = "https://karma-network.ai"

_LOCK = threading.Lock()
_LOADED = False
_RECORDS: dict[str, dict[str, Any]] = {}


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def client_bucket(ip: str) -> str:
    """Short digest of a client address — the per-IP cap does not need the raw IP."""
    raw = (ip or "").strip()
    return _sha256_hex(raw)[:32] if raw else ""


def normalize_requested_vertical(raw: str | None) -> str:
    """Map a vertical alias ("food") onto the catalog industry_id ("food_delivery").

    The console has to match the agent's request against its industry dropdown and
    render that industry's hard requirements, so the record stores the resolved
    industry_id. Aliases live in ``services/agent_one_click.py`` — the same table
    ``/v1/agents/owner-connect`` resolves against, so there is one answer, not two.
    An unknown value is kept as-is: the owner can still pick the industry by hand.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        from services.agent_one_click import VERTICAL_ALIASES
    except Exception:  # noqa: BLE001 - pairing must not fail on an import
        return value
    alias = VERTICAL_ALIASES.get(value.lower())
    if alias and alias.get("industry_id"):
        return str(alias["industry_id"])
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


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


def reset_pairings() -> None:
    """Test hook: forget every pairing, in memory and on disk."""
    global _LOADED
    with _LOCK:
        _RECORDS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def normalize_user_code(value: str) -> str:
    """``k4qp-3m2x`` / ``K4QP 3M2X`` / ``K4QP3M2X`` all mean the same code."""
    raw = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if len(raw) != _USER_CODE_LEN:
        return ""
    if any(ch not in _CODE_ALPHABET for ch in raw):
        return ""
    return raw[:4] + "-" + raw[4:]


def _user_code_key(user_code: str) -> str:
    return normalize_user_code(user_code).replace("-", "")


def _new_user_code() -> str:
    while True:
        body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_USER_CODE_LEN))
        code = body[:4] + "-" + body[4:]
        if _user_code_key(code) not in {_user_code_key(r.get("user_code", "")) for r in _RECORDS.values()}:
            return code


def _public_base_url() -> str:
    try:
        from config.settings import settings

        base = (getattr(settings, "public_runtime_base_url", "") or "").strip()
    except Exception:  # noqa: BLE001
        base = ""
    return (base or _DEFAULT_BASE_URL).rstrip("/")


def _public_key_fingerprint(public_key: str | None) -> str:
    key = (public_key or "").strip()
    if not key:
        return ""
    return _sha256_hex(key)[:16]


def _pending_for_ip(ip: str) -> int:
    return sum(
        1
        for row in _RECORDS.values()
        if row.get("status") == "pending" and str(row.get("request_ip") or "") == ip
    )


def _purge_expired_unlocked() -> int:
    """Mark timed-out requests expired and drop any credentials they still hold."""
    now = _utcnow()
    touched = 0
    for row in _RECORDS.values():
        if row.get("status") not in {"pending", "approved"}:
            continue
        exp = _parse_iso(str(row.get("expires_at") or ""))
        if exp is None or now <= exp:
            continue
        row["status"] = "expired"
        row["delivery"] = {}
        touched += 1
    if len(_RECORDS) > MAX_RECORDS:
        for key, _ in sorted(
            _RECORDS.items(), key=lambda kv: str(kv[1].get("created_at") or "")
        )[: len(_RECORDS) - MAX_RECORDS]:
            _RECORDS.pop(key, None)
        touched += 1
    if touched:
        _persist_unlocked()
    return touched


def _env_snippet(row: dict[str, Any]) -> dict[str, str]:
    delivery = dict(row.get("delivery") or {})
    env = {
        "KARMA_AGENT_ID": str(row.get("agent_id") or ""),
        "KARMA_RUNTIME_URL": _public_base_url(),
    }
    if delivery.get("api_key"):
        env["KARMA_API_KEY"] = str(delivery["api_key"])
    if delivery.get("runtime_key"):
        env["KARMA_RUNTIME_KEY"] = str(delivery["runtime_key"])
    return env


def _public_view(row: dict[str, Any]) -> dict[str, Any]:
    """What the console may see: never a pairing code, never a credential."""
    delivery = dict(row.get("delivery") or {})
    return {
        "pairing_id": row.get("pairing_id"),
        "user_code": row.get("user_code"),
        "status": row.get("status"),
        "agent_name": row.get("agent_name"),
        "platform": row.get("platform"),
        "public_key_fingerprint": row.get("public_key_fingerprint") or "",
        "endpoint_url": row.get("endpoint_url") or "",
        "self_description": row.get("self_description") or "",
        "requested_side": row.get("requested_side"),
        "requested_vertical": row.get("requested_vertical"),
        "requested_industry_id": row.get("requested_industry_id") or "",
        "requested_answers": dict(row.get("requested_answers") or {}),
        "created_at": row.get("created_at"),
        "expires_at": row.get("expires_at"),
        "approved_at": row.get("approved_at"),
        "claimed_at": row.get("claimed_at"),
        "agent_id": row.get("agent_id"),
        "owner_identity_id": row.get("owner_identity_id"),
        "has_api_key": bool(delivery.get("api_key")),
        "has_runtime_key": bool(delivery.get("runtime_key")),
        "runtime_key_id": delivery.get("runtime_key_id") or "",
        "deny_reason": row.get("deny_reason") or "",
    }


def create_request(
    *,
    agent_name: str,
    platform: str = "custom",
    public_key: str | None = None,
    endpoint_url: str | None = None,
    self_description: str | None = None,
    requested_side: str | None = None,
    requested_vertical: str | None = None,
    requested_answers: dict[str, Any] | None = None,
    request_ip: str = "",
) -> dict[str, Any]:
    """Open a pairing request. The pairing code is returned exactly once."""
    name = (agent_name or "").strip()
    if not name:
        raise HTTPException(400, "agent_name is required")

    pairing_id = secrets.token_hex(16)
    pairing_code = secrets.token_urlsafe(32)
    now = _utcnow()
    expires = now + timedelta(seconds=DEFAULT_TTL_SECONDS)

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        ip = (request_ip or "").strip()
        if ip and _pending_for_ip(ip) >= MAX_PENDING_PER_IP:
            raise HTTPException(
                429, "too many open pairing requests from this address — approve or wait them out"
            )
        user_code = _new_user_code()
        _RECORDS[pairing_id] = {
            "pairing_id": pairing_id,
            "user_code": user_code,
            "pairing_code_sha256": _sha256_hex(pairing_code),
            "status": "pending",
            "created_at": _iso(now),
            "expires_at": _iso(expires),
            "agent_name": name,
            "platform": (platform or "").strip()[:64] or "custom",
            "public_key": (public_key or "").strip()[:512],
            "public_key_fingerprint": _public_key_fingerprint(public_key),
            "endpoint_url": (endpoint_url or "").strip()[:2048],
            "self_description": (self_description or "").strip()[:2000],
            "requested_side": (requested_side or "").strip()[:16] or None,
            "requested_vertical": (requested_vertical or "").strip()[:64] or None,
            "requested_industry_id": normalize_requested_vertical(requested_vertical)[:64] or None,
            # The agent knows its own hard metrics better than the owner does, so
            # it declares them here and the owner only approves or rejects; the
            # P1 gate still validates them against the industry contract.
            "requested_answers": dict(requested_answers or {}),
            "request_ip": ip,
            "owner_identity_id": None,
            "agent_id": None,
            "approved_at": None,
            "claimed_at": None,
            "deny_reason": "",
            "delivery": {},
        }
        _persist_unlocked()

    return {
        "schema_version": "karma-agent-pairing-v1",
        "pairing_id": pairing_id,
        "pairing_code": pairing_code,
        "user_code": user_code,
        "verification_uri": f"{_public_base_url()}/console/?pair={user_code}",
        "expires_at": _iso(expires),
        "expires_in_seconds": DEFAULT_TTL_SECONDS,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "claim_endpoint": "/v1/agent-pairing/claim",
        "instructions_zh": (
            "把 user_code 告诉你的主人，请他在 Karma 操作台 · Agent 接入 · 配对 里批准；"
            "然后用 pairing_code 轮询 claim 端点领取凭据（只发一次，拿到就存好）。"
        ),
        "instructions_en": (
            "Show the user_code to your owner and ask them to approve it in the Karma "
            "console (Agents · Pairing). Then poll the claim endpoint with pairing_code; "
            "credentials are delivered exactly once."
        ),
    }


def _find_by_user_code(user_code: str) -> dict[str, Any] | None:
    key = _user_code_key(user_code)
    if not key:
        return None
    for row in _RECORDS.values():
        if _user_code_key(str(row.get("user_code") or "")) == key:
            return row
    return None


def _find_by_pairing_code(pairing_code: str) -> dict[str, Any] | None:
    token = (pairing_code or "").strip()
    if not token:
        return None
    digest = _sha256_hex(token)
    for row in _RECORDS.values():
        expected = str(row.get("pairing_code_sha256") or "")
        if expected and hmac.compare_digest(digest, expected):
            return row
    return None


def lookup_by_user_code(user_code: str) -> dict[str, Any]:
    """Owner-side view of a request, for the approval screen."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found — check it with the agent and retry")
        return _public_view(row)


def approve(
    *,
    user_code: str,
    owner_identity_id: str,
    agent_id: str,
    api_key: str | None = None,
    agent_public_key: str | None = None,
) -> dict[str, Any]:
    """Bind an approved pairing to the agent created for it."""
    owner = (owner_identity_id or "").strip()
    aid = (agent_id or "").strip()
    if not owner or not aid:
        raise HTTPException(400, "owner_identity_id and agent_id are required")

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found — check it with the agent and retry")
        status = str(row.get("status") or "")
        if status != "pending":
            # Approving twice must not mint a second agent for the same request.
            raise HTTPException(409, f"pairing is already {status}")
        row["status"] = "approved"
        row["owner_identity_id"] = owner
        row["agent_id"] = aid
        row["approved_at"] = _iso(_utcnow())
        delivery: dict[str, Any] = dict(row.get("delivery") or {})
        if api_key:
            delivery["api_key"] = api_key
        if agent_public_key:
            delivery["agent_public_key"] = agent_public_key
        row["delivery"] = delivery
        _persist_unlocked()
        # Never hand the console the payload: the whole point is that the agent
        # collects it. The owner screen only gets "is it there yet".
        return _public_view(row)


def deny(*, user_code: str, owner_identity_id: str, reason: str = "") -> dict[str, Any]:
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found")
        if str(row.get("status") or "") != "pending":
            raise HTTPException(409, f"pairing is already {row.get('status')}")
        row["status"] = "denied"
        row["owner_identity_id"] = (owner_identity_id or "").strip() or None
        row["deny_reason"] = (reason or "").strip()[:200]
        row["delivery"] = {}
        _persist_unlocked()
        return _public_view(row)


def attach_runtime_key(
    *,
    user_code: str,
    owner_identity_id: str,
    runtime_key: str,
    runtime_key_id: str,
) -> dict[str, Any]:
    """Park an already-minted runtime key in this pairing's one-shot delivery."""
    token = (runtime_key or "").strip()
    if not token:
        raise HTTPException(400, "runtime_key is required")

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found")
        status = str(row.get("status") or "")
        if status == "pending":
            raise HTTPException(409, "approve the pairing before attaching a runtime key")
        if status != "approved":
            raise HTTPException(409, f"pairing is already {status}")
        if (owner_identity_id or "").strip() != str(row.get("owner_identity_id") or ""):
            raise HTTPException(403, "this pairing belongs to another identity")
        delivery = dict(row.get("delivery") or {})
        delivery["runtime_key"] = token
        delivery["runtime_key_id"] = (runtime_key_id or "").strip()
        row["delivery"] = delivery
        _persist_unlocked()
        return _public_view(row)


def claim(*, pairing_code: str) -> dict[str, Any]:
    """Agent side. Credentials are handed over once and then gone."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_pairing_code(pairing_code)
        if row is None:
            raise HTTPException(404, "unknown pairing_code")
        status = str(row.get("status") or "")
        if status == "pending":
            return {
                "status": "pending",
                "poll_interval_seconds": POLL_INTERVAL_SECONDS,
                "expires_at": row.get("expires_at"),
                "message_zh": "主人还没批准。请把这个 user_code 给他，并稍后重试。",
                "message_en": "Not approved yet. Give your owner the user_code and retry.",
            }
        if status != "approved":
            return {
                "status": status,
                "message_zh": "这次配对没有可交付的凭据。",
                "message_en": "This pairing has nothing left to deliver.",
            }

        delivery = dict(row.get("delivery") or {})
        env = _env_snippet(row)
        row["status"] = "claimed"
        row["claimed_at"] = _iso(_utcnow())
        # One shot: the plaintext leaves the store the moment it is handed over.
        row["delivery"] = {}
        _persist_unlocked()

    return {
        "schema_version": "karma-agent-pairing-claim-v1",
        "status": "approved",
        "agent_id": row.get("agent_id"),
        "owner_identity_id": row.get("owner_identity_id"),
        "credentials": {
            "api_key": delivery.get("api_key"),
            "agent_public_key": delivery.get("agent_public_key"),
            "runtime_key": delivery.get("runtime_key"),
            "runtime_key_id": delivery.get("runtime_key_id") or None,
            "store_now": True,
        },
        "env_snippet": env,
        "next_steps": [
            "export KARMA_AGENT_ID / KARMA_API_KEY (and KARMA_RUNTIME_KEY when granted)",
            "GET /v1/agents/mine with X-Karma-Api-Key to confirm the identity resolves",
            "GET /runtime/policy with X-Karma-Runtime-Key to read the granted limits",
        ],
        "note_zh": "凭据只在这一次返回，服务端已不再保留明文；丢失就要重新配对。",
    }


def list_for_owner(owner_identity_id: str) -> list[dict[str, Any]]:
    owner = (owner_identity_id or "").strip()
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        rows = [
            row for row in _RECORDS.values() if str(row.get("owner_identity_id") or "") == owner
        ]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return [_public_view(r) for r in rows]
