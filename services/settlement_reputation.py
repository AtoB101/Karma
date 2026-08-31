"""P8 Settlement & Reputation — scene-differentiated settle + encrypted public attest.

Privacy model
-------------
- Public surface: commitments / hashes only (outcome_commitment, scope_hash, …)
- Private detail: karma2 AES-GCM ciphertext per role (parties | regulator | protocol)
- Anyone can verify commitment match; only role key holders decrypt PII/amounts
- Regulator role supports audit/traceback without plaintext public indexes

Agent smart-verify
------------------
When scene policy ``agent_auto_verify`` and P7 VERIFIED (if required), Agent may
complete settle confirmation on behalf of the user to save time — never for
high_risk / OWNER_CONFIRM-only delayed_explicit scenes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "settlement-reputation.v1.json"
)
_STORE_PATH = (
    Path(__file__).resolve().parents[1]
    / ".karma_data"
    / "settlement_attestations.json"
)

_LOCK = threading.Lock()
_ATTESTATIONS: dict[str, dict[str, Any]] = {}
_SCENE_REP: dict[str, dict[str, Any]] = {}  # agent_id -> {scene_id: stats}
_LOADED = False

PREFIX = "karma2."


class SettlementReputationError(ValueError):
    pass


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _master_key() -> bytes:
    raw = (
        os.getenv("KARMA_SETTLE_ATTEST_KEY", "").strip()
        or os.getenv("KARMA_IMPORTANT_FIELDS_KEY", "").strip()
    )
    if raw:
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
        return hashlib.sha256(raw.encode("utf-8")).digest()
    env = (os.getenv("APP_ENV") or os.getenv("KARMA_ENV") or "dev").lower()
    if env in {"prod", "production", "staging"}:
        raise SettlementReputationError(
            "KARMA_SETTLE_ATTEST_KEY (or KARMA_IMPORTANT_FIELDS_KEY) required in prod/staging"
        )
    return hashlib.sha256(b"karma-settle-attest-dev-only").digest()


def _hkdf(info: bytes, length: int = 32) -> bytes:
    return HKDF(
        algorithm=SHA256(),
        length=length,
        salt=b"karma-settle-attest-v1",
        info=info,
    ).derive(_master_key())


def _role_key(attestation_id: str, role: str) -> bytes:
    r = (role or "protocol").lower().strip()
    return _hkdf(f"aes|settle|v1|{attestation_id}|{r}".encode("utf-8"))


def _encrypt_role(
    payload: dict[str, Any],
    *,
    attestation_id: str,
    task_id: str,
    scene_id: str,
    scope_hash: str,
    outcome: str,
    role: str,
) -> str:
    key = _role_key(attestation_id, role)
    aad = "|".join(
        [attestation_id, task_id, scene_id, scope_hash, outcome, role]
    ).encode("utf-8")
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, _canonical(payload).encode("utf-8"), aad)
    blob = base64.urlsafe_b64encode(nonce + ct).decode("ascii").rstrip("=")
    return PREFIX + blob


def _decrypt_role(
    ciphertext: str,
    *,
    attestation_id: str,
    task_id: str,
    scene_id: str,
    scope_hash: str,
    outcome: str,
    role: str,
) -> dict[str, Any]:
    if not ciphertext.startswith(PREFIX):
        raise SettlementReputationError("ciphertext must use karma2. envelope")
    raw_b64 = ciphertext[len(PREFIX) :]
    pad = "=" * (-len(raw_b64) % 4)
    data = base64.urlsafe_b64decode(raw_b64 + pad)
    if len(data) < 12 + 16:
        raise SettlementReputationError("ciphertext too short")
    nonce, ct = data[:12], data[12:]
    key = _role_key(attestation_id, role)
    aad = "|".join(
        [attestation_id, task_id, scene_id, scope_hash, outcome, role]
    ).encode("utf-8")
    try:
        plain = AESGCM(key).decrypt(nonce, ct, aad)
    except Exception as exc:  # noqa: BLE001
        raise SettlementReputationError("decrypt failed (wrong role or tampered)") from exc
    obj = json.loads(plain.decode("utf-8"))
    if not isinstance(obj, dict):
        raise SettlementReputationError("decrypted payload must be object")
    return obj


@lru_cache(maxsize=1)
def load_settle_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"settlement-reputation catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-settlement-reputation-v1":
        raise SettlementReputationError("unsupported settlement-reputation schema_version")
    return data


def scene_settle_policy(scene_id: str) -> dict[str, Any]:
    cat = load_settle_catalog()
    defaults = deepcopy(cat.get("global_defaults") or {})
    scene = deepcopy((cat.get("scenes") or {}).get(scene_id) or {})
    if scene_id not in (cat.get("scenes") or {}):
        scene = {
            "scene_id": scene_id,
            "mode": "milestone_accept",
            "confirm": "OWNER_CONFIRM",
            "agent_auto_verify": False,
            "unknown_scene": True,
            "reputation_profile": "professional",
        }
    merged = {**defaults, **scene}
    merged["scene_id"] = scene_id
    profiles = cat.get("reputation_profiles") or {}
    pid = merged.get("reputation_profile") or "professional"
    merged["reputation_profile_body"] = deepcopy(profiles.get(pid) or profiles.get("professional") or {})
    return merged


def list_settle_scenes() -> list[dict[str, Any]]:
    cat = load_settle_catalog()
    out = []
    for sid, body in (cat.get("scenes") or {}).items():
        pol = scene_settle_policy(sid)
        out.append(
            {
                "scene_id": sid,
                "mode": pol.get("mode"),
                "confirm": pol.get("confirm"),
                "agent_auto_verify": bool(pol.get("agent_auto_verify")),
                "require_p7_verified": bool(pol.get("require_p7_verified")),
                "reputation_profile": pol.get("reputation_profile"),
                "settle_delay_seconds": int(pol.get("settle_delay_seconds") or 0),
                "invoice_window_seconds": int(pol.get("invoice_window_seconds") or 0),
                "reality_note_zh": body.get("reality_note_zh"),
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
                    _ATTESTATIONS.update(
                        {str(k): dict(v) for k, v in (raw.get("attestations") or {}).items()}
                    )
                    _SCENE_REP.update(
                        {str(k): dict(v) for k, v in (raw.get("scene_reputation") or {}).items()}
                    )
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"attestations": _ATTESTATIONS, "scene_reputation": _SCENE_REP}
    _STORE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def reset_settle_attestations() -> None:
    global _LOADED
    with _LOCK:
        _ATTESTATIONS.clear()
        _SCENE_REP.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def assert_settle_gates(
    *,
    task_id: str,
    scene_id: str,
    delivery_verified: bool | None = None,
    confirmation_satisfied: bool = True,
    success_receipt: bool = True,
    agent_auto: bool = False,
) -> dict[str, Any]:
    """Unified P8 settle gate checklist (P4/P6/P7 aligned)."""
    pol = scene_settle_policy(scene_id)
    errors: list[str] = []

    if pol.get("require_success_receipt", True) and not success_receipt:
        errors.append("success_receipt_required")

    require_p7 = bool(pol.get("require_p7_verified", True))
    if require_p7:
        if delivery_verified is None:
            try:
                from services.delivery_verification import (  # noqa: PLC0415
                    get_verification_for_task,
                    require_verified_for_settle,
                )

                require_verified_for_settle(
                    task_id=task_id,
                    scene_id=scene_id,
                    allow_missing_session_for_digital=not require_p7,
                )
                delivery_verified = True
            except Exception as exc:  # noqa: BLE001
                # digital scenes may skip
                mode = pol.get("mode")
                if mode in {"metered_instant"} and "digital" in str(
                    pol.get("reputation_profile")
                ):
                    delivery_verified = True
                else:
                    try:
                        from services.delivery_verification import (  # noqa: PLC0415
                            get_verification_for_task,
                        )

                        sess = get_verification_for_task(task_id)
                        if sess is None and pol.get("reputation_profile") == "digital":
                            delivery_verified = True
                        else:
                            errors.append(f"p7_not_verified:{exc}")
                            delivery_verified = False
                    except Exception:  # noqa: BLE001
                        errors.append(f"p7_not_verified:{exc}")
                        delivery_verified = False
        elif not delivery_verified:
            errors.append("p7_not_verified")

    if pol.get("confirm") == "OWNER_CONFIRM" and not confirmation_satisfied and not (
        agent_auto and pol.get("agent_auto_verify")
    ):
        errors.append("owner_confirm_required")

    if agent_auto and not pol.get("agent_auto_verify"):
        errors.append("agent_auto_verify_not_allowed_for_scene")

    if pol.get("mode") == "delayed_explicit" and agent_auto:
        errors.append("high_risk_forbids_agent_auto")

    profile = pol.get("reputation_profile_body") or {}
    if profile.get("require_explicit_buyer") and agent_auto:
        errors.append("high_risk_requires_explicit_buyer")

    ok = len(errors) == 0
    return {
        "ok": ok,
        "scene_id": scene_id,
        "policy": {
            "mode": pol.get("mode"),
            "confirm": pol.get("confirm"),
            "agent_auto_verify": bool(pol.get("agent_auto_verify")),
            "require_p7_verified": require_p7,
            "reputation_profile": pol.get("reputation_profile"),
            "settle_delay_seconds": int(pol.get("settle_delay_seconds") or 0),
            "invoice_window_seconds": int(pol.get("invoice_window_seconds") or 0),
        },
        "errors": errors,
        "delivery_verified": delivery_verified,
    }


def compute_scene_reputation_delta(
    *,
    scene_id: str,
    success: bool,
    disputed: bool = False,
    volume: float = 0.0,
) -> dict[str, Any]:
    pol = scene_settle_policy(scene_id)
    body = pol.get("reputation_profile_body") or {}
    if disputed:
        delta = -float(body.get("dispute_penalty") or 15.0)
        reason = "dispute"
    elif success:
        base = float(body.get("success_base") or 5.0)
        vol = min(max(float(volume), 0.0), 500.0) * float(body.get("volume_factor") or 0.05)
        delta = base + vol
        reason = "settled_success"
    else:
        delta = -8.0
        reason = "settle_fail"
    # Public commitment hides exact delta amount in plaintext APIs — still store for parties
    commitment = _sha256_hex(
        _canonical(
            {
                "scene_id": scene_id,
                "delta": round(delta, 6),
                "reason": reason,
                "profile": pol.get("reputation_profile"),
            }
        )
    )
    return {
        "scene_id": scene_id,
        "delta": round(delta, 6),
        "reason": reason,
        "profile": pol.get("reputation_profile"),
        "reputation_delta_commitment": commitment,
    }


def _agent_rep_key(agent_id: str) -> str:
    """Disk/index key — commitment only; never persist raw agent_id."""
    return _sha256_hex(f"agent|{agent_id}")


def record_scene_reputation(
    *,
    agent_id: str,
    scene_id: str,
    delta: float,
    success: bool,
) -> dict[str, Any]:
    _ensure_loaded()
    key = _agent_rep_key(agent_id)
    with _LOCK:
        entry = dict(
            _SCENE_REP.get(key)
            or {"agent_commitment": key, "scenes": {}}
        )
        # Drop legacy plaintext agent_id if present from older store versions
        entry.pop("agent_id", None)
        entry["agent_commitment"] = key
        scenes = dict(entry.get("scenes") or {})
        sc = dict(
            scenes.get(scene_id)
            or {
                "scene_id": scene_id,
                "settled_count": 0,
                "success_count": 0,
                "score_delta_total": 0.0,
            }
        )
        sc["settled_count"] = int(sc.get("settled_count") or 0) + 1
        if success:
            sc["success_count"] = int(sc.get("success_count") or 0) + 1
        sc["score_delta_total"] = round(float(sc.get("score_delta_total") or 0) + float(delta), 6)
        sc["updated_at"] = _utcnow_iso()
        scenes[scene_id] = sc
        entry["scenes"] = scenes
        entry["updated_at"] = _utcnow_iso()
        _SCENE_REP[key] = entry
        # Migrate away from legacy plaintext keys
        if agent_id in _SCENE_REP:
            _SCENE_REP.pop(agent_id, None)
        _persist_unlocked()
    return public_agent_reputation(agent_id)


def public_agent_reputation(
    agent_id: str, *, include_agent_id: bool = False
) -> dict[str, Any]:
    """Public reputation view — aggregates + commitments, no PII by default."""
    _ensure_loaded()
    agent_commitment = _agent_rep_key(agent_id)
    with _LOCK:
        entry = (
            _SCENE_REP.get(agent_commitment)
            or _SCENE_REP.get(agent_id)  # legacy plaintext key
            or {"scenes": {}}
        )
        scenes = dict(entry.get("scenes") or {})
    scene_public = []
    total_settled = 0
    total_success = 0
    for sid, sc in scenes.items():
        settled = int(sc.get("settled_count") or 0)
        success = int(sc.get("success_count") or 0)
        total_settled += settled
        total_success += success
        scene_public.append(
            {
                "scene_id": sid,
                "settled_count": settled,
                "success_count": success,
                "success_rate": round(success / settled, 4) if settled else None,
                "score_delta_commitment": _sha256_hex(
                    _canonical(
                        {
                            "agent": agent_id,
                            "scene_id": sid,
                            "score_delta_total": sc.get("score_delta_total"),
                        }
                    )
                ),
            }
        )
    out: dict[str, Any] = {
        "agent_commitment": agent_commitment,
        "total_settled": total_settled,
        "total_success": total_success,
        "success_rate": round(total_success / total_settled, 4) if total_settled else None,
        "scenes": scene_public,
        "privacy_note_zh": "公开侧为聚合与承诺哈希；明细金额/身份仅密文可查",
    }
    # Directory/lookup may opt in; default public export omits raw agent_id
    if include_agent_id:
        out["agent_id"] = agent_id
    return out


def seal_settlement_attestation(
    *,
    task_id: str,
    scene_id: str,
    buyer_agent_id: str,
    seller_agent_id: str,
    amount: float,
    currency: str = "USDC",
    outcome: str = "SETTLED",
    scope_hash: str | None = None,
    proof_hash: str | None = None,
    capture_id: str | None = None,
    delivery_verification_id: str | None = None,
    agent_auto_verified: bool = False,
    extra_private: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal settle outcome: public commitments + role-encrypted private audit pack."""
    pol = scene_settle_policy(scene_id)
    att_id = "sat_" + secrets.token_hex(12)
    outcome = (outcome or "SETTLED").upper()
    scope = scope_hash or _sha256_hex(
        _canonical(
            {
                "task_id": task_id,
                "scene_id": scene_id,
                "buyer": buyer_agent_id,
                "seller": seller_agent_id,
                "amount": amount,
                "capture_id": capture_id,
            }
        )
    )
    proof = proof_hash or _sha256_hex(
        _canonical(
            {
                "delivery_verification_id": delivery_verification_id,
                "capture_id": capture_id,
                "outcome": outcome,
            }
        )
    )
    rep = compute_scene_reputation_delta(
        scene_id=scene_id, success=(outcome == "SETTLED"), volume=amount
    )
    private_detail = {
        "buyer_agent_id": buyer_agent_id,
        "seller_agent_id": seller_agent_id,
        "amount": amount,
        "currency": currency,
        "capture_id": capture_id,
        "delivery_verification_id": delivery_verification_id,
        "reputation_delta": rep["delta"],
        "extra": dict(extra_private or {}),
        "audit": {
            "sealed_at": _utcnow_iso(),
            "policy_mode": pol.get("mode"),
            "traceback": [
                "P4 confirmation (if required)",
                "P5 important fields lock",
                "P6 liability armed",
                "P7 delivery VERIFIED (if required)",
                "P8 settle attestation sealed",
            ],
        },
    }
    # Strip PII from public outcome commitment input — use commitments of parties
    outcome_body = {
        "task_id_commitment": _sha256_hex(f"task|{task_id}"),
        "scene_id": scene_id,
        "outcome": outcome,
        "buyer_commitment": _sha256_hex(f"agent|{buyer_agent_id}"),
        "seller_commitment": _sha256_hex(f"agent|{seller_agent_id}"),
        "amount_commitment": _sha256_hex(f"amt|{amount:.6f}|{currency}"),
        "scope_hash": scope,
        "proof_hash": proof,
        "reputation_delta_commitment": rep["reputation_delta_commitment"],
        "policy_mode": pol.get("mode"),
        "agent_auto_verified": bool(agent_auto_verified),
    }
    outcome_commitment = _sha256_hex(_canonical(outcome_body))

    cipher_parties = _encrypt_role(
        private_detail,
        attestation_id=att_id,
        task_id=task_id,
        scene_id=scene_id,
        scope_hash=scope,
        outcome=outcome,
        role="parties",
    )
    cipher_regulator = _encrypt_role(
        {**private_detail, "regulator_access": True},
        attestation_id=att_id,
        task_id=task_id,
        scene_id=scene_id,
        scope_hash=scope,
        outcome=outcome,
        role="regulator",
    )
    cipher_protocol = _encrypt_role(
        private_detail,
        attestation_id=att_id,
        task_id=task_id,
        scene_id=scene_id,
        scope_hash=scope,
        outcome=outcome,
        role="protocol",
    )

    # Persist commitments + ciphertext only — no plaintext amount / party ids
    # (adversarial disk scrape must not recover private settle detail).
    record = {
        "attestation_id": att_id,
        "task_id": task_id,
        "scene_id": scene_id,
        "outcome": outcome,
        "outcome_commitment": outcome_commitment,
        "scope_hash": scope,
        "proof_hash": proof,
        "reputation_delta_commitment": rep["reputation_delta_commitment"],
        "policy_mode": pol.get("mode"),
        "agent_auto_verified": bool(agent_auto_verified),
        "settled_at": _utcnow_iso(),
        "ciphertext": {
            "parties": cipher_parties,
            "regulator": cipher_regulator,
            "protocol": cipher_protocol,
        },
        "outcome_body": outcome_body,
        "buyer_commitment": outcome_body["buyer_commitment"],
        "seller_commitment": outcome_body["seller_commitment"],
    }
    _ensure_loaded()
    with _LOCK:
        _ATTESTATIONS[att_id] = record
        # index by task
        _ATTESTATIONS[f"task:{task_id}"] = {"ref": att_id}
        _persist_unlocked()

    # scene reputation ledger (public aggregates)
    if outcome == "SETTLED":
        record_scene_reputation(
            agent_id=seller_agent_id,
            scene_id=scene_id,
            delta=rep["delta"],
            success=True,
        )

    return public_attestation_view(att_id)


def public_attestation_view(attestation_id: str) -> dict[str, Any]:
    _ensure_loaded()
    with _LOCK:
        rec = _ATTESTATIONS.get(attestation_id)
        if rec and rec.get("ref"):
            rec = _ATTESTATIONS.get(str(rec["ref"]))
        if not rec:
            raise SettlementReputationError(f"unknown attestation_id: {attestation_id}")
        return {
            "attestation_id": rec["attestation_id"],
            "task_id_commitment": rec["outcome_body"]["task_id_commitment"],
            "scene_id": rec["scene_id"],
            "outcome": rec["outcome"],
            "outcome_commitment": rec["outcome_commitment"],
            "scope_hash": rec["scope_hash"],
            "proof_hash": rec["proof_hash"],
            "reputation_delta_commitment": rec["reputation_delta_commitment"],
            "settled_at": rec["settled_at"],
            "policy_mode": rec["policy_mode"],
            "agent_auto_verified": rec["agent_auto_verified"],
            "envelope": PREFIX,
            "has_encrypted_audit": True,
            "privacy_note_zh": (
                "公开字段仅为承诺哈希与场景/结果；金额与当事人身份在 karma2 密文中，"
                "持 parties/regulator 角色密钥可解密审计"
            ),
        }


def get_attestation_for_task(task_id: str) -> dict[str, Any] | None:
    _ensure_loaded()
    with _LOCK:
        ref = _ATTESTATIONS.get(f"task:{task_id}")
        if not ref:
            return None
        aid = str(ref.get("ref") or "")
        if not aid or aid not in _ATTESTATIONS:
            return None
    return public_attestation_view(aid)


def verify_outcome_commitment(
    *,
    attestation_id: str,
    expected_commitment: str | None = None,
    outcome_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public verify: recompute commitment without revealing private plaintext."""
    _ensure_loaded()
    with _LOCK:
        rec = _ATTESTATIONS.get(attestation_id)
        if rec and rec.get("ref"):
            rec = _ATTESTATIONS.get(str(rec["ref"]))
        if not rec:
            raise SettlementReputationError(f"unknown attestation_id: {attestation_id}")
        stored = rec["outcome_commitment"]
        body = dict(rec.get("outcome_body") or {})
    if outcome_body is not None:
        recomputed = _sha256_hex(_canonical(outcome_body))
        match = hmac.compare_digest(recomputed, stored)
        return {
            "valid": match,
            "attestation_id": attestation_id,
            "stored_commitment": stored,
            "recomputed_commitment": recomputed,
            "mode": "body_recompute",
        }
    if expected_commitment:
        match = hmac.compare_digest(expected_commitment, stored)
        return {
            "valid": match,
            "attestation_id": attestation_id,
            "stored_commitment": stored,
            "mode": "commitment_compare",
        }
    # Self-check stored body
    recomputed = _sha256_hex(_canonical(body))
    return {
        "valid": hmac.compare_digest(recomputed, stored),
        "attestation_id": attestation_id,
        "stored_commitment": stored,
        "recomputed_commitment": recomputed,
        "public_body": body,
        "mode": "integrity_self_check",
        "note_zh": "公开可核验承诺完整性；不含金额明文",
    }


def decrypt_attestation(
    attestation_id: str,
    *,
    role: str,
) -> dict[str, Any]:
    """Decrypt private audit pack — parties or regulator only (key derived)."""
    role = role.lower().strip()
    if role not in {"parties", "regulator", "protocol"}:
        raise SettlementReputationError("role must be parties|regulator|protocol")
    _ensure_loaded()
    with _LOCK:
        rec = _ATTESTATIONS.get(attestation_id)
        if rec and rec.get("ref"):
            rec = _ATTESTATIONS.get(str(rec["ref"]))
        if not rec:
            raise SettlementReputationError(f"unknown attestation_id: {attestation_id}")
        ct = (rec.get("ciphertext") or {}).get(role)
        if not ct:
            raise SettlementReputationError(f"no ciphertext for role {role}")
        task_id = rec["task_id"]
        scene_id = rec["scene_id"]
        scope = rec["scope_hash"]
        outcome = rec["outcome"]
        aid = rec["attestation_id"]
    detail = _decrypt_role(
        ct,
        attestation_id=aid,
        task_id=task_id,
        scene_id=scene_id,
        scope_hash=scope,
        outcome=outcome,
        role=role,
    )
    return {
        "attestation_id": aid,
        "role": role,
        "detail": detail,
        "audit_note_zh": "解密仅供当事人或监管审计；禁止将明文写入公开索引",
    }


def agent_auto_verify_decision(
    *,
    scene_id: str,
    task_id: str,
    delivery_verified: bool = False,
) -> dict[str, Any]:
    """Whether Agent may settle-confirm for the user (save time)."""
    pol = scene_settle_policy(scene_id)
    allowed = bool(pol.get("agent_auto_verify"))
    if pol.get("mode") == "delayed_explicit":
        allowed = False
    profile = pol.get("reputation_profile_body") or {}
    if profile.get("require_explicit_buyer"):
        allowed = False
    if pol.get("require_p7_verified") and not delivery_verified:
        # try live check
        try:
            from services.delivery_verification import get_verification_for_task  # noqa: PLC0415

            sess = get_verification_for_task(task_id)
            delivery_verified = bool(sess and sess.get("status") == "VERIFIED")
        except Exception:  # noqa: BLE001
            delivery_verified = False
        if pol.get("reputation_profile") == "digital":
            delivery_verified = True
    if allowed and pol.get("require_p7_verified") and not delivery_verified:
        allowed = False
    return {
        "allowed": allowed,
        "scene_id": scene_id,
        "task_id": task_id,
        "policy_mode": pol.get("mode"),
        "confirm": pol.get("confirm"),
        "delivery_verified": delivery_verified,
        "reason_zh": (
            "Agent 可在验真通过后代用户完成结算确认，节省时间"
            if allowed
            else "本场景要求主人显式确认或验真未完成，禁止 Agent 代结算"
        ),
    }


async def apply_settle_reputation(
    db: Any,
    *,
    seller_agent_id: str,
    scene_id: str,
    amount: float,
    success: bool = True,
    disputed: bool = False,
    buyer_agent_id: str | None = None,
    exclude_task_id: str | None = None,
) -> dict[str, Any]:
    """Update global reputation (existing) + scene ledger (P8)."""
    from services.agent_trust import record_worker_settlement_outcome  # noqa: PLC0415

    rep = compute_scene_reputation_delta(
        scene_id=scene_id, success=success, disputed=disputed, volume=amount
    )
    row = await record_worker_settlement_outcome(
        db,
        worker_agent_id=seller_agent_id,
        success=success and not disputed,
        disputed=disputed,
        volume=amount,
        buyer_agent_id=buyer_agent_id,
        exclude_task_id=exclude_task_id,
    )
    # Scene ledger is written by seal_settlement_attestation to avoid double-count
    return {
        "global_score": float(getattr(row, "score", 0) or 0),
        "scene_delta": rep,
        "public_reputation": public_agent_reputation(seller_agent_id),
    }
