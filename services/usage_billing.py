"""按次计费与阈值结算 —— 数据 API 商业化的第二层。

小额高频的调用（一次 0.001 USDC 的行情、一次 0.0005 的地址风控）如果每次都上链，
gas 比货款还贵。所以这里分三段走：

1. **记账（record_usage）**：一次调用 = 一条 ``usage_charges`` 流水，幂等键是
   ``(skill_id, request_id)``。重放同一个 request_id 不会重复计费 —— 这是 API
   调用方最容易踩的坑（超时重试），必须由服务端兜住，而不是指望调用方。
2. **出账（settle_meter）**：某个「付款方 × 技能」的累计到了 ``settlement_threshold``
   才生成一张 ``usage_settlements``，此时调用流水被钉进这张单子（``settlement_id``），
   不会再次被计价。**这一步还没有动钱。**
3. **划转（chain）**：走 Karma 现有的非托管授权通道
   （``allowance_escrow.open_and_submit_order``：买方承诺 → 卖方质押 → 提交凭证 →
   挑战期后由自动结算器执行）。链上真的划走了，结算单才变成 ``settled``。

诚实性约束（本模块最重要的不变量）
----------------------------------
* 只有链上真的结了，``settled_usdc`` 才会增加。上游拒单时结算单停在 ``open`` 并带上
  失败原因，**绝不**把已经出账的调用标成"已结算"。
* 账本恒等式：``accrued + billed = 已计费总额``，``settled <= billed``。
  一笔调用要么在 accrued（待出账），要么在 billed（已出账），不会两处都在。
* 链上失败（slashed / cancelled）时，结算单转 ``failed``，并且把这批调用**退回待出账**，
  让它们有机会重新结算 —— 而不是把损失静默转嫁给任何一方。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import (
    EscrowBindingModel,
    SkillModel,
    UsageChargeModel,
    UsageMeterModel,
    UsageSettlementModel,
)
from services import seller_stake
from services.chain import allowance_escrow as escrow

logger = structlog.get_logger(__name__)

METER_STATUSES = ("open", "paused", "closed")
SETTLEMENT_STATUSES = ("open", "submitted", "settled", "failed")
SETTLEMENT_MODES = ("escrow_allowance", "manual")

RECONCILE_BATCH = 50
MAX_UNITS_PER_CALL = 1_000_000
MAX_HISTORY = 200

EPSILON = 1e-9

#: 链上绑定走到的终态 → 结算单状态
_BINDING_DONE = {
    "settled": "settled",
    "slashed": "failed",
    "cancelled": "failed",
}


class UsageBillingError(Exception):
    """带 HTTP 状态的领域错误，路由层直接翻译。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def estimate_amount(units: int, unit_price_usdc: float) -> float:
    """一次调用的金额：单价 × 计量单位数，6 位小数。"""
    try:
        count = int(units)
    except (TypeError, ValueError):
        raise UsageBillingError(400, "units 必须是整数") from None
    if count <= 0 or count > MAX_UNITS_PER_CALL:
        raise UsageBillingError(400, f"units 必须在 1 - {MAX_UNITS_PER_CALL} 之间")
    return round(count * float(unit_price_usdc or 0.0), 6)


def normalize_request_id(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text or len(text) > 80:
        raise UsageBillingError(400, "request_id 必填（1-80 字符）—— 它是一次调用的幂等键")
    return text


# ------------------------------------------------------------------- 计费器


async def get_meter(
    db: AsyncSession, *, skill_id: str, payer_identity_id: str
) -> UsageMeterModel | None:
    return (
        await db.execute(
            select(UsageMeterModel).where(
                UsageMeterModel.skill_id == skill_id,
                UsageMeterModel.payer_identity_id == payer_identity_id,
            )
        )
    ).scalars().first()


async def get_or_create_meter(
    db: AsyncSession, *, skill: SkillModel, payer_identity_id: str
) -> UsageMeterModel:
    row = await get_meter(db, skill_id=skill.skill_id, payer_identity_id=payer_identity_id)
    if row is not None:
        return row
    row = UsageMeterModel(
        skill_id=skill.skill_id,
        payer_identity_id=payer_identity_id,
        provider_identity_id=skill.owner_identity_id,
        threshold_usdc=float(skill.settlement_threshold_usdc or 0.0),
        cap_usdc=skill.default_cap_usdc,
        status="open",
    )
    db.add(row)
    await db.flush()
    return row


def assert_meter_allows(meter: UsageMeterModel, *, amount: float) -> None:
    """边界检查：状态可用 + 不越过上限。超了就在这里拒绝，别等出账才发现。"""
    if str(meter.status or "open") != "open":
        raise UsageBillingError(
            409, f"这个计费器当前状态是 {meter.status}，已停止接受新的调用"
        )
    cap = meter.cap_usdc
    if cap is None:
        return
    used = float(meter.billed_usdc or 0.0) + float(meter.accrued_usdc or 0.0)
    if used + float(amount) > float(cap) + EPSILON:
        raise UsageBillingError(
            409,
            f"超出这个身份的调用上限：已用 {round(used, 6)}，本次 {round(float(amount), 6)}，"
            f"上限 {float(cap)}。请提高额度或换一个计费器",
        )


# --------------------------------------------------------------------- 记账


def charge_view(row: UsageChargeModel) -> dict[str, Any]:
    return {
        "charge_id": row.charge_id,
        "request_id": row.request_id,
        "skill_id": row.skill_id,
        "payer_identity_id": row.payer_identity_id,
        "provider_identity_id": row.provider_identity_id,
        "units": int(row.units or 0),
        "unit_price_usdc": float(row.unit_price_usdc or 0.0),
        "amount_usdc": float(row.amount_usdc or 0.0),
        "settlement_id": row.settlement_id,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


def meter_view(row: UsageMeterModel) -> dict[str, Any]:
    accrued = float(row.accrued_usdc or 0.0)
    billed = float(row.billed_usdc or 0.0)
    return {
        "meter_id": row.meter_id,
        "skill_id": row.skill_id,
        "payer_identity_id": row.payer_identity_id,
        "provider_identity_id": row.provider_identity_id,
        "calls": int(row.calls or 0),
        "accrued_usdc": round(accrued, 6),
        "billed_usdc": round(billed, 6),
        "settled_usdc": round(float(row.settled_usdc or 0.0), 6),
        "pending_usdc": round(accrued, 6),
        "threshold_usdc": float(row.threshold_usdc or 0.0),
        "cap_usdc": float(row.cap_usdc) if row.cap_usdc is not None else None,
        "status": row.status,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


def settlement_view(row: UsageSettlementModel) -> dict[str, Any]:
    return {
        "settlement_id": row.settlement_id,
        "skill_id": row.skill_id,
        "payer_identity_id": row.payer_identity_id,
        "provider_identity_id": row.provider_identity_id,
        "amount_usdc": float(row.amount_usdc or 0.0),
        "stake_usdc": float(row.stake_usdc or 0.0),
        "calls": int(row.calls or 0),
        "status": row.status,
        "mode": row.mode,
        "digest": row.digest,
        "escrow_binding_id": row.escrow_binding_id,
        "tx_hash": row.tx_hash,
        "failure_reason": row.failure_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
    }


async def record_usage(
    db: AsyncSession,
    *,
    skill: SkillModel,
    payer_identity_id: str,
    request_id: str,
    units: int = 1,
    occurred_at: datetime | None = None,
    provider_identity_id: str | None = None,
) -> dict[str, Any]:
    """记一次调用。幂等：同一个 request_id 重放时原样返回第一次的结果。"""
    rid = normalize_request_id(request_id)
    provider = (provider_identity_id or skill.owner_identity_id or "").strip()
    if not provider:
        raise UsageBillingError(409, "这个技能没有归属主体，不能计费")
    if provider == payer_identity_id:
        raise UsageBillingError(409, "不能给自己的技能计费（付款方与提供方必须是不同主体）")

    existing = (
        await db.execute(
            select(UsageChargeModel).where(
                UsageChargeModel.skill_id == skill.skill_id,
                UsageChargeModel.request_id == rid,
            )
        )
    ).scalars().first()
    if existing is not None:
        meter = await get_meter(
            db, skill_id=skill.skill_id, payer_identity_id=payer_identity_id
        )
        logger.info(
            "usage_charge_replayed",
            skill_id=skill.skill_id,
            request_id=rid,
            payer_identity_id=payer_identity_id,
        )
        return {
            "charge": charge_view(existing),
            "meter": meter_view(meter) if meter is not None else None,
            "duplicate": True,
            "amount_usdc": float(existing.amount_usdc or 0.0),
            "units": int(existing.units or 0),
        }

    amount = estimate_amount(units, skill.unit_price_usdc)
    meter = await get_or_create_meter(db, skill=skill, payer_identity_id=payer_identity_id)
    assert_meter_allows(meter, amount=amount)

    stamp = occurred_at or datetime.utcnow()
    row = UsageChargeModel(
        request_id=rid,
        skill_id=skill.skill_id,
        payer_identity_id=payer_identity_id,
        provider_identity_id=provider,
        units=int(units),
        unit_price_usdc=float(skill.unit_price_usdc or 0.0),
        amount_usdc=amount,
        occurred_at=stamp,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    meter.calls = int(meter.calls or 0) + int(units)
    meter.accrued_usdc = round(float(meter.accrued_usdc or 0.0) + amount, 6)
    meter.last_used_at = stamp
    meter.updated_at = datetime.utcnow()
    await db.flush()
    return {
        "charge": charge_view(row),
        "meter": meter_view(meter),
        "duplicate": False,
        "amount_usdc": amount,
        "units": int(units),
    }


# --------------------------------------------------------------------- 出账


async def unsettled_charges(
    db: AsyncSession,
    *,
    skill_id: str,
    payer_identity_id: str,
    cutoff: datetime,
) -> list[UsageChargeModel]:
    """到 ``cutoff`` 为止、还没有被任何结算单收走的流水。

    ``occurred_at <= cutoff`` 是刻意的：出账计算必须有一个明确的时点，
    这个时点之后到达的调用属于下一张单子，不能被提前算进这一张。
    """
    stmt = (
        select(UsageChargeModel)
        .where(UsageChargeModel.skill_id == skill_id)
        .where(UsageChargeModel.payer_identity_id == payer_identity_id)
        .where(UsageChargeModel.settlement_id.is_(None))
        .where(UsageChargeModel.occurred_at <= cutoff)
        .order_by(UsageChargeModel.occurred_at, UsageChargeModel.charge_id)
    )
    return list((await db.execute(stmt)).scalars().all())


def settlement_digest(
    *, skill_id: str, payer_identity_id: str, amount_usdc: float, calls: int, charges: list[UsageChargeModel]
) -> str:
    body = "|".join(
        [skill_id, payer_identity_id, f"{float(amount_usdc):.6f}", str(int(calls))]
        + [f"{c.charge_id}:{float(c.amount_usdc or 0.0):.6f}" for c in charges]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


async def _pick_bill(db: AsyncSession, identity_id: str, need_usdc: float) -> str | None:
    """挑一张还划得动的账单：未关闭、剩余额度够这一单，取剩余最多的那张。"""
    rows = await escrow.list_commits(db, identity_id)
    best: tuple[float, str] | None = None
    for row in rows:
        if row.state != escrow.IDLE:
            continue
        # 旧合约上的账单在当前合约里不存在（``available()`` 直接 revert），而且
        # 旧合约没有「验证通过才开窗」那道闸 —— 新单一律只用当前合约的账单。
        if not escrow.bill_is_spendable(row):
            continue
        free = float(row.amount_usdc or 0.0) - float(row.spent_usdc or 0.0) - float(
            row.reserved_usdc or 0.0
        )
        if free + EPSILON < need_usdc:
            continue
        if best is None or free > best[0]:
            best = (free, str(row.bill_id))
    return best[1] if best else None


async def settle_meter(
    db: AsyncSession,
    *,
    skill: SkillModel,
    payer_identity_id: str,
    cutoff: datetime | None = None,
    allow_chain: bool = True,
) -> dict[str, Any] | None:
    """到阈值就出账；能上链就顺手把划转提交上去。没到阈值返回 ``None``。"""
    stamp = cutoff or datetime.utcnow()
    meter = await get_meter(db, skill_id=skill.skill_id, payer_identity_id=payer_identity_id)
    if meter is None:
        return None

    charges = await unsettled_charges(
        db,
        skill_id=skill.skill_id,
        payer_identity_id=payer_identity_id,
        cutoff=stamp,
    )
    amount = round(sum(float(c.amount_usdc or 0.0) for c in charges), 6)
    threshold = float(meter.threshold_usdc or 0.0)
    if amount <= 0 or amount + EPSILON < threshold:
        return None

    calls = sum(int(c.units or 0) for c in charges)
    stake = seller_stake.required_stake_usdc(amount)
    on_chain = bool(allow_chain and escrow.can_server_settle())

    row = UsageSettlementModel(
        skill_id=skill.skill_id,
        payer_identity_id=payer_identity_id,
        provider_identity_id=skill.owner_identity_id,
        amount_usdc=amount,
        stake_usdc=stake,
        calls=calls,
        status="open",
        mode="escrow_allowance" if on_chain else "manual",
        digest=settlement_digest(
            skill_id=skill.skill_id,
            payer_identity_id=payer_identity_id,
            amount_usdc=amount,
            calls=calls,
            charges=charges,
        ),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()

    # 流水钉进这张单子：无论后面成不成，这些调用都不会被第二次计价。
    for charge in charges:
        charge.settlement_id = row.settlement_id
    meter.accrued_usdc = round(float(meter.accrued_usdc or 0.0) - amount, 6)
    meter.billed_usdc = round(float(meter.billed_usdc or 0.0) + amount, 6)
    meter.updated_at = datetime.utcnow()
    await db.flush()

    if not on_chain:
        row.failure_reason = "结算通道未开通（Karma 运营账户未配置），已出账待执行"
        row.updated_at = datetime.utcnow()
        await db.flush()
        logger.warning(
            "usage_settlement_recorded_without_chain",
            settlement_id=row.settlement_id,
            amount_usdc=amount,
            mode=row.mode,
        )
        return {"settlement": settlement_view(row), "charged": False, "reason": row.failure_reason}

    buyer_bill = await _pick_bill(db, payer_identity_id, amount)
    seller_bill = await _pick_bill(db, str(skill.owner_identity_id), stake)
    if buyer_bill is None or seller_bill is None:
        missing = "付款方" if buyer_bill is None else "提供方"
        row.failure_reason = (
            f"{missing}可用锁仓额度不足：本单需要付款方 {amount} USDC、"
            f"提供方质押 {stake} USDC。请在操作台补足锁仓后重试"
        )
        row.updated_at = datetime.utcnow()
        await db.flush()
        logger.warning(
            "usage_settlement_waiting_for_funds",
            settlement_id=row.settlement_id,
            amount_usdc=amount,
            stake_usdc=stake,
        )
        return {"settlement": settlement_view(row), "charged": False, "reason": row.failure_reason}

    task_id = f"usage-{row.settlement_id}"[:64]
    scope = f"{settings.settlement_scope}:skill:{skill.slug}"[:120]
    proof = f"usage:{row.settlement_id}:{row.digest}"
    try:
        result = escrow.open_and_submit_order(
            buyer_bill_id=buyer_bill,
            seller_bill_id=seller_bill,
            amount_usdc=amount,
            stake_usdc=stake,
            scope=scope,
            task_id=task_id,
            proof=proof,
            contract_address=escrow.configured_address(),
        )
    except Exception as exc:  # noqa: BLE001 - 出账已经落地，链上失败要如实记下
        row.failure_reason = f"链上提交失败：{exc}"[:500]
        row.updated_at = datetime.utcnow()
        await db.flush()
        logger.warning(
            "usage_settlement_chain_failed",
            settlement_id=row.settlement_id,
            amount_usdc=amount,
            error=str(exc),
        )
        return {"settlement": settlement_view(row), "charged": False, "reason": row.failure_reason}

    binding = EscrowBindingModel(
        binding_id=str(result["binding_id"]),
        buyer_identity_id=payer_identity_id,
        seller_identity_id=str(skill.owner_identity_id),
        buyer_bill_id=buyer_bill,
        seller_bill_id=seller_bill,
        contract_address=escrow.configured_address(),
        scope_hash=result["scope_hash"],
        task_id=task_id,
        amount_usdc=amount,
        stake_usdc=stake,
        state="finalizing",
        proof_hash=result["proof_hash"],
        bind_tx_hash=result["bind_tx_hash"],
        submit_tx_hash=result["submit_tx_hash"],
        pull_after=int(result["pull_after"] or 0),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(binding)
    row.escrow_binding_id = str(result["binding_id"])
    row.status = "submitted"
    row.failure_reason = None
    row.updated_at = datetime.utcnow()
    await db.flush()
    logger.info(
        "usage_settlement_submitted",
        settlement_id=row.settlement_id,
        binding_id=row.escrow_binding_id,
        amount_usdc=amount,
        stake_usdc=stake,
    )
    return {"settlement": settlement_view(row), "charged": True, "reason": None}


# ----------------------------------------------------------------- 对账回写


async def reconcile_settlements(db: AsyncSession, *, limit: int = RECONCILE_BATCH) -> list[dict[str, Any]]:
    """看链上绑定走到哪一步，把结算单的状态追平。

    链上结了 → ``settled``（这是 ``settled_usdc`` 唯一会增长的地方）；
    链上被罚没 / 取消 → ``failed``，并把调用退回待出账，让它们有机会重新结算。
    """
    rows = (
        await db.execute(
            select(UsageSettlementModel)
            .where(UsageSettlementModel.status == "submitted")
            .order_by(UsageSettlementModel.created_at)
            .limit(max(1, int(limit)))
        )
    ).scalars().all()
    changed: list[dict[str, Any]] = []
    for row in rows:
        if not row.escrow_binding_id:
            continue
        binding = await db.get(EscrowBindingModel, str(row.escrow_binding_id))
        if binding is None:
            continue
        target = _BINDING_DONE.get(str(binding.state or ""))
        if target is None:
            continue
        meter = await get_meter(
            db, skill_id=row.skill_id, payer_identity_id=row.payer_identity_id
        )
        amount = float(row.amount_usdc or 0.0)
        if target == "settled":
            row.status = "settled"
            row.tx_hash = binding.finalize_tx_hash or binding.submit_tx_hash
            row.settled_at = datetime.utcnow()
            row.failure_reason = None
            if meter is not None:
                meter.settled_usdc = round(float(meter.settled_usdc or 0.0) + amount, 6)
                meter.updated_at = datetime.utcnow()
        else:
            row.status = "failed"
            row.failure_reason = f"链上状态：{binding.state}"
            row.updated_at = datetime.utcnow()
            if meter is not None:
                meter.billed_usdc = round(max(0.0, float(meter.billed_usdc or 0.0) - amount), 6)
                meter.accrued_usdc = round(float(meter.accrued_usdc or 0.0) + amount, 6)
                meter.updated_at = datetime.utcnow()
            for charge in (
                await db.execute(
                    select(UsageChargeModel).where(
                        UsageChargeModel.settlement_id == row.settlement_id
                    )
                )
            ).scalars().all():
                charge.settlement_id = None
        changed.append(settlement_view(row))
        logger.info(
            "usage_settlement_reconciled",
            settlement_id=row.settlement_id,
            status=row.status,
            binding_state=binding.state,
        )
    if changed:
        await db.flush()
    return changed


# --------------------------------------------------------------------- 视图


async def billing_state(
    db: AsyncSession,
    *,
    skill_id: str,
    payer_identity_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """收付中心看的一段：计费器 + 最近流水 + 结算单。"""
    meter = await get_meter(db, skill_id=skill_id, payer_identity_id=payer_identity_id)
    top = max(1, min(int(limit), MAX_HISTORY))
    charges = (
        await db.execute(
            select(UsageChargeModel)
            .where(UsageChargeModel.skill_id == skill_id)
            .where(UsageChargeModel.payer_identity_id == payer_identity_id)
            .order_by(UsageChargeModel.occurred_at.desc())
            .limit(top)
        )
    ).scalars().all()
    settlements = (
        await db.execute(
            select(UsageSettlementModel)
            .where(UsageSettlementModel.skill_id == skill_id)
            .where(UsageSettlementModel.payer_identity_id == payer_identity_id)
            .order_by(UsageSettlementModel.created_at.desc())
            .limit(top)
        )
    ).scalars().all()
    return {
        "skill_id": skill_id,
        "payer_identity_id": payer_identity_id,
        "meter": meter_view(meter) if meter is not None else None,
        "charges": [charge_view(c) for c in charges],
        "settlements": [settlement_view(s) for s in settlements],
    }


__all__ = [
    "EPSILON",
    "MAX_HISTORY",
    "MAX_UNITS_PER_CALL",
    "METER_STATUSES",
    "SETTLEMENT_MODES",
    "SETTLEMENT_STATUSES",
    "UsageBillingError",
    "assert_meter_allows",
    "billing_state",
    "charge_view",
    "estimate_amount",
    "get_meter",
    "get_or_create_meter",
    "meter_view",
    "normalize_request_id",
    "reconcile_settlements",
    "record_usage",
    "settle_meter",
    "settlement_digest",
    "settlement_view",
    "unsettled_charges",
]
