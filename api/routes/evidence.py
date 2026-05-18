"""Evidence API — GET evidence, verify digest, AP2 external verify (Phase 3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import EvidenceBundleModel
from db.session import get_db
from services.evidence_export import bundle_to_evidence_object, verify_evidence_digest, verify_sd_jwt_export
from services.path_param_safety import validate_public_url_segment
from trusted_agent_runtime.ap2_adapter import (
    evidence_digest,
    from_ap2_mandate,
    to_ap2_mandate,
    verify_ap2_digest_consistency,
)

router = APIRouter()


def _row_to_bundle(row: EvidenceBundleModel):
    from core.schemas import EvidenceBundle, TaskStatus

    return EvidenceBundle(
        bundle_id=row.bundle_id,
        task_id=row.task_id,
        task_contract_hash=row.task_contract_hash,
        receipt_ids=row.receipt_ids,
        receipt_hashes=row.receipt_hashes,
        final_result_hash=row.final_result_hash,
        total_steps=row.total_steps,
        successful_steps=row.successful_steps,
        failed_steps=row.failed_steps,
        total_duration_ms=row.total_duration_ms,
        agent_signature=row.agent_signature,
        storage_path=row.storage_path,
        settlement_status=TaskStatus(row.settlement_status),
        created_at=row.created_at,
    )


@router.get("/{evidence_id}")
async def get_evidence(evidence_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("evidence_id", evidence_id)
    row = await db.get(EvidenceBundleModel, evidence_id)
    if not row:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    bundle = _row_to_bundle(row)
    return bundle_to_evidence_object(bundle, evidence_id=evidence_id)


class VerifyEvidenceBody(BaseModel):
    expectedDigestSha256: str
    expectedSchemaVersion: str | None = None


@router.post("/{evidence_id}/verify")
async def verify_evidence(evidence_id: str, body: VerifyEvidenceBody, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("evidence_id", evidence_id)
    row = await db.get(EvidenceBundleModel, evidence_id)
    if not row:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    bundle = _row_to_bundle(row)
    result = verify_evidence_digest(
        bundle,
        body.expectedDigestSha256,
        body.expectedSchemaVersion,
    )
    return {
        "evidenceId": evidence_id,
        "verified": result["verified"],
        "checks": result["checks"],
    }


class VerifyExternalBody(BaseModel):
    ap2_mandate: dict[str, Any] = Field(description="AP2 mandate JSON (Intent/Cart/Payment layers)")
    sd_jwt_export: str | None = Field(default=None, description="Optional karma-sd-jwt+v1 export token")


@router.post("/{evidence_id}/verify-external")
async def verify_evidence_external(
    evidence_id: str,
    body: VerifyExternalBody,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify AP2 mandate signatures/digests against stored Karma evidence bundle.
    """
    validate_public_url_segment("evidence_id", evidence_id)
    row = await db.get(EvidenceBundleModel, evidence_id)
    if not row:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    bundle = _row_to_bundle(row)
    try:
        parsed = from_ap2_mandate(body.ap2_mandate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ok, detail = verify_ap2_digest_consistency(body.ap2_mandate, recomputed_bundle=bundle)
    stored_digest = evidence_digest(bundle)
    digest_match = parsed["karma_evidence_digest"] == stored_digest
    if body.sd_jwt_export:
        sd_ok, _, sd_detail = verify_sd_jwt_export(body.sd_jwt_export)
        if not sd_ok:
            raise HTTPException(status_code=400, detail=f"sd_jwt_export invalid: {sd_detail}")

    verified = ok and digest_match
    return {
        "evidenceId": evidence_id,
        "verified": verified,
        "digestSha256": stored_digest,
        "ap2DigestMatch": digest_match,
        "mandateConsistency": ok,
        "detail": detail if verified else f"{detail}; digest_match={digest_match}",
    }


class ExportAp2Body(BaseModel):
    payer: str
    payee: str
    token: str
    amount: str
    chainId: int
    policyId: str
    merchantRef: str
    expiresAt: str


@router.post("/{evidence_id}/export-ap2")
async def export_ap2_mandate(evidence_id: str, body: ExportAp2Body, db: AsyncSession = Depends(get_db)):
    """Helper: build AP2 mandate + SD-JWT export for a stored bundle (operator tooling)."""
    validate_public_url_segment("evidence_id", evidence_id)
    row = await db.get(EvidenceBundleModel, evidence_id)
    if not row:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    bundle = _row_to_bundle(row)
    mandate = to_ap2_mandate(
        bundle,
        payer=body.payer,
        payee=body.payee,
        token=body.token,
        amount=body.amount,
        chain_id=body.chainId,
        policy_id=body.policyId,
        merchant_ref=body.merchantRef,
        expires_at=body.expiresAt,
    )
    from services.evidence_export import export_sd_jwt_disclosure

    sd = export_sd_jwt_disclosure(
        bundle,
        payer=body.payer,
        payee=body.payee,
        token=body.token,
        amount=body.amount,
        chain_id=body.chainId,
        policy_id=body.policyId,
        merchant_ref=body.merchantRef,
        expires_at=body.expiresAt,
    )
    return {"ap2_mandate": mandate, "sd_jwt_export": sd, "digestSha256": mandate["karma_evidence_digest"]}
