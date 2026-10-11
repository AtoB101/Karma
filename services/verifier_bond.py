"""验证者质押金库（G12）—— 「质押即准入」的另一半：在任跟着押金走。

背景（2026-10-11 复核）
----------------------
节点质押此前只是 ``verifier_nodes.stake_amount`` 一个记数：没有锁仓背书、没有下限，
也没有罚没 / 退出闭环。于是「免人工审核 + 纯质押准入」等于「审核去掉、担保也没上」 ——
节点作恶没有经济成本。

这一层把节点也做成**跟押金走**的一档，判法与 ``services/governance_stake.py``
完全一致（同一本锁仓账 ``capacity.total_locked_usdc``）：

1. **名单档**（``owner_identity_id`` 为空）：运维 / 白名单直接建档 —— 跟名单，不跟押金。
   生产环境 ``VERIFIER_REQUIRE_OWNER_IDENTITY=true`` 时这条入口开不出来，
   所以它不是绕开质押的后门。
2. **金库档**（``owner_identity_id`` 非空）：**押金在则岗在，押金走则岗停** ——
   每次出证、每次被派活都重新算一遍，锁仓被划走（含罚没）当场 403。

三档别混着看：

==============  ==============================  ==================
档位            判据                            在任跟着谁走
==============  ==============================  ==================
名单档          ``owner_identity_id`` 为空      名单（不是押金）
金库档          质押 ≥ 下限 且 有锁仓背书       **押金**
退出冷却档      已发起 unstake，冷却期内        押金（仍可被罚没）
==============  ==============================  ==================

一句话：**质押状态不缓存。缓存出来的「在任」等于一张可以过期的通行证。**
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from services.governance_stake import locked_capacity_of
from services.identity_wallet_binding import get_bound_wallet

EPSILON = 1e-9

#: 金库档可能出现的在任状态。
BOND_STATES = (
    "appointed",
    "active",
    "no_stake",
    "below_min",
    "unbacked",
    "cooling",
    "released",
)


# ---------------------------------------------------------------------------
# 策略读取
# ---------------------------------------------------------------------------

def min_bond_amount() -> float:
    """有效节点必须押够的下限（USDC）。0 = 不设下限（测试网先跑通）。"""
    try:
        return max(0.0, float(settings.verifier_min_bond_usdc or 0.0))
    except (TypeError, ValueError):
        return 0.0


def backed_bond_required() -> bool:
    """押金是否必须由已锁仓 USDC 背书。生产环境强制为真（见 config/settings.py）。"""
    return bool(settings.verifier_require_backed_bond)


def require_owner_identity() -> bool:
    """登记节点是否必须声明主人身份（生产环境强制为真）。"""
    return bool(settings.verifier_require_owner_identity)


def unbond_cooldown() -> timedelta:
    try:
        hours = int(settings.verifier_unbond_cooldown_hours or 0)
    except (TypeError, ValueError):
        hours = 0
    return timedelta(hours=max(0, hours))


def vault_address() -> str:
    return (settings.verifier_bond_vault_address or "").strip()


def vault_configured() -> bool:
    return bool(vault_address())


def victim_share_bps() -> int:
    try:
        return int(settings.verifier_slash_victim_share_bps)
    except (TypeError, ValueError):
        return 8000


def pool_share_bps() -> int:
    try:
        return int(settings.verifier_slash_pool_share_bps)
    except (TypeError, ValueError):
        return 2000


# ---------------------------------------------------------------------------
# 质押状态（现算，不缓存）
# ---------------------------------------------------------------------------

def _in_cooldown(unbond_requested_at: datetime | None, now: datetime | None) -> bool:
    if unbond_requested_at is None:
        return False
    moment = now or datetime.utcnow()
    return moment < unbond_requested_at + unbond_cooldown()


async def bond_state(
    db: AsyncSession,
    *,
    identity_id: str,
    stake_amount: float | None,
    unbond_requested_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """算一遍这个节点现在算不算「在任」。

    ``code`` 只有 ``active`` / ``no_stake`` / ``below_min`` / ``unbacked`` / ``cooling``。
    故意不做缓存：押金是活的，缓存出来的「在任」等于一张可以过期的通行证。

    注意 ``cooling``（已发起退出、还在冷却期）**不算在任** —— 不接受新活，但保证金
    仍在金库里、**仍可被罚没**：这才是冷却期的意义。
    """
    floor = min_bond_amount()
    stake = float(stake_amount or 0.0)
    locked = await locked_capacity_of(db, identity_id)
    backed = locked + EPSILON >= stake
    cooling = _in_cooldown(unbond_requested_at, now)

    if stake <= 0:
        code = "no_stake"
    elif stake + EPSILON < floor:
        code = "below_min"
    elif backed_bond_required() and not backed:
        code = "unbacked"
    elif cooling:
        code = "cooling"
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
        "cooling": cooling,
        "require_backed_stake": backed_bond_required(),
    }


def describe(state: dict[str, Any]) -> str:
    """把「为什么不在任」说成人话 —— 用户得知道差多少、去哪补。"""
    code = state.get("code")
    if code == "no_stake":
        return "这个节点没有质押：请先锁仓 USDC 并带上质押金额重新开通"
    if code == "below_min":
        return "质押 %.6f USDC 低于平台下限 %.6f" % (state["stake_amount"], state["floor"])
    if code == "unbacked":
        return (
            "质押 %.6f USDC 没有锁仓背书：%s 现在只锁着 %.6f USDC，补足锁仓或下调质押后再试"
            % (state["stake_amount"], state["identity_id"], state["locked_usdc"])
        )
    if code == "cooling":
        return "该节点已发起退出、正在冷却期：冷却期内不接受新活（保证金仍可被罚没）"
    return "节点在任"


async def assert_bond_acceptable(
    db: AsyncSession, *, identity_id: str, stake_amount: float | None
) -> dict[str, Any]:
    """开通 / 加押时用的闸门：不合格直接拒，并把原因写清楚。"""
    state = await bond_state(db, identity_id=identity_id, stake_amount=stake_amount)
    if state["ok"]:
        return state
    if state["code"] == "no_stake":
        raise HTTPException(422, "verifier bond must be greater than 0")
    if state["code"] == "below_min":
        raise HTTPException(
            422,
            "verifier bond %.6f is below the platform minimum %.6f"
            % (state["stake_amount"], state["floor"]),
        )
    if state["code"] == "cooling":
        raise HTTPException(409, "verifier bond is mid-exit (cooldown): " + describe(state))
    raise HTTPException(409, "verifier bond is not backed by locked USDC: " + describe(state))


async def assert_owner_wallet_matches(
    db: AsyncSession, *, identity_id: str, wallet_address: str
) -> None:
    """金库档的绑定：节点钱包必须是主人身份在 Console 里绑定的那个钱包。

    少了这一关，A 可以拿自己的锁仓押金去给 B 的钱包登记节点 —— 押金与责任就脱钩了。
    """
    bound = await get_bound_wallet(db, identity_id)
    if not bound:
        raise HTTPException(
            409,
            "identity %s has no bound wallet — bind the node wallet in Console first"
            % identity_id,
        )
    if (bound or "").strip().lower() != (wallet_address or "").strip().lower():
        raise HTTPException(
            403,
            "node wallet %s does not match the wallet bound to identity %s"
            % (wallet_address, identity_id),
        )


# ---------------------------------------------------------------------------
# 在任判定（每次出证 / 派活都要过这一关）
# ---------------------------------------------------------------------------

async def assert_node_bond_ok(
    db: AsyncSession, *, node: Any, what: str
) -> dict[str, Any] | None:
    """只有**金库档**才跟着押金走。

    * 名单档（``owner_identity_id`` 为空）→ 放行：平台自己的岗，不拿用户的押金背书；
    * 金库档 → 押金不够 / 冷却中 / 没背书，一律 403，当场生效。

    返回 ``None`` 表示「这个节点是名单档」，调用方不需要额外的状态。
    """
    identity_id = (getattr(node, "owner_identity_id", None) or "").strip()
    if not identity_id:
        return {"identity_id": "", "code": "appointed", "ok": True}

    state = await bond_state(
        db,
        identity_id=identity_id,
        stake_amount=getattr(node, "stake_amount", 0.0),
        unbond_requested_at=getattr(node, "unbond_requested_at", None),
    )
    if not state["ok"]:
        raise HTTPException(
            403,
            "this verifier node is not active right now (%s): %s" % (what, describe(state)),
        )
    return state


async def refresh_node_bond_state(db: AsyncSession, *, node: Any) -> str:
    """把现算出的状态写回 ``node.bond_state``（快照，仅用于展示与过滤）。"""
    identity_id = (getattr(node, "owner_identity_id", None) or "").strip()
    if not identity_id:
        node.bond_state = "appointed"
        return node.bond_state
    state = await bond_state(
        db,
        identity_id=identity_id,
        stake_amount=getattr(node, "stake_amount", 0.0),
        unbond_requested_at=getattr(node, "unbond_requested_at", None),
    )
    node.bond_state = state["code"]
    return node.bond_state
