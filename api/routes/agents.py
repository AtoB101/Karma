"""Karma API — Agents (P1: identity / responsibility / capability / anti-forgery)."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
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
)
from services.agent_directory import connect_agent, refresh_p1_ready
from services.agent_bootstrap_credentials import has_minted_api_key, mint_agent_api_key
from services.agent_key_store import (
    AgentSigner,
    has_agent_key,
    mint_agent_signer,
    new_agent_id,
    revoke_agent_key,
)
from services.agent_one_click import build_next_steps, list_vertical_aliases, resolve_one_click
from services.agent_onboarding_template import OnboardingError, materialize_onboarding, suggest_industries_for_text
from services.agent_p1_readiness import (
    attest_responsibility_ack,
    responsibility_ack_stable_message,
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
from services.identity_actor import resolve_actor_identity_id
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


class OneClickConnectRequest(BaseModel):
    """Minimal vertical agent connect — side + vertical → full P1 template connect."""

    side: Literal["buyer", "seller"]
    vertical: str | None = Field(
        default=None,
        max_length=64,
        description="hotel|food|ecommerce|customer_service|enterprise|ride|flight|api|…",
    )
    display_name: str | None = Field(default=None, max_length=256)
    self_description: str | None = Field(default=None, max_length=4000)
    owner_identity_id: str | None = Field(default=None, max_length=128)
    agent_id: str | None = Field(default=None, max_length=128)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    public_key: str | None = Field(default=None, max_length=512)
    ownership_proof: OwnershipProof | None = None
    responsibility_ack: ResponsibilityAckBody | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    mint_api_key: bool = True
    allow_example_specs: bool = True

    @field_validator("display_name", mode="before")
    @classmethod
    def _safe_display(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text(str(v), field="display_name")

    @field_validator("self_description", mode="before")
    @classmethod
    def _safe_desc(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="self_description")


class OwnerConnectRequest(BaseModel):
    """Owner-console one-click connect.

    Same vertical resolution as ``/one-click-connect`` but the caller is the
    **authenticated identity card holder**, not the agent process. Karma mints
    and custody-binds the agent's operational Ed25519 key server-side, so the
    owner never has to handle an agent private key in the browser.
    """

    side: Literal["buyer", "seller"]
    vertical: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=256)
    self_description: str | None = Field(default=None, max_length=4000)
    owner_identity_id: str | None = Field(default=None, max_length=128)
    agent_id: str | None = Field(default=None, max_length=128)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    scope_profile_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional identity role profile this agent spends under",
    )
    answers: dict[str, Any] = Field(default_factory=dict)
    mint_api_key: bool = True

    @field_validator("display_name", mode="before")
    @classmethod
    def _safe_display(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text(str(v), field="display_name")

    @field_validator("self_description", mode="before")
    @classmethod
    def _safe_desc(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="self_description")


class OwnerRevokeRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)


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


async def _connect_from_template_core(
    db: AsyncSession,
    body: ConnectFromTemplateRequest,
    *,
    connect_path: str = "template",
    owner_signer: AgentSigner | None = None,
) -> dict[str, Any]:
    """Shared P1 template connect used by /connect-from-template and /one-click-connect."""
    answers = dict(body.answers or {})
    identity_class = body.profile_id
    owner_id = (body.owner_identity_id or answers.get("owner_identity_id") or "").strip()
    if not owner_id:
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
            if "use_example_service_specs" not in answers and not answers.get("service_specs"):
                answers["use_example_service_specs"] = True
                used_examples = True

    if body.profile_id == "user":
        answers.setdefault("display_name", answers.get("display_name") or "Karma User Agent")
        answers.setdefault("preferred_currency", "USDC")

    if body.responsibility_ack is None:
        if is_prod_like_env():
            raise HTTPException(400, "responsibility_ack is required")
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
    public_key = body.public_key
    ownership_proof = body.ownership_proof
    if owner_signer is not None and not ownership_proof:
        # Server-side custody path: Karma holds this agent's operational key, so
        # proof-of-possession is produced here rather than by the client.
        public_key = owner_signer.public_key_b64
        nonce = secrets.token_hex(16)
        issued_at = _iso_now()
        challenge = canonical_connect_challenge(
            agent_id=provisional_id,
            owner_identity_id=owner_id,
            identity_class=identity_class,
            nonce=nonce,
            issued_at=issued_at,
        )
        canonical = json.dumps(challenge, sort_keys=True, separators=(",", ":")).encode()
        ownership_proof = OwnershipProof(
            nonce=nonce,
            issued_at=issued_at,
            signature=owner_signer.sign_bytes(canonical),
            public_key=public_key,
        )
    _require_ownership_proof_if_prod(
        agent_id=provisional_id,
        owner_identity_id=owner_id,
        identity_class=identity_class,
        public_key=public_key,
        proof=ownership_proof,
    )

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

    def _ack_for(aid: str, boundary_hash: str) -> ResponsibilityAckBody:
        """Re-sign the responsibility ack whenever Karma custody-holds the key."""
        if owner_signer is None:
            return ack_body
        return ResponsibilityAckBody(
            acknowledged=True,
            signature=owner_signer.sign_bytes(
                responsibility_ack_stable_message(
                    agent_id=aid,
                    owner_identity_id=owner_id,
                    identity_class=identity_class,
                    boundary_hash=boundary_hash,
                )
            ),
            signer_public_key=owner_signer.public_key_b64,
            mode="owner_ed25519",
        )

    ack_record = _build_responsibility_ack_record(
        agent_id=provisional_id,
        owner_identity_id=owner_id,
        identity_class=identity_class,
        boundary_hash=bhash,
        ack_body=_ack_for(provisional_id, bhash),
    )

    row = await connect_agent(
        db,
        agent_id=connect.get("agent_id") or body.agent_id,
        name=connect["name"],
        role=role.value,
        endpoint_url=connect.get("endpoint_url") or None,
        capabilities=caps,
        public_key=public_key,
        profile_card=card,
        ensure_boundary=True,
        identity_class=identity_class,
        owner_identity_id=owner_id,
        responsibility_acknowledged=True,
        onboarding_meta={
            "connect_path": connect_path,
            "identity_class": identity_class,
            "owner_identity_id": owner_id,
            "scope_profile_id": answers.get("scope_profile_id"),
            "used_example_service_specs": used_examples,
            "responsibility_ack": ack_record,
            "boundary_hash": bhash,
        },
    )
    final_boundary = get_agent_boundary(row.agent_id)
    final_hash = boundary_content_hash(final_boundary) or bhash
    if row.agent_id != provisional_id or final_hash != bhash:
        ack_record = _build_responsibility_ack_record(
            agent_id=row.agent_id,
            owner_identity_id=owner_id,
            identity_class=identity_class,
            boundary_hash=final_hash,
            ack_body=_ack_for(row.agent_id, final_hash),
        )
        meta = dict(row.onboarding_meta or {})
        meta["responsibility_ack"] = ack_record
        meta["boundary_hash"] = final_hash
        row.onboarding_meta = meta
        row.boundary_hash = final_hash
        await db.flush()

    p1 = await refresh_p1_ready(db, row.agent_id)
    boundary = get_agent_boundary(row.agent_id) or final_boundary
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
    out = await _connect_from_template_core(db, body, connect_path="template")
    await db.commit()
    return out


@router.get("/one-click-verticals")
async def list_one_click_verticals() -> dict[str, Any]:
    """List friendly vertical aliases for one-click connect."""
    return {
        "schema_version": "karma-agent-one-click-v1",
        "verticals": list_vertical_aliases(),
        "sides": ["buyer", "seller"],
        "connect": "POST /v1/agents/one-click-connect",
    }


@router.post("/one-click-connect")
async def one_click_connect(
    body: OneClickConnectRequest,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_agent_rate_limit),
):
    """
    One-click vertical agent connect.

    Minimal input: ``side`` + ``vertical`` (hotel/food/ecommerce/customer_service/…).
    Materializes industry template, P1 connect, boundary, and optional bootstrap API key.
    """
    try:
        resolved = resolve_one_click(
            side=body.side,
            vertical=body.vertical,
            self_description=body.self_description,
            display_name=body.display_name,
            answers=body.answers,
        )
    except OnboardingError as exc:
        raise HTTPException(400, str(exc)) from exc

    answers = dict(resolved["answers"])
    if body.endpoint_url:
        answers["endpoint_url"] = body.endpoint_url

    tmpl = ConnectFromTemplateRequest(
        profile_id=resolved["profile_id"],
        answers=answers,
        agent_id=body.agent_id,
        self_description=body.self_description,
        owner_identity_id=body.owner_identity_id,
        public_key=body.public_key,
        ownership_proof=body.ownership_proof,
        responsibility_ack=body.responsibility_ack,
        allow_example_specs=body.allow_example_specs,
    )
    core = await _connect_from_template_core(db, tmpl, connect_path="one_click")
    agent = core["agent"]
    agent_id = agent.agent_id if hasattr(agent, "agent_id") else agent["agent_id"]
    scene_ids = list(
        (core.get("discovery_hints") or {}).get("scene_ids")
        or resolved.get("scene_ids")
        or []
    )

    credentials: dict[str, Any] = {
        "api_key": None,
        "api_key_hint": None,
        "runtime_key": None,
        "runtime_key_hint": (
            "Optional: POST /runtime/create-key with wallet personal_sign for voucher/receipt path"
        ),
    }
    if body.mint_api_key:
        minted = mint_agent_api_key(str(agent_id))
        credentials["api_key"] = minted["api_key"]
        credentials["api_key_hint"] = minted["api_key_hint"]

    await db.commit()
    return {
        "schema_version": "karma-agent-one-click-v1",
        "side": resolved["side"],
        "vertical": resolved.get("vertical"),
        "profile_id": resolved["profile_id"],
        "scene_ids": scene_ids,
        "agent": agent,
        "profile_card": core.get("profile_card"),
        "boundary": core.get("boundary"),
        "boundary_hash": core.get("boundary_hash"),
        "p1_ready": core.get("p1_ready"),
        "p1_status": core.get("p1_status"),
        "verification_url": core.get("verification_url"),
        "credentials": credentials,
        "env_snippet": {
            "KARMA_AGENT_ID": str(agent_id),
            "KARMA_API_KEY": credentials.get("api_key") or "<set from credentials.api_key>",
            "KARMA_RUNTIME_URL": "http://127.0.0.1:8000",
        },
        "next_steps": build_next_steps(
            agent_id=str(agent_id), side=resolved["side"], scene_ids=scene_ids
        ),
        "discovery_hints": core.get("discovery_hints"),
        "note_zh": (
            "一键接入完成：已按垂直场景落库身份/边界/责任签认，并签发引导 API Key（仅此一次明文）。"
            "对端 GET /p1-status 核验后再成交。"
        ),
    }


@router.post("/owner-connect")
async def owner_connect(
    body: OwnerConnectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(register_agent_rate_limit),
):
    """
    身份卡持有人一键接入自己的 agent（操作台主链路）。

    - 只有已认证的身份卡本人可调用（SIWE JWT 或 API Key）
    - Karma 生成并托管该 agent 的 Ed25519 运行密钥（服务端 0600，可随时吊销）；
      这把密钥与主人的钱包私钥/助记词没有任何关系
    - 完成 P1 接入：身份类别 + 主人绑定 + 真实 service_specs + 责任签认
    - bootstrap API Key 仅此一次明文返回
    """
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(
            403,
            "authentication required: connect a wallet to obtain an identity card first",
        )
    owner_id = (body.owner_identity_id or actor).strip()
    if owner_id != actor:
        raise HTTPException(403, "owner_identity_id must match the authenticated identity")

    try:
        resolved = resolve_one_click(
            side=body.side,
            vertical=body.vertical,
            self_description=body.self_description,
            display_name=body.display_name,
            answers=body.answers,
        )
    except OnboardingError as exc:
        raise HTTPException(400, str(exc)) from exc

    answers = dict(resolved["answers"])
    if body.endpoint_url:
        answers["endpoint_url"] = body.endpoint_url
    if body.scope_profile_id:
        from db.models.orm import IdentityRoleProfile

        profile_row = await db.get(IdentityRoleProfile, body.scope_profile_id)
        if profile_row is None or profile_row.owner_identity_id != owner_id:
            raise HTTPException(404, "scope_profile_id not found for this identity")
        answers["scope_profile_id"] = body.scope_profile_id

    agent_id = (body.agent_id or "").strip() or new_agent_id("agent")
    signer, key_info = mint_agent_signer(agent_id)

    tmpl = ConnectFromTemplateRequest(
        profile_id=resolved["profile_id"],
        answers=answers,
        agent_id=agent_id,
        self_description=body.self_description,
        owner_identity_id=owner_id,
        public_key=key_info["public_key"],
        responsibility_ack=ResponsibilityAckBody(acknowledged=True),
    )
    try:
        core = await _connect_from_template_core(
            db, tmpl, connect_path="owner_console", owner_signer=signer
        )
    except Exception:
        # Never leave an orphan key behind for an agent that was not created.
        try:
            revoke_agent_key(agent_id)
        except Exception:  # noqa: BLE001
            pass
        raise

    agent = core["agent"]
    final_id = agent.agent_id if hasattr(agent, "agent_id") else agent["agent_id"]
    if str(final_id) != agent_id:
        # Core chose a different id (should not happen once we pass one explicitly).
        revoke_agent_key(agent_id)
        signer, key_info = mint_agent_signer(str(final_id))
        agent_id = str(final_id)

    scene_ids = list(
        (core.get("discovery_hints") or {}).get("scene_ids") or resolved.get("scene_ids") or []
    )

    credentials: dict[str, Any] = {
        "api_key": None,
        "api_key_hint": None,
        "agent_public_key": key_info["public_key"],
        "key_custody": "server_side_revocable",
        "revoke": "POST /v1/agents/owner-revoke",
    }
    if body.mint_api_key:
        minted = mint_agent_api_key(str(agent_id))
        credentials["api_key"] = minted["api_key"]
        credentials["api_key_hint"] = minted["api_key_hint"]

    await db.commit()
    return {
        "schema_version": "karma-agent-owner-connect-v1",
        "side": resolved["side"],
        "vertical": resolved.get("vertical"),
        "profile_id": resolved["profile_id"],
        "scene_ids": scene_ids,
        "agent": agent,
        "profile_card": core.get("profile_card"),
        "boundary": core.get("boundary"),
        "boundary_hash": core.get("boundary_hash"),
        "p1_ready": core.get("p1_ready"),
        "p1_status": core.get("p1_status"),
        "verification_url": core.get("verification_url"),
        "credentials": credentials,
        "env_snippet": {
            "KARMA_AGENT_ID": str(agent_id),
            "KARMA_API_KEY": credentials.get("api_key") or "<set from credentials.api_key>",
            "KARMA_RUNTIME_URL": "https://karma-network.ai",
        },
        "next_steps": build_next_steps(
            agent_id=str(agent_id), side=resolved["side"], scene_ids=scene_ids
        ),
        "discovery_hints": core.get("discovery_hints"),
        "note_zh": (
            "接入完成：身份卡 → agent 已绑定，责任签认与履约边界已落库。"
            "API Key 仅此一次明文返回；对端可 GET /p1-status 核验。"
        ),
    }


@router.get("/mine")
async def list_my_agents(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """已认证身份卡名下的 agent 清单（含 P1 就绪度与密钥托管状态）。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required")
    rows = (
        await db.execute(
            select(AgentModel)
            .where(AgentModel.owner_identity_id == actor)
            .order_by(AgentModel.registered_at.desc())
        )
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = dict(getattr(row, "onboarding_meta", None) or {})
        item = _to_identity(row).model_dump()
        item.update(
            {
                "identity_class": getattr(row, "identity_class", None),
                "owner_identity_id": getattr(row, "owner_identity_id", None),
                "scope_profile_id": meta.get("scope_profile_id"),
                "connect_path": meta.get("connect_path"),
                "key_custody": "server_side_revocable" if has_agent_key(row.agent_id) else "external",
                "api_key_minted": has_minted_api_key(row.agent_id),
                "boundary_hash": getattr(row, "boundary_hash", None),
            }
        )
        p1 = await evaluate_p1_readiness(db, row.agent_id)
        item["p1_ready"] = p1.get("p1_ready")
        item["p1_gaps"] = p1.get("gaps") or []
        out.append(item)
    return {"owner_identity_id": actor, "agents": out, "total": len(out)}


@router.post("/owner-revoke")
async def owner_revoke_agent(
    body: OwnerRevokeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """吊销 agent：停用目录条目 + 销毁 Karma 托管的运行密钥。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required")
    row = await db.get(AgentModel, body.agent_id)
    if row is None or (getattr(row, "owner_identity_id", None) or "") != actor:
        raise HTTPException(404, "agent not found for this identity")
    row.is_active = False
    await db.flush()
    key_revoked = revoke_agent_key(body.agent_id)
    await db.commit()
    return {
        "agent_id": body.agent_id,
        "is_active": False,
        "agent_key_revoked": key_revoked,
        "note_zh": "agent 已停用；Karma 托管的运行密钥已销毁，API Key 不再可通过鉴权。",
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
    # Persist readiness flag only — never heal boundary_hash from live (P2 anti-drift)
    row.p1_ready = bool(status.get("p1_ready"))
    await db.commit()
    return status


@router.get("/{agent_id}/boundary")
async def get_agent_boundary_card(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Capability + responsibility + confirmation boundaries for counterparties."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    boundary = get_agent_boundary(agent_id)
    ephemeral = False
    if not boundary:
        # Ephemeral materialize only — do not persist (avoids silent hash/ack drift)
        boundary = materialize_agent_boundary(
            agent_id=row.agent_id,
            name=row.name,
            karma_role=row.role,
            profile_id=getattr(row, "identity_class", None)
            or (get_profile_card(agent_id) or {}).get("profile_id"),
            capabilities=list(row.capabilities or []),
            profile_card=get_profile_card(agent_id),
            owner_identity_id=getattr(row, "owner_identity_id", None) or row.agent_id,
        )
        ephemeral = True
    return {
        "agent_id": agent_id,
        "agent": _to_identity(row),
        "boundary": boundary,
        "ephemeral": ephemeral,
        "boundary_hash": getattr(row, "boundary_hash", None),
        "profile_card": get_profile_card(agent_id),
    }


@router.get("/{agent_id}/boundary/verify")
async def verify_agent_boundary_route(
    agent_id: str,
    scene_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """P2: verify published boundary against catalogs (anti-forgery / scene coverage)."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        raise HTTPException(404, f"Agent {agent_id} not found")
    from services.agent_boundary_verify import verify_agent_boundary

    return await verify_agent_boundary(db, agent_id, scene_id=scene_id)


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
