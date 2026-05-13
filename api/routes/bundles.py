"""Karma API — Evidence Bundles"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import EvidenceBundle, TaskStatus
from db.session import get_db
from db.models.orm import EvidenceBundleModel
from services.evidence_bundle_limits import enforce_limits_for_bundle_post

router = APIRouter()


@router.post("", response_model=EvidenceBundle, status_code=201)
async def submit_bundle(bundle: EvidenceBundle, db: AsyncSession = Depends(get_db)):
    enforce_limits_for_bundle_post(bundle)
    existing = await db.execute(
        select(EvidenceBundleModel).where(EvidenceBundleModel.task_id == bundle.task_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Bundle for task {bundle.task_id} already exists")

    db.add(EvidenceBundleModel(
        bundle_id=bundle.bundle_id,
        task_id=bundle.task_id,
        task_contract_hash=bundle.task_contract_hash,
        receipt_ids=bundle.receipt_ids,
        receipt_hashes=bundle.receipt_hashes,
        final_result_hash=bundle.final_result_hash,
        total_steps=bundle.total_steps,
        successful_steps=bundle.successful_steps,
        failed_steps=bundle.failed_steps,
        total_duration_ms=bundle.total_duration_ms,
        agent_signature=bundle.agent_signature,
        storage_path=bundle.storage_path,
        settlement_status=bundle.settlement_status.value
            if hasattr(bundle.settlement_status, "value") else bundle.settlement_status,
        created_at=bundle.created_at,
    ))
    return bundle


@router.get("/{bundle_id}", response_model=EvidenceBundle)
async def get_bundle(bundle_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(EvidenceBundleModel, bundle_id)
    if not row:
        raise HTTPException(404)
    return _from_row(row)


@router.get("/task/{task_id}", response_model=EvidenceBundle)
async def get_bundle_by_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EvidenceBundleModel).where(EvidenceBundleModel.task_id == task_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404)
    return _from_row(row)


def _from_row(row: EvidenceBundleModel) -> EvidenceBundle:
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
