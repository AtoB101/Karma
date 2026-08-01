"""Encrypt ImportantFields for wire submission (AES-256-GCM, high-assurance).

Envelope versions
-----------------
- ``karma2.`` (preferred): AAD = capture_id|scene_id|role|protocol_fields_hash
  Session key = HKDF(master, info=aes|capture_id|role) — role-separated keys
- ``karma1.`` (legacy decrypt only): AAD = capture_id; HMAC session key

Even if a submission is intercepted, an attacker only sees encrypted bytes
until they obtain the *role-specific* capture session key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services.important_fields_standard import canonical_json

PREFIX_V1 = "karma1."
PREFIX_V2 = "karma2."
PREFIX = PREFIX_V2  # default encrypt envelope


class FieldsCryptoError(ValueError):
    pass


def master_key_bytes() -> bytes:
    """32-byte master key from env or deterministic dev fallback (never use fallback in prod)."""
    raw = os.getenv("KARMA_IMPORTANT_FIELDS_KEY", "").strip()
    if raw:
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
        # Prefer strong passphrase hashing — SHA-256 is minimum; prod should use 64-hex
        return hashlib.sha256(raw.encode("utf-8")).digest()
    env = (
        os.getenv("APP_ENV")
        or os.getenv("KARMA_ENV")
        or "dev"
    ).lower()
    if env in {"prod", "production", "staging"}:
        raise FieldsCryptoError("KARMA_IMPORTANT_FIELDS_KEY is required in production/staging")
    return hashlib.sha256(b"karma-important-fields-dev-only").digest()


def _hkdf(*, info: bytes, length: int = 32) -> bytes:
    return HKDF(
        algorithm=SHA256(),
        length=length,
        salt=b"karma-important-fields-v1",
        info=info,
    ).derive(master_key_bytes())


def capture_session_key(capture_id: str, *, role: str = "protocol") -> bytes:
    """Per-capture **and per-role** AES key (HKDF domain-separated)."""
    r = (role or "protocol").lower().strip()
    return _hkdf(info=f"aes|v2|{capture_id}|{r}".encode("utf-8"))


def mac_key_bytes() -> bytes:
    """HMAC key distinct from AES keys (domain separation)."""
    return _hkdf(info=b"mac|v2|protocol")


def protocol_mac(message: str) -> str:
    return hmac.new(mac_key_bytes(), message.encode("utf-8"), hashlib.sha256).hexdigest()


def build_aad(
    *,
    capture_id: str,
    scene_id: str,
    role: str,
    protocol_fields_hash: str,
) -> bytes:
    """Bind ciphertext to capture / scene / role / protocol hash (anti-splice)."""
    return "|".join(
        [
            capture_id,
            scene_id,
            (role or "").lower().strip(),
            protocol_fields_hash or "",
        ]
    ).encode("utf-8")


def encrypt_canonical_fields(
    fields: dict[str, Any],
    *,
    capture_id: str,
    scene_id: str,
    role: str,
    protocol_fields_hash: str,
) -> str:
    """Encrypt canonical JSON under the role-specific capture session key (karma2)."""
    key = capture_session_key(capture_id, role=role)
    plaintext = canonical_json(fields).encode("utf-8")
    nonce = os.urandom(12)
    aes = AESGCM(key)
    aad = build_aad(
        capture_id=capture_id,
        scene_id=scene_id,
        role=role,
        protocol_fields_hash=protocol_fields_hash,
    )
    ct = aes.encrypt(nonce, plaintext, aad)
    blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii").rstrip("=")
    return PREFIX_V2 + blob


def decrypt_canonical_fields(
    ciphertext: str,
    *,
    capture_id: str,
    scene_id: str = "",
    role: str = "protocol",
    protocol_fields_hash: str = "",
) -> dict[str, Any]:
    if not isinstance(ciphertext, str):
        raise FieldsCryptoError("ciphertext must be a string")
    if ciphertext.startswith(PREFIX_V2):
        return _decrypt_v2(
            ciphertext,
            capture_id=capture_id,
            scene_id=scene_id,
            role=role,
            protocol_fields_hash=protocol_fields_hash,
        )
    if ciphertext.startswith(PREFIX_V1):
        return _decrypt_v1(ciphertext, capture_id=capture_id)
    raise FieldsCryptoError("ciphertext must use karma2. (or legacy karma1.) envelope")


def _decrypt_v2(
    ciphertext: str,
    *,
    capture_id: str,
    scene_id: str,
    role: str,
    protocol_fields_hash: str,
) -> dict[str, Any]:
    raw_b64 = ciphertext[len(PREFIX_V2) :]
    pad = "=" * (-len(raw_b64) % 4)
    try:
        data = base64.urlsafe_b64decode(raw_b64 + pad)
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("invalid ciphertext encoding") from exc
    if len(data) < 12 + 16:
        raise FieldsCryptoError("ciphertext too short")
    nonce, ct = data[:12], data[12:]
    key = capture_session_key(capture_id, role=role)
    aad = build_aad(
        capture_id=capture_id,
        scene_id=scene_id,
        role=role,
        protocol_fields_hash=protocol_fields_hash,
    )
    aes = AESGCM(key)
    try:
        plaintext = aes.decrypt(nonce, ct, aad)
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("decryption failed (tampered, wrong role, or wrong capture)") from exc
    return _parse_fields_json(plaintext)


def _decrypt_v1(ciphertext: str, *, capture_id: str) -> dict[str, Any]:
    """Legacy decrypt — HMAC session key, AAD=capture_id only."""
    raw_b64 = ciphertext[len(PREFIX_V1) :]
    pad = "=" * (-len(raw_b64) % 4)
    try:
        data = base64.urlsafe_b64decode(raw_b64 + pad)
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("invalid ciphertext encoding") from exc
    if len(data) < 12 + 16:
        raise FieldsCryptoError("ciphertext too short")
    nonce, ct = data[:12], data[12:]
    key = hmac.new(master_key_bytes(), capture_id.encode("utf-8"), hashlib.sha256).digest()
    aes = AESGCM(key)
    try:
        plaintext = aes.decrypt(nonce, ct, capture_id.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("decryption failed (tampered or wrong capture)") from exc
    return _parse_fields_json(plaintext)


def _parse_fields_json(plaintext: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FieldsCryptoError("decrypted payload is not JSON") from exc
    if not isinstance(obj, dict):
        raise FieldsCryptoError("decrypted payload must be an object")
    return obj
