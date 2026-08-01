"""P7 Delivery Verification — scene-aware proof against locked Important Fields.

Modes
-----
- physical_triple: seller ship → logistics intake (item match) → logistics deliver
  + tagged photo POD → buyer confirm / 30min silent default
- ticket_stub: email receipt / confirmation code / PNR (issuer API deferred)
- ride_track: trip complete + route/fare proofs
- digital_light: SUCCESS receipt + proof field coverage

Security
--------
- Capture-time system tag: challenge nonce + HMAC over task|party|nonce|ts|geo
- Dual photo (ship + deliver) for physical scenes
- Wrong-item at intake → loss_share + P6 breach_fraction
- Silent buyer only after seller+logistics+proof verified
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.accept_fulfillment import compute_breach_compensation
from services.important_fields_capture import CaptureError, get_capture_public
from services.important_fields_standard import get_scene as get_if_scene

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "delivery-verification.v1.json"
)
_STORE_PATH = (
    Path(__file__).resolve().parents[1]
    / ".karma_data"
    / "delivery_verification_sessions.json"
)

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}
_LOADED = False

PHYSICAL_MODES = frozenset({"physical_triple"})
TICKET_MODES = frozenset({"ticket_stub"})
DIGITAL_MODES = frozenset({"digital_light", "ride_track"})


class DeliveryVerificationError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    d = dt or _utcnow()
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _tag_master_key() -> bytes:
    raw = os.getenv("KARMA_DELIVERY_TAG_KEY", "").strip()
    if raw:
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
        return hashlib.sha256(raw.encode("utf-8")).digest()
    env = (os.getenv("APP_ENV") or os.getenv("KARMA_ENV") or "dev").lower()
    if env in {"prod", "production", "staging"}:
        raise DeliveryVerificationError("KARMA_DELIVERY_TAG_KEY required in production/staging")
    return hashlib.sha256(b"karma-delivery-tag-dev-only").digest()


@lru_cache(maxsize=1)
def load_delivery_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"delivery-verification catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-delivery-verification-v1":
        raise DeliveryVerificationError("unsupported delivery-verification schema_version")
    return data


def scene_policy(scene_id: str) -> dict[str, Any]:
    cat = load_delivery_catalog()
    defaults = deepcopy(cat.get("global_defaults") or {})
    scene = deepcopy((cat.get("scenes") or {}).get(scene_id) or {})
    if scene_id not in (cat.get("scenes") or {}):
        # Unknown → digital_light safest default (no fake physical silent confirm)
        scene = {
            "scene_id": scene_id,
            "mode": "digital_light",
            "unknown_scene": True,
            "buyer_silent_confirm_seconds": 0,
            "required_events": ["execution_receipt_success", "proof_fields_covered"],
        }
    merged = {**defaults, **scene}
    base_loss = deepcopy(defaults.get("loss_share") or {})
    scene_loss = deepcopy(scene.get("loss_share") or {})
    for k, v in scene_loss.items():
        if isinstance(v, dict) and isinstance(base_loss.get(k), dict):
            base_loss[k] = {**base_loss[k], **v}
        else:
            base_loss[k] = v
    merged["loss_share"] = base_loss
    merged["scene_id"] = scene_id
    merged["mode"] = scene.get("mode") or "digital_light"
    return merged


def list_delivery_scenes() -> list[dict[str, Any]]:
    cat = load_delivery_catalog()
    out = []
    for sid, body in (cat.get("scenes") or {}).items():
        pol = scene_policy(sid)
        out.append(
            {
                "scene_id": sid,
                "mode": pol.get("mode"),
                "group": body.get("group"),
                "buyer_silent_confirm_seconds": pol.get("buyer_silent_confirm_seconds"),
                "high_risk": bool(body.get("high_risk")),
                "reality_note_zh": body.get("reality_note_zh"),
                "extra_methods": body.get("extra_methods") or [],
            }
        )
    return out


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
                    _SESSIONS.update({str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)})
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(_SESSIONS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def reset_delivery_sessions() -> None:
    global _LOADED
    with _LOCK:
        _SESSIONS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def _public(sess: dict[str, Any]) -> dict[str, Any]:
    return {
        "verification_id": sess.get("verification_id"),
        "task_id": sess.get("task_id"),
        "scene_id": sess.get("scene_id"),
        "mode": sess.get("mode"),
        "status": sess.get("status"),
        "seller_agent_id": sess.get("seller_agent_id"),
        "buyer_agent_id": sess.get("buyer_agent_id"),
        "logistics_agent_id": sess.get("logistics_agent_id"),
        "capture_id": sess.get("capture_id"),
        "events": list(sess.get("events") or []),
        "proofs": dict(sess.get("proofs") or {}),
        "required_events": list(sess.get("required_events") or []),
        "buyer_silent_deadline": sess.get("buyer_silent_deadline"),
        "verified_at": sess.get("verified_at"),
        "liability": sess.get("liability"),
        "loss_share": sess.get("loss_share_result"),
        "created_at": sess.get("created_at"),
        "updated_at": sess.get("updated_at"),
        "note_zh": sess.get("note_zh"),
    }


def _get(verification_id: str) -> dict[str, Any]:
    _ensure_loaded()
    with _LOCK:
        sess = _SESSIONS.get(verification_id)
        if not sess:
            raise DeliveryVerificationError(f"unknown verification_id: {verification_id}")
        return sess


def get_verification(verification_id: str) -> dict[str, Any]:
    return _public(_get(verification_id))


def get_verification_for_task(task_id: str) -> dict[str, Any] | None:
    _ensure_loaded()
    with _LOCK:
        for sess in _SESSIONS.values():
            if sess.get("task_id") == task_id:
                return _public(sess)
    return None


def _append_event(sess: dict[str, Any], kind: str, **extra: Any) -> None:
    ev = {"kind": kind, "at": _iso(), **extra}
    events = list(sess.get("events") or [])
    events.append(ev)
    sess["events"] = events
    sess["updated_at"] = _iso()


def _has_event(sess: dict[str, Any], kind: str) -> bool:
    return any(e.get("kind") == kind for e in (sess.get("events") or []))


def create_verification_session(
    *,
    task_id: str,
    scene_id: str,
    seller_agent_id: str,
    buyer_agent_id: str,
    logistics_agent_id: str | None = None,
    capture_id: str | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
    """Open a delivery verification session bound to a task / IF capture."""
    pol = scene_policy(scene_id)
    mode = str(pol.get("mode") or "digital_light")
    if mode in PHYSICAL_MODES and not logistics_agent_id:
        raise DeliveryVerificationError(
            "physical_triple mode requires logistics_agent_id (三方物流)"
        )
    if logistics_agent_id and logistics_agent_id in {seller_agent_id, buyer_agent_id}:
        raise DeliveryVerificationError(
            "logistics_agent_id must be distinct from buyer/seller (anti-collusion)"
        )

    if pol.get("require_matched_if_capture") and capture_id:
        try:
            pub = get_capture_public(capture_id)
        except CaptureError as exc:
            raise DeliveryVerificationError(str(exc)) from exc
        if pub.get("status") != "MATCHED":
            raise DeliveryVerificationError(
                f"important fields capture must be MATCHED, got {pub.get('status')}"
            )
        if pub.get("scene_id") and pub.get("scene_id") != scene_id:
            raise DeliveryVerificationError("capture scene_id mismatch")

    # Reuse open session for same task
    existing = get_verification_for_task(task_id)
    if existing and existing.get("status") not in {"VERIFIED", "FAILED", "REJECTED"}:
        return existing

    vid = "dv_" + secrets.token_hex(12)
    if mode in PHYSICAL_MODES:
        status = "AWAITING_SELLER_SHIP"
    elif mode in TICKET_MODES:
        status = "AWAITING_SELLER_SHIP"  # seller issues confirmation
    elif mode == "ride_track":
        status = "AWAITING_SELLER_SHIP"
    else:
        status = "CREATED"

    sess = {
        "verification_id": vid,
        "task_id": task_id,
        "scene_id": scene_id,
        "mode": mode,
        "status": status,
        "seller_agent_id": seller_agent_id,
        "buyer_agent_id": buyer_agent_id,
        "logistics_agent_id": logistics_agent_id,
        "capture_id": capture_id,
        "amount": amount,
        "required_events": list(pol.get("required_events") or []),
        "extra_methods": list(pol.get("extra_methods") or []),
        "buyer_silent_confirm_seconds": pol.get("buyer_silent_confirm_seconds"),
        "events": [],
        "proofs": {},
        "challenges": {},
        "created_at": _iso(),
        "updated_at": _iso(),
        "buyer_silent_deadline": None,
        "verified_at": None,
        "liability": None,
        "loss_share_result": None,
        "note_zh": pol.get("reality_note_zh"),
        "high_risk": bool(pol.get("high_risk")),
        "issuer_verify": pol.get("issuer_verify"),
    }
    _ensure_loaded()
    with _LOCK:
        _SESSIONS[vid] = sess
        _persist_unlocked()
    return _public(sess)


def issue_capture_challenge(
    verification_id: str,
    *,
    party_role: str,
    geo_hash: str | None = None,
) -> dict[str, Any]:
    """Issue capture-time anti-forge tag challenge before photo upload."""
    role = party_role.lower().strip()
    if role not in {"seller", "logistics", "buyer"}:
        raise DeliveryVerificationError("party_role must be seller|logistics|buyer")
    sess = _get(verification_id)
    nonce = secrets.token_hex(16)
    captured_at = _iso()
    geo = (geo_hash or "").strip()
    material = "|".join(
        [
            sess["verification_id"],
            sess["task_id"],
            role,
            nonce,
            captured_at,
            geo,
        ]
    )
    tag_hmac = hmac.new(_tag_master_key(), material.encode("utf-8"), hashlib.sha256).hexdigest()
    challenge = {
        "challenge_id": "ch_" + secrets.token_hex(8),
        "party_role": role,
        "nonce": nonce,
        "captured_at": captured_at,
        "geo_hash": geo or None,
        "tag_hmac": tag_hmac,
        "overlay_text": (
            f"KARMA|{sess['task_id'][:12]}|{role}|{nonce[:8]}|{captured_at}"
        ),
        "expires_at": _iso(_utcnow() + timedelta(minutes=15)),
        "note_zh": "请在拍摄界面叠加 overlay_text；上传时提交 nonce/captured_at/geo_hash/tag_hmac",
    }
    with _LOCK:
        challenges = dict(sess.get("challenges") or {})
        challenges[challenge["challenge_id"]] = challenge
        sess["challenges"] = challenges
        sess["updated_at"] = _iso()
        _persist_unlocked()
    return challenge


def _verify_tag(
    sess: dict[str, Any],
    *,
    party_role: str,
    nonce: str,
    captured_at: str,
    geo_hash: str | None,
    tag_hmac: str,
) -> None:
    material = "|".join(
        [
            sess["verification_id"],
            sess["task_id"],
            party_role,
            nonce,
            captured_at,
            (geo_hash or "").strip(),
        ]
    )
    expect = hmac.new(_tag_master_key(), material.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, tag_hmac):
        raise DeliveryVerificationError("anti-forge photo tag HMAC mismatch (可能翻拍/挪用)")
    exp_challenge = None
    for ch in (sess.get("challenges") or {}).values():
        if ch.get("nonce") == nonce and ch.get("party_role") == party_role:
            exp_challenge = ch
            break
    if not exp_challenge:
        raise DeliveryVerificationError("unknown capture challenge nonce")
    exp_at = _parse_iso(exp_challenge.get("expires_at"))
    if exp_at and _utcnow() > exp_at.astimezone(timezone.utc):
        raise DeliveryVerificationError("capture challenge expired — re-issue challenge")


def submit_proof(
    verification_id: str,
    *,
    proof_type: str,
    content_hash: str,
    actor_agent_id: str,
    party_role: str,
    media_uri: str | None = None,
    nonce: str | None = None,
    captured_at: str | None = None,
    geo_hash: str | None = None,
    tag_hmac: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a typed proof (photo hash, receipt ref, route hash, …)."""
    sess = _get(verification_id)
    role = party_role.lower().strip()
    ptype = (proof_type or "").strip()
    if not ptype or not content_hash:
        raise DeliveryVerificationError("proof_type and content_hash required")
    if len(content_hash) < 16:
        raise DeliveryVerificationError("content_hash too short")

    # Tagged photo proofs require anti-forge fields
    if ptype.endswith("_tagged") or ptype in {
        "ship_photo_tagged",
        "delivery_photo_tagged",
    }:
        if not (nonce and captured_at and tag_hmac):
            raise DeliveryVerificationError(
                "tagged photo requires nonce, captured_at, tag_hmac from capture-challenge"
            )
        _verify_tag(
            sess,
            party_role=role,
            nonce=nonce,
            captured_at=captured_at,
            geo_hash=geo_hash,
            tag_hmac=tag_hmac,
        )

    with _LOCK:
        proofs = dict(sess.get("proofs") or {})
        proofs[ptype] = {
            "proof_type": ptype,
            "content_hash": content_hash,
            "media_uri": media_uri,
            "party_role": role,
            "actor_agent_id": actor_agent_id,
            "nonce": nonce,
            "captured_at": captured_at,
            "geo_hash": geo_hash,
            "tag_hmac": tag_hmac,
            "meta": dict(meta or {}),
            "submitted_at": _iso(),
        }
        sess["proofs"] = proofs
        _append_event(
            sess,
            f"proof:{ptype}",
            actor_agent_id=actor_agent_id,
            content_hash=content_hash,
        )
        _persist_unlocked()
    return _public(sess)


def seller_ship(
    verification_id: str,
    *,
    actor_agent_id: str,
    ship_proof_hash: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sess = _get(verification_id)
    if actor_agent_id != sess.get("seller_agent_id"):
        raise DeliveryVerificationError("only seller_agent_id may confirm ship/issue")
    mode = sess.get("mode")
    with _LOCK:
        if mode in PHYSICAL_MODES:
            if sess["status"] not in {"AWAITING_SELLER_SHIP", "CREATED"}:
                raise DeliveryVerificationError(f"cannot ship from status {sess['status']}")
            _append_event(sess, "seller_shipped", actor_agent_id=actor_agent_id, meta=meta or {})
            if ship_proof_hash:
                proofs = dict(sess.get("proofs") or {})
                proofs["ship_ref"] = {
                    "proof_type": "ship_ref",
                    "content_hash": ship_proof_hash,
                    "submitted_at": _iso(),
                }
                sess["proofs"] = proofs
            sess["status"] = "AWAITING_LOGISTICS_INTAKE"
        elif mode in TICKET_MODES:
            _append_event(
                sess,
                "seller_issued_confirmation",
                actor_agent_id=actor_agent_id,
                meta=meta or {},
            )
            sess["status"] = "AWAITING_BUYER_RECEIPT"
            # Ticket path: no logistics silent default unless configured
        elif mode == "ride_track":
            _append_event(
                sess,
                "seller_trip_completed",
                actor_agent_id=actor_agent_id,
                meta=meta or {},
            )
            sess["status"] = "AWAITING_BUYER_RECEIPT"
            silent = sess.get("buyer_silent_confirm_seconds")
            if silent is not None and int(silent) > 0:
                sess["buyer_silent_deadline"] = _iso(
                    _utcnow() + timedelta(seconds=int(silent))
                )
        else:
            _append_event(
                sess,
                "seller_delivered_digital",
                actor_agent_id=actor_agent_id,
                meta=meta or {},
            )
            sess["status"] = "AWAITING_BUYER_RECEIPT"
        _persist_unlocked()
    return _public(sess)


def logistics_intake(
    verification_id: str,
    *,
    actor_agent_id: str,
    item_matches: bool,
    note: str | None = None,
    intake_proof_hash: str | None = None,
) -> dict[str, Any]:
    """Logistics confirms received correct item for transport — or wrong_item."""
    sess = _get(verification_id)
    if sess.get("mode") not in PHYSICAL_MODES:
        raise DeliveryVerificationError("logistics_intake only for physical_triple")
    if actor_agent_id != sess.get("logistics_agent_id"):
        raise DeliveryVerificationError("only logistics_agent_id may confirm intake")
    if sess.get("status") != "AWAITING_LOGISTICS_INTAKE":
        raise DeliveryVerificationError(f"cannot intake from status {sess.get('status')}")

    pol = scene_policy(str(sess.get("scene_id")))
    with _LOCK:
        if item_matches:
            _append_event(
                sess,
                "logistics_intake_ok",
                actor_agent_id=actor_agent_id,
                note=note,
                intake_proof_hash=intake_proof_hash,
            )
            sess["status"] = "IN_TRANSIT"
            sess["note_zh"] = "物流已核验接件，货品与锁定交付物一致"
        else:
            _append_event(
                sess,
                "logistics_wrong_item",
                actor_agent_id=actor_agent_id,
                note=note,
            )
            sess["status"] = "WRONG_ITEM"
            share = (pol.get("loss_share") or {}).get("wrong_item_at_intake") or {}
            amount = float(sess.get("amount") or 0)
            loss = {
                "reason": "wrong_item_at_intake",
                "logistics_bps": int(share.get("logistics_bps") or 5000),
                "seller_bps": int(share.get("seller_bps") or 5000),
                "logistics_amount": round(amount * int(share.get("logistics_bps") or 5000) / 10000, 6),
                "seller_amount": round(amount * int(share.get("seller_bps") or 5000) / 10000, 6),
                "note_zh": share.get("note_zh"),
            }
            sess["loss_share_result"] = loss
            try:
                sess["liability"] = compute_breach_compensation(
                    seller_id=str(sess.get("seller_agent_id")),
                    scene_id=str(sess.get("scene_id")),
                    amount=amount,
                    breach_fraction=0.5,
                )
            except Exception:  # noqa: BLE001
                sess["liability"] = {"error": "breach_quote_failed"}
            sess["note_zh"] = "物流拒收：交付物与锁定字段不一致；错件损失共担"
        _persist_unlocked()
    return _public(sess)


def logistics_deliver(
    verification_id: str,
    *,
    actor_agent_id: str,
    delivery_proof_type: str = "delivery_photo_tagged",
    content_hash: str,
    nonce: str | None = None,
    captured_at: str | None = None,
    geo_hash: str | None = None,
    tag_hmac: str | None = None,
    media_uri: str | None = None,
) -> dict[str, Any]:
    """Logistics confirms delivered + uploads POD (tagged photo). Starts buyer silent clock."""
    sess = _get(verification_id)
    if sess.get("mode") not in PHYSICAL_MODES:
        raise DeliveryVerificationError("logistics_deliver only for physical_triple")
    if actor_agent_id != sess.get("logistics_agent_id"):
        raise DeliveryVerificationError("only logistics_agent_id may confirm deliver")
    if sess.get("status") not in {"IN_TRANSIT", "AWAITING_LOGISTICS_DELIVER"}:
        raise DeliveryVerificationError(f"cannot deliver from status {sess.get('status')}")
    if not _has_event(sess, "logistics_intake_ok"):
        raise DeliveryVerificationError("logistics intake_ok required before deliver")

    # Require tagged POD for physical
    submit_proof(
        verification_id,
        proof_type=delivery_proof_type,
        content_hash=content_hash,
        actor_agent_id=actor_agent_id,
        party_role="logistics",
        media_uri=media_uri,
        nonce=nonce,
        captured_at=captured_at,
        geo_hash=geo_hash,
        tag_hmac=tag_hmac,
    )
    sess = _get(verification_id)
    with _LOCK:
        _append_event(sess, "logistics_delivered", actor_agent_id=actor_agent_id)
        sess["status"] = "AWAITING_BUYER_RECEIPT"
        silent = sess.get("buyer_silent_confirm_seconds")
        if silent is None:
            silent = 1800
        if int(silent) > 0:
            sess["buyer_silent_deadline"] = _iso(
                _utcnow() + timedelta(seconds=int(silent))
            )
        sess["note_zh"] = (
            f"物流已送达并上传防伪凭证；买方需在 {silent}s 内确认，"
            "超时且链路正确则默认确认"
        )
        _persist_unlocked()
    return _public(sess)


def _proof_keys_present(sess: dict[str, Any]) -> set[str]:
    return set((sess.get("proofs") or {}).keys())


def _event_kinds(sess: dict[str, Any]) -> set[str]:
    return {str(e.get("kind")) for e in (sess.get("events") or [])}


def _required_satisfied(sess: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check required_events — proof:X means proof key X or event proof:X."""
    missing: list[str] = []
    kinds = _event_kinds(sess)
    proofs = _proof_keys_present(sess)
    for req in sess.get("required_events") or []:
        r = str(req)
        if r == "proof:recipient_ack_or_silent":
            if (
                "buyer_confirmed" in kinds
                or "buyer_silent_default" in kinds
                or "recipient_ack" in proofs
            ):
                continue
            missing.append(r)
            continue
        if r == "proof_fields_covered":
            # Checked separately via IF
            continue
        if r == "execution_receipt_success":
            if "execution_receipt_success" in kinds or sess.get("execution_receipt_ok"):
                continue
            missing.append(r)
            continue
        if r == "buyer_explicit_accept":
            if "buyer_confirmed" in kinds:
                continue
            missing.append(r)
            continue
        if r.startswith("proof:"):
            key = r.split(":", 1)[1]
            # allow aliases
            aliases = {
                "delivery_photo_tagged": {
                    "delivery_photo_tagged",
                    "delivery_photo_or_code",
                },
                "email_receipt_or_confirmation_code": {
                    "email_receipt",
                    "confirmation_code",
                    "booking_ref",
                    "email_receipt_or_confirmation_code",
                },
                "ticket_number_or_pnr": {
                    "ticket_number_hash",
                    "pnr",
                    "ticket_number_or_pnr",
                },
                "email_receipt_ref": {"email_receipt", "email_receipt_ref"},
                "route_or_odometer": {"route_or_odometer", "route_track_hash"},
                "fare_final": {"fare_final"},
                "goods_receipt": {"goods_receipt"},
                "qa_or_quantity": {"qa_report_hash", "quantity_accepted", "qa_or_quantity"},
                "qa_report_hash": {"qa_report_hash"},
                "deliverable_hash": {"deliverable_hash"},
                "campaign_report_hash": {"campaign_report_hash"},
                "service_completion_ref": {
                    "service_completion_ref",
                    "completion_code",
                    "appointment_ack",
                },
                "attendance_or_completion_ref": {
                    "attendance_or_completion_ref",
                    "attendance_code",
                    "certificate_ref",
                },
            }
            allowed = aliases.get(key, {key})
            if proofs & allowed or any(f"proof:{a}" in kinds for a in allowed):
                continue
            missing.append(r)
            continue
        if r in kinds:
            continue
        missing.append(r)
    return (len(missing) == 0, missing)


def assert_seller_logistics_chain_ok(sess: dict[str, Any]) -> tuple[bool, str]:
    """Precondition for buyer silent default: seller + logistics path correct."""
    mode = sess.get("mode")
    if mode in PHYSICAL_MODES:
        if not _has_event(sess, "seller_shipped"):
            return False, "missing seller_shipped"
        if not _has_event(sess, "logistics_intake_ok"):
            return False, "missing logistics_intake_ok"
        if not _has_event(sess, "logistics_delivered"):
            return False, "missing logistics_delivered"
        if sess.get("status") == "WRONG_ITEM":
            return False, "wrong_item"
        proofs = _proof_keys_present(sess)
        if not (
            proofs
            & {
                "delivery_photo_tagged",
                "delivery_photo_or_code",
            }
        ):
            return False, "missing tagged delivery photo"
        return True, "ok"
    if mode == "ride_track":
        if not _has_event(sess, "seller_trip_completed"):
            return False, "missing trip completed"
        return True, "ok"
    if mode in TICKET_MODES:
        if not _has_event(sess, "seller_issued_confirmation"):
            return False, "missing seller confirmation"
        return True, "ok"
    return True, "digital"


def mark_execution_receipt(
    verification_id: str,
    *,
    ok: bool = True,
) -> dict[str, Any]:
    sess = _get(verification_id)
    with _LOCK:
        sess["execution_receipt_ok"] = bool(ok)
        if ok:
            _append_event(sess, "execution_receipt_success")
        _persist_unlocked()
    return _public(sess)


def cover_proof_fields_from_if(
    verification_id: str,
    *,
    submitted_field_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Mark proof_fields_covered when submitted keys cover IF required_proof_fields."""
    sess = _get(verification_id)
    scene_id = str(sess.get("scene_id"))
    required: list[str] = []
    try:
        scene = get_if_scene(scene_id)
        required = list(scene.get("default_required_proof_fields") or [])
    except Exception:  # noqa: BLE001
        required = []

    submitted = set(submitted_field_keys or [])
    submitted |= _proof_keys_present(sess)
    for k in list(submitted):
        if k.endswith("_tagged"):
            submitted.add(k.replace("_tagged", ""))
            # delivery_photo_tagged covers delivery_photo_or_code
            if "delivery_photo" in k:
                submitted.add("delivery_photo_or_code")
                submitted.add("delivery_proof")
                submitted.add("delivered_at")
                submitted.add("recipient_ack")
    missing = [
        r
        for r in required
        if r not in submitted and not any(r in s or s in r for s in submitted)
    ]
    with _LOCK:
        if not missing:
            if not _has_event(sess, "proof_fields_covered"):
                _append_event(sess, "proof_fields_covered", required=required)
            sess["proof_fields_ok"] = True
            sess["proof_fields_missing"] = []
        else:
            sess["proof_fields_ok"] = False
            sess["proof_fields_missing"] = missing
        _persist_unlocked()
    out = _public(sess)
    out["proof_fields_required"] = required
    out["proof_fields_missing"] = missing
    return out


def try_verify(verification_id: str) -> dict[str, Any]:
    """Advance to VERIFIED when required events/proofs satisfied."""
    sess = _get(verification_id)
    if sess.get("status") in {"VERIFIED", "WRONG_ITEM", "FAILED", "DISPUTED"}:
        out = _public(sess)
        out["verified"] = sess.get("status") == "VERIFIED"
        return out

    if sess.get("mode") in DIGITAL_MODES and sess.get("execution_receipt_ok"):
        cover_proof_fields_from_if(verification_id)
        sess = _get(verification_id)

    ok, missing = _required_satisfied(sess)
    if sess.get("proof_fields_ok"):
        missing = [m for m in missing if m != "proof_fields_covered"]
        ok = len(missing) == 0

    if sess.get("high_risk") and not _has_event(sess, "buyer_confirmed"):
        out = _public(sess)
        out["missing"] = ["buyer_explicit_accept"]
        out["verified"] = False
        return out

    if not ok:
        with _LOCK:
            s = _SESSIONS[verification_id]
            s["note_zh"] = "验真未完成，缺少: " + ", ".join(missing)
            s["updated_at"] = _iso()
            _persist_unlocked()
        out = _public(_get(verification_id))
        out["missing"] = missing
        out["verified"] = False
        return out

    with _LOCK:
        s = _SESSIONS[verification_id]
        if _has_event(s, "buyer_confirmed") or _has_event(s, "buyer_silent_default"):
            s["status"] = "VERIFIED"
            s["verified_at"] = _iso()
            s["note_zh"] = "交付验真通过（对照锁定字段）"
        elif s.get("mode") in DIGITAL_MODES and not s.get("high_risk"):
            if s.get("execution_receipt_ok") and (
                s.get("proof_fields_ok") or s.get("buyer_silent_confirm_seconds") == 0
            ):
                if not _has_event(s, "auto_verified_digital"):
                    _append_event(s, "auto_verified_digital")
                s["status"] = "VERIFIED"
                s["verified_at"] = _iso()
                s["note_zh"] = "数字/行程场景验真通过"
        elif s.get("mode") in TICKET_MODES and _has_event(s, "seller_issued_confirmation"):
            # Ticket: proofs present (ok above) but still awaiting buyer unless silent null
            if s.get("status") == "BUYER_CONFIRMED":
                s["status"] = "VERIFIED"
                s["verified_at"] = _iso()
        _persist_unlocked()

    out = _public(_get(verification_id))
    out["verified"] = out.get("status") == "VERIFIED"
    out["missing"] = [] if out["verified"] else missing
    return out


def buyer_confirm(
    verification_id: str,
    *,
    actor_agent_id: str,
    confirm: bool = True,
    note: str | None = None,
) -> dict[str, Any]:
    sess = _get(verification_id)
    if actor_agent_id != sess.get("buyer_agent_id"):
        raise DeliveryVerificationError("only buyer_agent_id may confirm receipt")
    if sess.get("status") in {"VERIFIED", "WRONG_ITEM", "FAILED"}:
        return _public(sess)
    chain_ok, reason = assert_seller_logistics_chain_ok(sess)
    if sess.get("mode") in PHYSICAL_MODES and not chain_ok:
        raise DeliveryVerificationError(f"cannot buyer-confirm: {reason}")

    with _LOCK:
        if confirm:
            _append_event(sess, "buyer_confirmed", note=note)
            sess["status"] = "BUYER_CONFIRMED"
        else:
            _append_event(sess, "buyer_rejected", note=note)
            sess["status"] = "REJECTED"
            try:
                sess["liability"] = compute_breach_compensation(
                    seller_id=str(sess.get("seller_agent_id")),
                    scene_id=str(sess.get("scene_id")),
                    amount=float(sess.get("amount") or 0),
                    breach_fraction=0.3,
                )
            except Exception:  # noqa: BLE001
                pass
        _persist_unlocked()
    if confirm:
        return try_verify(verification_id)
    return _public(_get(verification_id))


def apply_silent_buyer_default(verification_id: str) -> dict[str, Any] | None:
    """If past silent deadline and seller+logistics chain OK → default confirm."""
    sess = _get(verification_id)
    if sess.get("status") in {"VERIFIED", "BUYER_CONFIRMED", "BUYER_SILENT_DEFAULT", "WRONG_ITEM", "FAILED", "REJECTED"}:
        return None
    if sess.get("high_risk"):
        return None
    silent = sess.get("buyer_silent_confirm_seconds")
    if silent is None or int(silent) <= 0:
        return None
    deadline = _parse_iso(sess.get("buyer_silent_deadline"))
    if not deadline or _utcnow() <= deadline.astimezone(timezone.utc):
        return None
    chain_ok, reason = assert_seller_logistics_chain_ok(sess)
    if not chain_ok:
        with _LOCK:
            sess["note_zh"] = f"静默窗已过但链路未通过: {reason} — 不默认确认"
            _persist_unlocked()
        return _public(sess)

    with _LOCK:
        _append_event(
            sess,
            "buyer_silent_default",
            reason="buyer_silent_after_logistics_pod",
            verified_chain=reason,
        )
        sess["status"] = "BUYER_SILENT_DEFAULT"
        sess["note_zh"] = "买方超时未确认；已校验卖方发出+物流接件/送达凭证正确 → 默认确认"
        _persist_unlocked()
    return try_verify(verification_id)


def expire_silent_buyers(*, limit: int = 100) -> dict[str, Any]:
    _ensure_loaded()
    applied = []
    with _LOCK:
        ids = list(_SESSIONS.keys())[: limit * 2]
    for vid in ids:
        if len(applied) >= limit:
            break
        try:
            out = apply_silent_buyer_default(vid)
        except DeliveryVerificationError:
            continue
        if out and out.get("status") in {"VERIFIED", "BUYER_SILENT_DEFAULT"}:
            applied.append(out)
    return {"swept": len(applied), "sessions": applied}


def require_verified_for_settle(
    *,
    task_id: str,
    scene_id: str | None = None,
    allow_missing_session_for_digital: bool = True,
) -> dict[str, Any]:
    """Gate for settlement submit/buyer-accept."""
    # Sweep silent first
    expire_silent_buyers(limit=50)
    sess = get_verification_for_task(task_id)
    if not sess:
        sid = scene_id or "api_tool_call"
        mode = scene_policy(sid).get("mode")
        if allow_missing_session_for_digital and mode in DIGITAL_MODES:
            return {
                "ok": True,
                "skipped": True,
                "reason": "digital_light_no_session",
                "mode": mode,
            }
        raise DeliveryVerificationError(
            "delivery verification session required — "
            "POST /v1/delivery-verification/sessions"
        )
    if sess.get("status") != "VERIFIED":
        # try advance
        advanced = try_verify(sess["verification_id"])
        if advanced.get("status") != "VERIFIED":
            raise DeliveryVerificationError(
                f"delivery not VERIFIED (status={advanced.get('status')}); "
                f"missing={advanced.get('missing')}"
            )
        sess = advanced
    return {"ok": True, "verification": sess}


def demo_complete_physical_flow(
    *,
    task_id: str,
    scene_id: str,
    seller_agent_id: str,
    buyer_agent_id: str,
    logistics_agent_id: str,
    capture_id: str | None = None,
    amount: float = 0,
) -> dict[str, Any]:
    """Test/demo helper: happy-path triple confirm + tagged POD + buyer confirm."""
    sess = create_verification_session(
        task_id=task_id,
        scene_id=scene_id,
        seller_agent_id=seller_agent_id,
        buyer_agent_id=buyer_agent_id,
        logistics_agent_id=logistics_agent_id,
        capture_id=capture_id,
        amount=amount,
    )
    vid = sess["verification_id"]
    seller_ship(vid, actor_agent_id=seller_agent_id, ship_proof_hash="ship_" + secrets.token_hex(8))
    logistics_intake(vid, actor_agent_id=logistics_agent_id, item_matches=True)
    ch = issue_capture_challenge(vid, party_role="logistics", geo_hash="geo_demo")
    logistics_deliver(
        vid,
        actor_agent_id=logistics_agent_id,
        content_hash="pod_" + secrets.token_hex(16),
        nonce=ch["nonce"],
        captured_at=ch["captured_at"],
        geo_hash=ch.get("geo_hash"),
        tag_hmac=ch["tag_hmac"],
    )
    # Extra proofs often required
    submit_proof(
        vid,
        proof_type="recipient_ack",
        content_hash="ack_" + secrets.token_hex(8),
        actor_agent_id=buyer_agent_id,
        party_role="buyer",
    )
    return buyer_confirm(vid, actor_agent_id=buyer_agent_id, confirm=True)
