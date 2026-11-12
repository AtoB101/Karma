"""资金溯源与对齐（2026-10-14）。

用户口径：**每一笔资金都要有源头；结算前要能回溯整条链路，并确认各环节互相
指得着、对得上**。这里把「这笔钱从哪来、挂在谁身上、落在哪台合约上、现在在哪
个状态」串成一条链，任一环节对不上就拒绝动钱。

设计取舍
--------
* **只读台账（DB），不读链**。请求路径上多一次 ``eth_call`` 就是几十个用户的等待
  时间（2026-10-14 实测：一轮 tick 90% 花在链上读）。链上事实由**动钱那一刻**
  的闸来对：``escrow_autosettle.settle_due`` 发 finalize 之前先 ``_onchain_state``，
  ``submit_for_task`` 先 ``adopt_chain_finalizing``、``binding_snapshot``。
* **拒绝的只有「钱会划错地方 / 根本划不动」**；金额漂移（部分结算合法）之类的只
  记 warning，不拦单 —— 拦错了比不拦更伤用户。
* 两个状态口径分清楚：``settlements.status`` 是**账上的验证结论**（该不该结），
  ``settlements.onchain_status`` / ``escrow_bindings.state`` 才是**链上事实**。
  「status=settled 而 binding 还 active」是**正常**的（窗口刚开、还没划）；只有
  「链上钱已经划走、账上却没跟上」才是对不上。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import EscrowBindingModel, SettlementModel, SettlementTransitionAuditModel
from services.settlement_amounts import to_minor_units

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TraceLink:
    """链路里的一个环节：谁指谁、指上没有。"""

    name: str
    ref: str
    ok: bool
    detail: str = ""


@dataclass
class FundsTrace:
    """一条资金的完整链路 + 对不上的地方。"""

    task_id: str
    settlement_id: str | None = None
    binding_id: str | None = None
    onchain_binding_id: int | None = None
    buyer_identity_id: str | None = None
    seller_identity_id: str | None = None
    buyer_bill_id: str | None = None
    seller_bill_id: str | None = None
    buyer_wallet: str | None = None
    seller_wallet: str | None = None
    amount_usdc: float = 0.0
    links: list[TraceLink] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def as_log_fields(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "settlement_id": self.settlement_id,
            "binding_id": self.binding_id,
            "onchain_binding_id": self.onchain_binding_id,
            "buyer_identity_id": self.buyer_identity_id,
            "seller_identity_id": self.seller_identity_id,
            "buyer_bill_id": self.buyer_bill_id,
            "seller_bill_id": self.seller_bill_id,
            "buyer_wallet": self.buyer_wallet,
            "seller_wallet": self.seller_wallet,
            "amount_usdc": self.amount_usdc,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
        }

    def describe(self) -> str:
        """一句话说清「这笔钱是从哪来的」（给用户看的中文）。"""
        origin = (
            f"资金来源：{self.buyer_identity_id or '未知'}"
            f" 的账单 {self.buyer_bill_id or '未知'}"
            f"（{self.buyer_wallet or '没有钱包'}）"
        )
        parts = [origin]
        if self.seller_identity_id or self.seller_bill_id:
            parts.append(
                f"受款方：{self.seller_identity_id or '未知'}"
                f" 的账单 {self.seller_bill_id or '未知'}"
                f"（{self.seller_wallet or '没有钱包'}）"
            )
        parts.append(f"链上绑定 #{self.onchain_binding_id if self.onchain_binding_id is not None else '未知'}")
        parts.append(f"托管金额 {self.amount_usdc:g} USDC")
        return "；".join(parts)


def _minor(value: Any) -> int:
    try:
        return int(to_minor_units(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _wallet_of(row: Any) -> str | None:
    from services.chain.escrow_settlement import _norm_wallet

    return _norm_wallet(getattr(row, "wallet_address", None)) or None


async def _find_bill(db: AsyncSession, *, identity_id: str, bill_id: str | None) -> Any | None:
    """在**这个身份**的账单列表里找那张账单 —— 找不到就说明这一环断了。"""
    from services.chain import allowance_escrow as escrow

    if not identity_id or not bill_id:
        return None
    for row in await escrow.list_commits(db, identity_id):
        if str(getattr(row, "bill_id", "")) == str(bill_id):
            return row
    return None


async def trace_task_funds(db: AsyncSession, *, task_id: str) -> FundsTrace:
    """把这一单的资金链路整条读出来。**不抛异常** —— 调用方决定怎么处置。"""
    from services.chain import allowance_escrow as escrow
    from services.chain.escrow_settlement import (
        SETTLED,
        SLASHED,
        chain_binding_id,
        resolve_party_identity,
    )

    trace = FundsTrace(task_id=task_id)
    settlement = (
        await db.execute(
            select(SettlementModel).where(SettlementModel.task_id == task_id)
        )
    ).scalars().first()
    if settlement is None:
        trace.issues.append("这一单在账上没有结算记录：资金没有源头，不能动")
        return trace
    trace.settlement_id = settlement.settlement_id
    trace.amount_usdc = float(settlement.escrow_amount or 0.0)

    binding = (
        await db.execute(
            select(EscrowBindingModel)
            .where(EscrowBindingModel.task_id == task_id)
            .order_by(EscrowBindingModel.created_at.desc())
        )
    ).scalars().first()
    if binding is None:
        trace.issues.append(
            "这一单没有链上绑定台账（escrow_bindings）：钱从哪来、要划给谁都没有记录，不能动"
        )
        return trace

    trace.binding_id = str(binding.binding_id)
    trace.buyer_bill_id = str(binding.buyer_bill_id)
    trace.seller_bill_id = str(binding.seller_bill_id)
    try:
        trace.onchain_binding_id = chain_binding_id(binding)
    except (TypeError, ValueError):
        trace.issues.append(
            f"绑定主键 {binding.binding_id!r} 解析不出链上 id：这条绑定指不回链，不能动"
        )

    # ── 环节 1：结算单 ↔ 绑定，链上指认必须一致
    if settlement.onchain_binding_id is not None:
        try:
            expected = int(settlement.onchain_binding_id)
        except (TypeError, ValueError):
            expected = None
        if expected is not None and expected != trace.onchain_binding_id:
            trace.issues.append(
                f"结算单指的链上绑定是 #{expected}，台账里这条是 "
                f"#{trace.onchain_binding_id}：两边指的不是同一条，不能动"
            )
    for label, pointer, actual in (
        ("买方账单", settlement.onchain_buyer_bill_id, binding.buyer_bill_id),
        ("卖方账单", settlement.onchain_agent_bill_id, binding.seller_bill_id),
    ):
        if pointer is None:
            continue
        try:
            expected = int(pointer)
        except (TypeError, ValueError):
            continue
        try:
            got = int(str(actual).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            got = None
        if got != expected:
            trace.issues.append(
                f"结算单记的{label}链上 id 是 {expected}，绑定里是 {actual!r}：两边对不上，不能动"
            )

    # ── 环节 2：绑定 ↔ 当事人身份
    buyer_ledger = (
        await resolve_party_identity(db, settlement.client_agent_id)
        or (settlement.client_agent_id or "").strip()
    )
    seller_ledger = (
        await resolve_party_identity(db, settlement.worker_agent_id)
        or (settlement.worker_agent_id or "").strip()
    )
    trace.buyer_identity_id = buyer_ledger or None
    trace.seller_identity_id = seller_ledger or None
    binding_buyer = (
        await resolve_party_identity(db, binding.buyer_identity_id)
        or (binding.buyer_identity_id or "").strip()
    )
    binding_seller = (
        await resolve_party_identity(db, binding.seller_identity_id)
        or (binding.seller_identity_id or "").strip()
    )
    if buyer_ledger and binding_buyer and buyer_ledger != binding_buyer:
        trace.warnings.append(
            f"结算单的买方是 {buyer_ledger}，绑定的买方是 {binding_buyer}"
        )
    if seller_ledger and binding_seller and seller_ledger != binding_seller:
        trace.warnings.append(
            f"结算单的卖方是 {seller_ledger}，绑定的卖方是 {binding_seller}"
        )

    # ── 环节 3：绑定 ↔ 账单（钱真正躺着的那两张）
    buyer_bill = await _find_bill(db, identity_id=buyer_ledger, bill_id=binding.buyer_bill_id)
    seller_bill = await _find_bill(
        db, identity_id=seller_ledger, bill_id=binding.seller_bill_id
    )
    if buyer_bill is None:
        trace.issues.append(
            f"买方的账单 {binding.buyer_bill_id!r} 在 {buyer_ledger or '未知身份'} "
            f"名下找不到：这一单的钱没有出处，不能动"
        )
    if seller_bill is None:
        trace.issues.append(
            f"卖方的账单 {binding.seller_bill_id!r} 在 {seller_ledger or '未知身份'} "
            f"名下找不到：这一单的受款方对不上，不能动"
        )
    trace.buyer_wallet = _wallet_of(buyer_bill) if buyer_bill is not None else None
    trace.seller_wallet = _wallet_of(seller_bill) if seller_bill is not None else None
    if buyer_bill is not None and trace.buyer_wallet is None:
        trace.warnings.append("买方的账单上没有可用的钱包地址")
    if seller_bill is not None and trace.seller_wallet is None:
        trace.warnings.append("卖方的账单上没有可用的钱包地址")
    if trace.buyer_wallet and trace.seller_wallet:
        if trace.buyer_wallet == trace.seller_wallet:
            trace.issues.append(
                f"买卖双方是同一把钱包（{trace.buyer_wallet}）：链上会 SameOwner() revert，不能动"
            )
        else:
            trace.links.append(
                TraceLink("钱包分离", trace.buyer_wallet, True, trace.seller_wallet)
            )

    # ── 环节 4：绑定 ↔ 合约（旧合约上链上划不动）
    if not escrow.is_current_contract(escrow.binding_contract(binding)):
        trace.issues.append(
            f"这条绑定在旧托管合约 {escrow.binding_contract(binding)} 上，当前合约是 "
            f"{escrow.configured_address()}：链上划不动，不能开结算窗"
        )
    settlement_contract = (settlement.contract_address or "").strip().lower()
    if settlement_contract and settlement_contract != (
        escrow.binding_contract(binding) or ""
    ).strip().lower():
        trace.warnings.append(
            f"结算单记的合约 {settlement.contract_address} 与绑定的 "
            f"{escrow.binding_contract(binding)} 不一致"
        )

    # ── 环节 5：金额（划的不能多于托管的）
    escrow_minor = _minor(settlement.escrow_amount)
    bound_minor = _minor(binding.amount_usdc)
    if bound_minor > escrow_minor:
        trace.issues.append(
            f"这条绑定要划 {float(binding.amount_usdc or 0):g} USDC，"
            f"比托管的 {float(settlement.escrow_amount or 0):g} USDC 还多：金额没有源头，不能动"
        )
    elif bound_minor != escrow_minor:
        trace.warnings.append(
            f"绑定金额 {float(binding.amount_usdc or 0):g} 与托管金额 "
            f"{float(settlement.escrow_amount or 0):g} 不同（部分结算/关窗后重绑是正常的）"
        )

    # ── 环节 6：链上事实 ↔ 台账（只查「钱已经动了、账上没跟上」这种硬矛盾）
    onchain = (settlement.onchain_status or "").strip().lower()
    if binding.state in (SETTLED, SLASHED) and onchain != binding.state:
        trace.issues.append(
            f"链上这一单已经落定（{binding.state}），账上记的是 "
            f"{onchain or '空'}：钱动了账没动，不能继续动钱"
        )

    # ── 环节 7：状态机审计流水（只报不缺，不拦单）
    try:
        audit = (
            await db.execute(
                select(SettlementTransitionAuditModel.audit_id)
                .where(SettlementTransitionAuditModel.task_id == task_id)
                .limit(1)
            )
        ).scalars().first()
        if audit is None:
            trace.warnings.append("这一单没有状态机审计流水（settlement_transition_audits）")
    except Exception as exc:  # noqa: BLE001 - 审计表读不到不该拦住动钱
        logger.debug("funds_trace_audit_lookup_failed", task_id=task_id, error=str(exc))

    return trace


async def assert_funds_traceable(
    db: AsyncSession, *, task_id: str, stage: str
) -> FundsTrace:
    """动钱之前的最后一道：整条资金链路必须互相指得着。

    对不上就 409，并把整条链路 + 对不上的地方写进日志和一条安全事件 ——
    事后要能回答「这笔钱当初是从哪来的、为什么被拒」。
    """
    from services.chain.escrow_settlement import EscrowSettlementError

    trace = await trace_task_funds(db, task_id=task_id)
    if trace.ok:
        logger.info("escrow_funds_trace_ok", stage=stage, trace=trace.describe())
        return trace

    logger.warning(
        "escrow_funds_trace_mismatch", stage=stage, **trace.as_log_fields()
    )
    try:
        from services.security_monitoring import (
            SecurityMonitoringEventType,
            record_security_event,
        )

        record_security_event(
            SecurityMonitoringEventType.FUNDS_TRACE_MISMATCH,
            metadata={"stage": stage, **trace.as_log_fields()},
        )
    except Exception as exc:  # noqa: BLE001 - 留痕失败绝不能让这一单过去
        logger.warning("escrow_funds_trace_audit_failed", task_id=task_id, error=str(exc))

    detail = "；".join(trace.issues)
    raise EscrowSettlementError(
        409,
        f"这一单的资金链路对不上，钱不划（{stage}）：{detail}。"
        "每一笔资金都必须有源头、每个环节都要互相指得着 —— 请先查清这一单的绑定与账单",
    )