"""Karma API — Agents (P1: identity / responsibility / capability / anti-forgery)."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import register_agent_rate_limit

from core.schemas import AgentIdentity, AgentRole
from db.session import get_db
from db.models.orm import AgentModel
from services.agent_boundary import (
    get_agent_boundary,
    materialize_agent_boundary,
    materialize_from_onboarding_result,
)
from services.agent_directory import connect_agent, refresh_p1_ready
from services.agent_onboarding_template import OnboardingError, materialize_onboarding, suggest_industries_for_text
from services.agent_p1_readiness import (
    attest_responsibility_ack,
    boundary_content_hash,
    canonical_connect_challenge,
    canonical_responsibility_ack,
    ensure_owner_identity,
    evaluate_p1_readiness,
    is_prod_like_env,
    verify_ownership_proof,
)
from services.agent_profile_store import get_profile_card
from services.agent_trust import ensure_reputation_row, load_trust_stats_batch
from services.human_confirmation_policy import allow_demo_confirmation_bypass
from services.signing import signing_service
from services.text_safety import validate_safe_storage_text, validate_safe_storage_text_optional

router = APIRouter()


class RegisterAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    role: AgentRole
    endpoint_url: str | None = Field(default=None, max_length=2048)
    capabilities: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="name")

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def _safe_endpoint(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="endpoint_url")

    @field_validator("capabilities")
    @classmethod
    def _capability_item_length(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 128:
                raise ValueError("each capability string must be at most 128 characters")
            validate_safe_storage_text(item, field="capabilities[]")
        return v


class OwnershipProof(BaseModel):
    nonce: str = Field(min_length=8, max_length=128)
    issued_at: str = Field(min_length=10, max_length=64)
    signature: str = Field(min_length=8, max_length=512)
    public_key: str | None = Field(default=None, max_length=512)


class ResponsibilityAckBody(BaseModel):
    acknowledged: bool = True
    signature: str | None = Field(default=None, max_length=512)
    signer_public_key: str | None = Field(default=None, max_length=512)
    mode: Literal["platform_ed25519", "owner_ed25519"] | None = None


class ConnectAgentRequest(BaseModel):
    """Upsert path: agent connects to Karma ⇒ immediately discoverable."""
    agent_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    role: AgentRole = AgentRole.WORKER
    endpoint_url: str | None = Field(default=None, max_length=2048)
    capabilities: list[str] = Field(default_factory=list, max_length=64)
    identity_class: Literal["user", "merchant", "enterprise"] | None = None
    owner_identity_id: str | None = Field(default=None, max_length=128)
    public_key: str | None = Field(default=None, max_length=512)
    ownership_proof: OwnershipProof | None = None
    responsibility_ack: ResponsibilityAckBody | None = None

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="name")

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def _safe_endpoint(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="endpoint_url")

    @field_validator("capabilities")
    @classmethod
    def _capability_item_length(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 128:
                raise ValueError("each capability string must be at most 128 characters")
            validate_safe_storage_text(item, field="capabilities[]")
        return v


class ConnectFromTemplateRequest(BaseModel):
    """P1 auto-connect: identity class + owner bind + capability specs + responsibility ack."""

    profile_id: Literal["user", "merchant", "enterprise"]
    answers: dict[str, Any] = Field(default_factory=dict)
    extra_capabilities: list[str] = Field(default_factory=list, max_length=64)
    agent_id: str | None = Field(default=None, max_length=128)
    self_description: str | None = Field(default=None, max_length=4000)
    owner_identity_id: str | None = Field(default=None, max_length=128)
    public_key: str | None = Field(default=None, max_length=512)
    ownership_proof: OwnershipProof | None = None
    responsibility_ack: ResponsibilityAckBody | None = None
    allow_example_specs: bool = False


class ConnectChallengeRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    owner_identity_id: str = Field(min_length=1, max_length=128)
    identity_class: Literal["user", "merchant", "enterprise"]


def _to_identity(row: AgentModel) -> AgentIdentity:
    return AgentIdentity(
        agent_id=row.agent_id,
        name=row.name,
        role=AgentRole(row.role),
        public_key=row.public_key,
        endpoint_url=row.endpoint_url,
        capabilities=row.capabilities or [],
        registered_at=row.registered_at,
        is_active=row.is_active,
    )


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_ownership_proof_if_prod(
    *,
    agent_id: str,
    owner_identity_id: str,
    identity_class: str,
    public_key: str | None,
    proof: OwnershipProof | None,
) -> None:
    if not is_prod_like_env():
        return
    if not proof or not public_key:
        raise HTTPException(
            400,
            "production connect requires public_key + ownership_proof (Ed25519 PoP)",
        )
    challenge = canonical_connect_challenge(
        agent_id=agent_id,
        owner_identity_id=owner_identity_id,
        identity_class=identity_class,
        nonce=proof.nonce,
        issued_at=proof.issued_at,
    )
    pk = proof.public_key or public_key
    if not verify_ownership_proof(
        challenge=challenge, signature_b64=proof.signature, public_key_b64=pk
    ):
        raise HTTPException(403, "ownership_proof verification failed")


def _build_responsibility_ack_record(
    *,
    agent_id: str,
    owner_identity_id: str,
    identity_class: str,
    boundary_hash: str,
    ack_body: ResponsibilityAckBody | None,
) -> dict[str, Any]:
    if ack_body is None or not ack_body.acknowledged:
        raise HTTPException(
            400,
            "responsibility_ack.acknowledged=true is required for P1 connect-from-template",
        )
    payload = canonical_responsibility_ack(
        agent_id=agent_id,
        owner_identity_id=owner_identity_id,
        identity_class=identity_class,
        boundary_hash=boundary_hash,
        acknowledged_at=_iso_now(),
    )
    payload["acknowledged"] = True
    if ack_body.signature and ack_body.signer_public_key:
        from services.agent_p1_readiness import responsibility_ack_stable_message
        from services.signing import signing_service as _ss

        msg = responsibility_ack_stable_message(
            agent_id=agent_id,
            owner_identity_id=owner_identity_id,
            identity_class=identity_class,
            boundary_hash=boundary_hash,
        )
        ok = _ss.verify(msg, ack_body.signature, ack_body.signer_public_key)
        if not ok:
            raise HTTPException(403, "responsibility_ack owner signature invalid")
        payload["attestation"] = {
            "mode": "owner_ed25519",
            "signature": ack_body.signature,
            "public_key": ack_body.signer_public_key,
        }
        return payload
    if is_prod_like_env():
        raise HTTPException(
            400,
            "production requires owner-signed responsibility_ack (signer_public_key + signature)",
        )
    # Demo/dev: platform attestation binds integrity of the ack record
    return attest_responsibility_ack(payload)


@router.post("/connect-challenge")
async def connect_challenge(body: ConnectChallengeRequest) -> dict[str, Any]:
    """Issue a canonical ownership challenge for Ed25519 proof-of-possession."""
    nonce = secrets.token_hex(16)
    issued_at = _iso_now()
    challenge = canonical_connect_challenge(
        agent_id=body.agent_id,
        owner_identity_id=body.owner_identity_id,
        identity_class=body.identity_class,
        nonce=nonce,
        issued_at=issued_at,
    )
    return {
        "schema_version": "karma-agent-p1-v1",
        "nonce": nonce,
        "issued_at": issued_at,
        "canonical_message": challenge,
        "note_zh": "用 agent 私钥对 canonical_message 做 Ed25519 签名，填入 ownership_proof",
    }


@router.post("/connect")
async def connect_agent_route(
    body: ConnectAgentRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_agent_rate_limit),
):
    """
    Plain connect — discoverable but usually **not** P1-ready.

    Merchants/enterprises should use ``/connect-from-template`` with owner bind,
    service_specs, and responsibility ack. Plain connect is for bootstrap only.
    """
    if is_prod_like_env() and body.role == AgentRole.WORKER and not body.identity_class:
        raise HTTPException(
            400,
            "production worker connect requires identity_class or use connect-from-template",
        )
    owner_id = body.owner_identity_id
    if body.identity_class and not owner_id:
        raise HTTPException(400, "owner_identity_id required when identity_class is set")
    if owner_id:
        await ensure_owner_identity(db, owner_id, display_hint=body.name)
    if body.agent_id and owner_id and body.identity_class:
        _require_ownership_proof_if_prod(
            agent_id=body.agent_id,
            owner_identity_id=owner_id,
            identity_class=body.identity_class,
            public_key=body.public_key,
            proof=body.ownership_proof,
        )
    row = await connect_agent(
        db,
        agent_id=body.agent_id,
        name=body.name,
        role=body.role.value,
        endpoint_url=body.endpoint_url,
        capabilities=body.capabilities,
        public_key=body.public_key,
        ensure_boundary=True,
        identity_class=body.identity_class,
        owner_identity_id=owner_id,
        responsibility_acknowledged=bool(
            body.responsibility_ack and body.responsibility_ack.acknowledged
        ),
        onboarding_meta={"connect_path": "plain"},
    )
    p1 = await refresh_p1_ready(db, row.agent_id)
    await db.commit()
    return {
        "agent": _to_identity(row),
        "p1_ready": p1.get("p1_ready"),
        "p1_status": p1,
        "note_zh": (
            "已写入目录。若 p1_ready=false，对端核验将拒绝将其视为可履约商家；"
            "请走 connect-from-template 补齐身份/责任/履约能力。"
        ),
    }


@router.post("/connect-from-template")
async def connect_from_template(
    body: ConnectFromTemplateRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_agent_rate_limit),
):
    """
    P1 standardized connect: identity class + owner bind + hard service_specs +
    non-forgeable responsibility ack. Counterparties verify via GET …/p1-status.
    """
    answers = dict(body.answers or {})
    identity_class = body.profile_id
    owner_id = (body.owner_identity_id or answers.get("owner_identity_id") or "").strip()
    if not owner_id:
        # Default owner to stable agent_id or generated placeholder for demo only
        if is_prod_like_env():
            raise HTTPException(400, "owner_identity_id is required for P1 connect-from-template")
        owner_id = body.agent_id or f"owner-{identity_class}-{secrets.token_hex(4)}"

    await ensure_owner_identity(
        db, owner_id, display_hint=str(answers.get("display_name") or owner_id)
    )

    if body.profile_id in {"merchant", "enterprise"} and not answers.get("industry_ids") and body.self_description:
        suggestions = suggest_industries_for_text(body.self_description, limit=3)
        answers["industry_ids"] = [s["industry_id"] for s in suggestions]
        answers.setdefault("capability_summary", body.self_description.strip()[:500])
        answers.setdefault("service_targets", ["consumer", "agent"])
        answers.setdefault("service_area", {"mode": "hybrid", "regions": ["global"]})
        if body.profile_id == "enterprise":
            answers.setdefault("enterprise_type", "other")
            answers.setdefault("trade_side", ["sell"])
            answers.setdefault("compliance_flags", {"no_fund_custody": True, "non_clinical_only": True})

    used_examples = False
    if body.profile_id in {"merchant", "enterprise"}:
        if body.allow_example_specs and allow_demo_confirmation_bypass():
            answers.setdefault("use_example_service_specs", True)
            used_examples = bool(answers.get("use_example_service_specs"))
        elif is_prod_like_env():
            answers["use_example_service_specs"] = False
            if not answers.get("service_specs"):
                raise HTTPException(
                    400,
                    "production merchant/enterprise require real service_specs "
                    "(allow_example_specs only in development)",
                )
        else:
            # Dev convenience: still allow examples unless explicitly disabled
            if "use_example_service_specs" not in answers and not answers.get("service_specs"):
                answers["use_example_service_specs"] = True
                used_examples = True

    if body.profile_id == "user":
        answers.setdefault("display_name", answers.get("display_name") or "Karma User Agent")
        answers.setdefault("preferred_currency", "USDC")

    # Responsibility ack required
    if body.responsibility_ack is None:
        if is_prod_like_env():
            raise HTTPException(400, "responsibility_ack is required")
        # Dev default: explicit ack true so local scenarios still reach p1_ready
        ack_body = ResponsibilityAckBody(acknowledged=True)
    else:
        ack_body = body.responsibility_ack

    try:
        materialized = materialize_onboarding(
            profile_id=body.profile_id,
            answers=answers,
            extra_capabilities=body.extra_capabilities,
            agent_id=body.agent_id,
        )
    except OnboardingError as exc:
        raise HTTPException(400, str(exc)) from exc

    connect = materialized["agent_connect"]
    card = materialized["profile_card"]
    caps = list(connect.get("capabilities") or [])
    caps.append(f"onboarding:{body.profile_id}")
    for sid in materialized.get("discovery_hints", {}).get("scene_ids") or []:
        tag = f"industry:{sid}"
        if tag not in caps:
            caps.append(tag)

    try:
        role = AgentRole(connect["role"])
    except ValueError:
        role = AgentRole.WORKER

    provisional_id = connect.get("agent_id") or body.agent_id or f"agent-{secrets.token_hex(6)}"
    _require_ownership_proof_if_prod(
        agent_id=provisional_id,
        owner_identity_id=owner_id,
        identity_class=identity_class,
        public_key=body.public_key,
        proof=body.ownership_proof,
    )

    # Pre-materialize boundary to compute hash for ack binding
    pre_boundary = materialize_from_onboarding_result(
        {
            **materialized,
            "agent_connect": {**connect, "capabilities": caps, "agent_id": provisional_id},
        },
        agent_id=provisional_id,
    )
    # Force owner into boundary
    pre_boundary = materialize_agent_boundary(
        agent_id=provisional_id,
        name=connect["name"],
        karma_role=role.value,
        profile_id=identity_class,
        capabilities=caps,
        scene_ids=list(materialized.get("discovery_hints", {}).get("scene_ids") or []),
        profile_card=card,
        owner_identity_id=owner_id,
        responsibility_acknowledged=True,
    )
    bhash = boundary_content_hash(pre_boundary) or ""
    ack_record = _build_responsibility_ack_record(
        agent_id=provisional_id,
        owner_identity_id=owner_id,
        identity_class=identity_class,
        boundary_hash=bhash,
        ack_body=ack_body,
    )

    row = await connect_agent(
        db,
        agent_id=connect.get("agent_id") or body.agent_id,
        name=connect["name"],
        role=role.value,
        endpoint_url=connect.get("endpoint_url"),
        capabilities=caps,
        public_key=body.public_key,
        profile_card=card,
        ensure_boundary=True,
        identity_class=identity_class,
        owner_identity_id=owner_id,
        responsibility_acknowledged=True,
        onboarding_meta={
            "connect_path": "template",
            "identity_class": identity_class,
            "owner_identity_id": owner_id,
            "used_example_service_specs": used_examples,
            "responsibility_ack": ack_record,
            "boundary_hash": bhash,
        },
    )
    # Re-bind ack to final agent_id/hash if id was server-generated
    final_boundary = get_agent_boundary(row.agent_id)
    final_hash = boundary_content_hash(final_boundary) or bhash
    if row.agent_id != provisional_id or final_hash != bhash:
        ack_record = _build_responsibility_ack_record(
            agent_id=row.agent_id,
            owner_identity_id=owner_id,
            identity_class=identity_class,
            boundary_hash=final_hash,
            ack_body=ack_body,
        )
        meta = dict(row.onboarding_meta or {})
        meta["responsibility_ack"] = ack_record
        meta["boundary_hash"] = final_hash
        row.onboarding_meta = meta
        row.boundary_hash = final_hash
        await db.flush()

    p1 = await refresh_p1_ready(db, row.agent_id)
    boundary = get_agent_boundary(row.agent_id) or final_boundary
    await db.commit()
    return {
        "agent": _to_identity(row),
        "profile_card": card,
        "boundary": boundary,
        "p1_ready": p1.get("p1_ready"),
        "p1_status": p1,
        "boundary_hash": p1.get("boundary_hash"),
        "verification_url": f"/v1/agents/{row.agent_id}/p1-status",
        "discovery_hints": materialized.get("discovery_hints"),
        "materialized": {
            "capabilities": caps,
            "description": card.get("description"),
            "boundary_complete": (boundary or {}).get("boundary_complete"),
            "identity_class": identity_class,
            "owner_identity_id": owner_id,
        },
        "note_zh": (
            "P1 接入完成：身份类别、主人绑定、履约能力与责任签认已落库。"
            "对端请 GET /p1-status 核验后再成交。"
        ),
    }


@router.post("", response_model=AgentIdentity, status_code=201)
async def register_agent(
    body: RegisterAgentRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_agent_rate_limit),
):
    row = await connect_agent(
        db,
        name=body.name,
        role=body.role.value,
        endpoint_url=body.endpoint_url,
        capabilities=body.capabilities,
        public_key=signing_service.get_public_key_b64(),
    )
    await db.commit()
    return _to_identity(row)


@router.get("/{agent_id}", response_model=AgentIdentity)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return _to_identity(row)


@router.get("/{agent_id}/trust")
async def get_agent_trust(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Reputation + settlement volume used by discovery ranking."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    await ensure_reputation_row(db, agent_id, role="client" if row.role == "client" else "worker")
    stats = await load_trust_stats_batch(db, [agent_id])
    return {
        "agent_id": agent_id,
        "agent": _to_identity(row),
        "trust": (stats.get(agent_id).to_dict() if stats.get(agent_id) else {}),
    }


@router.get("/{agent_id}/profile-card")
async def get_agent_profile_card(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Onboarding profile card (industry, hours, targets, description) for discovery."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    card = get_profile_card(agent_id)
    if not card:
        raise HTTPException(404, f"No onboarding profile_card for {agent_id}")
    return {"agent_id": agent_id, "agent": _to_identity(row), "profile_card": card}


@router.get("/{agent_id}/p1-status")
async def get_agent_p1_status(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Counterparty verification: identity / responsibility / capability / anti-forgery checks."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    status = await evaluate_p1_readiness(db, agent_id)
    # Persist refreshed flag for discovery filters
    row.p1_ready = bool(status.get("p1_ready"))
    if status.get("boundary_hash"):
        row.boundary_hash = status["boundary_hash"]
    await db.commit()
    return status


@router.get("/{agent_id}/boundary")
async def get_agent_boundary_card(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Capability + responsibility + confirmation boundaries for counterparties."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    boundary = get_agent_boundary(agent_id)
    if not boundary:
        # Lazy materialize so older connects still expose a readable boundary
        boundary = materialize_agent_boundary(
            agent_id=row.agent_id,
            name=row.name,
            karma_role=row.role,
            profile_id=(get_profile_card(agent_id) or {}).get("profile_id"),
            capabilities=list(row.capabilities or []),
            profile_card=get_profile_card(agent_id),
            owner_identity_id=row.agent_id,
        )
        from services.agent_boundary import save_agent_boundary

        save_agent_boundary(row.agent_id, boundary)
    return {
        "agent_id": agent_id,
        "agent": _to_identity(row),
        "boundary": boundary,
        "profile_card": get_profile_card(agent_id),
    }


@router.get("", response_model=list[AgentIdentity])
async def list_agents(
    role: AgentRole | None = None,
    capability: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(AgentModel).where(AgentModel.is_active == True)  # noqa: E712
    if role:
        q = q.where(AgentModel.role == role.value)
    result = await db.execute(q)
    rows = result.scalars().all()
    out = [_to_identity(r) for r in rows]
    if capability:
        cap = capability.lower()
        out = [a for a in out if any(str(c).lower() == cap for c in (a.capabilities or []))]
    return out
