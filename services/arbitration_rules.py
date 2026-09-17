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
from core.schemas import ArbitrationPoolMemberStatus
from db.models.orm import (
    ArbitrationPoolMemberModel,
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


def stake_coverage_multiple() -> float:
    """抵押对案值的覆盖倍数。

    下限锁死在 1.0：这是「被处理的订单金额必须低于抵押」这条底线本身，
    配置只能把要求**调高**（多留安全垫），不能把仲裁员的抵押压到低于案值。
    """
    try:
        value = float(settings.arbitration_stake_coverage_multiple)
    except (TypeError, ValueError):
        value = 1.0
    return max(1.0, value)


def stake_covers_case(
    stake: float, case_value: float, *, multiple: float | None = None
) -> bool:
    """这个仲裁员的抵押，够不够处理这个金额的争议。

    规则（2026-09-17 收紧）：**质押必须严格大于 案值 × 倍数**。

    * 等号不算覆盖：抵押刚好等于案值时，一次误判就能把抵押打穿；
    * 倍数由 ``ARBITRATION_STAKE_COVERAGE_MULTIPLE`` 控制，平台可以调高留安全垫；
    * 案值为 0（没有托管金额）时，只要求质押 > 0。
    """
    ratio = stake_coverage_multiple() if multiple is None else max(0.0, float(multiple))
    try:
        stake_value = float(stake or 0.0)
    except (TypeError, ValueError):
        return False
    if case_value is None or float(case_value) <= 0:
        return stake_value > 0
    return stake_value > float(case_value) * ratio + EPSILON


async def case_value_of(db: AsyncSession, case_row: object) -> float:
    """案件标的 = 该任务结算里被托管的总额（争议里真正可能被划走的钱）。"""
    task_id = str(getattr(case_row, "task_id", "") or "")
    if not task_id:
        return 0.0
    from db.stores.settlement_store import PostgresSettlementStore

    state = await PostgresSettlementStore(db).get(task_id)
    if state is None:
        return 0.0
    try:
        return max(0.0, float(getattr(state, "escrow_amount", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


async def assert_arbitrator_covers_case(
    db: AsyncSession, *, case_row: object, identity_id: str, what: str
) -> float:
    """仲裁员当前质押必须覆盖案值，否则不许参与这场争议。"""
    member = await db.get(ArbitrationPoolMemberModel, identity_id)
    try:
        stake = float(getattr(member, "stake_amount", 0.0) or 0.0) if member else 0.0
    except (TypeError, ValueError):
        stake = 0.0
    case_value = await case_value_of(db, case_row)
    if not stake_covers_case(stake, case_value):
        raise HTTPException(
            409,
            "arbitrator stake %.6f does not cover the case value %.6f "
            "(stake must exceed case value x %.2f) for %s"
            % (stake, case_value, stake_coverage_multiple(), what),
        )
    return stake


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
    members: Sequence[object],
    *,
    conflicted: set[str],
    exclude_ids: set[str] = frozenset(),
    case_value: float | None = None,
) -> list[object]:
    """只留下：ACTIVE + 质押 > 0 + **抵押能覆盖案值** + 不回避 + 未在庭。"""
    floor = min_stake_amount()
    out = []
    for member in members:
        member_id = str(getattr(member, "arbitrator_identity_id", "") or "")
        if not member_id or member_id in exclude_ids or member_id in conflicted:
            continue
        # 状态在这里再确认一次：SQL 已经筛过 ACTIVE，但一个刚被停权的仲裁员不该
        # 因为「查询和派庭之间差了几毫秒」就坐进庭里。
        if str(getattr(member, "status", "") or "").lower() != ArbitrationPoolMemberStatus.ACTIVE.value:
            continue
        try:
            stake = float(getattr(member, "stake_amount", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if stake <= 0 or stake + EPSILON < floor:
            continue
        # 抵押必须覆盖案值：让抵押 10 的人去裁 100 的争议，等于让他拿 10 去赌 100。
        if case_value is not None and not stake_covers_case(stake, case_value):
            continue
        out.append(member)
    return out
