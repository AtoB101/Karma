"""
Evidence bundle size / shape limits for public HTTP surfaces.

Mitigates DoS against ``POST /v1/verify`` (private runtime proxy) and ``POST /v1/bundles``
via oversized JSON or huge receipt id lists.
"""
from __future__ import annotations

import json

from fastapi import HTTPException

from config.settings import settings
from core.schemas import EvidenceBundle, TaskContract


def enforce_bundle_receipt_list_limits(bundle: EvidenceBundle) -> None:
    n = len(bundle.receipt_ids)
    if len(bundle.receipt_hashes) != n:
        raise HTTPException(400, "receipt_ids and receipt_hashes must have the same length")
    cap = settings.evidence_bundle_max_receipt_entries
    if n > cap:
        raise HTTPException(
            400,
            f"receipt_ids length {n} exceeds maximum allowed ({cap})",
        )


def enforce_bundle_json_size(bundle: EvidenceBundle, *, max_bytes: int) -> None:
    raw = json.dumps(bundle.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
    if len(raw) > max_bytes:
        raise HTTPException(
            413,
            f"bundle JSON exceeds maximum size of {max_bytes} bytes",
        )


def enforce_verify_combined_json_size(bundle: EvidenceBundle, contract: TaskContract, *, max_bytes: int) -> None:
    payload = {
        "bundle": bundle.model_dump(mode="json"),
        "contract": contract.model_dump(mode="json"),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(raw) > max_bytes:
        raise HTTPException(
            413,
            f"verify request JSON exceeds maximum size of {max_bytes} bytes",
        )


def enforce_limits_for_bundle_post(bundle: EvidenceBundle) -> None:
    """``POST /v1/bundles`` — structure + serialized size."""
    enforce_bundle_receipt_list_limits(bundle)
    enforce_bundle_json_size(bundle, max_bytes=settings.evidence_bundle_max_json_bytes)


def enforce_limits_for_verify_request(bundle: EvidenceBundle, contract: TaskContract) -> None:
    """``POST /v1/verify`` — structure + combined JSON size sent to private runtime."""
    enforce_bundle_receipt_list_limits(bundle)
    enforce_verify_combined_json_size(
        bundle,
        contract,
        max_bytes=settings.verify_max_combined_json_bytes,
    )
