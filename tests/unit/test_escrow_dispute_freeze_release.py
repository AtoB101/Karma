"""链上终局之后，业务侧那份「争议冻结」和业务状态机必须跟着走。

2026-09-21 真钱实测抓到的漏账（两笔，各 0.2）：业务停在 ``disputed``、链上早已
``cancelled`` ——

* ``capacity.disputed_credits`` 永远留在账上，操作台永久显示「争议冻结 N，等待仲裁推进」；
* ``assert_can_release_locked_funds`` 永远拒绝解锁（责任状态没清），用户锁在托管里的钱取不回来。

根因：链上终局并不总从 API 走。裁定方直接在链上撤了绑定、或者保护期到点后别人先推了
``finalizeSettlement``，这些由 ``escrow_autosettle`` 的兜底那一遍补台账，而那条路过去
只写 ``onchain_status`` —— ``apply_capacity_resolution`` 与业务状态机一步都没走。

这些用例钉死三件事：

1. 链上终局 + 业务停在争议 -> 冻结必须被放掉，且业务状态机只走 ``VALID_TRANSITIONS`` 里有的边；
2. 业务已经终局的单子，这一层必须是空操作 —— 否则会把**同一账上另一笔争议**的冻结挪走；
3. 冻结放不掉（并发冲突）时必须留着 ``disputed`` 当重试锚点，不能假装成功。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from core.schemas import CapacityState
from db.models.orm import CapacityModel, SettlementModel, SettlementTransitionAuditModel
from services import atomic_ledger, capacity_resolution
from services.capacity_ledger import assert_can_release_locked_funds, assert_capacity_invariants
from services.chain import allowance_escrow as escrow
from services.chain import escrow_autosettle, escrow_settlement

PREFIX = "task-dispute-freeze"
TASK = PREFIX + "-n1"
TASK_SETTLED = PREFIX + "-settled"
TASK_OTHER = PREFIX + "-other"
BUYER = "kid_dispute_freeze_buyer"
SELLER = "kid_dispute_freeze_seller"
TOTAL = 12.0


@pytest.fixture(autouse=True)
async def _clean(db_session):
    for model in (SettlementTransitionAuditModel,):
        await db_session.execute(delete(model).where(model.task_id.like(PREFIX + "%")))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id.like(PREFIX + "%")))
    await db_session.execute(delete(CapacityModel).where(CapacityModel.identity_id == BUYER))
    await db_session.commit()
    yield
    for model in (SettlementTransitionAuditModel,):
        await db_session.execute(delete(model).where(model.task_id.like(PREFIX + "%")))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id.like(PREFIX + "%")))
    await db_session.execute(delete(CapacityModel).where(CapacityModel.identity_id == BUYER))
    await db_session.commit()


async def _dispute_frozen_books(db, *, disputed: float, escrow_amount: float = 0.2) -> CapacityModel:
    """买方账上：锁仓 TOTAL，其中 ``disputed`` 被一笔争议冻着。"""
    cap = CapacityModel(
        identity_id=BUYER,
        total_locked_usdc=TOTAL,
        total_bill_credits=TOTAL,
        available_credits=TOTAL - disputed,
        disputed_credits=disputed,
    )
    db.add(cap)
    await db.flush()
    return cap


async def _settlement(
    db,
    *,
    task_id: str,
    status: str = "disputed",
    onchain_status: str = "cancelled",
    escrow_amount: float = 0.2,
) -> SettlementModel:
    row = SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=escrow_amount,
        currency="USD",
        status=status,
        client_agent_id=BUYER,
        worker_agent_id=SELLER,
        onchain_status=onchain_status,
    )
    db.add(row)
    await db.flush()
    return row


def _state(cap: CapacityModel) -> CapacityState:
    return CapacityState(
        identity_id=cap.identity_id,
        total_locked_usdc=cap.total_locked_usdc,
        total_bill_credits=cap.total_bill_credits,
        available_credits=cap.available_credits,
        reserved_credits=cap.reserved_credits,
        in_progress_credits=cap.in_progress_credits,
        confirmed_progress_credits=cap.confirmed_progress_credits,
        disputed_credits=cap.disputed_credits,
        pending_settlement_credits=cap.pending_settlement_credits,
        burned_credits=cap.burned_credits,
        released_credits=cap.released_credits,
    )


# ------------------------------------------------------- 链上撤销：放冻结 + 推状态

@pytest.mark.asyncio
async def test_chain_cancel_releases_the_freeze_and_moves_the_business_status(db_session):
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(db_session, task_id=TASK, status="disputed", onchain_status="cancelled")

    out = await escrow_settlement.settle_chain_terminal_bookkeeping(
        db_session, task_id=TASK, onchain_status="cancelled"
    )

    assert out["freeze_released"] == pytest.approx(0.2)
    # 争议 -> 撤销没有直边，只能照状态机划好的路走（经 FROZEN 这一态）。
    assert out["status_hops"] == ["frozen", "cancelled"]

    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.0)
    assert cap.released_credits == pytest.approx(0.2)
    # 钱退回买方：锚点跟着责任一起降，可用额度一分不动（v2 非托管，钱一直在用户钱包里）。
    assert cap.total_bill_credits == pytest.approx(TOTAL - 0.2)
    assert cap.total_locked_usdc == pytest.approx(TOTAL - 0.2)
    assert cap.available_credits == pytest.approx(TOTAL - 0.2)
    # 账本内部必须自洽：total_bill_credits == 各责任桶之和。
    assert_capacity_invariants(_state(cap))

    fresh = await db_session.get(SettlementModel, "stl-" + TASK)
    await db_session.refresh(fresh)
    assert fresh.status == "cancelled"

    audits = (
        await db_session.execute(
            select(SettlementTransitionAuditModel)
            .where(SettlementTransitionAuditModel.task_id == TASK)
            .order_by(SettlementTransitionAuditModel.created_at)
        )
    ).scalars().all()
    assert [(a.from_status, a.to_status) for a in audits] == [
        ("disputed", "frozen"),
        ("frozen", "cancelled"),
    ]
    assert all(a.guard_stage == "chain_terminal" for a in audits)
    assert all(a.actor_id == escrow_settlement.CHAIN_ALIGN_ACTOR_ID for a in audits)


@pytest.mark.asyncio
async def test_the_freeze_is_what_was_blocking_the_unlock(db_session):
    """冻结在账上时锁仓解不开；链上终局补完账，解锁这道闸必须松开。"""
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(db_session, task_id=TASK, status="disputed", onchain_status="cancelled")
    blocked = await db_session.get(CapacityModel, BUYER)
    assert_capacity_invariants(_state(blocked))
    with pytest.raises(ValueError, match="active responsibility"):
        assert_can_release_locked_funds(_state(blocked), 1.0)

    await escrow_settlement.settle_chain_terminal_bookkeeping(
        db_session, task_id=TASK, onchain_status="cancelled"
    )

    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert_capacity_invariants(_state(cap))
    assert_can_release_locked_funds(_state(cap), 1.0)


@pytest.mark.asyncio
async def test_chain_settlement_burns_credit_and_goes_through_arbitration(db_session):
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(db_session, task_id=TASK_SETTLED, status="disputed", onchain_status="settled")

    out = await escrow_settlement.settle_chain_terminal_bookkeeping(
        db_session, task_id=TASK_SETTLED, onchain_status="settled"
    )

    assert out["freeze_released"] == pytest.approx(0.2)
    # 货款付给卖方 -> 记 burned；争议 -> 已结算也只能经 ARBITRATED。
    assert out["status_hops"] == ["arbitrated", "settled"]
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.0)
    assert cap.burned_credits == pytest.approx(0.2)
    assert cap.released_credits == pytest.approx(0.0)
    assert_capacity_invariants(_state(cap))


# ------------------------------------------------------- 不许动别人的冻结

@pytest.mark.asyncio
async def test_already_terminal_settlement_is_a_noop_and_never_steals_a_freeze(db_session):
    """业务早就终局（裁决那一笔已经放过了）-> 这一层必须一个字都不动。

    账上那 0.2 是**另一笔**还在争议里的单子的冻结。补账如果认不出这一点，
    就会把它当成自己的挪走 —— 那笔争议的裁决落地时只剩 409。
    """
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(
        db_session, task_id=TASK, status="refunded", onchain_status="slashed"
    )

    out = await escrow_settlement.settle_chain_terminal_bookkeeping(
        db_session, task_id=TASK, onchain_status="slashed"
    )

    assert out == {}
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.2)
    assert cap.released_credits == pytest.approx(0.0)
    audits = (
        await db_session.execute(
            select(SettlementTransitionAuditModel).where(
                SettlementTransitionAuditModel.task_id == TASK
            )
        )
    ).scalars().all()
    assert audits == []


@pytest.mark.asyncio
async def test_a_live_dispute_is_untouched(db_session):
    """链上还没终局：什么都不该发生（争议正当开着的时候账不能被动）。"""
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(db_session, task_id=TASK, status="disputed", onchain_status="breaching")

    assert await escrow_settlement.settle_chain_terminal_bookkeeping(
        db_session, task_id=TASK, onchain_status="breaching"
    ) == {}
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_release_is_idempotent(db_session):
    await _dispute_frozen_books(db_session, disputed=0.2)

    first = await capacity_resolution.release_dispute_freeze(
        db=db_session, buyer_identity_id=BUYER, escrow_amount=0.2, settled=False
    )
    second = await capacity_resolution.release_dispute_freeze(
        db=db_session, buyer_identity_id=BUYER, escrow_amount=0.2, settled=False
    )

    assert first == pytest.approx(0.2)
    assert second == pytest.approx(0.0)
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.released_credits == pytest.approx(0.2)
    assert cap.total_bill_credits == pytest.approx(TOTAL - 0.2)


@pytest.mark.asyncio
async def test_release_never_exceeds_this_bindings_escrow(db_session):
    """桶里冻着 0.5，这一单只有 0.2 —— 只能放掉自己那 0.2。"""
    await _dispute_frozen_books(db_session, disputed=0.5)

    released = await capacity_resolution.release_dispute_freeze(
        db=db_session, buyer_identity_id=BUYER, escrow_amount=0.2, settled=False
    )

    assert released == pytest.approx(0.2)
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.3)
    assert cap.total_bill_credits == pytest.approx(TOTAL - 0.2)
    assert_capacity_invariants(_state(cap))


# ------------------------------------------------------- 冲突：留着重试锚点

@pytest.mark.asyncio
async def test_conflict_keeps_disputed_as_the_retry_anchor(db_session, monkeypatch):
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(db_session, task_id=TASK, status="disputed", onchain_status="cancelled")

    async def _boom(*_a, **_kw):
        raise atomic_ledger.LedgerConflict("disputed freeze changed concurrently")

    monkeypatch.setattr(capacity_resolution, "release_dispute_freeze", _boom)

    out = await escrow_settlement.settle_chain_terminal_bookkeeping(
        db_session, task_id=TASK, onchain_status="cancelled"
    )

    assert out["freeze_released"] is None
    fresh = await db_session.get(SettlementModel, "stl-" + TASK)
    await db_session.refresh(fresh)
    # 状态必须留在 disputed：不然 sweeper 下一轮就再也找不到这笔要补的账。
    assert fresh.status == "disputed"
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.2)


# ------------------------------------------------------- sweeper

@pytest.mark.asyncio
async def test_sweeper_heals_a_settlement_stuck_in_dispute(db_session, monkeypatch):
    monkeypatch.setattr(escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(escrow, "can_server_settle", lambda: True)
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(db_session, task_id=TASK, status="disputed", onchain_status="cancelled")

    healed = await escrow_autosettle.align_disputed_settlements(db_session)

    assert [h["task_id"] for h in healed] == [TASK]
    assert healed[0]["freeze_released"] == pytest.approx(0.2)
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.0)
    fresh = await db_session.get(SettlementModel, "stl-" + TASK)
    await db_session.refresh(fresh)
    assert fresh.status == "cancelled"


@pytest.mark.asyncio
async def test_sweeper_leaves_a_live_dispute_alone(db_session, monkeypatch):
    monkeypatch.setattr(escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(escrow, "can_server_settle", lambda: True)
    await _dispute_frozen_books(db_session, disputed=0.2)
    await _settlement(db_session, task_id=TASK, status="disputed", onchain_status="disputed")

    assert await escrow_autosettle.align_disputed_settlements(db_session) == []
    cap = await db_session.get(CapacityModel, BUYER)
    await db_session.refresh(cap)
    assert cap.disputed_credits == pytest.approx(0.2)
