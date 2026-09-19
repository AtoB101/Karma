"""Karma — 把「任务结算」接到非托管授权托管（allowance escrow）上。

背景：``/v1/settlement/*`` 这条业务流原先只改数据库 —— 接单写 ACCEPTED、验收写
SETTLED，链上一分钱没动。于是「已锁仓额度」只是台账里的一个数字，卖家拿到的
「结算完成」在链上不存在。

这个模块把它接到已经跑通的 v2 allowance escrow 上，链路是：

接单（→ ACCEPTED）   买方账单 + 卖方质押账单 ``bind`` 成一个 binding。钱还在买方
                     自己的钱包里，只是被「承诺」占住了 —— 没有人托管。
验收（→ SETTLED）    ``submitSettlement`` 打开挑战期。挑战期一过，API 进程内的
                     escrow autosettle 循环执行 ``finalizeSettlement``，钱从买方
                     钱包直接划到卖方钱包。
退款 / 取消           ``cancelBinding``，把买方被占住的授权原样放回去，钱不动。

门槛：买方和卖方都必须**先在链上锁过仓**。没有真账单就不 bind —— 接单直接 409，
并把缺多少说清楚。额度从此不是可以凭空记的数字。

这一层只写「钱的事实」：它不做金额裁决，也不替任何人签名。operator 只能 bind /
submit，划款与否由买方自己的 ERC-20 授权额决定，买方随时可以 revoke。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import AllowanceCommitModel, EscrowBindingModel, SettlementModel
from services import seller_stake
from services.chain import allowance_escrow as escrow

logger = structlog.get_logger(__name__)

EPSILON = 1e-9

#: 台账口径：binding 的本地状态
ACTIVE = "active"          # 已 bind，挑战期还没开（钱没动）
FINALIZING = "finalizing"  # 已 submit，等 autosettle 划款
SETTLED = "settled"        # 链上已经划完
CANCELLED = "cancelled"    # 授权已放回
SLASHED = "slashed"        # 卖方质押被划给买方
BREACHING = "breaching"    # 已裁定违约，等争议窗口到点后罚没（此刻钱还没动）

_DONE_STATES = (SETTLED, CANCELLED, SLASHED)

#: 合约自己记的 binding 状态（见 allowance_escrow.BINDING_STATE）
_CHAIN_FINAL = {3: SETTLED, 4: SLASHED, 5: CANCELLED}


class EscrowSettlementError(Exception):
    """带 HTTP 状态的领域错误，路由层直接翻译成人话。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def enabled() -> bool:
    """这个部署真的配了托管合约 + operator key 吗。"""
    return bool(escrow.escrow_enabled())


def _proof(task_id: str, amount_usdc: float) -> str:
    """这一单的凭证摘要：跟着任务和实际释放金额走，改一个字节就对不上。"""
    return f"karma-settlement:{task_id}:{float(amount_usdc):.6f}"


async def _find_binding(db: AsyncSession, *, task_id: str) -> EscrowBindingModel | None:
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.task_id == task_id)
        .order_by(EscrowBindingModel.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _live_bills(db: AsyncSession, identity_id: str) -> list[AllowanceCommitModel]:
    rows = await escrow.list_commits(db, identity_id)
    return [r for r in rows if r.state == escrow.IDLE]


async def _pick_bill(db: AsyncSession, *, identity_id: str, role: str, need_usdc: float) -> str:
    """挑一张**真划得动**的账单。

    台账上「剩余额度够」不等于「链上划得动」：同一个钱包的多张账单共用一条 ERC-20
    授权额，先到先得（见 ``backing_report``）。所以这里两个口径都要过。
    """
    need = max(0.0, float(need_usdc or 0.0))
    live = await _live_bills(db, identity_id)
    if not live:
        raise EscrowSettlementError(
            409,
            f"{role}还没有链上锁仓额度。请在操作台「资金」里锁仓 USDC —— "
            f"授权额就是这一单能动的上限，钱始终留在自己的钱包里",
        )
    report = await escrow.backing_report(db, identity_id)
    if not report.get("chain_checked"):
        raise EscrowSettlementError(
            503, f"读不到{role}的链上授权额（RPC 抖动）。没有链上事实就不该动钱，请稍后重试"
        )
    secured_by_bill = report.get("bills") or {}
    best: tuple[float, str] | None = None
    candidates: list[float] = []
    for row in live:
        free = (
            float(row.amount_usdc or 0.0)
            - float(row.spent_usdc or 0.0)
            - float(row.reserved_usdc or 0.0)
        )
        secured = float((secured_by_bill.get(str(row.bill_id)) or {}).get("secured_usdc") or 0.0)
        if free + EPSILON < need or secured + EPSILON < need:
            candidates.append(min(free, secured))
            continue
        # 台账只在链上确认之后才更新，两个结算挨得近时它会高估。以合约自己记的
        # 「还剩多少」为准：挑中的账单必须真的 Bind 得动，不能拿台账去赌。
        onchain = await asyncio.to_thread(escrow.bill_available, bill_id=int(row.bill_id))
        if onchain is None:
            continue
        candidates.append(min(free, secured, onchain))
        if onchain + EPSILON < need:
            continue
        if best is None or min(free, onchain) > best[0]:
            best = (min(free, onchain), str(row.bill_id))
    if best is None:
        have = max(candidates) if candidates else 0.0
        raise EscrowSettlementError(
            409,
            f"{role}的可用锁仓额度不足：这一单需要 {round(need, 6)} USDC，"
            f"链上真正划得动的只有 {round(max(0.0, have), 6)} USDC。"
            f"请先在操作台补足锁仓（或提高对该托管合约的 USDC 授权额）再重试",
        )
    return best[1]


async def _reflect(
    db: AsyncSession,
    *,
    task_id: str,
    binding: EscrowBindingModel,
    onchain_status: str,
    tx_hash: str | None = None,
) -> None:
    """把链上的事实写回结算单（操作台读的就是这一行）。"""
    stmt = select(SettlementModel).where(SettlementModel.task_id == task_id)
    model = (await db.execute(stmt)).scalars().first()
    if model is None:
        return
    model.settlement_mode = "escrow_allowance"
    model.chain_id = int(settings.testnet_chain_id or 0) or None
    model.contract_address = (settings.allowance_escrow_address or "").strip() or None
    try:
        model.onchain_binding_id = int(binding.binding_id)
    except (TypeError, ValueError):
        pass
    for attr, raw in (
        ("onchain_buyer_bill_id", binding.buyer_bill_id),
        ("onchain_agent_bill_id", binding.seller_bill_id),
    ):
        try:
            setattr(model, attr, int(raw))
        except (TypeError, ValueError):
            pass
    model.onchain_status = onchain_status
    if tx_hash:
        model.tx_hash = tx_hash
    model.updated_at = datetime.utcnow()


async def bind_for_task(
    db: AsyncSession,
    *,
    task_id: str,
    buyer_identity_id: str,
    seller_identity_id: str | None,
    amount_usdc: float,
) -> dict[str, Any]:
    """接单时把买方承诺和卖方质押绑在一起（钱还没动）。"""
    if not enabled():
        return {"status": "disabled"}
    amount = float(amount_usdc or 0.0)
    if amount <= 0:
        return {"status": "skipped", "reason": "settlement has no escrow amount"}
    if not seller_identity_id:
        raise EscrowSettlementError(409, "接单前必须先有 worker_agent_id —— 没有收款方就没有结算")

    existing = await _find_binding(db, task_id=task_id)
    if existing is not None and existing.state not in ("cancelled",):
        return {"status": "already_bound", "binding_id": existing.binding_id, "state": existing.state}

    stake = seller_stake.required_stake_usdc(amount)
    buyer_bill = await _pick_bill(db, identity_id=buyer_identity_id, role="付款方", need_usdc=amount)
    seller_bill = await _pick_bill(db, identity_id=seller_identity_id, role="提供方", need_usdc=stake)

    scope = f"{settings.settlement_scope}:task"
    try:
        bound = await asyncio.to_thread(
            escrow.open_order,
            buyer_bill_id=buyer_bill,
            seller_bill_id=seller_bill,
            amount_usdc=amount,
            stake_usdc=stake,
            scope=scope,
            task_id=task_id,
        )
    except Exception as exc:  # 链上没绑上，业务状态就不该往前走
        logger.warning("escrow_settlement_bind_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上锁定失败：{exc}") from exc

    row = EscrowBindingModel(
        binding_id=str(bound["binding_id"]),
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        buyer_bill_id=str(buyer_bill),
        seller_bill_id=str(seller_bill),
        scope_hash=str(bound.get("scope_hash") or ""),
        task_id=task_id,
        amount_usdc=amount,
        stake_usdc=stake,
        state=ACTIVE,
        bind_tx_hash=str(bound.get("bind_tx_hash") or "") or None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    await _reflect(db, task_id=task_id, binding=row, onchain_status="bound", tx_hash=row.bind_tx_hash)
    logger.info(
        "escrow_settlement_bound",
        task_id=task_id,
        binding_id=row.binding_id,
        amount_usdc=amount,
        stake_usdc=stake,
        tx=row.bind_tx_hash,
    )
    return {
        "status": "bound",
        "binding_id": row.binding_id,
        "bind_tx_hash": row.bind_tx_hash,
        "amount_usdc": amount,
        "stake_usdc": stake,
    }


async def _rebind_partial(
    db: AsyncSession, *, row: EscrowBindingModel, task_id: str, amount_usdc: float
) -> None:
    """部分结算：原绑定锁的是全额，链上没有「少划一点」的入口 —— 撤掉重绑。"""
    await asyncio.to_thread(escrow.cancel_binding, binding_id=int(row.binding_id))
    stake = seller_stake.required_stake_usdc(amount_usdc)
    buyer_bill = await _pick_bill(
        db, identity_id=row.buyer_identity_id, role="付款方", need_usdc=amount_usdc
    )
    seller_bill = await _pick_bill(
        db, identity_id=str(row.seller_identity_id), role="提供方", need_usdc=stake
    )
    bound = await asyncio.to_thread(
        escrow.open_order,
        buyer_bill_id=buyer_bill,
        seller_bill_id=seller_bill,
        amount_usdc=amount_usdc,
        stake_usdc=stake,
        scope=f"{settings.settlement_scope}:task",
        task_id=task_id,
    )
    row.binding_id = str(bound["binding_id"])
    row.buyer_bill_id = str(buyer_bill)
    row.seller_bill_id = str(seller_bill)
    row.scope_hash = str(bound.get("scope_hash") or "")
    row.amount_usdc = amount_usdc
    row.stake_usdc = stake
    row.bind_tx_hash = str(bound.get("bind_tx_hash") or "") or None
    row.updated_at = datetime.utcnow()
    await db.flush()


async def submit_for_task(
    db: AsyncSession, *, task_id: str, released_amount: float | None = None
) -> dict[str, Any]:
    """验收通过：把 binding 交上去，打开挑战期，等 autosettle 真划款。"""
    if not enabled():
        return {"status": "disabled"}
    row = await _find_binding(db, task_id=task_id)
    if row is None:
        return {"status": "unbound"}
    if row.state in _DONE_STATES:
        return {"status": row.state, "binding_id": row.binding_id}
    if row.state != ACTIVE:
        return {"status": row.state, "binding_id": row.binding_id}

    target = float(row.amount_usdc)
    if released_amount is not None:
        settled = float(released_amount)
        if settled + EPSILON < target:
            target = max(0.0, settled)
    if target <= 0:
        await cancel_for_task(db, task_id=task_id)
        return {"status": "cancelled", "reason": "nothing to release"}
    if abs(target - float(row.amount_usdc)) > EPSILON:
        await _rebind_partial(db, row=row, task_id=task_id, amount_usdc=target)

    try:
        submitted = await asyncio.to_thread(
            escrow.submit_settlement,
            binding_id=int(row.binding_id),
            proof=_proof(task_id, target),
        )
    except Exception as exc:
        logger.warning("escrow_settlement_submit_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上结算提交失败：{exc}") from exc

    row.state = FINALIZING
    row.submit_tx_hash = str(submitted.get("submit_tx_hash") or "") or None
    row.proof_hash = str(submitted.get("proof_hash") or "") or None
    row.pull_after = int(submitted.get("pull_after") or 0) or None
    row.updated_at = datetime.utcnow()
    await db.flush()
    await _reflect(
        db, task_id=task_id, binding=row, onchain_status=FINALIZING, tx_hash=row.submit_tx_hash
    )
    logger.info(
        "escrow_settlement_submitted",
        task_id=task_id,
        binding_id=row.binding_id,
        amount_usdc=target,
        pull_after=row.pull_after,
        tx=row.submit_tx_hash,
    )
    return {
        "status": FINALIZING,
        "binding_id": row.binding_id,
        "submit_tx_hash": row.submit_tx_hash,
        "pull_after": row.pull_after,
    }


def _breach_proof(task_id: str) -> str:
    """罚没这一单的凭证摘要。最终划多少由合约里的 stakeAmount 决定，摘要只留痕。"""
    return f"karma-breach:{task_id}"


async def slash_for_task(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
    """判卖方违约：卖方质押划给买方（``finalizeBreach``，卖方钱包 → 买方钱包）。

    「全额退款（REFUNDED）」的含义是「这次交付被裁定为一文不值」，所以卖方要付代价：
    质押划给买方。链上没有一步到位的入口 —— ``finalizeBreach`` 只认 FINALIZING，
    而且必须等争议窗口到点。所以这里先把 binding 交上去打开窗口，再由
    ``escrow_autosettle`` 在窗口到点后真正执行罚没。

    窗口开启后 binding 记成 ``breaching``：正常结算通道只看 ``finalizing``，
    所以这一单绝不会被误当成「该付卖方」而把货款划出去。
    """
    if not enabled():
        return {"status": "disabled"}
    row = await _find_binding(db, task_id=task_id)
    if row is None:
        return {"status": "unbound"}
    if row.state in _DONE_STATES or row.state == BREACHING:
        return {"status": row.state, "binding_id": row.binding_id}
    if row.state == FINALIZING:
        # 窗口本来就开着（例如先被冻结过）：直接改判罚没，不重复 submit。
        row.state = BREACHING
        row.updated_at = datetime.utcnow()
        await db.flush()
        await _reflect(
            db, task_id=task_id, binding=row, onchain_status=BREACHING, tx_hash=row.submit_tx_hash
        )
        logger.info("escrow_settlement_breach_rearmed", task_id=task_id, binding_id=row.binding_id)
        return {"status": BREACHING, "binding_id": row.binding_id, "pull_after": row.pull_after}
    if row.state != ACTIVE:
        return {"status": row.state, "binding_id": row.binding_id}

    try:
        submitted = await asyncio.to_thread(
            escrow.submit_settlement,
            binding_id=int(row.binding_id),
            proof=_breach_proof(task_id),
        )
    except Exception as exc:
        logger.warning("escrow_settlement_breach_submit_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上罚没提交失败：{exc}") from exc

    row.state = BREACHING
    row.submit_tx_hash = str(submitted.get("submit_tx_hash") or "") or None
    row.proof_hash = str(submitted.get("proof_hash") or "") or None
    row.pull_after = int(submitted.get("pull_after") or 0) or None
    row.updated_at = datetime.utcnow()
    await db.flush()
    await _reflect(
        db, task_id=task_id, binding=row, onchain_status=BREACHING, tx_hash=row.submit_tx_hash
    )
    logger.info(
        "escrow_settlement_breach_armed",
        task_id=task_id,
        binding_id=row.binding_id,
        stake_usdc=row.stake_usdc,
        pull_after=row.pull_after,
        tx=row.submit_tx_hash,
    )
    return {
        "status": BREACHING,
        "binding_id": row.binding_id,
        "submit_tx_hash": row.submit_tx_hash,
        "pull_after": row.pull_after,
    }


async def cancel_for_task(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
    """取消：把买方被占住的授权放回去，钱一步都没动过。"""

    if not enabled():
        return {"status": "disabled"}
    row = await _find_binding(db, task_id=task_id)
    if row is None or row.state in _DONE_STATES or row.state != ACTIVE:
        return {"status": row.state if row is not None else "unbound"}
    try:
        await asyncio.to_thread(escrow.cancel_binding, binding_id=int(row.binding_id))
    except Exception as exc:
        logger.warning("escrow_settlement_cancel_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上撤销锁定失败：{exc}") from exc
    row.state = CANCELLED
    row.updated_at = datetime.utcnow()
    await db.flush()
    await _reflect(db, task_id=task_id, binding=row, onchain_status=CANCELLED)
    return {"status": CANCELLED, "binding_id": row.binding_id}


async def reconcile_task(db: AsyncSession, *, task_id: str) -> dict[str, Any] | None:
    """把结算单和链上对齐。

    只在台账停在 ``finalizing`` 时才去问链（正常路径由 autosettle 自己回写），
    所以这个调用对绝大多数结算单是纯读库。
    """
    if not enabled():
        return None
    row = await _find_binding(db, task_id=task_id)
    if row is None:
        return None
    if row.state in _DONE_STATES:
        await _reflect(
            db,
            task_id=task_id,
            binding=row,
            onchain_status=row.state,
            tx_hash=row.finalize_tx_hash or row.submit_tx_hash or row.bind_tx_hash,
        )
        return {"status": row.state, "binding_id": row.binding_id, "tx_hash": row.finalize_tx_hash}
    if row.state not in (FINALIZING, BREACHING):
        return None
    try:
        chain_state = await asyncio.to_thread(escrow.binding_state, binding_id=int(row.binding_id))
    except Exception as exc:  # RPC 抖动：保持现状，下次再对
        logger.warning("escrow_settlement_state_read_failed", task_id=task_id, error=str(exc))
        return None
    mapped = _CHAIN_FINAL.get(chain_state) if chain_state is not None else None
    if mapped is None:
        return None
    row.state = mapped
    row.updated_at = datetime.utcnow()
    await db.flush()
    tx = row.finalize_tx_hash or row.submit_tx_hash
    await _reflect(db, task_id=task_id, binding=row, onchain_status=mapped, tx_hash=tx)
    logger.info("escrow_settlement_reconciled", task_id=task_id, binding_id=row.binding_id, state=mapped)
    return {"status": mapped, "binding_id": row.binding_id, "tx_hash": tx}
