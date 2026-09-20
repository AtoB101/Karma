"""Auto-settlement: the caller that makes "verify, then the money moves" true.

The chain has always allowed the pull - it is permissionless once the challenge
window elapses. What these tests pin down is that Karma's own process makes the
call, exactly once, records the tx, and backs off instead of hammering the
operator account when a binding cannot settle yet.
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import delete, select

from db.models.orm import EscrowBindingModel, SettlementModel
from services.chain import escrow_autosettle as autosettle
from services.chain.wallet_lock import WalletLockError


#: 窗口「过点」要留出余量：本机钟到点 ≠ 链上到点，正好卡边界会被合约拒掉
#: （见 escrow_autosettle.SETTLE_DELAY_MARGIN_SECONDS）。所以测试里用「30 秒前」。
THIRTY_SECONDS_AGO = 30


def binding(
    binding_id: str,
    *,
    state: str = "finalizing",
    pull_after: int | None = None,
    buyer_identity_id: str = "kid_buyer",
    seller_identity_id: str | None = "kid_seller",
) -> EscrowBindingModel:
    return EscrowBindingModel(
        binding_id=binding_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        buyer_bill_id="10",
        seller_bill_id="11",
        scope_hash="0x" + "00" * 32,
        task_id="task-autosettle",
        amount_usdc=30.0,
        stake_usdc=9.0,
        state=state,
        pull_after=pull_after,
    )


async def _noop_sync(db, identity_id):  # bookkeeping only; the real one re-reads the chain
    return []


@pytest.fixture(autouse=True)
async def _armed(db_session, monkeypatch):
    """Every test starts armed, with the chain faked and the table empty."""
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.commit()
    autosettle.reset_backoff()
    monkeypatch.setattr(autosettle.escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(autosettle.escrow, "can_server_settle", lambda: True)
    monkeypatch.setattr(autosettle.escrow, "sync_commits", _noop_sync)
    # 默认「链上读不到」：对账只在真的读到已落定状态时才改写台账，
    # 各用例要测对账就自己覆盖它。
    monkeypatch.setattr(autosettle.escrow, "binding_state", lambda *, binding_id, **kw: None)
    yield
    autosettle.reset_backoff()
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.commit()


@pytest.mark.asyncio
async def test_due_bindings_picks_only_bindings_whose_window_elapsed(db_session):
    now = int(time.time())
    db_session.add_all(
        [
            binding("1", pull_after=now - 5),
            binding("2", pull_after=now + 3600),   # window still open
            binding("3", pull_after=None),          # never submitted
            binding("4", state="settled", pull_after=now - 5),   # already paid
            binding("5", state="active", pull_after=0),          # not yet finalizing
        ]
    )
    await db_session.commit()

    rows = await autosettle.due_bindings(db_session, now=now)

    assert [r.binding_id for r in rows] == ["1"]


# ------------------------------- F10-2 / F11：链上落定之后，账上那行必须跟着走


def settlement(status: str = "settled", *, task_id: str = "task-autosettle") -> SettlementModel:
    return SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=30.0,
        currency="USD",
        status=status,
        client_agent_id="kid_buyer",
        worker_agent_id="kid_seller",
    )


async def _wipe_settlements(db_session) -> None:
    await db_session.execute(
        delete(SettlementModel).where(SettlementModel.task_id == "task-autosettle")
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_settling_writes_the_chain_verdict_back_to_the_settlement_row(
    db_session, monkeypatch
):
    """钱划走之后，操作台读的那一行（settlements.onchain_status）必须变成 settled。

    只改 escrow_bindings 的话，链上钱都到了卖方钱包，页面还停在「结算中」—— F10-2。
    """
    await _wipe_settlements(db_session)
    monkeypatch.setattr(
        autosettle.escrow,
        "finalize_settlement",
        lambda *, binding_id, **kw: {"finalize_tx_hash": "0xf11settle"},
    )
    db_session.add(settlement())
    db_session.add(binding("21", pull_after=int(time.time()) - 30))
    await db_session.commit()

    settled = await autosettle.settle_due(db_session)

    assert len(settled) == 1
    row = await db_session.get(EscrowBindingModel, "21")
    assert row.state == "settled"
    model = (
        await db_session.execute(
            select(SettlementModel).where(SettlementModel.task_id == "task-autosettle")
        )
    ).scalars().one()
    assert model.onchain_status == "settled"
    assert model.tx_hash == "0xf11settle"
    await _wipe_settlements(db_session)


@pytest.mark.asyncio
async def test_the_reconcile_tick_adopts_a_settlement_somebody_else_executed(
    db_session, monkeypatch
):
    """保护期一到，任何地址都能推 finalizeSettlement（合约故意无权限门）。

    别人推了、我们这边没记，账上就会永远停在 finalizing —— 对账那一遍必须把它补齐。
    """
    await _wipe_settlements(db_session)
    monkeypatch.setattr(
        autosettle.escrow, "binding_state", lambda *, binding_id, **kw: 3
    )  # settled
    db_session.add(settlement())
    db_session.add(binding("23", pull_after=int(time.time()) - 30))
    await db_session.commit()

    aligned = await autosettle.reconcile_from_chain(db_session)

    assert [r["binding_id"] for r in aligned] == ["23"]
    row = await db_session.get(EscrowBindingModel, "23")
    assert row.state == "settled"
    model = (
        await db_session.execute(
            select(SettlementModel).where(SettlementModel.task_id == "task-autosettle")
        )
    ).scalars().one()
    assert model.onchain_status == "settled"
    await _wipe_settlements(db_session)


@pytest.mark.asyncio
async def test_the_reconcile_tick_leaves_a_still_open_binding_alone(db_session, monkeypatch):
    """链上说「还在等保护期」，就不许动台账 —— 更不能顺手把钱划走。"""
    await _wipe_settlements(db_session)
    called: list[int] = []
    monkeypatch.setattr(
        autosettle.escrow, "binding_state", lambda *, binding_id, **kw: 2
    )  # finalizing
    monkeypatch.setattr(
        autosettle.escrow,
        "finalize_settlement",
        lambda *, binding_id, **kw: called.append(binding_id),
    )
    db_session.add(binding("25", pull_after=int(time.time()) + 3600))
    await db_session.commit()

    assert await autosettle.reconcile_from_chain(db_session) == []
    row = await db_session.get(EscrowBindingModel, "25")
    assert row.state == "finalizing"
    assert called == []
    await _wipe_settlements(db_session)


@pytest.mark.asyncio
async def test_settle_due_executes_the_pull_and_records_the_tx(db_session, monkeypatch):
    seen: list[int] = []

    def _finalize(*, binding_id: int, **_kw):
        seen.append(binding_id)
        return {"finalize_tx_hash": "0xdeadbeef"}

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _finalize)
    db_session.add(binding("7", pull_after=int(time.time()) - 30))
    await db_session.commit()

    settled = await autosettle.settle_due(db_session)

    assert seen == [7]
    assert settled == [
        {"binding_id": "7", "finalize_tx_hash": "0xdeadbeef", "amount_usdc": 30.0}
    ]
    row = await db_session.get(EscrowBindingModel, "7")
    assert row.state == "settled"
    assert row.finalize_tx_hash == "0xdeadbeef"


@pytest.mark.asyncio
async def test_a_binding_that_cannot_settle_yet_backs_off(db_session, monkeypatch):
    attempts: list[int] = []

    def _boom(*, binding_id: int, **_kw):
        attempts.append(binding_id)
        raise RuntimeError("execution reverted: not funded yet")

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _boom)
    db_session.add(binding("9", pull_after=int(time.time()) - 30))
    await db_session.commit()

    assert await autosettle.settle_due(db_session) == []
    assert await autosettle.settle_due(db_session) == []
    assert attempts == [9]  # the second tick skipped it instead of paying twice
    row = await db_session.get(EscrowBindingModel, "9")
    assert row.state == "finalizing"

    autosettle.reset_backoff()
    assert await autosettle.settle_due(db_session) == []
    assert attempts == [9, 9]  # an explicit reset is what retries


@pytest.mark.asyncio
async def test_a_declined_pull_backs_off_too(db_session, monkeypatch):
    attempts: list[int] = []

    def _refuse(*, binding_id: int, **_kw):
        attempts.append(binding_id)
        raise WalletLockError("allowance is not funded yet")

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _refuse)
    db_session.add(binding("12", pull_after=int(time.time()) - 30))
    await db_session.commit()

    assert await autosettle.settle_due(db_session) == []
    assert await autosettle.settle_due(db_session) == []
    assert attempts == [12]


@pytest.mark.asyncio
async def test_nothing_is_executed_without_the_operator_key(db_session, monkeypatch):
    monkeypatch.setattr(autosettle.escrow, "can_server_settle", lambda: False)
    called: list[int] = []
    monkeypatch.setattr(
        autosettle.escrow,
        "finalize_settlement",
        lambda *, binding_id, **kw: called.append(binding_id),
    )
    db_session.add(binding("14", pull_after=int(time.time()) - 30))
    await db_session.commit()

    assert await autosettle.settle_due(db_session) == []
    assert called == []


@pytest.mark.asyncio
async def test_a_settled_binding_is_never_pulled_twice(db_session, monkeypatch):
    calls: list[int] = []

    def _finalize(*, binding_id: int, **_kw):
        calls.append(binding_id)
        return {"finalize_tx_hash": "0xfeed"}

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _finalize)
    db_session.add(binding("16", pull_after=int(time.time()) - 5))
    await db_session.commit()

    assert len(await autosettle.settle_due(db_session)) == 1
    assert await autosettle.settle_due(db_session) == []
    assert calls == [16]


@pytest.mark.asyncio
async def test_settling_a_sub_identity_order_clears_its_quota(db_session, monkeypatch):
    """子身份额度的闭环：这一单占的额度，钱划走后必须结清（in_progress → released）。

    否则每成一单，那个子身份的可用额度就永久少一截，几次之后 agent 会被自己
    的额度卡死。
    """
    from db.models.orm import ProfileCapacityModel

    monkeypatch.setattr(
        autosettle.escrow,
        "finalize_settlement",
        lambda *, binding_id, **kw: {"finalize_tx_hash": "0xabc"},
    )
    db_session.add(
        ProfileCapacityModel(
            profile_id="prof-quota-1",
            owner_identity_id="kid_buyer",
            allocated_credits=50.0,
            available_credits=20.0,
            in_progress_credits=30.0,
        )
    )
    row = binding("21", pull_after=int(time.time()) - 30)
    row.buyer_profile_id = "prof-quota-1"
    db_session.add(row)
    await db_session.commit()

    assert len(await autosettle.settle_due(db_session)) == 1

    pc = await db_session.get(ProfileCapacityModel, "prof-quota-1")
    assert pc.in_progress_credits == 0.0
    assert pc.released_credits == 30.0
    assert pc.available_credits == 20.0

    await db_session.delete(pc)
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_transaction_that_landed_late_is_recorded_not_retried(
    db_session, monkeypatch
):
    """回执等待超时 != 交易失败。

    我们停止等待的那笔交易可以随后上链。旧代码把这当失败：钱已经 wallet→wallet
    划走，绑定行却永远停在 finalizing，它占的子身份额度也永远不释放。链说了算。
    """
    from db.models.orm import ProfileCapacityModel

    sent: list[int] = []
    monkeypatch.setattr(autosettle.escrow, "binding_state", lambda *, binding_id, **kw: 3)
    monkeypatch.setattr(
        autosettle.escrow,
        "finalize_settlement",
        lambda *, binding_id, **kw: sent.append(binding_id),
    )
    db_session.add(
        ProfileCapacityModel(
            profile_id="prof-late",
            owner_identity_id="kid_buyer",
            allocated_credits=30.0,
            available_credits=0.0,
            in_progress_credits=30.0,
        )
    )
    row = binding("30", pull_after=int(time.time()) - 30)
    row.buyer_profile_id = "prof-late"
    row.finalize_tx_hash = "0xlate"
    db_session.add(row)
    await db_session.commit()

    settled = await autosettle.settle_due(db_session)

    assert sent == [], "链上已经结算，不该再花 gas 重发一次"
    assert settled[0]["binding_id"] == "30"
    fresh = await db_session.get(EscrowBindingModel, "30")
    assert fresh.state == "settled"
    pc = await db_session.get(ProfileCapacityModel, "prof-late")
    assert pc.in_progress_credits == 0.0
    assert pc.released_credits == 30.0

    await db_session.delete(pc)
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_cancelled_binding_gives_the_quota_back(db_session, monkeypatch):
    """链上被取消 = 钱没动，额度该退回可用，而不是记成已结算。"""
    from db.models.orm import ProfileCapacityModel

    monkeypatch.setattr(autosettle.escrow, "binding_state", lambda *, binding_id, **kw: 5)
    db_session.add(
        ProfileCapacityModel(
            profile_id="prof-cancel",
            owner_identity_id="kid_buyer",
            allocated_credits=30.0,
            available_credits=0.0,
            in_progress_credits=30.0,
        )
    )
    row = binding("31", pull_after=int(time.time()) - 30)
    row.buyer_profile_id = "prof-cancel"
    db_session.add(row)
    await db_session.commit()

    settled = await autosettle.settle_due(db_session)

    assert settled[0]["binding_id"] == "31"
    assert (await db_session.get(EscrowBindingModel, "31")).state == "cancelled"
    pc = await db_session.get(ProfileCapacityModel, "prof-cancel")
    assert pc.in_progress_credits == 0.0
    assert pc.available_credits == 30.0
    assert pc.released_credits == 0.0

    await db_session.delete(pc)
    await db_session.commit()

@pytest.mark.asyncio
async def test_due_bindings_leaves_the_boundary_second_to_the_chain(db_session):
    """实测打出来的：本机钟到点 ≠ 链上到点。

    卡在 settleAfter 那一秒发出去的 finalize 会被合约以 SettleDelayActive 拒掉，
    operator 白付一笔 gas，还要等满退避周期才重试。所以窗口到点后要再等一会儿。
    """
    now = int(time.time())
    db_session.add_all(
        [
            binding("1", pull_after=now - 30),   # 早就过点
            binding("2", pull_after=now - 1),    # 就差一秒：让链先说时间到了
            binding("3", pull_after=now),        # 正卡在边界
        ]
    )
    await db_session.commit()

    rows = await autosettle.due_bindings(db_session, now=now)

    assert [r.binding_id for r in rows] == ["1"]
