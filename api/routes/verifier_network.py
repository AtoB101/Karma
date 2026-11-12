"""
Karma Verifier Network — API Routes
====================================
REST API for the decentralized verification network:

- Verifier node registration and management
- Attestation submission and retrieval
- Challenge lifecycle
- Network statistics
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from decentralized_verifier.models import Attestation as AttestationModel
from decentralized_verifier.models import Challenge as ChallengeModel
from decentralized_verifier.models import VerifierNode as VerifierNodeModel
from decentralized_verifier.schemas import (
    AttestationListResponse,
    AttestationResponse,
    AttestationSubmitRequest,
    ChallengeOpenRequest,
    ChallengeResolveRequest,
    ChallengeResponse,
    NetworkStatsResponse,
    VerifierListResponse,
    VerifierNodeResponse,
    VerifierRegisterRequest,
    VerifierStakeUpdateRequest,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Verifier Nodes
# ═══════════════════════════════════════════════════════════════════


@router.post("/register", response_model=VerifierNodeResponse, status_code=201)
async def register_verifier(
    body: VerifierRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new verifier node in the network."""
    # Check for duplicate wallet
    existing = await db.execute(
        select(VerifierNodeModel).where(
            VerifierNodeModel.wallet_address == body.wallet_address
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "A verifier with this wallet address already exists")

    node = VerifierNodeModel(
        wallet_address=body.wallet_address,
        stake_amount=body.stake_amount,
        endpoint_url=body.endpoint_url,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)

    logger.info("verifier_registered", verifier_id=node.id, wallet=body.wallet_address)
    return node


@router.get("", response_model=VerifierListResponse)
async def list_verifiers(
    active_only: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List registered verifier nodes."""
    base_q = select(VerifierNodeModel)
    count_q = select(func.count(VerifierNodeModel.id))

    if active_only:
        base_q = base_q.where(VerifierNodeModel.is_active.is_(True))
        count_q = count_q.where(VerifierNodeModel.is_active.is_(True))

    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    result = await db.execute(
        base_q.order_by(VerifierNodeModel.reputation_score.desc())
        .offset(offset)
        .limit(limit)
    )
    verifiers = result.scalars().all()

    return VerifierListResponse(
        verifiers=[VerifierNodeResponse.model_validate(v) for v in verifiers],
        total=total,
    )


@router.get("/{verifier_id}", response_model=VerifierNodeResponse)
async def get_verifier(
    verifier_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get details for a specific verifier node."""
    result = await db.execute(
        select(VerifierNodeModel).where(VerifierNodeModel.id == verifier_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(404, f"Verifier not found: {verifier_id}")
    return node


@router.post("/{verifier_id}/stake", response_model=VerifierNodeResponse)
async def update_verifier_stake(
    verifier_id: str,
    body: VerifierStakeUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a verifier's stake amount."""
    result = await db.execute(
        select(VerifierNodeModel).where(VerifierNodeModel.id == verifier_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(404, f"Verifier not found: {verifier_id}")

    node.stake_amount = body.stake_amount
    await db.commit()
    await db.refresh(node)

    logger.info(
        "verifier_stake_updated", verifier_id=verifier_id, stake=body.stake_amount
    )
    return node


# ═══════════════════════════════════════════════════════════════════
# Attestations
# ═══════════════════════════════════════════════════════════════════


@router.post("/attestations", response_model=AttestationResponse, status_code=201)
async def submit_attestation(
    body: AttestationSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit an attestation from a verifier node."""
    # Verify verifier exists and is active
    verifier_result = await db.execute(
        select(VerifierNodeModel).where(VerifierNodeModel.id == body.verifier_id)
    )
    verifier = verifier_result.scalar_one_or_none()
    if not verifier:
        raise HTTPException(404, f"Verifier not found: {body.verifier_id}")
    if not verifier.is_active:
        raise HTTPException(400, f"Verifier is not active: {body.verifier_id}")

    attestation = AttestationModel(
        task_id=body.task_id,
        verifier_id=body.verifier_id,
        bundle_id=body.bundle_id,
        bundle_cid=body.bundle_cid,
        decision=body.decision,
        confidence=body.confidence,
        checks_passed=body.checks_passed,
        checks_total=body.checks_total,
        eip712_signature=body.eip712_signature,
    )
    db.add(attestation)

    # Update verifier stats
    verifier.total_attestations += 1
    if body.decision == "ATTESTED_OK":
        verifier.successful_attestations += 1

    await db.commit()
    await db.refresh(attestation)

    logger.info(
        "attestation_submitted",
        attestation_id=attestation.id,
        task_id=body.task_id,
        verifier_id=body.verifier_id,
        decision=body.decision,
    )
    return attestation


@router.get(
    "/attestations/{attestation_id}",
    response_model=AttestationResponse,
)
async def get_attestation(
    attestation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific attestation by ID."""
    result = await db.execute(
        select(AttestationModel).where(AttestationModel.id == attestation_id)
    )
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(404, f"Attestation not found: {attestation_id}")
    return att


@router.get(
    "/attestations/task/{task_id}",
    response_model=AttestationListResponse,
)
async def list_attestations_for_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all attestations for a given task."""
    result = await db.execute(
        select(AttestationModel)
        .where(AttestationModel.task_id == task_id)
        .order_by(AttestationModel.created_at.desc())
    )
    attestations = result.scalars().all()
    return AttestationListResponse(
        attestations=[AttestationResponse.model_validate(a) for a in attestations],
        task_id=task_id,
        total=len(attestations),
    )


# ═══════════════════════════════════════════════════════════════════
# Challenges
# ═══════════════════════════════════════════════════════════════════


@router.post("/challenges", response_model=ChallengeResponse, status_code=201)
async def open_challenge(
    body: ChallengeOpenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Open a new challenge against a task / evidence bundle."""
    now = datetime.utcnow()
    window_end = now + timedelta(minutes=30)

    challenge = ChallengeModel(
        task_id=body.task_id,
        bundle_id=body.bundle_id,
        raised_by=body.raised_by,
        reason=body.reason,
        status="OPEN",
        window_start=now,
        window_end=window_end,
        quorum_size=body.quorum_size,
    )
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)

    logger.info(
        "challenge_opened",
        challenge_id=challenge.id,
        task_id=body.task_id,
        raised_by=body.raised_by,
    )
    return challenge


@router.get("/challenges/{challenge_id}", response_model=ChallengeResponse)
async def get_challenge(
    challenge_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific challenge by ID."""
    result = await db.execute(
        select(ChallengeModel).where(ChallengeModel.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(404, f"Challenge not found: {challenge_id}")
    return challenge


@router.post("/challenges/{challenge_id}/resolve", response_model=ChallengeResponse)
async def resolve_challenge(
    challenge_id: str,
    body: ChallengeResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resolve an open challenge."""
    result = await db.execute(
        select(ChallengeModel).where(ChallengeModel.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(404, f"Challenge not found: {challenge_id}")
    if challenge.status not in ("OPEN", "ACTIVE"):
        raise HTTPException(400, f"Challenge is not open: {challenge.status}")

    challenge.status = body.status
    challenge.resolution = body.resolution
    challenge.resolved_at = datetime.utcnow()
    await db.commit()
    await db.refresh(challenge)

    logger.info(
        "challenge_resolved",
        challenge_id=challenge_id,
        status=body.status,
    )
    return challenge


# ═══════════════════════════════════════════════════════════════════
# Network Stats
# ═══════════════════════════════════════════════════════════════════


@router.get("/network/stats", response_model=NetworkStatsResponse)
async def get_network_stats(db: AsyncSession = Depends(get_db)):
    """Get aggregate statistics for the verifier network."""
    total_v = await _count(db, VerifierNodeModel)
    active_v = await _count(db, VerifierNodeModel, VerifierNodeModel.is_active.is_(True))
    total_att = await _count(db, AttestationModel)
    total_chall = await _count(db, ChallengeModel)
    open_chall = await _count(
        db, ChallengeModel, ChallengeModel.status.in_(["OPEN", "ACTIVE"])
    )

    avg_rep_result = await db.execute(
        select(func.avg(VerifierNodeModel.reputation_score))
    )
    avg_rep = avg_rep_result.scalar() or 0.0

    return NetworkStatsResponse(
        total_verifiers=total_v,
        active_verifiers=active_v,
        total_attestations=total_att,
        total_challenges=total_chall,
        open_challenges=open_chall,
        average_reputation=round(float(avg_rep), 4),
    )


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


async def _count(
    db: AsyncSession, model, *filters, column=None
) -> int:
    col = column or model.id
    q = select(func.count(col))
    for f in filters:
        q = q.where(f)
    result = await db.execute(q)
    return result.scalar() or 0


def __challenge_duration_seconds() -> float:
    """Default challenge window duration (30 minutes) in seconds."""
    import datetime as _dt
    return _dt.timedelta(minutes=30).total_seconds()
