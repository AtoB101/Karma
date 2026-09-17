"""Karma API — Evidence Bundles"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import EvidenceBundle, TaskStatus
from db.session import get_db
from db.models.orm import EvidenceBundleModel
from db.stores.settlement_store import PostgresSettlementStore
from services.actor_guards import caller_is_privileged
from services.evidence_bundle_limits import enforce_limits_for_bundle_post
from services.identity_actor import resolve_actor_identity_id
from services.path_param_safety import validate_public_url_segment
from services.receipt_guard import (
    evidence_bundle_signature_acceptable,
    evidence_bundle_signature_required,
)

router = APIRouter()


@router.post("", response_model=EvidenceBundle, status_code=201)
async def submit_bundle(
    bundle: EvidenceBundle,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """提交证据包。

    2026-09-17 复核：这条路径此前**没有任何归属校验** —— 实测任何身份都能给
    别人的任务建包（返回 201，且 ``agent_signature`` 可以是 NULL）。这既可以
    伪造证据，也能抢先占位把真正的交割方挤掉（一个任务只允许一个包）。
    现在：必须存在该任务的结算，且提交者必须是买家/卖家本人（运维岗可代办）；
    签名必填且强制验签（占位签名只在非生产环境放行）。
    """
    validate_public_url_segment("bundle_id", bundle.bundle_id)
    validate_public_url_segment("task_id", bundle.task_id)
    enforce_limits_for_bundle_post(bundle)

    settlement = await PostgresSettlementStore(db).get(bundle.task_id)
    if settlement is None:
        raise HTTPException(404, f"settlement {bundle.task_id} not found")
    allowed = {settlement.client_agent_id}
    if settlement.worker_agent_id:
        allowed.add(settlement.worker_agent_id)
    actor_identity = await resolve_actor_identity_id(db, request)
    if actor_identity not in allowed and not caller_is_privileged(request):
        raise HTTPException(
            403, "only the task's buyer or worker may submit an evidence bundle"
        )

    if evidence_bundle_signature_required() and not (bundle.agent_signature or "").strip():
        raise HTTPException(422, "agent_signature is required")
    if not evidence_bundle_signature_acceptable(bundle):
        raise HTTPException(400, "agent_signature does not verify")

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


@router.get("/task/{task_id}", response_model=EvidenceBundle)
async def get_bundle_by_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Registered before ``/{bundle_id}`` so ``task`` is not captured as a bundle id."""
    validate_public_url_segment("task_id", task_id)
    result = await db.execute(
        select(EvidenceBundleModel).where(EvidenceBundleModel.task_id == task_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404)
    return _from_row(row)


@router.get("/{bundle_id}", response_model=EvidenceBundle)
async def get_bundle(bundle_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("bundle_id", bundle_id)
    row = await db.get(EvidenceBundleModel, bundle_id)
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
