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
from services import atomic_ledger
from services.chain import allowance_escrow as escrow


async def ceiling_breakdown(db: AsyncSession, *, identity_id: str) -> dict:
    """责任上限的两个来源，拆开给操作台看。

    v1：USDC 真锁进 ``KarmaBilateral`` 合约，``capacity.total_locked_usdc`` 有数。
    v2：非托管的，钱始终在用户自己钱包里，只给了托管合约一份授权额度，所以看的是
    **当前有效的 commit 之和**。

    上限取两者**较大的那个** —— 和操作台顶栏 ``Math.max(locked, committed)`` 同一条规则。
    以前这里写成「台账有数就只认台账」，于是钱包明明承诺了 170、界面却只认 50，
    授权额度无缘无故被卡住。子身份额度加起来永远不能超过这个上限。
    """
    cap = await db.get(CapacityModel, identity_id)
    ledger_locked = float(cap.total_locked_usdc or 0.0) if cap is not None else 0.0
    commits = await escrow.list_commits(db, identity_id)
    committed = round(
        sum(float(c.amount_usdc or 0.0) for c in commits if c.state == escrow.IDLE),
        6,
    )
    return {
        "ledger_locked_usdc": round(ledger_locked, 6),
        "committed_usdc": committed,
        "ceiling_usdc": round(max(ledger_locked, committed), 6),
    }


async def master_ceiling_usdc(db: AsyncSession, *, identity_id: str) -> float:
    """子身份额度分配的上限（见 :func:`ceiling_breakdown`）。"""
    return (await ceiling_breakdown(db, identity_id=identity_id))["ceiling_usdc"]


def _in_use(row: ProfileCapacityModel) -> float:
    return (
        (row.in_progress_credits or 0.0)
        + (row.pending_settlement_credits or 0.0)
        + (row.disputed_credits or 0.0)
    )


def serialize_profile_capacity(row: ProfileCapacityModel) -> dict:
    """公开的序列化口径 —— 操作台与 Runtime Gateway 必须读同一份。"""
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
            await atomic_ledger.ensure_row(
                db,
                ProfileCapacityModel,
                "profile_id",
                profile_id,
                defaults={
                    "owner_identity_id": identity_id,
                    "allocated_credits": 0.0,
                    "available_credits": 0.0,
                    "in_progress_credits": 0.0,
                    "pending_settlement_credits": 0.0,
                    "disputed_credits": 0.0,
                    "released_credits": 0.0,
                    "updated_at": datetime.utcnow(),
                },
            )
            row = await atomic_ledger.reload(db, ProfileCapacityModel, profile_id)
        used = _in_use(row)
        if amount + 1e-9 < used:
            raise HTTPException(
                409,
                f"cannot reduce {profile_id} below in-use credits {used}",
            )
        # 并发安全：额度调整改成「基于快照的增量」，并把快照写进 WHERE。
        # 这样并发发生的 spend/release 不会被这次赋值覆盖掉。
        cur_allocated = float(row.allocated_credits or 0.0)
        cur_available = float(row.available_credits or 0.0)
        guards = [
            (lambda C, _v=cur_allocated: C.allocated_credits == _v),
            (lambda C, _v=cur_available: C.available_credits == _v),
            (lambda C, _v=float(row.in_progress_credits or 0.0): C.in_progress_credits == _v),
            (lambda C, _v=float(row.pending_settlement_credits or 0.0): C.pending_settlement_credits == _v),
            (lambda C, _v=float(row.disputed_credits or 0.0): C.disputed_credits == _v),
        ]
        try:
            await atomic_ledger.apply_delta_or_raise(
                db,
                ProfileCapacityModel,
                "profile_id",
                profile_id,
                {
                    "allocated_credits": amount - cur_allocated,
                    "available_credits": (amount - used) - cur_available,
                },
                guards=guards,
                message=f"profile {profile_id} credits changed concurrently; retry allocation",
            )
        except atomic_ledger.LedgerConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        row = await atomic_ledger.reload(db, ProfileCapacityModel, profile_id)
        out.append(serialize_profile_capacity(row))

    await db.flush()
    return out


async def get_allocations(db: AsyncSession, *, identity_id: str) -> list[dict]:
    result = await db.execute(
        select(ProfileCapacityModel)
        .where(ProfileCapacityModel.owner_identity_id == identity_id)
        .order_by(ProfileCapacityModel.profile_id)
    )
    return [serialize_profile_capacity(r) for r in result.scalars().all()]


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
    # 并发安全：占用额度必须原子，否则并发下单会超出子身份额度。
    try:
        await atomic_ledger.apply_delta_or_raise(
            db,
            ProfileCapacityModel,
            "profile_id",
            profile_id,
            {"available_credits": -amount, "in_progress_credits": amount},
            guards=[(lambda C, _need=amount: C.available_credits + 1e-9 >= _need)],
            message=(
                f"insufficient profile credits: need {amount}, "
                f"available {row.available_credits}"
            ),
        )
    except atomic_ledger.LedgerConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.flush()
    return await atomic_ledger.reload(db, ProfileCapacityModel, profile_id)


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
    # 并发安全：结算回写必须是原子增量，且以「读到的 in_progress」为守卫，
    # 避免并发结算把同一份额度释放两次。
    deltas = {"in_progress_credits": -total, "released_credits": settled}
    if refunded > 0:
        deltas["available_credits"] = refunded
    try:
        await atomic_ledger.apply_delta_or_raise(
            db,
            ProfileCapacityModel,
            "profile_id",
            profile_id,
            deltas,
            guards=[(lambda C, _v=in_progress: C.in_progress_credits == _v)],
            message=f"profile {profile_id} credits changed concurrently; retry release",
        )
    except atomic_ledger.LedgerConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.flush()
    return await atomic_ledger.reload(db, ProfileCapacityModel, profile_id)
