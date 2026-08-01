"""Protocol-side ImportantFields capture + encrypted bilateral submit + triple match.

Flow
----
1. During interaction, protocol extracts/locks ImportantFields → ProtocolCapture
   (stores only ciphertext + fields_hash + HMAC; plaintext not returned by default).
2. Buyer and seller each submit *encrypted* fields bound to capture_id + one-time nonce.
3. MATCHED only when:
     decrypt(buyer) hash == decrypt(seller) hash == protocol_capture_hash
4. Anti-abuse: nonce replay rejection, max attempts, ciphertext-only on secure path.

This prevents a MITM from silently rewriting one party's plaintext fields (causing
mismatch storms) without also breaking AEAD integrity / protocol HMAC.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.important_fields_crypto import (
    FieldsCryptoError,
    decrypt_canonical_fields,
    encrypt_canonical_fields,
    protocol_mac,
)
from services.important_fields_standard import (
    ImportantFieldsError,
    diff_fields,
    fields_hash,
    get_scene,
    validate_fields,
)

MAX_ATTEMPTS_PER_CAPTURE = 8
DEFAULT_TTL_SECONDS = 3600
_STORE_LOCK = threading.Lock()
_CAPTURES: dict[str, "ProtocolCapture"] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class PartySubmit:
    role: str
    ciphertext: str
    nonce: str
    fields_hash: str
    submitted_at: str


@dataclass
class ProtocolCapture:
    capture_id: str
    scene_id: str
    interaction_ref: str
    protocol_fields_hash: str
    protocol_ciphertext: str
    protocol_mac: str
    created_at: str
    expires_at: str
    status: str = "CAPTURED"  # CAPTURED | PARTIAL | MATCHED | FAILED | EXPIRED
    attempt_count: int = 0
    used_nonces: set[str] = field(default_factory=set)
    buyer: PartySubmit | None = None
    seller: PartySubmit | None = None
    last_error: str | None = None

    def public_view(self) -> dict[str, Any]:
        return {
            "capture_id": self.capture_id,
            "scene_id": self.scene_id,
            "interaction_ref": self.interaction_ref,
            "protocol_fields_hash": self.protocol_fields_hash,
            "protocol_mac": self.protocol_mac,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "attempt_count": self.attempt_count,
            "buyer_submitted": self.buyer is not None,
            "seller_submitted": self.seller is not None,
            "buyer_fields_hash": self.buyer.fields_hash if self.buyer else None,
            "seller_fields_hash": self.seller.fields_hash if self.seller else None,
            "last_error": self.last_error,
            # Never expose plaintext fields here
        }


class CaptureError(ValueError):
    pass


def reset_capture_store() -> None:
    with _STORE_LOCK:
        _CAPTURES.clear()


def _get(capture_id: str) -> ProtocolCapture:
    with _STORE_LOCK:
        cap = _CAPTURES.get(capture_id)
    if not cap:
        raise CaptureError(f"unknown capture_id: {capture_id}")
    if cap.expires_at < _iso(_utcnow()):
        cap.status = "EXPIRED"
        raise CaptureError("capture expired")
    return cap


def create_protocol_capture(
    *,
    scene_id: str,
    fields: dict[str, Any],
    interaction_ref: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Protocol locks ImportantFields extracted from the live interaction."""
    try:
        get_scene(scene_id)
    except ImportantFieldsError as exc:
        raise CaptureError(str(exc)) from exc
    errors = validate_fields(scene_id, fields)
    if errors:
        raise CaptureError("protocol capture fields invalid: " + "; ".join(errors))

    capture_id = "cap_" + secrets.token_hex(16)
    fhash = fields_hash(fields)
    ciphertext = encrypt_canonical_fields(fields, capture_id=capture_id)
    created = _utcnow()
    expires = datetime.fromtimestamp(created.timestamp() + max(60, int(ttl_seconds)), tz=timezone.utc)
    mac = protocol_mac(f"{capture_id}|{scene_id}|{fhash}|{interaction_ref}")

    cap = ProtocolCapture(
        capture_id=capture_id,
        scene_id=scene_id,
        interaction_ref=interaction_ref,
        protocol_fields_hash=fhash,
        protocol_ciphertext=ciphertext,
        protocol_mac=mac,
        created_at=_iso(created),
        expires_at=_iso(expires),
    )
    with _STORE_LOCK:
        _CAPTURES[capture_id] = cap
    return {
        **cap.public_view(),
        "encrypt_hint": {
            "envelope": "karma1.<base64url(nonce||ciphertext||tag)>",
            "aad": "capture_id",
            "note_zh": "双方必须用该 capture 的会话密钥加密后提交；协议只接受密文",
            "session_key_endpoint": f"/v1/standards/important-fields/captures/{capture_id}/session-key",
        },
    }


def get_capture_public(capture_id: str) -> dict[str, Any]:
    return _get(capture_id).public_view()


def issue_session_key(capture_id: str) -> dict[str, Any]:
    """Return hex session key for client-side encryption (TLS + auth recommended)."""
    from services.important_fields_crypto import capture_session_key

    cap = _get(capture_id)
    return {
        "capture_id": capture_id,
        "scene_id": cap.scene_id,
        "algorithm": "AES-256-GCM",
        "envelope": "karma1",
        "session_key_hex": capture_session_key(capture_id).hex(),
        "warning_zh": "仅通过 TLS + 已认证通道下发；勿写入日志或转发第三方",
    }


def encrypt_for_capture(capture_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Server-assisted encrypt (useful for trusted agents); prefer client-side encrypt."""
    cap = _get(capture_id)
    errors = validate_fields(cap.scene_id, fields)
    if errors:
        raise CaptureError("fields invalid: " + "; ".join(errors))
    ct = encrypt_canonical_fields(fields, capture_id=capture_id)
    return {
        "capture_id": capture_id,
        "scene_id": cap.scene_id,
        "fields_hash": fields_hash(fields),
        "ciphertext": ct,
    }


def submit_encrypted(
    *,
    capture_id: str,
    role: str,
    ciphertext: str,
    nonce: str,
) -> dict[str, Any]:
    role = role.lower().strip()
    if role not in {"buyer", "seller"}:
        raise CaptureError("role must be buyer or seller")
    if not nonce or len(nonce) < 8 or len(nonce) > 128:
        raise CaptureError("nonce must be 8..128 chars")
    if not ciphertext or not ciphertext.startswith("karma1."):
        raise CaptureError("secure path accepts only karma1. ciphertext (no plaintext)")

    cap = _get(capture_id)
    expected_mac = protocol_mac(
        f"{cap.capture_id}|{cap.scene_id}|{cap.protocol_fields_hash}|{cap.interaction_ref}"
    )
    if not secrets.compare_digest(expected_mac, cap.protocol_mac):
        raise CaptureError("protocol capture integrity check failed")

    with _STORE_LOCK:
        if nonce in cap.used_nonces:
            cap.last_error = "nonce_replay"
            cap.attempt_count += 1
            raise CaptureError("nonce already used (replay rejected)")
        if cap.attempt_count >= MAX_ATTEMPTS_PER_CAPTURE:
            cap.status = "FAILED"
            raise CaptureError("capture attempt limit exceeded — reopen interaction")
        cap.used_nonces.add(nonce)
        cap.attempt_count += 1

    try:
        plaintext = decrypt_canonical_fields(ciphertext, capture_id=capture_id)
    except FieldsCryptoError as exc:
        cap.last_error = str(exc)
        raise CaptureError(str(exc)) from exc

    errors = validate_fields(cap.scene_id, plaintext)
    if errors:
        cap.last_error = "validation: " + "; ".join(errors)
        raise CaptureError(cap.last_error)

    fhash = fields_hash(plaintext)
    submit = PartySubmit(
        role=role,
        ciphertext=ciphertext,
        nonce=nonce,
        fields_hash=fhash,
        submitted_at=_iso(_utcnow()),
    )
    with _STORE_LOCK:
        if role == "buyer":
            cap.buyer = submit
        else:
            cap.seller = submit
        if cap.buyer and cap.seller:
            cap.status = "PARTIAL"  # ready for finalize; still need triple check
        else:
            cap.status = "PARTIAL"

    return {
        **cap.public_view(),
        "accepted_role": role,
        "accepted_fields_hash": fhash,
    }


def finalize_triple_match(capture_id: str) -> dict[str, Any]:
    """Require buyer == seller == protocol capture hash after both encrypted submits."""
    cap = _get(capture_id)
    if not cap.buyer or not cap.seller:
        raise CaptureError("both buyer and seller encrypted submits required")

    try:
        buyer_fields = decrypt_canonical_fields(cap.buyer.ciphertext, capture_id=capture_id)
        seller_fields = decrypt_canonical_fields(cap.seller.ciphertext, capture_id=capture_id)
        protocol_fields = decrypt_canonical_fields(cap.protocol_ciphertext, capture_id=capture_id)
    except FieldsCryptoError as exc:
        cap.status = "FAILED"
        cap.last_error = str(exc)
        raise CaptureError(str(exc)) from exc

    bh = fields_hash(buyer_fields)
    sh = fields_hash(seller_fields)
    ph = fields_hash(protocol_fields)
    # Re-check stored protocol hash binding
    if ph != cap.protocol_fields_hash:
        cap.status = "FAILED"
        raise CaptureError("protocol capture hash drift")

    triple_ok = bh == sh == ph
    result: dict[str, Any] = {
        "schema_version": "karma-important-fields-v1",
        "capture_id": capture_id,
        "scene_id": cap.scene_id,
        "interaction_ref": cap.interaction_ref,
        "status": "MATCHED" if triple_ok else "COUNTERED",
        "protocol_fields_hash": ph,
        "buyer_fields_hash": bh,
        "seller_fields_hash": sh,
        "triple_match": triple_ok,
        "attempt_count": cap.attempt_count,
        "diff": {
            "buyer_vs_protocol": [] if bh == ph else diff_fields(buyer_fields, protocol_fields),
            "seller_vs_protocol": [] if sh == ph else diff_fields(seller_fields, protocol_fields),
            "buyer_vs_seller": [] if bh == sh else diff_fields(buyer_fields, seller_fields),
        },
    }
    if triple_ok:
        cap.status = "MATCHED"
        result["commitment_hint"] = {
            "fields_hash": ph,
            "protocol_mac": cap.protocol_mac,
            "next_steps": [
                "Seal evidence bundle with fields_hash + capture_id",
                "On-chain scopeHash ← fields_hash",
                "Verify delivery only against locked acceptance_criteria",
            ],
        }
        # Drop plaintext path: keep only hashes/ciphertexts already stored
    else:
        cap.status = "COUNTERED"
        cap.last_error = "triple_mismatch"
        # Congestion control: mismatched finalize counts toward attempt budget
        with _STORE_LOCK:
            cap.attempt_count += 1
            if cap.attempt_count >= MAX_ATTEMPTS_PER_CAPTURE:
                cap.status = "FAILED"
                result["status"] = "FAILED"
                result["error"] = "capture attempt limit exceeded — reopen interaction"
    return result


def capture_from_interaction(
    *,
    scene_id: str,
    interaction_ref: str,
    extracted_fields: dict[str, Any],
    source: str = "protocol_extract",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Entry used when protocol scrapes/locks fields during agent interaction."""
    out = create_protocol_capture(
        scene_id=scene_id,
        fields=extracted_fields,
        interaction_ref=interaction_ref,
        ttl_seconds=ttl_seconds,
    )
    out["capture_source"] = source
    out["security"] = {
        "wire_format": "encrypted_only",
        "match_rule": "buyer_hash == seller_hash == protocol_hash",
        "anti_replay": "per-capture nonce + attempt budget",
        "integrity": "AES-GCM AAD(capture_id) + protocol HMAC",
    }
    return out


# Scenes that must lock Important Fields before voucher/settle on the fulfill spine
FULFILL_IF_REQUIRED_SCENES = frozenset(
    {
        "ride_hailing",
        "food_delivery",
        "hotel_booking",
        "flight_booking",
        "b2b_procurement",
        "data_api_billing",
        "logistics_delivery",
        "software_development",
    }
)


def scene_requires_important_fields(scene_id: str) -> bool:
    return scene_id in FULFILL_IF_REQUIRED_SCENES


def require_matched_capture(*, capture_id: str, scene_id: str) -> dict[str, Any]:
    """Assert an existing capture is MATCHED for the given scene."""
    pub = get_capture_public(capture_id)
    if pub.get("scene_id") != scene_id:
        raise CaptureError(
            f"capture scene {pub.get('scene_id')} does not match required scene {scene_id}"
        )
    if pub.get("status") != "MATCHED":
        raise CaptureError(
            f"important fields capture status is {pub.get('status')}, need MATCHED"
        )
    return pub


def auto_triple_lock_fields(
    *,
    scene_id: str,
    fields: dict[str, Any],
    interaction_ref: str,
) -> dict[str, Any]:
    """Test/demo helper: protocol capture + both parties encrypt-submit + triple MATCHED.

    Production callers should capture/submit out-of-band and pass capture_id instead.
    """
    created = capture_from_interaction(
        scene_id=scene_id,
        interaction_ref=interaction_ref,
        extracted_fields=fields,
        source="fulfill_auto_lock",
    )
    cid = created["capture_id"]
    for role, nonce in (("buyer", "auto-buyer-" + secrets.token_hex(4)), ("seller", "auto-seller-" + secrets.token_hex(4))):
        ct = encrypt_for_capture(cid, fields)["ciphertext"]
        submit_encrypted(capture_id=cid, role=role, ciphertext=ct, nonce=nonce)
    matched = finalize_triple_match(cid)
    if not matched.get("triple_match"):
        raise CaptureError("auto_triple_lock_fields failed to MATCH")
    return matched
