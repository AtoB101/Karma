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

from config.settings import settings
from db.session import get_db
from decentralized_verifier.models import Attestation as AttestationModel
from decentralized_verifier.models import Challenge as ChallengeModel
from decentralized_verifier.models import BondSlash as BondSlashModel
from decentralized_verifier.models import VerifierNode as VerifierNodeModel
from decentralized_verifier.schemas import (
    AttestationListResponse,
    AttestationResponse,
    AttestationSubmitRequest,
    BondSlashListResponse,
    BondSlashResponse,
    ChallengeOpenRequest,
    ChallengeResolveRequest,
    ChallengeResponse,
    NetworkStatsResponse,
    NodeSignMessageRequest,
    NodeSignMessageResponse,
    VerifierListResponse,
    VerifierNodeResponse,
    VerifierRegisterRequest,
    VerifierStakeUpdateRequest,
    VerifierUnstakeRequest,
)
from services import bond_slash, verifier_bond, verifier_wallet
from services.actor_guards import require_arbitration_operator

logger = structlog.get_logger(__name__)
router = APIRouter()


def _enforce_node_signature(
    *,
    message: str,
    wallet_address: str | None,
    signature: str | None,
    nonce: str | None,
    endpoint: str,
) -> None:
    """写接口的签名闸门（开关默认关；生产强制打开，见 config/settings.py）。"""
    verifier_wallet.enforce_node_signature(
        enabled=settings.verifier_require_node_signature,
        message=message,
        wallet_address=wallet_address or "",
        signature=signature,
        nonce=nonce,
        endpoint=endpoint,
    )


@router.post("/sign-message", response_model=NodeSignMessageResponse)
async def node_sign_message(body: NodeSignMessageRequest):
    """按动作回一段**待签文字**（节点自有 key 的签名校验用）。

    格式只在 services/verifier_wallet.py 里定义一份：操作台和节点程序都不自己拼
    消息，免得两边格式漂了、签名永远验不过。回的文字不含任何秘密 —— 它就是调用方
    递进来的那几个字段。
    """
    payload = dict(body.payload or {})
    return NodeSignMessageResponse(
        kind=body.kind,
        message=verifier_wallet.build_message(body.kind, payload),
        nonce=str(payload.get("signature_nonce") or ""),
    )


# ═══════════════════════════════════════════════════════════════════
# Verifier Nodes
# ═══════════════════════════════════════════════════════════════════


@router.post("/register", response_model=VerifierNodeResponse, status_code=201)
async def register_verifier(
    body: VerifierRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new verifier node in the network."""
    _enforce_node_signature(
        message=verifier_wallet.build_node_register_message(
            wallet_address=body.wallet_address,
            stake_amount=body.stake_amount,
            endpoint_url=body.endpoint_url,
            nonce=body.signature_nonce,
        ),
        wallet_address=body.wallet_address,
        signature=body.signature,
        nonce=body.signature_nonce,
        endpoint="verifiers/register",
    )
    # Check for duplicate wallet
    existing = await db.execute(
        select(VerifierNodeModel).where(
            VerifierNodeModel.wallet_address == body.wallet_address
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "A verifier with this wallet address already exists")

    # ── G12 入场闸门：声明了主人身份就走金库档，押金必须真锁仓背书 ──────────
    owner_identity_id = (body.owner_identity_id or "").strip() or None
    if verifier_bond.require_owner_identity() and not owner_identity_id:
        raise HTTPException(
            422,
            "VERIFIER_REQUIRE_OWNER_IDENTITY is on: owner_identity_id is required to register a node",
        )
    if owner_identity_id:
        await verifier_bond.assert_owner_wallet_matches(
            db, identity_id=owner_identity_id, wallet_address=body.wallet_address
        )
        await verifier_bond.assert_bond_acceptable(
            db, identity_id=owner_identity_id, stake_amount=body.stake_amount
        )

    node = VerifierNodeModel(
        wallet_address=body.wallet_address,
        stake_amount=body.stake_amount,
        endpoint_url=body.endpoint_url,
        owner_identity_id=owner_identity_id,
        bond_floor=verifier_bond.min_bond_amount() if owner_identity_id else 0.0,
        bond_state="active" if owner_identity_id else "appointed",
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)

    logger.info(
        "verifier_registered",
        verifier_id=node.id,
        wallet=body.wallet_address,
        owner_identity_id=owner_identity_id,
        bond_state=node.bond_state,
    )
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


@router.get("/slashes", response_model=BondSlashListResponse)
async def list_bond_slashes(
    subject_kind: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """罚没台账（G12）：谁被罚了、罚了多少、80/20 怎么分、出账到哪一步。

    ``status`` 停在 ``pending`` 表示**账已记、节点已停，但链上还没出账**
    （金库未部署 / 治理账户还没签）—— 这里如实呈现，不把 pending 写成 settled。
    """
    rows = await bond_slash.list_slashes(
        db, subject_kind=subject_kind, subject_id=subject_id, status=status, limit=limit
    )
    return BondSlashListResponse(
        slashes=[BondSlashResponse.model_validate(row) for row in rows],
        total=len(rows),
        pool_total=await bond_slash.pool_total(db),
        vault_configured=verifier_bond.vault_configured(),
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

    _enforce_node_signature(
        message=verifier_wallet.build_node_stake_message(
            verifier_id=verifier_id,
            wallet_address=node.wallet_address,
            stake_amount=body.stake_amount,
            nonce=body.signature_nonce,
        ),
        wallet_address=node.wallet_address,
        signature=body.signature,
        nonce=body.signature_nonce,
        endpoint="verifiers/stake",
    )

    # ── G12：金库档加押 / 减押都要过闸门；加押同时撤销进行中的退出 ──────────
    if node.owner_identity_id:
        await verifier_bond.assert_bond_acceptable(
            db, identity_id=node.owner_identity_id, stake_amount=body.stake_amount
        )
        if node.unbond_requested_at is not None:
            node.unbond_requested_at = None
            node.unbond_amount = 0.0

    node.stake_amount = body.stake_amount
    await verifier_bond.refresh_node_bond_state(db, node=node)
    await db.commit()
    await db.refresh(node)

    logger.info(
        "verifier_stake_updated",
        verifier_id=verifier_id,
        stake=body.stake_amount,
        bond_state=node.bond_state,
    )
    return node


@router.post("/{verifier_id}/unstake", response_model=VerifierNodeResponse)
async def request_verifier_unstake(
    verifier_id: str,
    body: VerifierUnstakeRequest,
    db: AsyncSession = Depends(get_db),
):
    """发起退出：冻结提取额度、开始冷却计时（G12 退出闭环的第一步）。

    冷却期内**保证金仍可被罚没** —— 这正是冷却期的意义：堵住「被挑战了先跑」。
    冷却期满后用 ``POST /{id}/unstake/finalize`` 放款；期间随时可用加押取消退出。
    """
    node = await _load_node_or_404(db, verifier_id)

    _enforce_node_signature(
        message=verifier_wallet.build_node_unstake_message(
            verifier_id=verifier_id,
            wallet_address=node.wallet_address,
            amount=body.amount,
            nonce=body.signature_nonce,
        ),
        wallet_address=node.wallet_address,
        signature=body.signature,
        nonce=body.signature_nonce,
        endpoint="verifiers/unstake",
    )

    bond = float(node.stake_amount or 0.0)
    amount = float(body.amount or 0.0) or bond
    if amount <= 0:
        raise HTTPException(409, "this node has nothing to unstake")
    if amount - 1e-9 > bond:
        raise HTTPException(422, "unstake amount exceeds the bonded stake")

    node.unbond_amount = round(amount, 8)
    node.unbond_requested_at = datetime.utcnow()
    await verifier_bond.refresh_node_bond_state(db, node=node)
    await db.commit()
    await db.refresh(node)

    logger.info(
        "verifier_unstake_requested",
        verifier_id=verifier_id,
        amount=node.unbond_amount,
        cooldown_hours=int(verifier_bond.unbond_cooldown().total_seconds() // 3600),
    )
    return node


@router.post("/{verifier_id}/unstake/finalize", response_model=VerifierNodeResponse)
async def finalize_verifier_unstake(
    verifier_id: str,
    body: VerifierUnstakeRequest,
    db: AsyncSession = Depends(get_db),
):
    """冷却期满后放款并停用。冷却期没走完一律 409 —— 不给「抢跑」留口子。

    放款金额按**当前剩余保证金**取，被罚没过就少给 —— 台账与链上金库口径一致
    （``KarmaVerifierBond.withdrawUnstake`` 同样按剩余额度放款）。
    """
    node = await _load_node_or_404(db, verifier_id)

    _enforce_node_signature(
        message=verifier_wallet.build_node_unstake_message(
            verifier_id=verifier_id,
            wallet_address=node.wallet_address,
            amount=body.amount,
            nonce=body.signature_nonce,
        ),
        wallet_address=node.wallet_address,
        signature=body.signature,
        nonce=body.signature_nonce,
        endpoint="verifiers/unstake",
    )

    if node.unbond_requested_at is None:
        raise HTTPException(409, "this node has not requested an unstake")
    ready_at = node.unbond_requested_at + verifier_bond.unbond_cooldown()
    now = datetime.utcnow()
    if now < ready_at:
        raise HTTPException(409, f"unstake cooldown is still running until {ready_at.isoformat()}Z")

    released = min(float(node.unbond_amount or 0.0), float(node.stake_amount or 0.0))
    node.stake_amount = round(float(node.stake_amount or 0.0) - released, 8)
    node.unbond_amount = 0.0
    node.unbond_requested_at = None
    floor = verifier_bond.min_bond_amount()
    if node.bond_state == "appointed" and float(node.stake_amount or 0.0) <= 1e-9:
        node.is_active = False
    elif float(node.stake_amount or 0.0) <= 1e-9 or float(node.stake_amount or 0.0) + 1e-9 < floor:
        node.is_active = False
        node.bond_state = "released"
    await verifier_bond.refresh_node_bond_state(db, node=node)
    await db.commit()
    await db.refresh(node)

    logger.info(
        "verifier_unstake_finalized", verifier_id=verifier_id, released=released,
        remaining=node.stake_amount,
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

    # ── P2：出证前现算一次「在任」——押金被划走（含罚没）当场 403 ──────────
    await verifier_bond.assert_node_bond_ok(db, node=verifier, what="attesting")

    _enforce_node_signature(
        message=verifier_wallet.build_node_attestation_message(
            verifier_id=body.verifier_id,
            wallet_address=verifier.wallet_address,
            task_id=body.task_id,
            decision=body.decision,
            bundle_id=body.bundle_id,
            bundle_cid=body.bundle_cid,
            checks_passed=body.checks_passed,
            checks_total=body.checks_total,
            nonce=body.signature_nonce,
        ),
        wallet_address=verifier.wallet_address,
        signature=body.signature,
        nonce=body.signature_nonce,
        endpoint="verifiers/attestations",
    )

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
    _enforce_node_signature(
        message=verifier_wallet.build_node_challenge_message(
            wallet_address=body.wallet_address,
            task_id=body.task_id,
            bundle_id=body.bundle_id,
            reason=body.reason,
            quorum_size=body.quorum_size,
            nonce=body.signature_nonce,
        ),
        wallet_address=body.wallet_address,
        signature=body.signature,
        nonce=body.signature_nonce,
        endpoint="verifiers/challenges",
    )
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
    actor: str = Depends(require_arbitration_operator),
    db: AsyncSession = Depends(get_db),
):
    """裁决一场挑战 —— **只认仲裁员 / 管理员白名单**（``ARBITRATOR_ACTOR_IDS`` ∪ ``ADMIN_ACTOR_IDS``）。

    此前这个接口谁都能调，``status`` / ``resolution`` 还是自由文本：不改节点状态、
    不动钱、不扣分，等于「挑战」没有后果。现在 ``UPHELD``（挑战成立）会走
    ``_apply_upheld_slash``：为该 task 出过证的节点当场停用 + 记罚没台账
    （80% 给受害方 / 20% 进罚没池，幂等）+ 扣声誉。
    """
    result = await db.execute(
        select(ChallengeModel).where(ChallengeModel.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(404, f"Challenge not found: {challenge_id}")
    if challenge.status not in ("OPEN", "ACTIVE"):
        raise HTTPException(400, f"Challenge is not open: {challenge.status}")

    _enforce_node_signature(
        message=verifier_wallet.build_node_challenge_resolve_message(
            wallet_address=body.wallet_address,
            challenge_id=challenge_id,
            status=body.status,
            resolution=body.resolution,
            nonce=body.signature_nonce,
        ),
        wallet_address=body.wallet_address,
        signature=body.signature,
        nonce=body.signature_nonce,
        endpoint="verifiers/challenges/resolve",
    )

    slashed: list[str] = []
    if body.status == "UPHELD":
        slashed = await _apply_upheld_slash(db, challenge=challenge, body=body, actor=actor)

    challenge.status = body.status
    challenge.resolution = body.resolution
    challenge.resolved_at = datetime.utcnow()
    await db.commit()
    await db.refresh(challenge)

    logger.info(
        "challenge_resolved",
        challenge_id=challenge_id,
        status=body.status,
        actor=actor,
        bond_slashes=len(slashed),
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


async def _load_node_or_404(db: AsyncSession, verifier_id: str) -> VerifierNodeModel:
    result = await db.execute(
        select(VerifierNodeModel).where(VerifierNodeModel.id == verifier_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(404, f"Verifier not found: {verifier_id}")
    return node


async def _apply_upheld_slash(
    db: AsyncSession,
    *,
    challenge: ChallengeModel,
    body: ChallengeResolveRequest,
    actor: str,
) -> list[str]:
    """挑战成立 → 判负后果：停用 + 记台账 + 扣声誉（幂等，重复裁决不重复扣）。

    * **台账**当场写，按（主体, 来源=challenge:id）唯一（见 services/bond_slash.py）；
    * **钱**的出账是另一件事：金库没部署就停在 ``pending``，绝不谎报已出账；
    * **停用**是当场生效的 —— 不存在「还没出账就先跑掉」的窗口：保证金在链上金库里锁着。
    """
    from db.models.orm import TaskContractModel
    from services.identity_wallet_binding import get_bound_wallet

    attestations = (
        await db.execute(
            select(AttestationModel).where(AttestationModel.task_id == challenge.task_id)
        )
    ).scalars().all()
    verifier_ids = sorted({a.verifier_id for a in attestations if a.verifier_id})

    victim_wallet = (body.victim_wallet_address or "").strip() or None
    victim_identity = (body.victim_identity_id or "").strip() or None
    if not victim_wallet:
        # 尽力从任务合同里认出受害方（买家身份）；认不出就让 80% 也进池 —— 不做无根据的指认。
        contract = await db.get(TaskContractModel, challenge.task_id)
        if contract is not None and contract.client_agent_id:
            victim_identity = victim_identity or contract.client_agent_id
            victim_wallet = await get_bound_wallet(db, victim_identity)

    floor = verifier_bond.min_bond_amount()
    slash_ids: list[str] = []
    for verifier_id in verifier_ids:
        node = await db.get(VerifierNodeModel, verifier_id)
        if node is None:
            continue
        bond = max(0.0, float(node.stake_amount or 0.0))
        if bond <= 0:
            continue
        amount = float(body.slash_amount) if body.slash_amount is not None else bond
        amount = min(amount, bond)
        if amount <= 0:
            continue

        row, created = await bond_slash.record_slash(
            db,
            subject_kind=bond_slash.SUBJECT_VERIFIER_NODE,
            subject_id=node.id,
            wallet_address=node.wallet_address,
            victim_wallet_address=victim_wallet,
            victim_identity_id=victim_identity,
            source_kind=bond_slash.SOURCE_CHALLENGE,
            source_id=challenge.id,
            amount=amount,
            reason=body.resolution,
        )
        slash_ids.append(row.id)
        if not created:
            continue

        node.stake_amount = round(bond - amount, 8)
        node.slash_unsettled = round(float(node.slash_unsettled or 0.0) + amount, 8)
        if node.stake_amount <= 1e-9 or node.stake_amount + 1e-9 < floor:
            node.is_active = False
            node.bond_state = "released"
        node.reputation_score = round(
            max(0.0, float(node.reputation_score or 0.0) - 25.0), 4
        )
        node.updated_at = datetime.utcnow()

    logger.info(
        "challenge_upheld",
        challenge_id=challenge.id,
        task_id=challenge.task_id,
        actor=actor,
        slashed_verifiers=len(slash_ids),
        victim_wallet=victim_wallet,
    )
    return slash_ids


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
