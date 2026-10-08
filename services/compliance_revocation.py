"""
Karma — 合规撤销（把「已认证」降回「驳回」的唯一出口）。

背景（2026-10-08 审计 O4）
---------------------------
企业与个体户认证一旦 ``verified`` 就是终态：正常复核路径（主体的
``assert_can_decide``、KYC 的 ``_TRANSITIONS``）在 ``verified`` 上**没有出边**。这本身是对的
—— 随机一名复核员不该能单独打掉别人的认证，否则「一把 verifier key 打掉竞争对手」
就是可行的 DoS。

但「永远不能撤销」对消费者不负责：事后发现假资料必须有降级出口。所以这里单开一条
**只对 verified 生效**的边 ``verified → rejected``，并给它两条更严的入口：

1. **运维白名单**（``settings.admin_actor_id_set``，brake-only 管理员）：单人直接执行。
   平台自己的合规动作，链路最短，也避免「网络里只有一名复核员时永远撤不动」。
2. **复核员两人**：一人发起（记录理由），**另一人**确认才执行。同一人既发起又确认 → 409。

发起记录落库（``verification_revocation_requests``），带 24h TTL：一天内没人确认就失效，
重新发起即可。撤销是消费者保护动作，必须可追溯（谁、什么时候、因为什么）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import IdentityRoleProfile, VerificationRevocationRequestModel
from services.governance_stake import assert_governor_active
from services.identity_actor import resolve_actor_identity_id

#: 撤销对象种类：主体认证 / 子身份 KYC。
TARGET_ENTITY = "entity_verification"
TARGET_ROLE_PROFILE_KYC = "role_profile_kyc"
TARGET_KINDS = (TARGET_ENTITY, TARGET_ROLE_PROFILE_KYC)

#: 认证终态的唯一一条出边。普通复核路径永远看不到它（它们只走 ENTITY_TRANSITIONS /
#: KYC _TRANSITIONS）—— 撤销只能从这里进来。
REVOCATION_TRANSITIONS: dict[str, set[str]] = {"verified": {"rejected"}}

#: 发起后多久没人确认就失效（重新发起即可，不留永远挂着的半成品）。
PROPOSAL_TTL = timedelta(hours=24)

#: 理由必须写清楚：这条记录要给被撤销方、复核方和消费者看。
MIN_REASON_CHARS = 10
MAX_REASON_CHARS = 2000


def normalize_reason(reason: str | None) -> str:
    text = (reason or "").strip()
    if len(text) < MIN_REASON_CHARS:
        raise HTTPException(
            422,
            "撤销必须写清理由（至少 %d 个字）：这条记录要给被撤销方和消费者看" % MIN_REASON_CHARS,
        )
    return text[:MAX_REASON_CHARS]


def assert_can_revoke(current_status: str | None, *, what: str) -> None:
    """只有 ``verified`` 能走合规撤销；其他状态一律 409。"""
    current = (current_status or "none").strip() or "none"
    if "rejected" not in REVOCATION_TRANSITIONS.get(current, set()):
        raise HTTPException(409, "%s 当前状态是 %s，只有 verified 能走合规撤销" % (what, current))


def is_privileged_revoker(identity_id: str | None) -> bool:
    actor = (identity_id or "").strip()
    return bool(actor) and actor in settings.admin_actor_id_set()


async def require_revoker(
    db: AsyncSession, request: Request, *, owner_identity_id: str, what: str
) -> tuple[str, bool]:
    """谁能发起合规撤销。返回 ``(actor, privileged)``。

    两条路，二选一：

    - **运维白名单**（``ADMIN_ACTOR_IDS``，brake-only 管理员）：``privileged=True``，
      单人即可直接执行 —— 平台自己的合规动作，链路最短；
    - **复核岗**：持 active 的 verifier 类档案、不是被撤销对象本人、且岗在任。``privileged=False``，
      必须两人（一人发起 + 另一人确认）才生效，避免「一把 verifier key 打掉竞争对手认证」。
    """
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to revoke a verification")
    if is_privileged_revoker(actor):
        return actor, True
    if actor == owner_identity_id:
        raise HTTPException(403, "本人不能撤销自己的认证")
    row = (
        await db.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == actor,
                IdentityRoleProfile.class_ == "verifier",
                IdentityRoleProfile.status == "active",
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(403, "只有复核岗或运维白名单能撤销认证")
    await assert_governor_active(db, identity_id=actor, what=what)
    return actor, False


async def _open_proposal(
    db: AsyncSession, *, target_kind: str, target_id: str, now: datetime
) -> VerificationRevocationRequestModel | None:
    row = (
        await db.execute(
            select(VerificationRevocationRequestModel)
            .where(
                VerificationRevocationRequestModel.target_kind == target_kind,
                VerificationRevocationRequestModel.target_id == target_id,
                VerificationRevocationRequestModel.status == "pending",
            )
            .order_by(VerificationRevocationRequestModel.proposed_at.desc())
        )
    ).scalars().first()
    if row is None:
        return None
    if row.proposed_at and (now - row.proposed_at) > PROPOSAL_TTL:
        row.status = "expired"
        await db.flush()
        return None
    return row


async def propose_or_confirm(
    db: AsyncSession,
    *,
    target_kind: str,
    target_id: str,
    actor: str,
    reason: str,
    privileged: bool,
) -> dict[str, Any]:
    """记录撤销申请，或（够条件时）判定本次调用**就是**那次执行。

    返回里 ``executed`` 告诉调用方：现在该不该去改目标行的状态。
    """
    now = datetime.utcnow()
    open_row = await _open_proposal(db, target_kind=target_kind, target_id=target_id, now=now)

    if privileged:
        if open_row is not None:
            open_row.status = "superseded"
        row = VerificationRevocationRequestModel(
            target_kind=target_kind,
            target_id=target_id,
            proposed_by=actor,
            reason=reason,
            status="executed",
            confirmed_by=actor,
            confirmed_at=now,
        )
        db.add(row)
        await db.flush()
        return {
            "executed": True,
            "path": "operator",
            "proposal_id": row.revocation_id,
            "proposed_by": actor,
            "confirmed_by": actor,
            "reason": reason,
            "requires_second_reviewer": False,
        }

    if open_row is None:
        row = VerificationRevocationRequestModel(
            target_kind=target_kind,
            target_id=target_id,
            proposed_by=actor,
            reason=reason,
            status="pending",
        )
        db.add(row)
        await db.flush()
        return {
            "executed": False,
            "path": "verifier",
            "proposal_id": row.revocation_id,
            "proposed_by": actor,
            "confirmed_by": None,
            "reason": reason,
            "requires_second_reviewer": True,
            "expires_at": (row.proposed_at + PROPOSAL_TTL).isoformat() if row.proposed_at else None,
        }

    if open_row.proposed_by == actor:
        raise HTTPException(409, "同一名复核员不能确认自己发起的撤销：请另一名复核员确认")

    open_row.status = "executed"
    open_row.confirmed_by = actor
    open_row.confirmed_at = now
    await db.flush()
    return {
        "executed": True,
        "path": "two_person",
        "proposal_id": open_row.revocation_id,
        "proposed_by": open_row.proposed_by,
        "confirmed_by": actor,
        "reason": open_row.reason,
        "requires_second_reviewer": False,
    }


def proposal_view(row: VerificationRevocationRequestModel | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "proposal_id": row.revocation_id,
        "proposed_by": row.proposed_by,
        "reason": row.reason,
        "proposed_at": row.proposed_at.isoformat() if row.proposed_at else None,
    }


async def open_proposals_by_target(
    db: AsyncSession,
) -> dict[tuple[str, str], VerificationRevocationRequestModel]:
    rows = (
        await db.execute(
            select(VerificationRevocationRequestModel).where(
                VerificationRevocationRequestModel.status == "pending"
            )
        )
    ).scalars().all()
    return {(row.target_kind, row.target_id): row for row in rows}


def apply_entity_revocation(
    row: Any, *, proposed_by: str, confirmed_by: str, reason: str
) -> None:
    """把主体认证从 verified 降回 rejected；理由写进 ``review_note``（对外可问责）。"""
    row.status = "rejected"
    row.reviewer_identity_id = confirmed_by
    row.review_note = (
        "合规撤销（发起 %s / 确认 %s）：%s" % (proposed_by, confirmed_by, reason)
    )[:2000]
    row.verified_at = None
    row.updated_at = datetime.utcnow()


def apply_kyc_revocation(
    profile: Any, *, proposed_by: str, confirmed_by: str, reason: str
) -> None:
    """把子身份 KYC 从 verified 降回 rejected，结论写进载荷（与复核结论同一处）。"""
    payload = dict(profile.kyc_payload or {})
    payload["verification"] = {
        "decision": "rejected",
        "kind": "compliance_revocation",
        "reason": reason,
        "proposed_by": proposed_by,
        "verified_by": confirmed_by,
        "verified_at": datetime.utcnow().isoformat(),
    }
    profile.kyc_status = "rejected"
    profile.kyc_payload = payload
    profile.updated_at = datetime.utcnow()
