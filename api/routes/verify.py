"""
Karma API — Verification Proxy
Receives bundle submissions, forwards to private runtime for decision.
Enqueues async Celery task for non-blocking flow.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    EvidenceBundle,
    TaskContract,
    VerificationResult,
)
from db.session import get_db
from db.models.orm import VerificationResultModel, EvidenceBundleModel
from api.middleware.auth import get_current_agent_id
from api.middleware.rate_limit import verify_rate_limit

router = APIRouter()


class VerifyRequest(BaseModel):
    bundle: EvidenceBundle
    contract: TaskContract


@router.post("", response_model=VerificationResult)
async def submit_for_verification(
    body: VerifyRequest,
    db: AsyncSession = Depends(get_db),
    agent_id: str = Depends(get_current_agent_id),
    _rl: None = Depends(verify_rate_limit),
):
    """
    Submit an evidence bundle for verification.
    Decision logic runs in the private runtime — result returned async via Celery
    or synchronously via HTTP call to private runtime.
    """
    from config.settings import settings
    import httpx

    # Persist bundle first
    from sqlalchemy import select
    existing = await db.execute(
        select(EvidenceBundleModel).where(
            EvidenceBundleModel.task_id == body.bundle.task_id
        )
    )
    if not existing.scalar_one_or_none():
        from api.routes.bundles import _from_row
        db.add(EvidenceBundleModel(
            bundle_id=body.bundle.bundle_id,
            task_id=body.bundle.task_id,
            task_contract_hash=body.bundle.task_contract_hash,
            receipt_ids=body.bundle.receipt_ids,
            receipt_hashes=body.bundle.receipt_hashes,
            final_result_hash=body.bundle.final_result_hash,
            total_steps=body.bundle.total_steps,
            successful_steps=body.bundle.successful_steps,
            failed_steps=body.bundle.failed_steps,
            total_duration_ms=body.bundle.total_duration_ms,
            agent_signature=body.bundle.agent_signature,
            storage_path=body.bundle.storage_path,
            settlement_status="verifying",
            created_at=body.bundle.created_at,
        ))
        await db.flush()

    # Forward to private runtime
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{settings.private_runtime_url}/v1/verify",
                json={
                    "bundle":   body.bundle.model_dump(mode="json"),
                    "contract": body.contract.model_dump(mode="json"),
                },
                headers={"X-Runtime-Key": settings.private_runtime_api_key},
            )
            resp.raise_for_status()
            result = VerificationResult(**resp.json())
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, "Private runtime returned an error") from e
    except httpx.ConnectError:
        raise HTTPException(503, "Private runtime unreachable")

    # Persist result
    db.add(VerificationResultModel(
        verification_id=result.verification_id,
        task_id=result.task_id,
        bundle_id=result.bundle_id,
        decision=result.decision.value if hasattr(result.decision, "value") else result.decision,
        confidence=result.confidence,
        checks=[c.model_dump() for c in result.checks],
        notes=result.notes,
        verified_at=result.verified_at,
    ))

    # Trigger async settlement + reputation update via Celery
    from worker.tasks import run_settlement, update_reputation
    run_settlement.delay(
        result.task_id,
        result.model_dump(mode="json"),
        body.bundle.model_dump(mode="json"),
        body.contract.model_dump(mode="json"),
    )

    return result


@router.get("/{task_id}", response_model=VerificationResult)
async def get_verification_result(task_id: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    res = await db.execute(
        select(VerificationResultModel).where(
            VerificationResultModel.task_id == task_id
        )
    )
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(404, f"No verification result for task {task_id}")
    from core.schemas import VerificationCheck, VerificationDecision
    return VerificationResult(
        verification_id=row.verification_id,
        task_id=row.task_id,
        bundle_id=row.bundle_id,
        decision=VerificationDecision(row.decision),
        confidence=row.confidence,
        checks=[VerificationCheck(**c) for c in (row.checks or [])],
        notes=row.notes,
        verified_at=row.verified_at,
    )
