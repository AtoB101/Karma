"""Persist Console operator handoff attestation — server source of truth for automation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import OpenclawHandoffAttestationModel
from karma_openclaw.handoff import validate_handoff_v1

from services.agent_automation_policy import get_automation_policy
from services.openclaw_handoff_draft import build_handoff_draft

Role = Literal["buyer", "seller"]


def canonical_handoff_hash(handoff: dict[str, Any]) -> str:
    raw = json.dumps(handoff, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_handoff_attestation(
    db: AsyncSession,
    *,
    task_id: str,
    karma_identity_id: str,
) -> OpenclawHandoffAttestationModel | None:
    result = await db.execute(
        select(OpenclawHandoffAttestationModel).where(
            OpenclawHandoffAttestationModel.task_id == task_id,
            OpenclawHandoffAttestationModel.karma_identity_id == karma_identity_id,
        )
    )
    return result.scalar_one_or_none()


async def has_handoff_attestation(db: AsyncSession, *, task_id: str, karma_identity_id: str) -> bool:
    row = await get_handoff_attestation(db, task_id=task_id, karma_identity_id=karma_identity_id)
    return row is not None


async def confirm_handoff_attestation(
    db: AsyncSession,
    *,
    task_id: str,
    karma_identity_id: str,
    role: Role,
    trace_id: str = "",
    handoff: dict[str, Any] | None = None,
    attested_by_actor: str | None = None,
) -> dict[str, Any]:
    """
    Record operator attestation after server readiness passes.

    Uses ``handoff`` when provided; otherwise builds from ledger draft.
    """
    from services.openclaw_automation_readiness import evaluate_automation_readiness

    readiness = await evaluate_automation_readiness(
        db,
        task_id=task_id,
        role=role,
        karma_identity_id=karma_identity_id,
        require_attestation=False,
    )
    if not readiness.get("ready_for_task_automation"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "automation_not_ready",
                "blockers": readiness.get("blockers") or [],
                "hint": "Resolve blockers before handoff-confirm",
            },
        )

    if handoff is None:
        draft = await build_handoff_draft(db, task_id=task_id, trace_id=trace_id)
        handoff = draft.get("handoff")
        if not isinstance(handoff, dict):
            raise HTTPException(status_code=400, detail="could not build handoff from ledger")

    ok, errors, normalized = validate_handoff_v1(handoff)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail={"error": "handoff_invalid", "validation_errors": errors},
        )

    policy = await get_automation_policy(db, karma_identity_id)
    h_hash = canonical_handoff_hash(normalized)
    existing = await get_handoff_attestation(db, task_id=task_id, karma_identity_id=karma_identity_id)

    row_data = {
        "trace_id": (trace_id or normalized.get("trace_id") or f"trace-{task_id}").strip(),
        "attested_by_actor": attested_by_actor,
        "handoff_hash": h_hash,
        "policy_version": int(policy.policy_version) if policy else None,
        "handoff_snapshot": normalized,
        "readiness_snapshot": readiness,
        "created_at": datetime.utcnow(),
    }

    if existing:
        for key, val in row_data.items():
            setattr(existing, key, val)
        row = existing
    else:
        row = OpenclawHandoffAttestationModel(
            task_id=task_id,
            karma_identity_id=karma_identity_id,
            **row_data,
        )
        db.add(row)

    await db.flush()
    return {
        "attested": True,
        "attestation_id": row.attestation_id,
        "task_id": task_id,
        "karma_identity_id": karma_identity_id,
        "handoff_hash": h_hash,
        "policy_version": row.policy_version,
        "created_at": row.created_at.isoformat(),
    }


async def assert_handoff_attested(
    db: AsyncSession,
    *,
    task_id: str,
    karma_identity_id: str,
) -> None:
    from config.settings import settings

    if not settings.runtime_require_handoff_attestation:
        return
    if await has_handoff_attestation(db, task_id=task_id, karma_identity_id=karma_identity_id):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": "handoff_not_attested",
            "task_id": task_id,
            "karma_identity_id": karma_identity_id,
            "hint": "Complete Console step: POST /v1/openclaw/handoff-confirm after automation-readiness",
        },
    )
