"""Karma Important Fields Standard — loader, validation, canonical hash, diff.

Machine-readable catalog:
  packages/evidence-schema/important-fields-standard.v1.json

Both buyer and seller agents should read the catalog, submit the same
ImportantFields for a scene, and only seal/on-chain when fields_hash matches.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "important-fields-standard.v1.json"
)

HASH_EXCLUDE = frozenset(
    {"party_role", "submitter_agent_id", "submitted_at", "signature", "fields_hash"}
)


class ImportantFieldsError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"important fields catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-important-fields-v1":
        raise ImportantFieldsError("unsupported important-fields schema_version")
    return data


def list_scenes(*, include_extensions: bool = False) -> list[dict[str, Any]]:
    cat = load_catalog()
    scenes = list(cat.get("scenes") or [])
    if include_extensions:
        scenes.extend(cat.get("extensions") or [])
    return [
        {
            "scene_id": s["scene_id"],
            "service_category": s.get("service_category"),
            "on_chain_enum": s.get("on_chain_enum"),
            "title_en": s.get("title_en"),
            "title_zh": s.get("title_zh"),
            "market_summary_zh": s.get("market_summary_zh") or s.get("note_zh"),
            "risk_tier": s.get("risk_tier"),
            "location_mode": s.get("location_mode"),
        }
        for s in scenes
    ]


def get_scene(scene_id: str, *, include_extensions: bool = True) -> dict[str, Any]:
    cat = load_catalog()
    for s in cat.get("scenes") or []:
        if s.get("scene_id") == scene_id:
            return s
    if include_extensions:
        for s in cat.get("extensions") or []:
            if s.get("scene_id") == scene_id:
                return s
    raise ImportantFieldsError(f"unknown scene_id: {scene_id}")


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def validate_fields(scene_id: str, fields: dict[str, Any]) -> list[str]:
    """Return list of validation errors (empty = ok)."""
    errors: list[str] = []
    if not isinstance(fields, dict):
        return ["fields must be an object"]

    cat = load_catalog()
    scene = get_scene(scene_id)

    for req in cat.get("common_fields", {}).get("required") or []:
        path = req["path"]
        val = _dig(fields, path)
        if _is_empty(val):
            errors.append(f"missing required common field: {path}")
            continue
        if path == "amount" and isinstance(val, (int, float)):
            errors.append("amount must be a decimal string, not number")
        if path == "acceptance_criteria":
            if not isinstance(val, list) or not all(isinstance(x, str) and x.strip() for x in val):
                errors.append("acceptance_criteria must be a non-empty string array")
        if path == "currency" and isinstance(val, str):
            allowed = set((req.get("enum") or []))
            if allowed and val not in allowed:
                errors.append(f"currency must be one of {sorted(allowed)}")

    for req in scene.get("required_scene_fields") or []:
        path = req["path"]
        val = _dig(fields, path)
        if _is_empty(val):
            errors.append(f"missing required scene field: {path}")
            continue
        if "const" in req and val != req["const"]:
            errors.append(f"{path} must be {req['const']!r}")
        if "enum" in req and isinstance(val, str) and val not in req["enum"]:
            errors.append(f"{path} must be one of {req['enum']}")

    # Encourage proof field coverage for seal readiness
    proofs = fields.get("required_proof_fields")
    if proofs is None:
        # soft default from scene — not an error, but note via empty check later
        pass
    elif not isinstance(proofs, list) or not proofs:
        errors.append("required_proof_fields must be a non-empty array when provided")

    return errors


def strip_for_hash(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if k not in HASH_EXCLUDE}


def canonicalize(value: Any) -> Any:
    """Deterministic JSON-ready structure (sorted keys, drop nulls in objects)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [canonicalize(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value.keys()):
            if key in HASH_EXCLUDE:
                continue
            item = canonicalize(value[key])
            if item is None:
                continue
            out[key] = item
        return out
    return str(value)


def canonical_json(fields: dict[str, Any]) -> str:
    cleaned = canonicalize(strip_for_hash(fields))
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def fields_hash(fields: dict[str, Any]) -> str:
    raw = canonical_json(fields).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def diff_fields(a: dict[str, Any], b: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    """Field-level diff for COUNTERED responses."""
    ca = canonicalize(strip_for_hash(a)) or {}
    cb = canonicalize(strip_for_hash(b)) or {}
    if not isinstance(ca, dict):
        ca = {}
    if not isinstance(cb, dict):
        cb = {}
    diffs: list[dict[str, Any]] = []
    keys = sorted(set(ca) | set(cb))
    for key in keys:
        path = f"{prefix}.{key}" if prefix else key
        va, vb = ca.get(key), cb.get(key)
        if isinstance(va, dict) and isinstance(vb, dict):
            diffs.extend(diff_fields(va, vb, prefix=path))
        elif va != vb:
            diffs.append({"path": path, "buyer": va, "seller": vb})
    return diffs


def match_submissions(
    scene_id: str,
    buyer_fields: dict[str, Any],
    seller_fields: dict[str, Any],
) -> dict[str, Any]:
    buyer_errors = validate_fields(scene_id, buyer_fields)
    seller_errors = validate_fields(scene_id, seller_fields)
    bh = fields_hash(buyer_fields) if not buyer_errors else None
    sh = fields_hash(seller_fields) if not seller_errors else None
    matched = bool(bh and sh and bh == sh)
    result: dict[str, Any] = {
        "schema_version": "karma-important-fields-v1",
        "scene_id": scene_id,
        "status": "MATCHED" if matched else "COUNTERED",
        "buyer_fields_hash": bh,
        "seller_fields_hash": sh,
        "buyer_errors": buyer_errors,
        "seller_errors": seller_errors,
        "diff": [] if matched else diff_fields(buyer_fields, seller_fields),
    }
    if matched and bh:
        result["commitment_hint"] = {
            "fields_hash": bh,
            "next_steps": [
                "Both parties sign fields_hash (optional EIP-712)",
                "Seal agreement → evidence bundle embeds fields_hash",
                "On-chain bind with scopeHash derived from fields_hash",
            ],
        }
    return result


def example_for_scene(scene_id: str) -> dict[str, Any]:
    scene = get_scene(scene_id)
    example = scene.get("example_fields")
    if not example:
        raise ImportantFieldsError(f"no example_fields for scene_id: {scene_id}")
    # Fill default proof fields if omitted
    out = dict(example)
    if "required_proof_fields" not in out:
        out["required_proof_fields"] = list(scene.get("default_required_proof_fields") or [])
    return {
        "schema_version": "karma-important-fields-v1",
        "scene_id": scene_id,
        "service_category": scene.get("service_category"),
        "fields": out,
        "fields_hash": fields_hash(out),
        "canonical_json": canonical_json(out),
        "submission_hint": {
            "buyer": {
                "party_role": "buyer",
                "fields": out,
            },
            "seller": {
                "party_role": "seller",
                "fields": out,
            },
            "note_zh": "双方提交的 fields 必须完全一致（hash 相等）才能 MATCHED 并上链",
        },
    }
