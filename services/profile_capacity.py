"""Per-profile quota allocation under the master identity capacity.

Master ``capacity`` (keyed by identity_id) is the total locked USDC anchor; each
role profile gets its own ``profile_capacity`` row (allocation + usage). This
enables 个人/商家/企业 各自在授权额度内行事、总账对齐、可随时调整。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import CapacityModel, IdentityRoleProfile, ProfileCapacityModel
from services.chain import allowance_escrow as escrow


async def master_ceiling_usdc(db: AsyncSession, *, identity_id: str) -> float:
    """我到底压了多少钱在这张身份卡上（子身份额度分配的上限）。

    v1 是把 USDC 真锁进 ``KarmaBilateral`` 合约，``capacity`` 台账因此有
    ``total_locked_usdc``。v2 是非托管的：钱始终在用户自己钱包里，只给了托管
    合约一份授权额度，所以上限就是**当前有效的 commit 之和**。两条路的共同点是
    「钱包真实押上的责任」，子身份额度加起来永远不能超过它。
    """
    cap = await db.get(CapacityModel, identity_id)
    locked = float(cap.total_locked_usdc or 0.0) if cap is not None else 0.0
    if locked > 0.0:
        return locked
    commits = await escrow.list_commits(db, identity_id)
    return round(
        sum(float(c.amount_usdc or 0.0) for c in commits if c.state == escrow.IDLE),
        6,
    )


def _in_use(row: ProfileCapacityModel) -> float:
    return (
        (row.in_progress_credits or 0.0)
        + (row.pending_settlement_credits or 0.0)
        + (row.disputed_credits or 0.0)
    )


def _serialize(row: ProfileCapacityModel) -> dict:
    return {
        "profile_id": row.profile_id,
        "owner_identity_id": row.owner_identity_id,
        "allocated_credits": row.allocated_credits,
        "available_credits": row.available_credits,
        "in_progress_credits": row.in_progress_credits,
        "pending_settlement_credits": row.pending_settlement_credits,
        "disputed_credits": row.disputed_credits,
        "released_credits": row.released_credits,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def allocate(
    db: AsyncSession,
    *,
    identity_id: str,
    allocations: dict[str, float],
) -> list[dict]:
    """Set per-profile allocations for an identity. Total must not exceed master locked."""
    total = 0.0
    for profile_id, amount in allocations.items():
        if amount < 0:
            raise HTTPException(400, f"negative allocation for {profile_id}")
        total += amount

    ceiling = await master_ceiling_usdc(db, identity_id=identity_id)
    if ceiling <= 0.0:
        raise HTTPException(
            409,
            "no locked USDC — lock USDC first (v1 lock, or a v2 wallet commitment)",
        )
    if total > ceiling + 1e-9:
        raise HTTPException(
            409,
            f"total allocation {total} exceeds locked {ceiling}",
        )

    out: list[dict] = []
    for profile_id, amount in allocations.items():
        profile = await db.get(IdentityRoleProfile, profile_id)
        if not profile or profile.owner_identity_id != identity_id:
            raise HTTPException(404, f"profile {profile_id} not found for this identity")

        row = await db.get(ProfileCapacityModel, profile_id)
        if row is None:
            row = ProfileCapacityModel(
                profile_id=profile_id,
                owner_identity_id=identity_id,
                allocated_credits=amount,
                available_credits=amount,
            )
            db.add(row)
        else:
            used = _in_use(row)
            if amount + 1e-9 < used:
                raise HTTPException(
                    409,
                    f"cannot reduce {profile_id} below in-use credits {used}",
                )
            row.allocated_credits = amount
            row.available_credits = amount - used
            row.updated_at = datetime.utcnow()
        out.append(_serialize(row))

    await db.flush()
    return out


async def get_allocations(db: AsyncSession, *, identity_id: str) -> list[dict]:
    result = await db.execute(
        select(ProfileCapacityModel)
        .where(ProfileCapacityModel.owner_identity_id == identity_id)
        .order_by(ProfileCapacityModel.profile_id)
    )
    return [_serialize(r) for r in result.scalars().all()]


async def get_profile_capacity(db: AsyncSession, *, profile_id: str) -> ProfileCapacityModel | None:
    return await db.get(ProfileCapacityModel, profile_id)


async def spend_profile_credits(
    db: AsyncSession,
    *,
    profile_id: str,
    amount: float,
) -> ProfileCapacityModel:
    """Reserve ``amount`` from a profile's available credits (in_progress)."""
    row = await get_profile_capacity(db, profile_id=profile_id)
    if row is None:
        raise HTTPException(409, f"profile {profile_id} has no allocation")
    if amount > (row.available_credits or 0.0) + 1e-9:
        raise HTTPException(
            409,
            f"insufficient profile credits: need {amount}, available {row.available_credits}",
        )
    row.available_credits -= amount
    row.in_progress_credits += amount
    row.updated_at = datetime.utcnow()
    await db.flush()
    return row


async def release_profile_credits(
    db: AsyncSession,
    *,
    profile_id: str,
    settled_amount: float,
    refunded_amount: float = 0.0,
) -> ProfileCapacityModel | None:
    """Settle/release a profile's in-progress credits (最后一环：结算回写额度).

    On finalize: ``in_progress`` → ``released`` (settled portion) and, for any
    refunded portion, back to ``available``. No-op if the profile has no row.
    """
    row = await get_profile_capacity(db, profile_id=profile_id)
    if row is None:
        return None
    settled = max(0.0, float(settled_amount))
    refunded = max(0.0, float(refunded_amount))
    total = settled + refunded
    in_progress = row.in_progress_credits or 0.0
    if total > in_progress + 1e-9:
        # never release more than was reserved; clamp defensively
        total = in_progress
        if total <= 0:
            return row
        scale = total / (settled + refunded) if (settled + refunded) > 0 else 0.0
        settled = round(settled * scale, 8)
        refunded = round(refunded * scale, 8)
    row.in_progress_credits -= total
    row.released_credits = (row.released_credits or 0.0) + settled
    if refunded > 0:
        row.available_credits = (row.available_credits or 0.0) + refunded
    row.updated_at = datetime.utcnow()
    await db.flush()
    return row
