"""Public evidence export — SD-JWT-style compact token (Phase 3).

No private risk scores; verifiable with documented offline commands
(see docs/AP2_EVIDENCE_PROFILE-zh.md § SD-JWT verification).
"""

from __future__ import annotations

import base64
import json
from typing import Any, Mapping

from trusted_agent_runtime.ap2_adapter import AP2_SCHEMA_VERSION, evidence_digest, to_ap2_mandate
from trusted_agent_runtime.hashing import canonical_json_bytes, sha256_hex

SD_JWT_TYP = "karma-sd-jwt+v1"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def export_sd_jwt_disclosure(
    bundle: Any,
    *,
    payer: str,
    payee: str,
    token: str,
    amount: str,
    chain_id: int,
    policy_id: str,
    merchant_ref: str,
    expires_at: str,
) -> str:
    """
    Compact SD-JWT-like export: ``<typ>.<payload_b64url>.<digest_b64url>``.

    Third parties recompute ``digest`` from decoded payload (see ``verify_sd_jwt_export``).
    """
    mandate = to_ap2_mandate(
        bundle,
        payer=payer,
        payee=payee,
        token=token,
        amount=amount,
        chain_id=chain_id,
        policy_id=policy_id,
        merchant_ref=merchant_ref,
        expires_at=expires_at,
    )
    payload = {
        "typ": SD_JWT_TYP,
        "ap2_version": AP2_SCHEMA_VERSION,
        "merchant_ref": merchant_ref,
        "karma_evidence_digest": mandate["karma_evidence_digest"],
        "mandate_digest": mandate["mandate_digest"],
        "task_id": mandate.get("karma_task_id"),
        "bundle_id": mandate.get("karma_bundle_id"),
        "disclosed_fields": ["karma_evidence_digest", "mandate_digest", "merchant_ref", "task_id"],
    }
    payload_bytes = canonical_json_bytes(payload)
    digest = sha256_hex(payload_bytes)
    return f"{SD_JWT_TYP}.{_b64url(payload_bytes)}.{_b64url(bytes.fromhex(digest))}"


def verify_sd_jwt_export(token: str) -> tuple[bool, dict[str, Any], str]:
    """Parse export token and verify embedded digest."""
    parts = token.split(".")
    if len(parts) != 3:
        return False, {}, "expected three segments: typ.payload.digest"
    typ, payload_seg, digest_seg = parts
    if typ != SD_JWT_TYP:
        return False, {}, f"unexpected typ: {typ}"
    try:
        payload_obj = json.loads(_b64url_decode(payload_seg))
        digest_bytes = _b64url_decode(digest_seg)
    except (json.JSONDecodeError, ValueError) as exc:
        return False, {}, f"decode error: {exc}"
    if len(digest_bytes) != 32:
        return False, payload_obj, "digest segment must be 32 bytes"
    recomputed = sha256_hex(canonical_json_bytes(payload_obj))
    if digest_bytes.hex() != recomputed:
        return False, payload_obj, f"payload digest mismatch: token={digest_bytes.hex()} recomputed={recomputed}"
    return True, payload_obj, "ok"


def bundle_to_evidence_object(bundle: Any, *, evidence_id: str | None = None) -> dict[str, Any]:
    """Map bundle to OpenAPI EvidenceObject-shaped dict."""
    canonical = bundle.model_dump(mode="json") if hasattr(bundle, "model_dump") else dict(bundle)
    eid = evidence_id or str(canonical.get("bundle_id", ""))
    digest = evidence_digest(bundle)
    receipt_hashes = list(canonical.get("receipt_hashes") or [])
    return {
        "evidenceId": eid,
        "schemaVersion": canonical.get("schema_version", "karma.evidence_bundle.v1"),
        "evidenceVersion": "1",
        "digestSha256": digest,
        "payload": canonical,
        "caller_authorization_signature": canonical.get("agent_signature") or "",
        "provider_execution_signature": "",
        "request_hash": receipt_hashes[0] if receipt_hashes else digest,
        "response_hash": canonical.get("final_result_hash") or digest,
        "execution_trace_hash": "",
        "dispute_status": "none",
        "settlement_status": _map_settlement_status(canonical.get("settlement_status")),
    }


def _map_settlement_status(status: Any) -> str:
    raw = getattr(status, "value", status) if status is not None else "pending"
    s = str(raw).lower()
    if s in ("settled",):
        return "settled"
    if s in ("disputed", "dispute"):
        return "disputed"
    if s in ("cancelled", "canceled", "refunded"):
        return "cancelled"
    return "pending"


def verify_evidence_digest(bundle: Any, expected_digest: str, expected_schema: str | None = None) -> dict[str, Any]:
    actual = evidence_digest(bundle)
    schema = (
        bundle.schema_version
        if hasattr(bundle, "schema_version")
        else (bundle.model_dump().get("schema_version") if hasattr(bundle, "model_dump") else None)
    )
    schema_str = str(schema or "karma.evidence_bundle.v1")
    return {
        "verified": actual == expected_digest.lower() and (
            expected_schema is None or schema_str == expected_schema
        ),
        "checks": {
            "digestMatch": actual == expected_digest.lower(),
            "schemaVersionMatch": expected_schema is None or schema_str == expected_schema,
        },
        "actualDigestSha256": actual,
        "schemaVersion": schema_str,
    }
