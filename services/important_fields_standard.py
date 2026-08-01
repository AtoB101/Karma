"""Karma Important Fields Standard — loader, validation, canonical hash, diff.

Machine-readable catalog:
  packages/evidence-schema/important-fields-standard.v1.json

Both buyer and seller agents should read the catalog, submit the same
ImportantFields for a scene, and only seal/on-chain when fields_hash matches.

P5: high-precision canonicalization so formatting noise cannot create false
matches or false COUNTERED — amount/datetime/string normalization is mandatory
before hash.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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

_AMOUNT_RE = re.compile(r"^[0-9]+(\.[0-9]{1,6})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def _scene_summary(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": s["scene_id"],
        "group": s.get("group"),
        "service_category": s.get("service_category"),
        "service_type": s.get("service_type"),
        "on_chain_enum": s.get("on_chain_enum"),
        "title_en": s.get("title_en"),
        "title_zh": s.get("title_zh"),
        "market_summary_zh": s.get("market_summary_zh") or s.get("note_zh"),
        "risk_tier": s.get("risk_tier"),
        "location_mode": s.get("location_mode"),
    }


def list_scenes(
    *,
    include_extensions: bool = False,
    group: str | None = None,
) -> list[dict[str, Any]]:
    """List scenes. group: market_vertical | daily_commerce | b2b_digital | extension."""
    cat = load_catalog()
    scenes = list(cat.get("scenes") or [])
    if include_extensions or (group == "extension"):
        scenes.extend(cat.get("extensions") or [])
    if group:
        scenes = [s for s in scenes if s.get("group") == group]
    return [_scene_summary(s) for s in scenes]


def list_scene_groups() -> dict[str, Any]:
    cat = load_catalog()
    return {
        "schema_version": cat.get("schema_version"),
        "groups": cat.get("scene_groups") or {},
        "counts": {
            "market_vertical": len(list_scenes(group="market_vertical")),
            "daily_commerce": len(list_scenes(group="daily_commerce")),
            "b2b_digital": len(list_scenes(group="b2b_digital")),
            "extension": len(list_scenes(include_extensions=True, group="extension")),
            "all_primary": len(list_scenes(include_extensions=False)),
        },
    }


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


def normalize_amount_string(val: Any) -> str | None:
    """High-precision money string: Decimal normalize, strip trailing zeros."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return None  # must be string on the wire
    if not isinstance(val, str):
        return None
    s = val.strip()
    if not _AMOUNT_RE.match(s):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    # Normalize without scientific notation; strip trailing zeros
    norm = format(d.normalize(), "f")
    if "." in norm:
        norm = norm.rstrip("0").rstrip(".")
    return norm or "0"


def normalize_datetime_utc(val: Any) -> str | None:
    """Parse ISO-8601 → ``YYYY-MM-DDTHH:MM:SSZ`` (second precision)."""
    if not isinstance(val, str) or not val.strip():
        return None
    s = val.strip().replace(" ", "T")
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:  # noqa: BLE001
        return None


def normalize_text(val: Any) -> str | None:
    if not isinstance(val, str):
        return None
    # Unicode NFC + trim — precision without PII expansion
    return unicodedata.normalize("NFC", val).strip()


def _validate_leaf(path: str, val: Any, spec: dict[str, Any], errors: list[str]) -> None:
    fmt = spec.get("format")
    typ = spec.get("type")
    if path == "amount" or (typ == "string" and path.endswith("amount")):
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            errors.append(f"{path} must be a decimal string, not number")
            return
        if normalize_amount_string(val) is None:
            errors.append(f"{path} must match decimal string pattern ^[0-9]+(\\.[0-9]{{1,6}})?$")
            return
    if fmt == "date-time":
        if normalize_datetime_utc(val) is None:
            errors.append(f"{path} must be ISO-8601 datetime (UTC Z)")
            return
    if fmt == "date":
        if not isinstance(val, str) or not _DATE_RE.match(val.strip()):
            errors.append(f"{path} must be YYYY-MM-DD")
            return
    if typ == "string" and isinstance(val, str):
        text = normalize_text(val) or ""
        min_len = spec.get("minLength")
        max_len = spec.get("maxLength")
        if min_len is not None and len(text) < int(min_len):
            errors.append(f"{path} shorter than minLength {min_len}")
        if max_len is not None and len(text) > int(max_len):
            errors.append(f"{path} longer than maxLength {max_len}")
    if "enum" in spec and isinstance(val, str) and val not in spec["enum"]:
        errors.append(f"{path} must be one of {spec['enum']}")
    if "const" in spec and val != spec["const"]:
        errors.append(f"{path} must be {spec['const']!r}")
    # Nested object required keys
    props = spec.get("properties")
    if isinstance(props, dict) and isinstance(val, dict):
        for pk, pspec in props.items():
            if not isinstance(pspec, dict):
                continue
            if pspec.get("required") is False:
                continue
            # treat nested property as required when listed under properties
            # unless explicitly optional
            child = val.get(pk)
            child_path = f"{path}.{pk}"
            if _is_empty(child) and pspec.get("optional") is not True:
                # only enforce when nested key is in a "required" array if present
                continue
            if child is not None and not _is_empty(child):
                _validate_leaf(child_path, child, pspec, errors)


def validate_fields(scene_id: str, fields: dict[str, Any]) -> list[str]:
    """Return list of validation errors (empty = ok). High-precision checks."""
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
        if path == "acceptance_criteria":
            if not isinstance(val, list) or not all(
                isinstance(x, str) and (normalize_text(x) or "") for x in val
            ):
                errors.append("acceptance_criteria must be a non-empty string array")
                continue
        else:
            _validate_leaf(path, val, req, errors)
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
        _validate_leaf(path, val, req, errors)
        # Nested required property keys only when explicitly listed
        props = req.get("properties") or {}
        required_keys = req.get("required")
        if isinstance(val, dict) and props and isinstance(required_keys, list):
            for pk in required_keys:
                if pk in props and _is_empty(val.get(pk)):
                    errors.append(f"missing required nested field: {path}.{pk}")

    proofs = fields.get("required_proof_fields")
    if proofs is None:
        pass
    elif not isinstance(proofs, list) or not proofs:
        errors.append("required_proof_fields must be a non-empty array when provided")

    return errors


def strip_for_hash(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if k not in HASH_EXCLUDE}


def canonicalize(value: Any, *, path: str = "") -> Any:
    """Deterministic JSON-ready structure with high-precision leaf normalization."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    if isinstance(value, str):
        # Path-aware normalization for precision
        leaf = path.split(".")[-1] if path else ""
        if leaf == "amount" or path.endswith(".amount") or path == "amount":
            amt = normalize_amount_string(value)
            return amt if amt is not None else normalize_text(value)
        if leaf.endswith("_at") or leaf in {"deadline_at", "check_in", "check_out", "depart_at"}:
            dt = normalize_datetime_utc(value)
            if dt is not None:
                return dt
        if leaf in {"date", "check_in_date", "check_out_date"} or (
            len(value.strip()) == 10 and _DATE_RE.match(value.strip())
        ):
            return value.strip()
        return normalize_text(value)
    if isinstance(value, list):
        return [canonicalize(v, path=path) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value.keys()):
            if key in HASH_EXCLUDE:
                continue
            child_path = f"{path}.{key}" if path else key
            item = canonicalize(value[key], path=child_path)
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
            "secure_flow_zh": [
                "1. 协议在交互中抓取字段 → POST /captures",
                "2. 双方领取 session-key?role=，本地 AES-GCM 加密（karma2. 信封）",
                "3. POST /submit-encrypted（仅密文 + nonce + submitter_agent_id）",
                "4. POST /match-secure → 必须 buyer==seller==protocol 三方一致并封存",
            ],
            "buyer": {"party_role": "buyer", "fields_example_only": out},
            "seller": {"party_role": "seller", "fields_example_only": out},
            "note_zh": "生产路径禁止明文对碰；示例 fields 仅供对齐结构",
        },
    }
