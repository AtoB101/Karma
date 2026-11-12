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
        }
        _persist_unlocked()
    return {
        "agent_id": aid,
        "api_key": api_key,
        "api_key_hint": "store now; plaintext is not re-shown",
    }


def verify_minted_api_key(agent_id: str, secret: str) -> bool:
    _ensure_loaded()
    with _LOCK:
        row = _KEYS.get(agent_id)
    if not row:
        return False
    expected = str(row.get("secret_sha256") or "")
    if not expected:
        return False
    return hmac.compare_digest(_sha256_hex(secret), expected)
