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
