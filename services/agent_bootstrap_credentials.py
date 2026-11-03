"""Bootstrap API keys for one-click agent connect.

Plaintext secret is returned once at mint time. Only a SHA-256 hash is persisted
under ``.karma_data/agent_api_keys.json``. Auth middleware can verify minted keys
without putting secrets in ``AUTH_API_KEYS``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

_STORE_PATH = (
    Path(__file__).resolve().parents[1] / ".karma_data" / "agent_api_keys.json"
)
_LOCK = threading.Lock()
_LOADED = False
_KEYS: dict[str, dict[str, Any]] = {}


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
                    _KEYS.update({str(k): dict(v) for k, v in raw.items()})
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(_KEYS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def reset_bootstrap_keys() -> None:
    global _LOADED
    with _LOCK:
        _KEYS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def mint_agent_api_key(agent_id: str) -> dict[str, str]:
    """Mint ``karma_{agent_id}_{secret}``; persist hash only; return plaintext once."""
    aid = (agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id required")
    secret = secrets.token_urlsafe(24)
    api_key = f"karma_{aid}_{secret}"
    _ensure_loaded()
    with _LOCK:
        _KEYS[aid] = {
            "agent_id": aid,
            "secret_sha256": _sha256_hex(secret),
            "key_prefix": f"karma_{aid}_",
            "scope": ["*"],
            "expires_at": None,
        }
        _persist_unlocked()
    return {
        "agent_id": aid,
        "api_key": api_key,
        "api_key_hint": "store now; plaintext is not re-shown",
    }


def mint_restricted_api_key(
    agent_id: str,
    *,
    scope: list[str] | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, str]:
    """Mint a permission-scoped bootstrap key (the "first key").

    A restricted key can open the owner-approval handshake
    (``POST /v1/spending-grants/approval-request``) but is rejected by the auth
    middleware everywhere else - it cannot spend, settle or mutate anything.
    ``ttl_seconds`` hard-expires the key regardless of revocation.
    """
    aid = (agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id required")
    scopes = [str(s).strip() for s in (scope or ["grant:apply"]) if str(s).strip()]
    if not scopes:
        raise ValueError("scope must contain at least one permission")
    if "*" in scopes:
        raise ValueError("restricted key must not carry the '*' scope")
    secret = secrets.token_urlsafe(24)
    api_key = f"karma_{aid}_{secret}"
    expires_at = None
    if ttl_seconds is not None:
        if int(ttl_seconds) <= 0:
            raise ValueError("ttl_seconds must be positive")
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _ensure_loaded()
    with _LOCK:
        _KEYS[aid] = {
            "agent_id": aid,
            "secret_sha256": _sha256_hex(secret),
            "key_prefix": f"karma_{aid}_",
            "scope": scopes,
            "expires_at": expires_at,
        }
        _persist_unlocked()
    return {
        "agent_id": aid,
        "api_key": api_key,
        "api_key_hint": "store now; plaintext is not re-shown",
        "scope": scopes,
        "expires_at": expires_at,
    }


def minted_key_scope(agent_id: str) -> list[str]:
    """Permission scope of a minted key; legacy keys without a scope are full."""
    aid = (agent_id or "").strip()
    _ensure_loaded()
    with _LOCK:
        row = _KEYS.get(aid)
    if not row:
        return []
    scope = row.get("scope")
    if not scope:
        return ["*"]
    return [str(s) for s in scope]


def minted_key_expired(agent_id: str) -> bool:
    aid = (agent_id or "").strip()
    _ensure_loaded()
    with _LOCK:
        row = _KEYS.get(aid)
    if not row:
        return False
    return _row_expired(row)


def _row_expired(row: dict[str, Any]) -> bool:
    exp = row.get("expires_at")
    if not exp:
        return False
    try:
        when = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return False
    return datetime.now(timezone.utc) >= when


def revoke_minted_api_key(agent_id: str) -> bool:
    aid = (agent_id or "").strip()
    _ensure_loaded()
    with _LOCK:
        if aid in _KEYS:
            _KEYS.pop(aid, None)
            _persist_unlocked()
            return True
        return False


def has_minted_api_key(agent_id: str) -> bool:
    """Whether a bootstrap key exists for this agent (hash only — secret re-shown never)."""
    aid = (agent_id or "").strip()
    if not aid:
        return False
    _ensure_loaded()
    with _LOCK:
        return aid in _KEYS


def known_agent_ids() -> set[str]:
    """Every agent id with a minted bootstrap key (hashes only — no secrets)."""
    _ensure_loaded()
    with _LOCK:
        return set(_KEYS.keys())


def verify_minted_api_key(agent_id: str, secret: str) -> bool:
    _ensure_loaded()
    with _LOCK:
        row = _KEYS.get(agent_id)
        if not row:
            return False
        expected = str(row.get("secret_sha256") or "")
        if not expected or not hmac.compare_digest(_sha256_hex(secret), expected):
            return False
        return not _row_expired(row)
