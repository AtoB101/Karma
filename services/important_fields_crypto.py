"""Encrypt ImportantFields for wire submission (AES-256-GCM).

Ciphertext format (versioned):
  karma1.<base64url(nonce_12 || ciphertext_with_tag)>

Even if a submission is intercepted, an attacker only sees encrypted bytes
until they obtain the capture session key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.important_fields_standard import canonical_json


PREFIX = "karma1."


class FieldsCryptoError(ValueError):
    pass


def master_key_bytes() -> bytes:
    """32-byte master key from env or deterministic dev fallback (never use fallback in prod)."""
    raw = os.getenv("KARMA_IMPORTANT_FIELDS_KEY", "").strip()
    if raw:
        # Accept hex (64 chars) or arbitrary passphrase → SHA-256
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
        return hashlib.sha256(raw.encode("utf-8")).digest()
    # Dev-only fallback so local tests work without secrets.
    if os.getenv("KARMA_ENV", "dev").lower() in {"prod", "production"}:
        raise FieldsCryptoError("KARMA_IMPORTANT_FIELDS_KEY is required in production")
    return hashlib.sha256(b"karma-important-fields-dev-only").digest()


def capture_session_key(capture_id: str) -> bytes:
    """Per-capture key via HMAC-SHA256(master, capture_id)."""
    return hmac.new(master_key_bytes(), capture_id.encode("utf-8"), hashlib.sha256).digest()


def protocol_mac(message: str) -> str:
    return hmac.new(master_key_bytes(), message.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_canonical_fields(fields: dict[str, Any], *, capture_id: str) -> str:
    """Encrypt canonical JSON of fields under the capture session key."""
    key = capture_session_key(capture_id)
    plaintext = canonical_json(fields).encode("utf-8")
    nonce = os.urandom(12)
    aes = AESGCM(key)
    # AAD binds ciphertext to capture_id (prevents cross-capture replay)
    ct = aes.encrypt(nonce, plaintext, capture_id.encode("utf-8"))
    blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii").rstrip("=")
    return PREFIX + blob


def decrypt_canonical_fields(ciphertext: str, *, capture_id: str) -> dict[str, Any]:
    if not isinstance(ciphertext, str) or not ciphertext.startswith(PREFIX):
        raise FieldsCryptoError("ciphertext must use karma1. envelope")
    raw_b64 = ciphertext[len(PREFIX) :]
    pad = "=" * (-len(raw_b64) % 4)
    try:
        data = base64.urlsafe_b64decode(raw_b64 + pad)
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("invalid ciphertext encoding") from exc
    if len(data) < 12 + 16:
        raise FieldsCryptoError("ciphertext too short")
    nonce, ct = data[:12], data[12:]
    key = capture_session_key(capture_id)
    aes = AESGCM(key)
    try:
        plaintext = aes.decrypt(nonce, ct, capture_id.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("decryption failed (tampered or wrong capture)") from exc
    import json

    try:
        obj = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("decrypted payload is not JSON") from exc
    if not isinstance(obj, dict):
        raise FieldsCryptoError("decrypted payload must be an object")
    return obj
