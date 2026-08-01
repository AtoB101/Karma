"""Protocol-side ImportantFields capture + encrypted bilateral submit + triple match.

P5 security model
-----------------
1. Protocol locks fields from the live interaction → ProtocolCapture
   (ciphertext + fields_hash + HMAC; plaintext never in public view).
2. Buyer and seller each submit *role-bound* karma2 AES-GCM ciphertext
   (per-role HKDF keys + AAD bind capture/scene/role/protocol_hash).
3. MATCHED only when:
     decrypt(buyer) hash == decrypt(seller) hash == protocol_capture_hash
4. Anti-collusion: distinct submitter_agent_id per role; optional party bind;
   MATCHED is immutable (sealed); nonce replay + attempt budget.
"""
from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.important_fields_crypto import (
    FieldsCryptoError,
    decrypt_canonical_fields,
    encrypt_canonical_fields,
    protocol_mac,
)
from services.important_fields_standard import (
    ImportantFieldsError,
    canonicalize,
    diff_fields,
    fields_hash,
    get_scene,
    normalize_amount_string,
    validate_fields,
)

MAX_ATTEMPTS_PER_CAPTURE = 8
DEFAULT_TTL_SECONDS = 3600
_STORE_LOCK = threading.Lock()
_CAPTURES: dict[str, "ProtocolCapture"] = {}
_STORE_PATH = (
    Path(__file__).resolve().parents[1] / ".karma_data" / "important_field_captures.json"
)
_LOADED = False


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
    submitter_agent_id: str | None = None


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
    status: str = "CAPTURED"  # CAPTURED | PARTIAL | MATCHED | COUNTERED | FAILED | EXPIRED
    attempt_count: int = 0
    used_nonces: set[str] = field(default_factory=set)
    buyer: PartySubmit | None = None
    seller: PartySubmit | None = None
    last_error: str | None = None
    buyer_agent_id: str | None = None
    seller_agent_id: str | None = None
    sealed_at: str | None = None
    envelope: str = "karma2"

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
            "sealed_at": self.sealed_at,
            "attempt_count": self.attempt_count,
            "buyer_submitted": self.buyer is not None,
            "seller_submitted": self.seller is not None,
            "buyer_fields_hash": self.buyer.fields_hash if self.buyer else None,
            "seller_fields_hash": self.seller.fields_hash if self.seller else None,
            "buyer_agent_id": self.buyer_agent_id,
            "seller_agent_id": self.seller_agent_id,
            "envelope": self.envelope,
            "last_error": self.last_error,
            "security": {
                "wire": "karma2 AES-256-GCM",
                "aad": "capture_id|scene_id|role|protocol_fields_hash",
                "keys": "HKDF per capture+role",
                "match_rule": "buyer_hash == seller_hash == protocol_hash",
                "anti_collusion": "distinct submitter_agent_id; MATCHED sealed",
            },
        }


class CaptureError(ValueError):
    pass


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _STORE_LOCK:
        if _LOADED:
            return
        if _STORE_PATH.is_file():
            try:
                raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for cid, body in raw.items():
                        if not isinstance(body, dict):
                            continue
                        buyer = body.get("buyer")
                        seller = body.get("seller")
                        _CAPTURES[str(cid)] = ProtocolCapture(
                            capture_id=str(body.get("capture_id") or cid),
                            scene_id=str(body.get("scene_id") or ""),
                            interaction_ref=str(body.get("interaction_ref") or ""),
                            protocol_fields_hash=str(body.get("protocol_fields_hash") or ""),
                            protocol_ciphertext=str(body.get("protocol_ciphertext") or ""),
                            protocol_mac=str(body.get("protocol_mac") or ""),
                            created_at=str(body.get("created_at") or ""),
                            expires_at=str(body.get("expires_at") or ""),
                            status=str(body.get("status") or "CAPTURED"),
                            attempt_count=int(body.get("attempt_count") or 0),
                            used_nonces=set(body.get("used_nonces") or []),
                            buyer=PartySubmit(**buyer) if isinstance(buyer, dict) else None,
                            seller=PartySubmit(**seller) if isinstance(seller, dict) else None,
                            last_error=body.get("last_error"),
                            buyer_agent_id=body.get("buyer_agent_id"),
                            seller_agent_id=body.get("seller_agent_id"),
                            sealed_at=body.get("sealed_at"),
                            envelope=str(body.get("envelope") or "karma2"),
                        )
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    for cid, cap in _CAPTURES.items():
        row = asdict(cap)
        row["used_nonces"] = sorted(cap.used_nonces)
        payload[cid] = row
    _STORE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def reset_capture_store() -> None:
    global _LOADED
    with _STORE_LOCK:
        _CAPTURES.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def _get(capture_id: str) -> ProtocolCapture:
    _ensure_loaded()
    with _STORE_LOCK:
        cap = _CAPTURES.get(capture_id)
    if not cap:
        raise CaptureError(f"unknown capture_id: {capture_id}")
    if cap.expires_at < _iso(_utcnow()) and cap.status != "MATCHED":
        cap.status = "EXPIRED"
        raise CaptureError("capture expired")
    return cap


def create_protocol_capture(
    *,
    scene_id: str,
    fields: dict[str, Any],
    interaction_ref: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    buyer_agent_id: str | None = None,
    seller_agent_id: str | None = None,
) -> dict[str, Any]:
    """Protocol locks ImportantFields extracted from the live interaction."""
    _ensure_loaded()
    try:
        get_scene(scene_id)
    except ImportantFieldsError as exc:
        raise CaptureError(str(exc)) from exc
    # Canonicalize before validate/hash for precision
    fields = canonicalize(fields)  # type: ignore[assignment]
    if not isinstance(fields, dict):
        raise CaptureError("fields must be an object")
    errors = validate_fields(scene_id, fields)
    if errors:
        raise CaptureError("protocol capture fields invalid: " + "; ".join(errors))

    if buyer_agent_id and seller_agent_id and buyer_agent_id == seller_agent_id:
        raise CaptureError("buyer_agent_id and seller_agent_id must be distinct (anti-collusion)")

    capture_id = "cap_" + secrets.token_hex(16)
    fhash = fields_hash(fields)
    ciphertext = encrypt_canonical_fields(
        fields,
        capture_id=capture_id,
        scene_id=scene_id,
        role="protocol",
        protocol_fields_hash=fhash,
    )
    created = _utcnow()
    expires = datetime.fromtimestamp(
        created.timestamp() + max(60, int(ttl_seconds)), tz=timezone.utc
    )
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
        buyer_agent_id=(buyer_agent_id or None),
        seller_agent_id=(seller_agent_id or None),
        envelope="karma2",
    )
    with _STORE_LOCK:
        _CAPTURES[capture_id] = cap
        _persist_unlocked()
    return {
        **cap.public_view(),
        "encrypt_hint": {
            "envelope": "karma2.<base64url(nonce||ciphertext||tag)>",
            "aad": "capture_id|scene_id|role|protocol_fields_hash",
            "note_zh": "双方必须用该 capture 的角色会话密钥加密后提交；协议只接受密文",
            "session_key_endpoint": (
                f"/v1/standards/important-fields/captures/{capture_id}/session-key?role=buyer"
            ),
        },
    }


def get_capture_public(capture_id: str) -> dict[str, Any]:
    return _get(capture_id).public_view()


def issue_session_key(capture_id: str, *, role: str = "buyer") -> dict[str, Any]:
    """Return hex session key for client-side encryption (TLS + auth recommended)."""
    from services.important_fields_crypto import capture_session_key

    role = role.lower().strip()
    if role not in {"buyer", "seller", "protocol"}:
        raise CaptureError("role must be buyer|seller|protocol")
    cap = _get(capture_id)
    return {
        "capture_id": capture_id,
        "scene_id": cap.scene_id,
        "role": role,
        "algorithm": "AES-256-GCM",
        "kdf": "HKDF-SHA256",
        "envelope": "karma2",
        "aad": "capture_id|scene_id|role|protocol_fields_hash",
        "protocol_fields_hash": cap.protocol_fields_hash,
        "session_key_hex": capture_session_key(capture_id, role=role).hex(),
        "warning_zh": "仅通过 TLS + 已认证通道下发；角色密钥不可混用；勿写入日志",
    }


def encrypt_for_capture(
    capture_id: str,
    fields: dict[str, Any],
    *,
    role: str = "buyer",
) -> dict[str, Any]:
    """Server-assisted encrypt (trusted agents); prefer client-side encrypt."""
    role = role.lower().strip()
    if role not in {"buyer", "seller", "protocol"}:
        raise CaptureError("role must be buyer|seller|protocol")
    cap = _get(capture_id)
    fields = canonicalize(fields)  # type: ignore[assignment]
    if not isinstance(fields, dict):
        raise CaptureError("fields must be an object")
    errors = validate_fields(cap.scene_id, fields)
    if errors:
        raise CaptureError("fields invalid: " + "; ".join(errors))
    ct = encrypt_canonical_fields(
        fields,
        capture_id=capture_id,
        scene_id=cap.scene_id,
        role=role,
        protocol_fields_hash=cap.protocol_fields_hash,
    )
    return {
        "capture_id": capture_id,
        "scene_id": cap.scene_id,
        "role": role,
        "fields_hash": fields_hash(fields),
        "ciphertext": ct,
        "envelope": "karma2",
    }


def submit_encrypted(
    *,
    capture_id: str,
    role: str,
    ciphertext: str,
    nonce: str,
    submitter_agent_id: str | None = None,
) -> dict[str, Any]:
    role = role.lower().strip()
    if role not in {"buyer", "seller"}:
        raise CaptureError("role must be buyer or seller")
    if not nonce or len(nonce) < 8 or len(nonce) > 128:
        raise CaptureError("nonce must be 8..128 chars")
    if not ciphertext or not (
        ciphertext.startswith("karma2.") or ciphertext.startswith("karma1.")
    ):
        raise CaptureError("secure path accepts only karma2./karma1. ciphertext (no plaintext)")

    cap = _get(capture_id)
    if cap.status == "MATCHED":
        raise CaptureError("capture is sealed MATCHED — reopen interaction for changes")
    if cap.status in {"FAILED", "EXPIRED"}:
        raise CaptureError(f"capture status {cap.status} cannot accept submits")

    expected_mac = protocol_mac(
        f"{cap.capture_id}|{cap.scene_id}|{cap.protocol_fields_hash}|{cap.interaction_ref}"
    )
    if not secrets.compare_digest(expected_mac, cap.protocol_mac):
        raise CaptureError("protocol capture integrity check failed")

    # Party bind + anti dual-role collusion
    bound = cap.buyer_agent_id if role == "buyer" else cap.seller_agent_id
    if bound:
        if not submitter_agent_id or submitter_agent_id != bound:
            raise CaptureError(
                f"submitter_agent_id must match bound {role}_agent_id (anti-collusion)"
            )
    if submitter_agent_id:
        other = cap.seller if role == "buyer" else cap.buyer
        if other and other.submitter_agent_id and other.submitter_agent_id == submitter_agent_id:
            raise CaptureError(
                "same submitter_agent_id cannot fill both buyer and seller (anti-collusion)"
            )

    with _STORE_LOCK:
        if nonce in cap.used_nonces:
            cap.last_error = "nonce_replay"
            cap.attempt_count += 1
            _persist_unlocked()
            raise CaptureError("nonce already used (replay rejected)")
        if cap.attempt_count >= MAX_ATTEMPTS_PER_CAPTURE:
            cap.status = "FAILED"
            _persist_unlocked()
            raise CaptureError("capture attempt limit exceeded — reopen interaction")
        cap.used_nonces.add(nonce)
        cap.attempt_count += 1

    try:
        plaintext = decrypt_canonical_fields(
            ciphertext,
            capture_id=capture_id,
            scene_id=cap.scene_id,
            role=role,
            protocol_fields_hash=cap.protocol_fields_hash,
        )
    except FieldsCryptoError as exc:
        cap.last_error = str(exc)
        with _STORE_LOCK:
            _persist_unlocked()
        raise CaptureError(str(exc)) from exc

    plaintext = canonicalize(plaintext)  # type: ignore[assignment]
    if not isinstance(plaintext, dict):
        raise CaptureError("decrypted fields must be an object")
    errors = validate_fields(cap.scene_id, plaintext)
    if errors:
        cap.last_error = "validation: " + "; ".join(errors)
        with _STORE_LOCK:
            _persist_unlocked()
        raise CaptureError(cap.last_error)

    fhash = fields_hash(plaintext)
    submit = PartySubmit(
        role=role,
        ciphertext=ciphertext,
        nonce=nonce,
        fields_hash=fhash,
        submitted_at=_iso(_utcnow()),
        submitter_agent_id=submitter_agent_id,
    )
    with _STORE_LOCK:
        if role == "buyer":
            cap.buyer = submit
        else:
            cap.seller = submit
        cap.status = "PARTIAL"
        _persist_unlocked()

    return {
        **cap.public_view(),
        "accepted_role": role,
        "accepted_fields_hash": fhash,
    }


def finalize_triple_match(capture_id: str) -> dict[str, Any]:
    """Require buyer == seller == protocol capture hash after both encrypted submits."""
    cap = _get(capture_id)
    if cap.status == "MATCHED":
        # Idempotent seal read
        return {
            "schema_version": "karma-important-fields-v1",
            "capture_id": capture_id,
            "scene_id": cap.scene_id,
            "interaction_ref": cap.interaction_ref,
            "status": "MATCHED",
            "protocol_fields_hash": cap.protocol_fields_hash,
            "buyer_fields_hash": cap.buyer.fields_hash if cap.buyer else None,
            "seller_fields_hash": cap.seller.fields_hash if cap.seller else None,
            "triple_match": True,
            "sealed_at": cap.sealed_at,
            "idempotent": True,
        }
    if not cap.buyer or not cap.seller:
        raise CaptureError("both buyer and seller encrypted submits required")

    try:
        buyer_fields = decrypt_canonical_fields(
            cap.buyer.ciphertext,
            capture_id=capture_id,
            scene_id=cap.scene_id,
            role="buyer",
            protocol_fields_hash=cap.protocol_fields_hash,
        )
        seller_fields = decrypt_canonical_fields(
            cap.seller.ciphertext,
            capture_id=capture_id,
            scene_id=cap.scene_id,
            role="seller",
            protocol_fields_hash=cap.protocol_fields_hash,
        )
        protocol_fields = decrypt_canonical_fields(
            cap.protocol_ciphertext,
            capture_id=capture_id,
            scene_id=cap.scene_id,
            role="protocol",
            protocol_fields_hash=cap.protocol_fields_hash,
        )
    except FieldsCryptoError as exc:
        cap.status = "FAILED"
        cap.last_error = str(exc)
        with _STORE_LOCK:
            _persist_unlocked()
        raise CaptureError(str(exc)) from exc

    bh = fields_hash(canonicalize(buyer_fields))  # type: ignore[arg-type]
    sh = fields_hash(canonicalize(seller_fields))  # type: ignore[arg-type]
    ph = fields_hash(canonicalize(protocol_fields))  # type: ignore[arg-type]
    if ph != cap.protocol_fields_hash:
        cap.status = "FAILED"
        with _STORE_LOCK:
            _persist_unlocked()
        raise CaptureError("protocol capture hash drift")

    # Anti-collusion: if both parties bound, submitters must be distinct and match binds
    if cap.buyer.submitter_agent_id and cap.seller.submitter_agent_id:
        if cap.buyer.submitter_agent_id == cap.seller.submitter_agent_id:
            cap.status = "FAILED"
            cap.last_error = "collusion_same_submitter"
            with _STORE_LOCK:
                _persist_unlocked()
            raise CaptureError("buyer and seller submitter_agent_id must differ (anti-collusion)")

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
        cap.sealed_at = _iso(_utcnow())
        result["sealed_at"] = cap.sealed_at
        result["commitment_hint"] = {
            "fields_hash": ph,
            "protocol_mac": cap.protocol_mac,
            "envelope": "karma2",
            "next_steps": [
                "Seal evidence bundle with fields_hash + capture_id",
                "On-chain scopeHash ← fields_hash",
                "Verify delivery only against locked acceptance_criteria",
            ],
        }
        with _STORE_LOCK:
            _persist_unlocked()
    else:
        cap.status = "COUNTERED"
        cap.last_error = "triple_mismatch"
        with _STORE_LOCK:
            cap.attempt_count += 1
            if cap.attempt_count >= MAX_ATTEMPTS_PER_CAPTURE:
                cap.status = "FAILED"
                result["status"] = "FAILED"
                result["error"] = "capture attempt limit exceeded — reopen interaction"
            _persist_unlocked()
    return result


def capture_from_interaction(
    *,
    scene_id: str,
    interaction_ref: str,
    extracted_fields: dict[str, Any],
    source: str = "protocol_extract",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    buyer_agent_id: str | None = None,
    seller_agent_id: str | None = None,
) -> dict[str, Any]:
    """Entry used when protocol scrapes/locks fields during agent interaction."""
    out = create_protocol_capture(
        scene_id=scene_id,
        fields=extracted_fields,
        interaction_ref=interaction_ref,
        ttl_seconds=ttl_seconds,
        buyer_agent_id=buyer_agent_id,
        seller_agent_id=seller_agent_id,
    )
    out["capture_source"] = source
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
        "api_tool_call",
        "logistics_delivery",
        "software_development",
        "design_creative",
        "consulting_advisory",
        "content_creation",
        "manufacturing",
        "real_estate_services",
        "financial_services",
        "marketing_advertising",
        "education_training",
        "healthcare_medical",
    }
)


def scene_requires_important_fields(scene_id: str) -> bool:
    return scene_id in FULFILL_IF_REQUIRED_SCENES


def require_matched_capture(
    *,
    capture_id: str,
    scene_id: str,
    interaction_ref: str | None = None,
    expected_amount: float | None = None,
) -> dict[str, Any]:
    """Assert an existing capture is sealed MATCHED for the given scene / deal."""
    pub = get_capture_public(capture_id)
    if pub.get("scene_id") != scene_id:
        raise CaptureError(
            f"capture scene {pub.get('scene_id')} does not match required scene {scene_id}"
        )
    if pub.get("status") != "MATCHED":
        raise CaptureError(
            f"important fields capture status is {pub.get('status')}, need MATCHED"
        )
    if interaction_ref and pub.get("interaction_ref") != interaction_ref:
        raise CaptureError(
            "capture interaction_ref does not match fulfill interaction (anti-splice)"
        )
    if expected_amount is not None:
        from decimal import Decimal, InvalidOperation

        cap = _get(capture_id)
        try:
            protocol_fields = decrypt_canonical_fields(
                cap.protocol_ciphertext,
                capture_id=capture_id,
                scene_id=cap.scene_id,
                role="protocol",
                protocol_fields_hash=cap.protocol_fields_hash,
            )
        except FieldsCryptoError as exc:
            raise CaptureError(str(exc)) from exc
        locked_amt = normalize_amount_string(protocol_fields.get("amount"))
        try:
            expect_norm = normalize_amount_string(
                format(Decimal(str(expected_amount)).normalize(), "f")
            )
        except (InvalidOperation, ValueError):
            expect_norm = None
        if locked_amt is None or expect_norm is None or locked_amt != expect_norm:
            raise CaptureError(
                f"locked amount {locked_amt!r} does not match deal amount {expected_amount}"
            )
    return pub


def auto_triple_lock_fields(
    *,
    scene_id: str,
    fields: dict[str, Any],
    interaction_ref: str,
    buyer_agent_id: str = "demo-buyer",
    seller_agent_id: str = "demo-seller",
) -> dict[str, Any]:
    """Test/demo helper: protocol capture + both parties encrypt-submit + triple MATCHED.

    Production callers should capture/submit out-of-band and pass capture_id instead.
    Uses distinct demo agent ids so anti-collusion checks stay honest in shape.
    """
    created = capture_from_interaction(
        scene_id=scene_id,
        interaction_ref=interaction_ref,
        extracted_fields=fields,
        source="fulfill_auto_lock",
        buyer_agent_id=buyer_agent_id,
        seller_agent_id=seller_agent_id,
    )
    cid = created["capture_id"]
    for role, agent, nonce in (
        ("buyer", buyer_agent_id, "auto-buyer-" + secrets.token_hex(4)),
        ("seller", seller_agent_id, "auto-seller-" + secrets.token_hex(4)),
    ):
        ct = encrypt_for_capture(cid, fields, role=role)["ciphertext"]
        submit_encrypted(
            capture_id=cid,
            role=role,
            ciphertext=ct,
            nonce=nonce,
            submitter_agent_id=agent,
        )
    matched = finalize_triple_match(cid)
    if not matched.get("triple_match"):
        raise CaptureError("auto_triple_lock_fields failed to MATCH")
    return matched
