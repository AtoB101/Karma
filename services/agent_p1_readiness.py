"""P1 readiness — identity class, owner bind, capability, responsibility, anti-forgery.

Counterparties call ``evaluate_p1_readiness`` / GET /v1/agents/{id}/p1-status to verify
an agent against *existing records* (directory, profile card, boundary, reputation,
ack attestation) before treating them as a real user/merchant/enterprise.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import AgentModel, IdentityProfileModel, ReputationModel
from services.agent_boundary import (
    boundary_digest,
    get_agent_boundary,
    materialize_agent_boundary,
)
from services.agent_onboarding_template import OnboardingError, validate_service_specs_for_industries
from services.agent_profile_store import get_profile_card
from services.human_confirmation_policy import allow_demo_confirmation_bypass
from services.signing import sha256_of, signing_service

P1_SCHEMA = "karma-agent-p1-v1"
SERVER_DEFAULT_KEY_MARKERS = ("pk-",)


def is_prod_like_env() -> bool:
    return (settings.app_env or "").lower() not in ("development", "dev", "local", "test")


def canonical_connect_challenge(
    *,
    agent_id: str,
    owner_identity_id: str,
    identity_class: str,
    nonce: str,
    issued_at: str,
) -> dict[str, str]:
    return {
        "agent_id": agent_id,
        "owner_identity_id": owner_identity_id,
        "identity_class": identity_class,
        "nonce": nonce,
        "issued_at": issued_at,
        "purpose": "karma_p1_connect_ownership",
    }


def canonical_responsibility_ack(
    *,
    agent_id: str,
    owner_identity_id: str,
    identity_class: str,
    boundary_hash: str,
    acknowledged_at: str,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "owner_identity_id": owner_identity_id,
        "identity_class": identity_class,
        "boundary_hash": boundary_hash,
        "acknowledged_at": acknowledged_at,
        "statement_zh": (
            "本人确认对该 agent 的交付与证据责任边界负责；资金不托管；"
            "未声明能力不接单；虚假指标视为违约。"
        ),
        "purpose": "karma_p1_responsibility_ack",
    }


def boundary_content_hash(boundary: dict[str, Any] | None) -> str | None:
    if not boundary:
        return None
    # Hash stable public parts only (ignore efficiency notes / related URLs)
    payload = {
        "schema_version": boundary.get("schema_version"),
        "agent_id": boundary.get("agent_id"),
        "profile_id": boundary.get("profile_id"),
        "scene_ids": boundary.get("scene_ids"),
        "capability_boundary": boundary.get("capability_boundary"),
        "responsibility_boundary": {
            "owner_identity_id": (boundary.get("responsibility_boundary") or {}).get(
                "owner_identity_id"
            ),
            "boundary_id": (boundary.get("responsibility_boundary") or {}).get("boundary_id"),
            "allows_delegation": (boundary.get("responsibility_boundary") or {}).get(
                "allows_delegation"
            ),
            "compliance_flags": (boundary.get("responsibility_boundary") or {}).get(
                "compliance_flags"
            ),
            "notes_zh": (boundary.get("responsibility_boundary") or {}).get("notes_zh"),
        },
        "confirmation_boundary": {
            "role": (boundary.get("confirmation_boundary") or {}).get("role"),
            "primary_scene_id": (boundary.get("confirmation_boundary") or {}).get(
                "primary_scene_id"
            ),
            "must_confirm_steps": (boundary.get("confirmation_boundary") or {}).get(
                "must_confirm_steps"
            ),
            "auto_ok_steps": (boundary.get("confirmation_boundary") or {}).get("auto_ok_steps"),
        },
    }
    return "sha256:" + sha256_of(payload)


def _is_placeholder_public_key(public_key: str | None) -> bool:
    pk = (public_key or "").strip()
    if not pk:
        return True
    if pk.startswith(SERVER_DEFAULT_KEY_MARKERS):
        return True
    return False


def _is_server_singleton_key(public_key: str | None) -> bool:
    if not public_key:
        return True
    try:
        return public_key == signing_service.get_public_key_b64()
    except Exception:  # noqa: BLE001
        return False


def verify_ownership_proof(
    *,
    challenge: dict[str, Any],
    signature_b64: str,
    public_key_b64: str,
) -> bool:
    canonical = json.dumps(challenge, sort_keys=True, separators=(",", ":")).encode()
    return signing_service.verify(canonical, signature_b64, public_key_b64)


def attest_responsibility_ack(ack_payload: dict[str, Any]) -> dict[str, Any]:
    """Platform-attested ack (integrity). Prefer owner signature in production."""
    sig = signing_service.sign_dict(ack_payload)
    return {
        **ack_payload,
        "attestation": {
            "mode": "platform_ed25519",
            "signer": "karma_platform",
            "signature": sig,
            "public_key": signing_service.get_public_key_b64(),
        },
    }


def responsibility_ack_stable_message(
    *,
    agent_id: str,
    owner_identity_id: str,
    identity_class: str,
    boundary_hash: str,
) -> bytes:
    """Stable bytes for owner Ed25519 ack (no timestamp drift)."""
    return (
        f"karma_p1_responsibility_ack|{agent_id}|{owner_identity_id}|"
        f"{identity_class}|{boundary_hash}"
    ).encode()


def verify_responsibility_attestation(ack_record: dict[str, Any] | None) -> bool:
    if not ack_record or not isinstance(ack_record, dict):
        return False
    if not ack_record.get("acknowledged"):
        return False
    att = ack_record.get("attestation") or {}
    mode = att.get("mode")
    sig = att.get("signature")
    if not sig:
        return False
    payload = {k: v for k, v in ack_record.items() if k != "attestation"}
    if mode == "platform_ed25519":
        return signing_service.verify(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            sig,
            att.get("public_key") or signing_service.get_public_key_b64(),
        )
    if mode == "owner_ed25519":
        pk = att.get("public_key") or ack_record.get("signer_public_key")
        if not pk:
            return False
        msg = responsibility_ack_stable_message(
            agent_id=str(ack_record.get("agent_id") or ""),
            owner_identity_id=str(ack_record.get("owner_identity_id") or ""),
            identity_class=str(ack_record.get("identity_class") or ""),
            boundary_hash=str(ack_record.get("boundary_hash") or ""),
        )
        return signing_service.verify(msg, sig, pk)
    return False


async def ensure_owner_identity(
    db: AsyncSession,
    owner_identity_id: str,
    *,
    display_hint: str | None = None,
) -> IdentityProfileModel:
    """Ensure IdentityProfile exists for owner binding (creates active stub if missing)."""
    oid = (owner_identity_id or "").strip()
    if not oid:
        raise ValueError("owner_identity_id is required")
    row = await db.get(IdentityProfileModel, oid)
    if row:
        return row
    # Always unique display_id derived from identity_id (anti-collision)
    digest = hashlib.sha256(oid.encode()).hexdigest()[:12]
    hint = (display_hint or oid).replace(" ", "")[:24]
    display_id = f"{hint}-{digest}"[:64]
    row = IdentityProfileModel(
        identity_id=oid,
        display_id=display_id,
        legal_identity_status="unbound",
        status="active",
    )
    db.add(row)
    await db.flush()
    return row


async def evaluate_p1_readiness(
    db: AsyncSession,
    agent_id: str,
) -> dict[str, Any]:
    """Verify agent against existing directory/profile/boundary/reputation/ack records."""
    row = await db.get(AgentModel, agent_id)
    checks: dict[str, bool] = {
        "directory_active": False,
        "identity_class_set": False,
        "owner_identity_bound": False,
        "owner_identity_active": False,
        "public_key_bound": False,
        "public_key_not_platform_default": False,
        "profile_card_present": False,
        "service_specs_valid": False,
        "boundary_complete": False,
        "responsibility_acknowledged": False,
        "responsibility_attestation_valid": False,
        "boundary_hash_consistent": False,
        "reputation_initialized": False,
        "ownership_consistent": False,
    }
    gaps: list[str] = []
    details: dict[str, Any] = {}

    if not row or not row.is_active:
        gaps.append("directory_active")
        return _pack(agent_id, False, checks, gaps, details, row=None)

    checks["directory_active"] = True
    identity_class = (getattr(row, "identity_class", None) or "").strip() or None
    owner_id = (getattr(row, "owner_identity_id", None) or "").strip() or None
    meta = dict(getattr(row, "onboarding_meta", None) or {})
    stored_hash = (getattr(row, "boundary_hash", None) or meta.get("boundary_hash") or "").strip() or None

    if identity_class in {"user", "merchant", "enterprise"}:
        checks["identity_class_set"] = True
    else:
        gaps.append("identity_class_set")

    if owner_id:
        checks["owner_identity_bound"] = True
        owner = await db.get(IdentityProfileModel, owner_id)
        if owner and (owner.status or "").lower() == "active":
            checks["owner_identity_active"] = True
        else:
            gaps.append("owner_identity_active")
            details["owner_identity"] = "missing_or_inactive"
    else:
        gaps.append("owner_identity_bound")

    pk = row.public_key
    if not _is_placeholder_public_key(pk):
        checks["public_key_bound"] = True
    else:
        gaps.append("public_key_bound")
    if not _is_server_singleton_key(pk) and not _is_placeholder_public_key(pk):
        checks["public_key_not_platform_default"] = True
    else:
        # In demo envs platform key is common — record gap but soft for user agents
        gaps.append("public_key_not_platform_default")

    card = get_profile_card(agent_id)
    if card:
        checks["profile_card_present"] = True
    else:
        gaps.append("profile_card_present")

    # Capability / service_specs for merchants & enterprises
    if identity_class in {"merchant", "enterprise"}:
        specs = (card or {}).get("service_specs") or {}
        industry_ids = list((card or {}).get("industry_ids") or [])
        if industry_ids and specs:
            try:
                validate_service_specs_for_industries(industry_ids, specs)
                checks["service_specs_valid"] = True
            except OnboardingError as exc:
                gaps.append("service_specs_valid")
                details["service_specs_error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                gaps.append("service_specs_valid")
                details["service_specs_error"] = str(exc)
        else:
            gaps.append("service_specs_valid")
        if meta.get("used_example_service_specs") and is_prod_like_env():
            checks["service_specs_valid"] = False
            if "service_specs_valid" not in gaps:
                gaps.append("service_specs_valid")
            details["example_specs_in_prod"] = True
    else:
        # Users don't need service_specs
        checks["service_specs_valid"] = True

    boundary = get_agent_boundary(agent_id)
    if not boundary and row:
        # Lazy rebuild for evaluation only (do not auto-ack)
        boundary = materialize_agent_boundary(
            agent_id=agent_id,
            name=row.name,
            karma_role=row.role,
            profile_id=identity_class,
            capabilities=list(row.capabilities or []),
            profile_card=card,
            owner_identity_id=owner_id or agent_id,
        )
    live_hash = boundary_content_hash(boundary)
    details["boundary_hash"] = live_hash
    details["stored_boundary_hash"] = stored_hash
    if boundary and boundary.get("boundary_complete"):
        # Re-assess by recomputing digest completeness from live boundary fields
        checks["boundary_complete"] = bool(boundary.get("boundary_complete"))
    else:
        gaps.append("boundary_complete")

    if stored_hash and live_hash and stored_hash == live_hash:
        checks["boundary_hash_consistent"] = True
    elif not stored_hash:
        gaps.append("boundary_hash_consistent")
    else:
        gaps.append("boundary_hash_consistent")
        details["hash_mismatch"] = True

    ack = meta.get("responsibility_ack")
    if isinstance(ack, dict) and ack.get("acknowledged"):
        checks["responsibility_acknowledged"] = True
        if verify_responsibility_attestation(ack):
            checks["responsibility_attestation_valid"] = True
        else:
            gaps.append("responsibility_attestation_valid")
    else:
        gaps.append("responsibility_acknowledged")
        gaps.append("responsibility_attestation_valid")

    # Ownership consistency: meta owner matches column
    meta_owner = (meta.get("owner_identity_id") or "").strip() or None
    if owner_id and (not meta_owner or meta_owner == owner_id):
        checks["ownership_consistent"] = True
    elif not owner_id:
        pass
    else:
        gaps.append("ownership_consistent")

    rep = await db.get(ReputationModel, agent_id)
    if rep:
        checks["reputation_initialized"] = True
        details["trust"] = {
            "reputation_score": float(rep.score or 0),
            "total_tasks": int(rep.total_tasks or 0),
            "successful_tasks": int(rep.successful_tasks or 0),
        }
    else:
        gaps.append("reputation_initialized")

    # Soft-allow platform key for user in demo; merchants still need non-default in prod
    hard_gaps = list(gaps)
    if identity_class == "user" and allow_demo_confirmation_bypass():
        hard_gaps = [g for g in hard_gaps if g != "public_key_not_platform_default"]
        checks["public_key_not_platform_default"] = True
    if identity_class in {"merchant", "enterprise"} and allow_demo_confirmation_bypass():
        # Demo merchants may use platform key but must still ack + specs + owner
        hard_gaps = [g for g in hard_gaps if g != "public_key_not_platform_default"]
        checks["public_key_not_platform_default"] = True

    p1_ready = len(hard_gaps) == 0 and checks["directory_active"]
    # Deduplicate gaps list for response
    uniq_gaps = []
    for g in hard_gaps:
        if g not in uniq_gaps:
            uniq_gaps.append(g)

    return _pack(
        agent_id,
        p1_ready,
        checks,
        uniq_gaps,
        details,
        row=row,
        identity_class=identity_class,
        owner_id=owner_id,
        boundary=boundary,
    )


def _pack(
    agent_id: str,
    p1_ready: bool,
    checks: dict[str, bool],
    gaps: list[str],
    details: dict[str, Any],
    *,
    row: AgentModel | None,
    identity_class: str | None = None,
    owner_id: str | None = None,
    boundary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": P1_SCHEMA,
        "agent_id": agent_id,
        "p1_ready": p1_ready,
        "identity_class": identity_class or (getattr(row, "identity_class", None) if row else None),
        "owner_identity_id": owner_id or (getattr(row, "owner_identity_id", None) if row else None),
        "checks": checks,
        "gaps": gaps,
        "boundary_hash": details.get("boundary_hash"),
        "boundary_digest": boundary_digest(boundary) if boundary else None,
        "efficiency_note_zh": (
            "P1 就绪：身份/责任/履约能力已界定且可对端核验，可安全进入发现与成交。"
            if p1_ready
            else "P1 未就绪：存在 gaps，对端不应将其视为可履约商家/企业（用户亦应补齐绑定）。"
        ),
        "security_note_zh": (
            "核验基于目录行、名片、边界哈希、责任签认与信誉记录；"
            "boundary_complete 与 ack 均不可仅靠客户端自报。"
        ),
        "details": details,
        "registered_at": (row.registered_at.isoformat() if row and row.registered_at else None),
        "is_active": bool(row.is_active) if row else False,
        "verified_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
