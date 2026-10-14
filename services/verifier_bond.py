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


def vault_bond_required() -> bool:
    """节点质押是否必须真的在链上金库里（④-B1）。

    关着的时候质押只看账面背书（锁仓额度），与历史行为一致；打开后
    —— 链上 ``slash()`` 只认金库里那笔 ``Bond`` —— 还要回链上核对"bondAmount >= 质押额"。
    """
    return bool(settings.verifier_require_vault_bond)


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
# 链上金库背书（④-B1）：“质押”到底在不在金库里
# ---------------------------------------------------------------------------


async def vault_bond_state(
    db: AsyncSession,
    *,
    identity_id: str,
    wallet_address: str | None = None,
    stake_amount: float | None = None,
) -> dict[str, Any]:
    """回链上核对：「这个身份的钱包在金库里押了多少」。

    ``code`` 只有这几种：

    ================  ============================================
    ``vault_unconfigured`` 金库没部署（没配地址）
    ``no_wallet``          这个身份还没绑定钱包
    ``vault_unavailable``  RPC / 合约读不到 —— **不当成 0**，fail-closed
    ``not_registered``     钱包在金库里没登记（没 ``stake()`` 过）
    ``below_bond``         链上余额不够质押额
    ``active``             链上确认有够额的押金
    ================  ============================================

    钱包取参数优先（节点传 ``node.wallet_address``），否则取该身份在 Console
    绑定的那个钱包（与 ``assert_owner_wallet_matches`` 同一个“身份根”口径）。
    """
    from services.chain import verifier_bond_vault

    stake = float(stake_amount or 0.0)
    wallet = (wallet_address or "").strip().lower()
    if not wallet:
        wallet = ((await get_bound_wallet(db, identity_id)) or "").strip().lower()
    base: dict[str, Any] = {
        "identity_id": identity_id,
        "wallet": wallet or None,
        "stake_amount": stake,
        "vault": verifier_bond_vault.vault_address(),
        "onchain_bond_usdc": 0.0,
        "registered": False,
        "active": False,
    }
    if not verifier_bond_vault.vault_configured():
        return {
            **base,
            "code": "vault_unconfigured",
            "ok": False,
            "detail": "金库还没部署（VERIFIER_BOND_VAULT_ADDRESS 为空），链上押金无从核对",
        }
    if not wallet:
        return {
            **base,
            "code": "no_wallet",
            "ok": False,
            "detail": "身份 %s 还没绑定钱包：先在 Console 绑定钱包，再用它在金库 stake()" % identity_id,
        }
    try:
        reading = await verifier_bond_vault.read_bond(wallet)
    except verifier_bond_vault.BondVaultUnavailable as exc:
        return {**base, "code": "vault_unavailable", "ok": False, "detail": str(exc)}
    if reading is None:
        return {**base, "code": "no_wallet", "ok": False, "detail": "没给钱包，无从核对"}

    bond = float(reading.get("bond_usdc") or 0.0)
    registered = bool(reading.get("registered"))
    state = {
        **base,
        "onchain_bond_usdc": round(bond, 8),
        "registered": registered,
        "active": bool(reading.get("active")),
    }
    if not registered:
        return {
            **state,
            "code": "not_registered",
            "ok": False,
            "detail": "钱包 %s 在金库里还没登记：先用这个钱包发一笔 stake()" % wallet,
        }
    if bond + EPSILON < stake:
        return {
            **state,
            "code": "below_bond",
            "ok": False,
            "detail": "链上押金 %.6f 低于声明的质押额 %.6f：先 stake() 补足，或下调质押额" % (bond, stake),
        }
    return {**state, "code": "active", "ok": True, "detail": "链上押金 %.6f ≥ 质押额 %.6f" % (bond, stake)}


async def assert_vault_bond_covers(
    db: AsyncSession,
    *,
    identity_id: str,
    stake_amount: float | None,
    what: str,
    wallet_address: str | None = None,
) -> dict[str, Any]:
    """质押必须由链上金库背书：不合格一律 409，并把差在哪说清楚。

    为什么是拒绝而不是放行：链上 ``slash()`` 只能划金库里那笔 ``Bond``。
    押金不在金库，「判负当场生效」就只剩一张空头承诺。
    """
    state = await vault_bond_state(
        db,
        identity_id=identity_id,
        wallet_address=wallet_address,
        stake_amount=stake_amount,
    )
    if state["ok"]:
        return state
    raise HTTPException(
        409,
        "on-chain bond is required for %s but %s: %s" % (what, state["code"], state["detail"]),
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
    if vault_bond_required():
        await assert_vault_bond_covers(
            db,
            identity_id=identity_id,
            stake_amount=getattr(node, "stake_amount", 0.0),
            what=what,
            wallet_address=getattr(node, "wallet_address", None),
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
