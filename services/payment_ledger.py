"""收付中心台账（只读）——把一个身份名下的「单」归一成同一种条目。

一个身份的收付来自四张表，这里把它们拉平成同一种形状，前端「收付中心」
只调一个接口就能画出：总览 / 收入明细 / 支出明细 / 确认区 / 争议区。

     settlements        任务结算单（client_agent_id=付款方，worker_agent_id=收款方）
     escrow_bindings    链上双边结算单（真 USDC 从买家钱包直付卖家钱包）
     vouchers           付款授权码（买家发起 → 卖家接单）
     allowance_commits  锁仓凭证（主身份的 USDC 承诺，钱还在自己钱包里）

三条硬约束：
- 只读。不写库、不改状态、不碰任何私钥。
- 只认本人：调用方解析出的 identity 就是唯一作用域；显式传别人的 id 一律拒绝。
- 子身份视角按档案 id 过滤，付款方一侧和收款方一侧都算归属，绝不混账。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import (
    AllowanceCommitModel,
    EscrowBindingModel,
    SettlementModel,
    SettlementTransitionAuditModel,
    VoucherEventModel,
    VoucherModel,
)

PHASE_ACTIVE = "active"
PHASE_CONFIRM = "confirm"
PHASE_DISPUTE = "dispute"
PHASE_CLOSED = "closed"

SETTLEMENT_PHASE = {
    "draft": PHASE_ACTIVE,
    "pending": PHASE_ACTIVE,
    "accepted": PHASE_ACTIVE,
    "in_progress": PHASE_ACTIVE,
    "progress_confirmed": PHASE_ACTIVE,
    "progress_submitted": PHASE_CONFIRM,
    "delivered": PHASE_CONFIRM,
    "disputed": PHASE_DISPUTE,
    "arbitrated": PHASE_DISPUTE,
    "settled": PHASE_CLOSED,
    "refunded": PHASE_CLOSED,
    "cancelled": PHASE_CLOSED,
}

BINDING_PHASE = {
    "none": PHASE_ACTIVE,
    "active": PHASE_ACTIVE,
    "finalizing": PHASE_CONFIRM,
    "settled": PHASE_CLOSED,
    "slashed": PHASE_CLOSED,
    "cancelled": PHASE_CLOSED,
}

VOUCHER_PHASE = {
    "created": PHASE_ACTIVE,
    "accepted": PHASE_CONFIRM,
    "used": PHASE_CLOSED,
    "expired": PHASE_CLOSED,
    "cancelled": PHASE_CLOSED,
    "rejected": PHASE_CLOSED,
}

KIND_LABELS = {
    "settlement": "任务结算单",
    "binding": "链上结算单",
    "voucher": "付款授权码",
    "lock": "锁仓凭证",
}

_READ_LIMIT = 1000


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _round(value: Any) -> float:
    return round(_num(value), 6)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _sort_key(entry: dict) -> str:
    return str(entry.get("updated_at") or entry.get("created_at") or "")


def _base_entry(
    *,
    kind: str,
    ref_id: str,
    title: str,
    role: str,
    amount_usdc: float,
    status: str,
    phase: str,
    identity_id: str,
    counterparty_identity_id: str | None,
    profile_id: str | None,
    counterparty_profile_id: str | None,
    task_id: str | None,
    created_at: Any,
    updated_at: Any,
    detail: dict,
    settled_usdc: float = 0.0,
    refunded_usdc: float = 0.0,
) -> dict:
    return {
        "entry_id": kind + ":" + str(ref_id),
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "ref_id": str(ref_id),
        "title": title,
        "role": role,
        "direction": "out" if role == "payer" else "in",
        "amount_usdc": _round(amount_usdc),
        "settled_usdc": _round(settled_usdc),
        "refunded_usdc": _round(refunded_usdc),
        "status": status or "unknown",
        "phase": phase,
        "identity_id": identity_id,
        "counterparty_identity_id": counterparty_identity_id,
        "profile_id": profile_id,
        "counterparty_profile_id": counterparty_profile_id,
        "task_id": task_id,
        "currency": "USDC",
        "created_at": _iso(created_at),
        "updated_at": _iso(updated_at),
        "detail": detail,
    }


def settlement_entry(row: SettlementModel, identity_id: str) -> dict:
    is_payer = row.client_agent_id == identity_id
    status = str(row.status or "")
    settled = _num(row.released_amount) if status == "settled" else 0.0
    return _base_entry(
        kind="settlement",
        ref_id=row.task_id,
        title="任务结算 · " + str(row.task_id),
        role="payer" if is_payer else "payee",
        amount_usdc=_num(row.escrow_amount),
        settled_usdc=settled,
        refunded_usdc=_num(row.refunded_amount),
        status=status,
        phase=SETTLEMENT_PHASE.get(status, PHASE_ACTIVE),
        identity_id=identity_id,
        counterparty_identity_id=(row.worker_agent_id if is_payer else row.client_agent_id),
        profile_id=(row.profile_id if is_payer else getattr(row, "worker_profile_id", None)),
        counterparty_profile_id=(
            getattr(row, "worker_profile_id", None) if is_payer else row.profile_id
        ),
        task_id=row.task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        detail={
            "settlement_id": row.settlement_id,
            "settlement_mode": getattr(row, "settlement_mode", None),
            "voucher_id": getattr(row, "voucher_id", None),
            "dispute_reason": row.dispute_reason,
            "arbitration_notes": row.arbitration_notes,
            "released_at": _iso(row.released_at),
            "delivery_deadline_at": _iso(getattr(row, "delivery_deadline_at", None)),
            "chain_id": getattr(row, "chain_id", None),
            "tx_hash": getattr(row, "tx_hash", None),
            "release_amount": _round(row.released_amount),
            "refund_amount": _round(row.refunded_amount),
        },
    )


def binding_entry(row: EscrowBindingModel, identity_id: str) -> dict:
    is_payer = row.buyer_identity_id == identity_id
    state = str(row.state or "")
    return _base_entry(
        kind="binding",
        ref_id=str(row.binding_id),
        title="链上结算 · " + str(row.task_id or row.binding_id),
        role="payer" if is_payer else "payee",
        amount_usdc=_num(row.amount_usdc),
        settled_usdc=(_num(row.amount_usdc) if state == "settled" else 0.0),
        status=state,
        phase=BINDING_PHASE.get(state, PHASE_ACTIVE),
        identity_id=identity_id,
        counterparty_identity_id=(row.seller_identity_id if is_payer else row.buyer_identity_id),
        profile_id=(row.buyer_profile_id if is_payer else getattr(row, "seller_profile_id", None)),
        counterparty_profile_id=(
            getattr(row, "seller_profile_id", None) if is_payer else row.buyer_profile_id
        ),
        task_id=row.task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        detail={
            "binding_id": row.binding_id,
            "stake_usdc": _round(row.stake_usdc),
            "buyer_bill_id": row.buyer_bill_id,
            "seller_bill_id": row.seller_bill_id,
            "proof_hash": row.proof_hash,
            "bind_tx_hash": row.bind_tx_hash,
            "submit_tx_hash": row.submit_tx_hash,
            "finalize_tx_hash": row.finalize_tx_hash,
            "pull_after": row.pull_after,
        },
    )


def voucher_entry(row: VoucherModel, identity_id: str) -> dict:
    is_payer = row.buyer_identity_id == identity_id
    status = str(row.status or "")
    return _base_entry(
        kind="voucher",
        ref_id=row.voucher_id,
        title="付款授权码 · " + str(row.task_type or ""),
        role="payer" if is_payer else "payee",
        amount_usdc=_num(row.amount),
        settled_usdc=(_num(row.amount) if status == "used" else 0.0),
        status=status,
        phase=VOUCHER_PHASE.get(status, PHASE_ACTIVE),
        identity_id=identity_id,
        counterparty_identity_id=(row.seller_identity_id if is_payer else row.buyer_identity_id),
        profile_id=(row.profile_id if is_payer else getattr(row, "seller_profile_id", None)),
        counterparty_profile_id=(
            getattr(row, "seller_profile_id", None) if is_payer else row.profile_id
        ),
        task_id=getattr(row, "task_id", None),
        created_at=row.created_at,
        updated_at=row.accepted_at or row.created_at,
        detail={
            "voucher_id": row.voucher_id,
            "task_type": row.task_type,
            "expiry_time": _iso(row.expiry_time),
            "accepted_at": _iso(row.accepted_at),
            "rejection_reason": getattr(row, "rejection_reason", None),
            "buyer_signature": row.buyer_signature,
            "bill_credit_amount": _round(row.bill_credit_amount),
            "payment_mode": getattr(row, "payment_mode", None),
        },
    )


def lock_entry(row: AllowanceCommitModel, identity_id: str) -> dict:
    state = str(row.state or "")
    available = _num(row.amount_usdc) - _num(row.spent_usdc) - _num(row.reserved_usdc)
    return _base_entry(
        kind="lock",
        ref_id=str(row.bill_id),
        title="锁仓凭证 · Bill #" + str(row.bill_id),
        role="payer",
        amount_usdc=_num(row.amount_usdc),
        settled_usdc=_num(row.spent_usdc),
        refunded_usdc=(available if state == "revoked" else 0.0),
        status=state,
        phase=PHASE_ACTIVE if state == "open" else PHASE_CLOSED,
        identity_id=identity_id,
        counterparty_identity_id=None,
        profile_id=None,
        counterparty_profile_id=None,
        task_id=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        detail={
            "bill_id": row.bill_id,
            "wallet_address": row.wallet_address,
            "operator": row.operator,
            "chain_id": row.chain_id,
            "contract_address": row.contract_address,
            "reserved_usdc": _round(row.reserved_usdc),
            "available_usdc": _round(available),
            "backed": bool(row.backed),
            "commit_tx_hash": row.commit_tx_hash,
            "revoke_tx_hash": row.revoke_tx_hash,
        },
    )


async def _settlements_for(db: AsyncSession, identity_id: str) -> list[SettlementModel]:
    result = await db.execute(
        select(SettlementModel)
        .where(
            or_(
                SettlementModel.client_agent_id == identity_id,
                SettlementModel.worker_agent_id == identity_id,
            )
        )
        .order_by(SettlementModel.created_at.desc())
        .limit(_READ_LIMIT)
    )
    return list(result.scalars().all())


async def _bindings_for(db: AsyncSession, identity_id: str) -> list[EscrowBindingModel]:
    result = await db.execute(
        select(EscrowBindingModel)
        .where(
            or_(
                EscrowBindingModel.buyer_identity_id == identity_id,
                EscrowBindingModel.seller_identity_id == identity_id,
            )
        )
        .order_by(EscrowBindingModel.created_at.desc())
        .limit(_READ_LIMIT)
    )
    return list(result.scalars().all())


async def _vouchers_for(db: AsyncSession, identity_id: str) -> list[VoucherModel]:
    result = await db.execute(
        select(VoucherModel)
        .where(
            or_(
                VoucherModel.buyer_identity_id == identity_id,
                VoucherModel.seller_identity_id == identity_id,
            )
        )
        .order_by(VoucherModel.created_at.desc())
        .limit(_READ_LIMIT)
    )
    return list(result.scalars().all())


async def _commits_for(db: AsyncSession, identity_id: str) -> list[AllowanceCommitModel]:
    result = await db.execute(
        select(AllowanceCommitModel)
        .where(AllowanceCommitModel.identity_id == identity_id)
        .order_by(AllowanceCommitModel.created_at.desc())
        .limit(_READ_LIMIT)
    )
    return list(result.scalars().all())


def entry_belongs_to_profile(entry: dict, profile_id: str) -> bool:
    return entry.get("profile_id") == profile_id or entry.get("counterparty_profile_id") == profile_id


def summarize(entries: list[dict]) -> dict:
    """总览数字：只有真金已结算的才算「已收 / 已付」。"""
    income = expense = in_flight = pending_income = 0.0
    status_counts: dict[str, int] = {}
    counts = {"total": len(entries), "income": 0, "expense": 0, "confirm": 0, "dispute": 0}
    for entry in entries:
        status = str(entry.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if entry["direction"] == "in":
            counts["income"] += 1
        else:
            counts["expense"] += 1
        phase = entry.get("phase")
        if phase == PHASE_CONFIRM:
            counts["confirm"] += 1
        elif phase == PHASE_DISPUTE:
            counts["dispute"] += 1

        amount = _num(entry.get("amount_usdc"))
        settled = _num(entry.get("settled_usdc"))
        if phase == PHASE_CLOSED:
            if entry["direction"] == "in":
                income += settled or amount
            else:
                expense += settled or amount
        elif phase in (PHASE_ACTIVE, PHASE_CONFIRM, PHASE_DISPUTE):
            # 争议中的钱同样被占着：不能算已付，也不能算可用。
            if entry["direction"] == "in":
                pending_income += amount
            else:
                in_flight += amount

    locked = sum(
        _num(e.get("amount_usdc"))
        for e in entries
        if e["kind"] == "lock" and e["status"] == "open"
    )
    reserved = sum(
        _num((e.get("detail") or {}).get("reserved_usdc"))
        for e in entries
        if e["kind"] == "lock" and e["status"] == "open"
    )
    return {
        "income_usdc": round(income, 6),
        "expense_usdc": round(expense, 6),
        "net_usdc": round(income - expense, 6),
        "in_flight_usdc": round(in_flight, 6),
        "pending_income_usdc": round(pending_income, 6),
        "locked_usdc": round(locked, 6),
        "locked_reserved_usdc": round(reserved, 6),
        "counts": counts,
        "status_counts": status_counts,
    }


async def build_ledger(
    db: AsyncSession,
    *,
    identity_id: str,
    profile_id: str | None = None,
    include_locks: bool = True,
) -> dict:
    """拉平一个身份的收付条目（未分页、未按 tab 过滤）。"""
    entries: list[dict] = []
    for row in await _settlements_for(db, identity_id):
        entries.append(settlement_entry(row, identity_id))
    for row in await _bindings_for(db, identity_id):
        entries.append(binding_entry(row, identity_id))
    for row in await _vouchers_for(db, identity_id):
        entries.append(voucher_entry(row, identity_id))
    if include_locks:
        for row in await _commits_for(db, identity_id):
            entries.append(lock_entry(row, identity_id))

    if profile_id:
        entries = [e for e in entries if entry_belongs_to_profile(e, profile_id)]

    entries.sort(key=_sort_key, reverse=True)
    return {"entries": entries, "summary": summarize(entries)}


async def settlement_history(db: AsyncSession, task_id: str, limit: int = 100) -> list[dict]:
    result = await db.execute(
        select(SettlementTransitionAuditModel)
        .where(SettlementTransitionAuditModel.task_id == task_id)
        .order_by(SettlementTransitionAuditModel.created_at.asc())
        .limit(limit)
    )
    return [
        {
            "at": _iso(row.created_at),
            "from_status": row.from_status,
            "to_status": row.to_status,
            "allowed": bool(row.transition_allowed),
            "guard_stage": row.guard_stage,
            "reason": row.reason,
            "route_path": row.route_path,
            "actor_id": row.actor_id,
        }
        for row in result.scalars().all()
    ]


async def voucher_history(db: AsyncSession, voucher_id: str, limit: int = 100) -> list[dict]:
    result = await db.execute(
        select(VoucherEventModel)
        .where(VoucherEventModel.voucher_id == voucher_id)
        .order_by(VoucherEventModel.created_at.asc())
        .limit(limit)
    )
    return [
        {
            "at": _iso(row.created_at),
            "event_type": row.event_type,
            "actor_identity_id": row.actor_identity_id,
            "target_identity_id": row.target_identity_id,
            "payload": row.payload or {},
        }
        for row in result.scalars().all()
    ]
