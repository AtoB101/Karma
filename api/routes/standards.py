"""Public standards endpoints — readable by both buyer and seller agents."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.important_fields_capture import (
    CaptureError,
    capture_from_interaction,
    encrypt_for_capture,
    finalize_triple_match,
    get_capture_public,
    issue_session_key,
    submit_encrypted,
)
from services.agent_onboarding_template import (
    OnboardingError,
    get_industry,
    get_profile,
    list_industries,
    list_profiles,
    load_onboarding_catalog,
    materialize_onboarding,
    suggest_industries_for_text,
)
from services.human_confirmation_policy import (
    ConfirmationPolicyError,
    get_scene_policy,
    list_policy_scenes,
    load_policy_catalog,
    plan_confirmations,
)
from services.important_fields_standard import (
    ImportantFieldsError,
    example_for_scene,
    fields_hash,
    get_scene,
    list_scene_groups,
    list_scenes,
    load_catalog,
    match_submissions,
    validate_fields,
    canonical_json,
)

router = APIRouter()


class CanonicalizeRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=128)
    fields: dict[str, Any]


class MatchRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=128)
    buyer_fields: dict[str, Any]
    seller_fields: dict[str, Any]


class CaptureRequest(BaseModel):
    """Protocol locks fields scraped/extracted during the live interaction."""

    scene_id: str = Field(min_length=1, max_length=128)
    interaction_ref: str = Field(min_length=1, max_length=256, description="A2A task / agreement / chat id")
    extracted_fields: dict[str, Any] = Field(description="ImportantFields extracted by protocol")
    source: str = Field(default="protocol_extract", max_length=64)
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)


class EncryptRequest(BaseModel):
    capture_id: str = Field(min_length=1, max_length=128)
    fields: dict[str, Any]


class SecureSubmitRequest(BaseModel):
    capture_id: str = Field(min_length=1, max_length=128)
    role: Literal["buyer", "seller"]
    ciphertext: str = Field(min_length=16, max_length=200_000)
    nonce: str = Field(min_length=8, max_length=128)


class FinalizeRequest(BaseModel):
    capture_id: str = Field(min_length=1, max_length=128)


class MaterializeOnboardingRequest(BaseModel):
    profile_id: Literal["user", "merchant", "enterprise"]
    answers: dict[str, Any] = Field(default_factory=dict)
    extra_capabilities: list[str] = Field(default_factory=list, max_length=64)
    agent_id: str | None = Field(default=None, max_length=128)
    self_description: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional free text; used to suggest industries when merchant/enterprise omit industry_ids",
    )


class SuggestIndustriesRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=18)


# --- Onboarding templates (register before parameterized IF routes) ---


@router.get("/onboarding")
async def get_onboarding_standard() -> dict[str, Any]:
    """Agent-readable connect templates: user / merchant / enterprise + industries."""
    cat = load_onboarding_catalog()
    return {
        "schema_version": cat.get("schema_version"),
        "title": cat.get("title"),
        "title_zh": cat.get("title_zh"),
        "description_zh": cat.get("description_zh"),
        "design_goals_zh": cat.get("design_goals_zh"),
        "profiles": list_profiles(),
        "industry_count": len(list_industries()),
        "recommended_agent_flow_zh": cat.get("recommended_agent_flow_zh"),
        "agent_read_apis": cat.get("agent_read_apis"),
        "catalog_path": "packages/evidence-schema/agent-onboarding-template.v1.json",
    }


@router.get("/onboarding/profiles")
async def get_onboarding_profiles() -> dict[str, Any]:
    return {"schema_version": "karma-agent-onboarding-v1", "profiles": list_profiles()}


@router.get("/onboarding/profiles/{profile_id}")
async def get_onboarding_profile(profile_id: str) -> dict[str, Any]:
    try:
        return {"schema_version": "karma-agent-onboarding-v1", "profile": get_profile(profile_id)}
    except OnboardingError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/onboarding/industries")
async def get_onboarding_industries(
    group: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    rows = list_industries(group=group, audience=audience)
    return {
        "schema_version": "karma-agent-onboarding-v1",
        "count": len(rows),
        "group": group,
        "audience": audience,
        "industries": rows,
    }


@router.get("/onboarding/industries/{industry_id}")
async def get_onboarding_industry(industry_id: str) -> dict[str, Any]:
    try:
        return {"schema_version": "karma-agent-onboarding-v1", "industry": get_industry(industry_id)}
    except OnboardingError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/onboarding/suggest-industries")
async def suggest_onboarding_industries(body: SuggestIndustriesRequest) -> dict[str, Any]:
    return {
        "schema_version": "karma-agent-onboarding-v1",
        "suggestions": suggest_industries_for_text(body.text, limit=body.limit),
    }


@router.post("/onboarding/materialize")
async def materialize_onboarding_payload(body: MaterializeOnboardingRequest) -> dict[str, Any]:
    """Agent fills answers (or auto-suggests industries) → standardized connect payload."""
    answers = dict(body.answers or {})
    if body.profile_id in {"merchant", "enterprise"} and not answers.get("industry_ids") and body.self_description:
        suggestions = suggest_industries_for_text(body.self_description, limit=3)
        answers["industry_ids"] = [s["industry_id"] for s in suggestions]
        if not answers.get("capability_summary"):
            answers["capability_summary"] = body.self_description.strip()[:500]
        if not answers.get("boundaries"):
            answers["boundaries"] = "以模板场景为界；未声明场景不接单。"
    try:
        return materialize_onboarding(
            profile_id=body.profile_id,
            answers=answers,
            extra_capabilities=body.extra_capabilities,
            agent_id=body.agent_id,
        )
    except OnboardingError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/confirmation-policy")
async def get_confirmation_policy_standard() -> dict[str, Any]:
    """Human vs auto gates by real-world scene — agents only ask owner when required."""
    cat = load_policy_catalog()
    return {
        "schema_version": cat.get("schema_version"),
        "title_zh": cat.get("title_zh"),
        "description_zh": cat.get("description_zh"),
        "design_goals_zh": cat.get("design_goals_zh"),
        "gate_modes": cat.get("gate_modes"),
        "lifecycle_steps": cat.get("lifecycle_steps"),
        "agent_ux_zh": cat.get("agent_ux_zh"),
        "scenes": list_policy_scenes(),
        "api": cat.get("api"),
        "catalog_path": "packages/evidence-schema/human-confirmation-policy.v1.json",
    }


@router.get("/confirmation-policy/scenes/{scene_id}")
async def get_confirmation_policy_scene(scene_id: str) -> dict[str, Any]:
    try:
        scene = get_scene_policy(scene_id)
    except ConfirmationPolicyError as exc:
        raise HTTPException(404, str(exc)) from exc
    plan_buyer = plan_confirmations(scene_id=scene_id, role="buyer")
    plan_seller = plan_confirmations(scene_id=scene_id, role="seller")
    return {
        "schema_version": "karma-human-confirmation-v1",
        "scene": scene,
        "buyer_plan": {
            "must_confirm_steps": [x["step"] for x in plan_buyer["must_confirm"]],
            "auto_ok_steps": [x["step"] for x in plan_buyer["auto_ok"]],
        },
        "seller_plan": {
            "must_confirm_steps": [x["step"] for x in plan_seller["must_confirm"]],
            "auto_ok_steps": [x["step"] for x in plan_seller["auto_ok"]],
        },
    }


@router.get("/important-fields")
async def get_important_fields_standard(
    include_extensions: bool = False,
    group: str | None = None,
) -> dict[str, Any]:
    """Important Fields catalog (market + daily commerce + B2B; filter with ?group=)."""
    cat = load_catalog()
    return {
        "schema_version": cat.get("schema_version"),
        "title": cat.get("title"),
        "title_zh": cat.get("title_zh"),
        "description": cat.get("description"),
        "description_zh": cat.get("description_zh"),
        "scene_groups": list_scene_groups(),
        "canonicalization": cat.get("canonicalization"),
        "submission_envelope": cat.get("submission_envelope"),
        "common_fields": cat.get("common_fields"),
        "lifecycle": cat.get("lifecycle"),
        "security_model": {
            "protocol_capture": True,
            "triple_match": "buyer_hash == seller_hash == protocol_hash",
            "wire": "karma1 AES-256-GCM ciphertext only on secure path",
            "apis": [
                "POST /v1/standards/important-fields/captures",
                "GET /v1/standards/important-fields/captures/{capture_id}/session-key",
                "POST /v1/standards/important-fields/encrypt",
                "POST /v1/standards/important-fields/submit-encrypted",
                "POST /v1/standards/important-fields/match-secure",
            ],
        },
        "agent_read_apis": cat.get("agent_read_apis"),
        "scenes": list_scenes(include_extensions=include_extensions, group=group),
        "catalog_path": "packages/evidence-schema/important-fields-standard.v1.json",
    }


@router.get("/important-fields/scenes")
async def list_important_field_scenes(
    include_extensions: bool = False,
    group: str | None = None,
) -> dict[str, Any]:
    scenes = list_scenes(include_extensions=include_extensions, group=group)
    return {
        "schema_version": "karma-important-fields-v1",
        "group": group,
        "count": len(scenes),
        "groups": list_scene_groups(),
        "scenes": scenes,
    }


@router.post("/important-fields/canonicalize")
async def canonicalize_important_fields(body: CanonicalizeRequest) -> dict[str, Any]:
    try:
        get_scene(body.scene_id)
    except ImportantFieldsError as exc:
        raise HTTPException(404, str(exc)) from exc
    errors = validate_fields(body.scene_id, body.fields)
    return {
        "schema_version": "karma-important-fields-v1",
        "scene_id": body.scene_id,
        "valid": not errors,
        "errors": errors,
        "canonical_json": canonical_json(body.fields) if not errors else None,
        "fields_hash": fields_hash(body.fields) if not errors else None,
    }


@router.post("/important-fields/match")
async def match_important_fields(body: MatchRequest) -> dict[str, Any]:
    """Legacy plaintext bilateral match (dev only). Prefer match-secure."""
    try:
        get_scene(body.scene_id)
    except ImportantFieldsError as exc:
        raise HTTPException(404, str(exc)) from exc
    out = match_submissions(body.scene_id, body.buyer_fields, body.seller_fields)
    out["deprecated_for_production"] = True
    out["prefer"] = "POST /v1/standards/important-fields/match-secure"
    return out


# --- Secure capture path (register before /{scene_id} to avoid path shadowing) ---


@router.post("/important-fields/captures")
async def create_important_fields_capture(body: CaptureRequest) -> dict[str, Any]:
    """Protocol captures/locks ImportantFields from the live interaction."""
    try:
        return capture_from_interaction(
            scene_id=body.scene_id,
            interaction_ref=body.interaction_ref,
            extracted_fields=body.extracted_fields,
            source=body.source,
            ttl_seconds=body.ttl_seconds,
        )
    except CaptureError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/important-fields/captures/{capture_id}")
async def get_important_fields_capture(capture_id: str) -> dict[str, Any]:
    try:
        return get_capture_public(capture_id)
    except CaptureError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/important-fields/captures/{capture_id}/session-key")
async def get_capture_session_key(capture_id: str) -> dict[str, Any]:
    """Issue AES session key for client-side encryption (serve only over TLS+auth)."""
    try:
        return issue_session_key(capture_id)
    except CaptureError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/important-fields/encrypt")
async def encrypt_important_fields(body: EncryptRequest) -> dict[str, Any]:
    """Encrypt fields under capture session key (trusted-agent helper)."""
    try:
        return encrypt_for_capture(body.capture_id, body.fields)
    except CaptureError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/important-fields/submit-encrypted")
async def submit_encrypted_important_fields(body: SecureSubmitRequest) -> dict[str, Any]:
    """Buyer/seller submit karma1 ciphertext only (plaintext rejected)."""
    try:
        return submit_encrypted(
            capture_id=body.capture_id,
            role=body.role,
            ciphertext=body.ciphertext,
            nonce=body.nonce,
        )
    except CaptureError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/important-fields/match-secure")
async def match_secure_important_fields(body: FinalizeRequest) -> dict[str, Any]:
    """Triple match: buyer == seller == protocol capture (after encrypted submits)."""
    try:
        return finalize_triple_match(body.capture_id)
    except CaptureError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/important-fields/{scene_id}")
async def get_important_fields_scene(scene_id: str) -> dict[str, Any]:
    try:
        scene = get_scene(scene_id)
    except ImportantFieldsError as exc:
        raise HTTPException(404, str(exc)) from exc
    cat = load_catalog()
    return {
        "schema_version": cat.get("schema_version"),
        "common_fields": cat.get("common_fields"),
        "canonicalization": cat.get("canonicalization"),
        "lifecycle": cat.get("lifecycle"),
        "scene": scene,
    }


@router.get("/important-fields/{scene_id}/example")
async def get_important_fields_example(scene_id: str) -> dict[str, Any]:
    try:
        return example_for_scene(scene_id)
    except ImportantFieldsError as exc:
        raise HTTPException(404, str(exc)) from exc
