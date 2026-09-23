"""治理岗（verifier / arbitrator）的「质押即开通」闸门。

背景（2026-09-23）
------------------
``verifier`` / ``arbitrator`` 是**治理角色**：verifier 能复核别人的主体认证、
开发者实名、子身份 KYC；arbitrator 能裁争议。此前这两个岗只有一条入口 ——
``GOVERNANCE_VERIFIER_IDS`` 里由运维点名。也就是说「谁是复核员」由平台说了算。

这一层补上第二条入口，以及更重要的**在任判定**：

- **开通**：``GOVERNANCE_OPEN_JOIN=true`` 之后，任何身份都能凭质押开治理岗 ——
  但质押必须是**已经锁仓的 USDC**（``capacity.total_locked_usdc``）；低于下限、
  或者锁仓不够，一律拒。规矩与仲裁入池一致，见 ``services/arbitration_rules.py``。
- **在任**：岗不是「开一次管一辈子」。每次动治理权限（复核、开复核台）都重新算一遍
  质押状态 —— 锁仓被划走（含罚没）之后这个岗立刻失效，不需要再维护一张状态表。
  这是「质押即开通」能不能成立的另一半：**只有出口也是自动的，押金才真的在担保。**
- **三档，别混着看**：
  1. 白名单（``GOVERNANCE_VERIFIER_IDS``）—— 跟名单，不跟押金；
  2. 运维直接建档（``stake_amount == 0``，等价于第 1 档）—— 跟名单，不跟押金；
  3. 质押开通（``stake_amount > 0``）—— **跟押金：押金在则岗在，押金走则岗停**。
  第 2 档在 API 上开不出来（没质押、没白名单就是 403），所以它不是绕开质押的后门。

一句话：**治理权限跟着押金走 —— 押金在则岗在，押金走则岗停。**
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import CapacityModel, IdentityRoleProfile

EPSILON = 1e-9

#: 治理角色。verifier 复核认证，arbitrator 裁争议 —— 两个岗都要押金在任。
GOVERNANCE_CLASSES = ("verifier", "arbitrator")


# ---------------------------------------------------------------------------
# 策略读取
# ---------------------------------------------------------------------------

def open_join() -> bool:
    """是否允许「质押即开通」（默认关闭 = 只有运维白名单能开）。"""
    return bool(settings.governance_open_join)


def min_stake_amount() -> float:
    return max(0.0, float(settings.governance_min_stake_amount or 0.0))


def backed_stake_required() -> bool:
    """质押是否必须由已锁仓 USDC 背书。生产环境必须为真（见 config/settings.py 校验）。"""
    return bool(settings.governance_require_backed_stake)


def whitelisted(identity_id: str) -> bool:
    """运维白名单：平台自己承担责任的治理岗。"""
    return (identity_id or "").strip() in settings.governance_verifier_id_set()


# ---------------------------------------------------------------------------
# 质押状态
# ---------------------------------------------------------------------------

async def locked_capacity_of(db: AsyncSession, identity_id: str) -> float:
    """这个身份现在锁着多少 USDC。与仲裁入池看的是同一本账。"""
    row = await db.get(CapacityModel, identity_id)
    if row is None:
        return 0.0
    return float(row.total_locked_usdc or 0.0)


async def stake_state(
    db: AsyncSession, *, identity_id: str, stake_amount: float | None
) -> dict[str, Any]:
    """算一遍这个岗位现在算不算「在任」。

    ``code`` 只有四种：``active`` / ``no_stake`` / ``below_min`` / ``unbacked``。
    故意不做缓存：押金是活的，缓存出来的「在任」等于一张可以过期的通行证。
    """
    floor = min_stake_amount()
    stake = float(stake_amount or 0.0)
    locked = await locked_capacity_of(db, identity_id)
    backed = locked + EPSILON >= stake
    if stake <= 0:
        code = "no_stake"
    elif stake + EPSILON < floor:
        code = "below_min"
    elif backed_stake_required() and not backed:
        code = "unbacked"
    else:
        code = "active"
    return {
        "identity_id": identity_id,
        "code": code,
        "ok": code == "active",
        "stake_amount": stake,
        "locked_usdc": locked,
        "floor": floor,
        "backed": backed,
        "open_join": open_join(),
    }


def describe(state: dict[str, Any]) -> str:
    """把「为什么不在任」说成人话 —— 用户得知道差多少、去哪补。"""
    code = state.get("code")
    if code == "no_stake":
        return "这个治理岗没有质押：请先锁仓 USDC 并带上质押金额重新开通"
    if code == "below_min":
        return "质押 %.6f USDC 低于平台下限 %.6f" % (state["stake_amount"], state["floor"])
    if code == "unbacked":
        return (
            "质押 %.6f USDC 没有锁仓背书：%s 现在只锁着 %.6f USDC，补足锁仓或下调质押后再试"
            % (state["stake_amount"], state["identity_id"], state["locked_usdc"])
        )
    return "治理岗在任"


async def assert_stake_acceptable(
    db: AsyncSession, *, identity_id: str, stake_amount: float | None
) -> dict[str, Any]:
    """开通治理岗时用的闸门：不合格直接拒，并把原因写清楚。"""
    state = await stake_state(db, identity_id=identity_id, stake_amount=stake_amount)
    if state["ok"]:
        return state
    if state["code"] == "no_stake":
        raise HTTPException(422, "governance stake must be greater than 0")
    if state["code"] == "below_min":
        raise HTTPException(
            422,
            "governance stake %.6f is below the platform minimum %.6f"
            % (state["stake_amount"], state["floor"]),
        )
    raise HTTPException(409, "governance stake is not backed by locked USDC: " + describe(state))


# ---------------------------------------------------------------------------
# 在任判定（复核入口每次都要过这一关）
# ---------------------------------------------------------------------------

async def governance_profile_of(
    db: AsyncSession, *, identity_id: str, class_: str | None = None
) -> IdentityRoleProfile | None:
    q = select(IdentityRoleProfile).where(
        IdentityRoleProfile.owner_identity_id == identity_id,
    )
    if class_:
        q = q.where(IdentityRoleProfile.class_ == class_)
    else:
        q = q.where(IdentityRoleProfile.class_.in_(GOVERNANCE_CLASSES))
    return (await db.execute(q)).scalars().first()


async def assert_governor_active(
    db: AsyncSession, *, identity_id: str, what: str
) -> dict[str, Any] | None:
    """复核入口的补充判定：只有**质押开出来的岗**才跟着押金走。

    - 白名单 → 放行：平台自己的岗，不拿用户的押金背书；
    - 岗不是靠质押开的（``stake_amount == 0``：运维直接建档 / 历史行）→ 放行：
      这一档跟的是名单，不是押金。API 上开不出这种岗（见
      ``api/routes/identity_role_profiles.py`` 的闸门），所以它不是一条绕过质押的后门；
    - 质押开出来的岗（``stake_amount > 0``）→ 押金不够就 403，当场生效。

    返回 ``None`` 表示「这个身份根本没开治理岗」—— 调用方自己的档案检查会拒它，
    这里不抢那份工作，只负责「曾经有岗、现在押金不够」这一种情况。
    """
    if whitelisted(identity_id):
        return {"identity_id": identity_id, "code": "whitelisted", "ok": True}
    row = await governance_profile_of(db, identity_id=identity_id)
    if row is None:
        return None
    if float(row.stake_amount or 0.0) <= 0:
        return {"identity_id": identity_id, "code": "appointed", "ok": True}
    state = await stake_state(db, identity_id=identity_id, stake_amount=row.stake_amount)
    if not state["ok"]:
        raise HTTPException(
            403,
            "this governance role is not active right now (%s): %s" % (what, describe(state)),
        )
    return state
