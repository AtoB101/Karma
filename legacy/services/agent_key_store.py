"""Owner-bound agent Ed25519 key store (server-side, revocable).

The console "owner-connect" path mints one operational keypair per agent the
owner is connecting. The private key never leaves the server: it is written to
``<repo>/.karma_data/agent_keys/<agent_id>.json`` with mode 0600 and is used for
exactly two things:

1. the P1 ownership proof (proof-of-possession over the connect challenge), and
2. the owner-signed responsibility ack.

This key is **not** the owner's wallet key. It has no relationship to any wallet,
mnemonic or user secret; it is a service credential equivalent in custody to the
bootstrap API key minted alongside it, and it can be revoked at any time.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_DEFAULT_STORE_DIR = Path(__file__).resolve().parents[1] / ".karma_data" / "agent_keys"
_LOCK = threading.Lock()


def _store_dir() -> Path:
    """Resolved lazily so tests (and alternate deployments) can redirect it."""
    override = (os.environ.get("KARMA_AGENT_KEY_DIR") or "").strip()
    return Path(override) if override else _DEFAULT_STORE_DIR

# Same shape the API-key parser and the directory accept, minus underscores:
# ``karma_{agent_id}_{secret}`` is split with maxsplit=2, so an underscore in the
# agent id would corrupt the parsed key.
_SAFE_AGENT_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9-]{1,63}\Z")


class AgentKeyError(ValueError):
    """Raised for malformed agent ids or unreadable key material."""


def _validate(agent_id: str) -> str:
    aid = (agent_id or "").strip()
    if not _SAFE_AGENT_ID.match(aid):
        raise AgentKeyError("agent_id must match [A-Za-z0-9][A-Za-z0-9-]{1,63}")
    return aid


def _path(agent_id: str) -> Path:
    return _store_dir() / f"{_validate(agent_id)}.json"


def new_agent_id(prefix: str = "agent") -> str:
    """Deterministic-shape id so the API-key parser can always split it back."""
    return f"{prefix}-{secrets.token_hex(6)}"


class AgentSigner:
    """Minimal signer surface shared with ``services.signing``."""

    def __init__(self, agent_id: str, private: Ed25519PrivateKey) -> None:
        self.agent_id = agent_id
        self._private = private
        self._public = private.public_key()

    @property
    def public_key_b64(self) -> str:
        raw = self._public.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return base64.b64encode(raw).decode()

    def sign_bytes(self, data: bytes) -> str:
        return base64.b64encode(self._private.sign(data)).decode()

    def sign_text(self, text: str) -> str:
        return self.sign_bytes(text.encode("utf-8"))


def mint_agent_key(agent_id: str) -> dict[str, Any]:
    """Create (or overwrite) the operational keypair for ``agent_id``."""
    aid = _validate(agent_id)
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    record = {
        "schema_version": "karma-agent-key-v1",
        "agent_id": aid,
        "private_key_b64": base64.b64encode(raw).decode(),
        "public_key_b64": base64.b64encode(
            private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode(),
        "created_at": _now(),
    }
    with _LOCK:
        _store_dir().mkdir(parents=True, exist_ok=True)
        path = _path(aid)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    return {
        "agent_id": aid,
        "public_key": record["public_key_b64"],
        "created_at": record["created_at"],
        "key_fingerprint": record["public_key_b64"][:16],
        "custody": "server_side_revocable",
    }


def mint_agent_signer(agent_id: str) -> tuple[AgentSigner, dict[str, Any]]:
    """Mint a keypair and hand back a ready-to-use signer plus public metadata."""
    info = mint_agent_key(agent_id)
    signer = load_agent_signer(agent_id)
    if signer is None:
        raise AgentKeyError("failed to load freshly minted agent key")
    return signer, info


def load_agent_signer(agent_id: str) -> AgentSigner | None:
    try:
        path = _path(agent_id)
    except AgentKeyError:
        return None
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        raw = base64.b64decode(str(record["private_key_b64"]))
        return AgentSigner(str(record.get("agent_id") or agent_id), Ed25519PrivateKey.from_private_bytes(raw))
    except Exception:  # noqa: BLE001
        return None


def has_agent_key(agent_id: str) -> bool:
    try:
        return _path(agent_id).is_file()
    except AgentKeyError:
        return False


def revoke_agent_key(agent_id: str) -> bool:
    try:
        path = _path(agent_id)
    except AgentKeyError:
        return False
    with _LOCK:
        if not path.is_file():
            return False
        path.unlink()
        return True


def list_agent_keys() -> list[dict[str, Any]]:
    store = _store_dir()
    if not store.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(store.glob("*.json")):
        try:
            record = json.loads(child.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out.append(
            {
                "agent_id": record.get("agent_id") or child.stem,
                "public_key": record.get("public_key_b64"),
                "created_at": record.get("created_at"),
            }
        )
    return out


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")