"""仲裁规则闸门 —— 入池资格、回避、人数窗口、调用者绑定。

背景（2026-09-17 全量复核，五处实测漏洞）：

1. ``POST /v1/arbitration/pool/join``：任何身份都能把**任意别人**加进仲裁池，
   ``stake_amount`` 还能填 0 —— 等于谁都能凭空造仲裁员。
2. ``POST /v1/arbitration/cases/{id}/assign-auto``：按入池先后取人，不校验质押、
   不校验资格，**也不回避当事人** —— 买卖双方可以自己给自己派仲裁员。
3. ``POST /v1/arbitration/cases/{id}/vote``：只查「这个 id 被指派过」，
   不查「你是不是这个 id」—— 任何人可冒名代投。
4. ``POST /v1/arbitration/cases``：``required_arbitrators`` 由调用方自填（可以填 1），
   一个人就能判掉一场争议。
5. ``POST /v1/arbitration/cases/{id}/execute``：写回结算但不写流转审计。

另外 ``ARBITRATOR_ACTOR_IDS`` 这条生产门禁此前只有小程序端在读，
仲裁路由完全不看 —— 属于「假安全」。现在这里把它接上。
"""
from __future__ import annotations

from typing import Iterable, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import (
    CapacityModel,
    IdentityRoleProfile,
    SubIdentityModel,
)
from services.actor_guards import (
    arbitrator_actor_ids,
    caller_is_privileged,
)
from services.identity_actor import resolve_actor_identity_id

EPSILON = 1e-9


# ---------------------------------------------------------------------------
# 策略读取
# ---------------------------------------------------------------------------

def actor_binding_required() -> bool:
    return bool(settings.arbitration_require_actor_binding)


def pool_open_join() -> bool:
    return bool(settings.arbitration_pool_open_join)


def panel_bounds() -> tuple[int, int]:
    lo = max(1, int(settings.arbitration_min_arbitrators or 1))
    hi = max(lo, int(settings.arbitration_max_arbitrators or lo))
    return lo, hi


def min_stake_amount() -> float:
    try:
        return max(0.0, float(settings.arbitration_min_stake_amount or 0.0))
    except (TypeError, ValueError):
        return 0.0


def backed_stake_required() -> bool:
    return bool(settings.arbitration_require_backed_stake)


# ---------------------------------------------------------------------------
# 调用者绑定
# ---------------------------------------------------------------------------

async def require_identity_binding(
    db: AsyncSession,
    request: Request,
    identity_id: str,
    *,
    what: str,
) -> None:
    """调用者必须就是这个身份，或者是有白名单的运维岗。

    这条规则挡住的是「我替别人说他要入池 / 我替别人投票」。
    """
    if not actor_binding_required():
        return
    actor_identity = await resolve_actor_identity_id(db, request)
    if actor_identity and actor_identity == identity_id:
        return
    if caller_is_privileged(request):
        return
    raise HTTPException(
        403,
        "authenticated actor must be %s for this operation (%s)" % (identity_id, what),
    )


def caller_is_operator(request: Request) -> bool:
    """平台运维岗（管理员 ∪ 仲裁员白名单）—— 实现见 services.actor_guards。"""
    return caller_is_privileged(request)


def require_pool_join_allowed(request: Request) -> None:
    """入池资格：开放申请，还是必须落在仲裁员白名单里。"""
    if pool_open_join():
        return
    from services.actor_guards import caller_actor_id

    actor = caller_actor_id(request)
    if not actor or actor.strip() not in arbitrator_actor_ids():
        raise HTTPException(
            403,
            "joining the arbitration pool requires an actor id listed in "
            "ARBITRATOR_ACTOR_IDS (set ARBITRATION_POOL_OPEN_JOIN=true to open applications)",
        )


# ---------------------------------------------------------------------------
# 质押：必须有真实锁仓背书
# ---------------------------------------------------------------------------

async def locked_capacity_of(db: AsyncSession, identity_id: str) -> float:
    row = await db.get(CapacityModel, identity_id)
    if row is None:
        return 0.0
    return float(row.total_locked_usdc or 0.0)


async def assert_stake_acceptable(
    db: AsyncSession, *, identity_id: str, stake_amount: float
) -> None:
    floor = min_stake_amount()
    if stake_amount is None or stake_amount <= 0:
        raise HTTPException(422, "arbitrator stake must be greater than 0")
    if stake_amount + EPSILON < floor:
        raise HTTPException(
            422,
            "arbitrator stake %.6f is below the platform minimum %.6f" % (stake_amount, floor),
        )
    if not backed_stake_required():
        return
    locked = await locked_capacity_of(db, identity_id)
    if locked + EPSILON < stake_amount:
        raise HTTPException(
            409,
            "arbitrator stake %.6f is not backed by locked USDC: %s has only %.6f locked"
            % (stake_amount, identity_id, locked),
        )


# ---------------------------------------------------------------------------
# 回避：当事人及其关联身份不得坐进这个仲裁庭
# ---------------------------------------------------------------------------

async def conflicted_identity_ids(
    db: AsyncSession,
    *,
    parties: Iterable[str],
    extra: Iterable[str] = (),
) -> set[str]:
    """把「当事人 + 他们的子身份 / 角色档案 / 父身份」展开成一张回避名单。"""
    seeds: set[str] = set()
    for value in list(parties) + list(extra):
        if value and str(value).strip():
            seeds.add(str(value).strip())
    if not seeds:
        return set()

    conflicted = set(seeds)

    children = await db.execute(
        select(SubIdentityModel.sub_identity_id, SubIdentityModel.parent_identity_id).where(
            SubIdentityModel.parent_identity_id.in_(sorted(seeds))
        )
    )
    for sub_id, parent_id in children.all():
        conflicted.add(sub_id)
        if parent_id:
            conflicted.add(parent_id)

    # 如果当事人本身就是某个子身份，父身份同样要回避。
    parents = await db.execute(
        select(SubIdentityModel.parent_identity_id).where(
            SubIdentityModel.sub_identity_id.in_(sorted(seeds))
        )
    )
    for (parent_id,) in parents.all():
        if parent_id:
            conflicted.add(parent_id)

    # 当事人名下的角色档案（生活/工作/企业助理）也一并回避。
    profiles = await db.execute(
        select(IdentityRoleProfile.profile_id, IdentityRoleProfile.owner_identity_id).where(
            IdentityRoleProfile.owner_identity_id.in_(sorted(seeds))
        )
    )
    for profile_id, owner_id in profiles.all():
        conflicted.add(profile_id)
        if owner_id:
            conflicted.add(owner_id)

    # 反过来：如果当事人是某个档案 id，其所有者也要回避。
    owners = await db.execute(
        select(IdentityRoleProfile.owner_identity_id).where(
            IdentityRoleProfile.profile_id.in_(sorted(seeds))
        )
    )
    for (owner_id,) in owners.all():
        if owner_id:
            conflicted.add(owner_id)

    return conflicted


def assert_panel_size_allowed(required: int) -> int:
    lo, hi = panel_bounds()
    if required is None:
        raise HTTPException(422, "required_arbitrators is required")
    if required < lo or required > hi:
        raise HTTPException(
            422,
            "required_arbitrators must be between %d and %d (platform policy)" % (lo, hi),
        )
    return int(required)


def filter_qualified_members(
    members: Sequence[object], *, conflicted: set[str], exclude_ids: set[str] = frozenset()
) -> list[object]:
    """只留下：ACTIVE + 质押 > 0 + 不回避 + 未在庭。"""
    floor = min_stake_amount()
    out = []
    for member in members:
        member_id = str(getattr(member, "arbitrator_identity_id", "") or "")
        if not member_id or member_id in exclude_ids or member_id in conflicted:
            continue
        try:
            stake = float(getattr(member, "stake_amount", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if stake <= 0 or stake + EPSILON < floor:
            continue
        out.append(member)
    return out
