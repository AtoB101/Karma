"""Agent-side Runtime Key binding: the Ed25519 key + the per-request signature.

Why this exists. A Runtime Key is a bearer token: whoever holds ``KRM_RT_...`` can spend
the owner's money within its limits. Karma therefore refuses to serve *any* key that is
not bound to an agent public key and activated by the owner with the 8-character
matching code. So an agent process must be able to

  (a) present its Ed25519 public key (``POST /runtime/bind-key``), and
  (b) sign every ``/runtime/*`` request (``X-Karma-Agent-Signature`` + timestamp + nonce).

This mirrors ``sdk/runtime_client.py`` and, on the server side,
``services/runtime_wallet.build_agent_request_message``. Both sides are pinned against
each other by tests so the format cannot drift.

Env:
  KARMA_AGENT_PRIVATE_KEY  base64(32 raw bytes) or 64-char hex -- never leaves this process
  KARMA_AGENT_ID           the agent id the owner authorized (falls back to what the key was minted for)
"""
from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any


def runtime_key_id(token: str) -> str:
    """Pull the key_id out of ``KRM_RT_<key_id>_<secret>`` (the signature message needs it)."""
    raw = (token or "").strip()
    if not raw.startswith("KRM_RT_"):
        return ""
    head, _, _ = raw[len("KRM_RT_") :].partition("_")
    return head


def agent_key_from_seed(seed: str):
    """base64(raw 32 bytes) or 64-char hex -> Ed25519PrivateKey."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    text = (seed or "").strip()
    if not text:
        raise ValueError("agent private key is empty")
    if len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text):
        raw = bytes.fromhex(text)
    else:
        raw = base64.b64decode(text, validate=True)
    if len(raw) != 32:
        raise ValueError("agent private key must be 32 raw bytes (base64 or hex seed)")
    return Ed25519PrivateKey.from_private_bytes(raw)


def agent_key_from_env() -> Any | None:
    """The agent's Ed25519 key, or None when ``KARMA_AGENT_PRIVATE_KEY`` is unset."""
    seed = (os.environ.get("KARMA_AGENT_PRIVATE_KEY") or "").strip()
    if not seed:
        return None
    return agent_key_from_seed(seed)


def agent_id_from_env() -> str:
    return (os.environ.get("KARMA_AGENT_ID") or "").strip()


def agent_public_key_b64(key: Any) -> str:
    """Ed25519 public key as base64 of the raw 32 bytes -- the shape the server stores."""
    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode()


def build_agent_request_message(
    *, key_id: str, method: str, path: str, timestamp: str, nonce: str, body_sha256: str
) -> str:
    """The exact text the server recomputes. Do not reorder these lines."""
    return "\n".join(
        [
            "Karma Runtime Request",
            "key_id:" + key_id,
            "method:" + method.upper(),
            "path:" + path,
            "timestamp:" + timestamp,
            "nonce:" + nonce,
            "body_sha256:" + body_sha256,
        ]
    )


def sign_runtime_request(
    *, key: Any, key_id: str, method: str, path: str, body: bytes
) -> dict[str, str]:
    """The three headers a bound key has to carry on every request."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    message = build_agent_request_message(
        key_id=key_id,
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=hashlib.sha256(body or b"").hexdigest(),
    )
    signature = base64.b64encode(key.sign(message.encode("utf-8"))).decode()
    return {
        "X-Karma-Agent-Signature": signature,
        "X-Karma-Runtime-Timestamp": timestamp,
        "X-Karma-Runtime-Nonce": nonce,
    }
