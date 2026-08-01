"""Public standards endpoints — readable by both buyer and seller agents."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.important_fields_standard import (
    ImportantFieldsError,
    example_for_scene,
    fields_hash,
    get_scene,
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


@router.get("/important-fields")
async def get_important_fields_standard(include_extensions: bool = False) -> dict[str, Any]:
    """Full Important Fields catalog (11 market scenes + optional extensions)."""
    cat = load_catalog()
    return {
        "schema_version": cat.get("schema_version"),
        "title": cat.get("title"),
        "title_zh": cat.get("title_zh"),
        "description": cat.get("description"),
        "description_zh": cat.get("description_zh"),
        "canonicalization": cat.get("canonicalization"),
        "submission_envelope": cat.get("submission_envelope"),
        "common_fields": cat.get("common_fields"),
        "lifecycle": cat.get("lifecycle"),
        "agent_read_apis": cat.get("agent_read_apis"),
        "scenes": list_scenes(include_extensions=include_extensions),
        "catalog_path": "packages/evidence-schema/important-fields-standard.v1.json",
    }


@router.get("/important-fields/scenes")
async def list_important_field_scenes(include_extensions: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "karma-important-fields-v1",
        "count": len(list_scenes(include_extensions=include_extensions)),
        "scenes": list_scenes(include_extensions=include_extensions),
    }


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


@router.post("/important-fields/canonicalize")
async def canonicalize_important_fields(body: CanonicalizeRequest) -> dict[str, Any]:
    try:
        get_scene(body.scene_id)
    except ImportantFieldsError as exc:
        raise HTTPException(404, str(exc)) from exc
    errors = validate_fields(body.scene_id, body.fields)
    payload = {
        "schema_version": "karma-important-fields-v1",
        "scene_id": body.scene_id,
        "valid": not errors,
        "errors": errors,
        "canonical_json": canonical_json(body.fields) if not errors else None,
        "fields_hash": fields_hash(body.fields) if not errors else None,
    }
    return payload


@router.post("/important-fields/match")
async def match_important_fields(body: MatchRequest) -> dict[str, Any]:
    """Compare buyer vs seller ImportantFields — MATCHED only when hashes equal."""
    try:
        get_scene(body.scene_id)
    except ImportantFieldsError as exc:
        raise HTTPException(404, str(exc)) from exc
    return match_submissions(body.scene_id, body.buyer_fields, body.seller_fields)
