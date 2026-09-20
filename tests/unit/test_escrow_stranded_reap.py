# -*- coding: utf-8 -*-
"""卡死的绑定要能自己解开 —— 钱不能被一个没人推进的订单永久占住。

实测里出现过的两种「钱被占住」：

1. 结算单在业务侧已经终局（取消 / 退款 / 已结算），链上那一步动作却没成功
   （RPC 抖动、operator 没 gas、进程重启）。台账说「完了」，链上说「还占着」：
   用户链上明明有钱，可用额度却怎么都不够，一单也开不出来。
2. 结算单没有授权凭证：生产配置下回执必须由 Runtime 网关代签，而网关要求先有
   卖方已接受的凭证 —— 这条单的回执永远写不进来，链上预留谁也解不开。所以
   接单（= 锁真钱）之前就该拒掉。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete

from db.models.orm import EscrowBindingModel, SettlementModel
from services.chain import escrow_settlement as bridge

TASK = "task-stranded"
BUYER = "kid_buyer"
SELLER = "kid_seller"


def _binding(binding_id: str, *, task_id: str = TASK, state: str = "active",
             age_seconds: int = 600) -> EscrowBindingModel:
    return EscrowBindingModel(
        binding_id=binding_id,
        buyer_identity_id=BUYER,
        seller_identity_id=SELLER,
        buyer_bill_id="1",
        seller_bill_id="2",
        scope_hash="0x" + "00" * 32,
        task_id=task_id,
        amount_usdc=4.0,
        stake_usdc=1.2,
        state=state,
        created_at=datetime.utcnow() - timedelta(seconds=age_seconds),
    )


def _settlement(status: str, *, task_id: str = TASK, voucher_id: str | None = None) -> SettlementModel:
    return SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=4.0,
        currency="USD",
        status=status,
        client_agent_id=BUYER,
        worker_agent_id=SELLER,
        voucher_id=voucher_id,
    )


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id.like("task-stranded%")))
    await db_session.commit()
    yield
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id.like("task-stranded%")))
    await db_session.commit()


@pytest.fixture
def autosettle(monkeypatch):
    from services.chain import escrow_autosettle as mod

    mod.reset_backoff()

    async def _noop_sync(db, identity_id):
        return []

    monkeypatch.setattr(mod.escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(mod.escrow, "can_server_settle", lambda: True)
    monkeypatch.setattr(mod.escrow, "sync_commits", _noop_sync)
    monkeypatch.setattr(mod.escrow, "binding_state", lambda *, binding_id, **kw: None)
    yield mod
    mod.reset_backoff()


@pytest.fixture
def spy(monkeypatch):
    from services.chain import escrow_autosettle as mod

    calls: dict[str, list] = {"cancel": [], "slash": [], "submit": []}

    async def _cancel(db, *, task_id):
        calls["cancel"].append(task_id)
        return {"status": "cancelled"}

    async def _slash(db, *, task_id):
        calls["slash"].append(task_id)
        return {"status": "breaching"}

    async def _submit(db, *, task_id, released_amount=None):
        calls["submit"].append(task_id)
        return {"status": "finalizing"}

    monkeypatch.setattr(mod.escrow_settlement, "cancel_for_task", _cancel)
    monkeypatch.setattr(mod.escrow_settlement, "slash_for_task", _slash)
    monkeypatch.setattr(mod.escrow_settlement, "submit_for_task", _submit)
    return calls


@pytest.mark.asyncio
async def test_business_final_but_chain_still_reserved_is_reaped(db_session, autosettle, spy):
    """取消 / 退款 / 已结算的单，链上还占着 —— 各走各的收尾动作。"""
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add_all([
        _binding("1", task_id="task-stranded-cancel"),
        _binding("2", task_id="task-stranded-refund"),
        _binding("3", task_id="task-stranded-settled"),
    ])
    db_session.add_all([
        _settlement("cancelled", task_id="task-stranded-cancel"),
        _settlement("refunded", task_id="task-stranded-refund"),
        _settlement("settled", task_id="task-stranded-settled"),
    ])
    await db_session.commit()

    freed = await autosettle.reap_stranded(db_session)

    assert spy["cancel"] == ["task-stranded-cancel"]
    assert spy["slash"] == ["task-stranded-refund"]
    assert spy["submit"] == ["task-stranded-settled"]
    assert {f["binding_id"] for f in freed} == {"1", "2", "3"}


@pytest.mark.asyncio
async def test_a_live_order_is_never_touched(db_session, autosettle, spy):
    """正常推进中的单（pending/accepted/delivered/disputed）一个字都不许动。"""
    await db_session.execute(delete(EscrowBindingModel))
    for idx, s in enumerate(
        ("pending", "accepted", "delivered", "disputed", "arbitrated", "in_progress")
    ):
        db_session.add(_binding(str(10 + idx), task_id="task-stranded-%s" % s))
    db_session.add_all([
        _settlement(s, task_id="task-stranded-%s" % s) for s in
        ("pending", "accepted", "delivered", "disputed", "arbitrated", "in_progress")
    ])
    await db_session.commit()

    assert await autosettle.reap_stranded(db_session) == []
    assert spy["cancel"] == [] and spy["slash"] == [] and spy["submit"] == []


@pytest.mark.asyncio
async def test_a_brand_new_binding_is_left_alone(db_session, autosettle, spy):
    """刚 bind 完那一秒，结算单可能已经是终态了（业务先落库、链上稍后回写）——
    余量之内不许动，免得和接单那一步的内联 sync 抢同一个绑定。"""
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add(_binding("20", task_id="task-stranded-fresh", age_seconds=1))
    db_session.add(_settlement("cancelled", task_id="task-stranded-fresh"))
    await db_session.commit()

    assert await autosettle.reap_stranded(db_session) == []
    assert spy["cancel"] == []


@pytest.mark.asyncio
async def test_only_active_bindings_are_candidates(db_session, autosettle, spy):
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add_all([
        _binding("30", task_id="task-stranded-settled", state="settled"),
        _binding("31", task_id="task-stranded-settled", state="finalizing"),
        _binding("32", task_id="task-stranded-settled", state="breaching"),
    ])
    db_session.add(_settlement("settled", task_id="task-stranded-settled"))
    await db_session.commit()

    assert await autosettle.reap_stranded(db_session) == []
    assert spy["submit"] == []


@pytest.mark.asyncio
async def test_a_failure_on_one_binding_does_not_stop_the_others(db_session, autosettle, monkeypatch):
    from services.chain import escrow_autosettle as mod

    seen: list[str] = []

    async def _cancel(db, *, task_id):
        seen.append(task_id)
        if task_id.endswith("boom"):
            raise bridge.EscrowSettlementError(409, "链上撤销失败")
        return {"status": "cancelled"}

    monkeypatch.setattr(mod.escrow_settlement, "cancel_for_task", _cancel)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add_all([
        _binding("40", task_id="task-stranded-boom"),
        _binding("41", task_id="task-stranded-ok"),
    ])
    db_session.add_all([
        _settlement("cancelled", task_id="task-stranded-boom"),
        _settlement("cancelled", task_id="task-stranded-ok"),
    ])
    await db_session.commit()

    freed = await autosettle.reap_stranded(db_session)

    assert seen == ["task-stranded-boom", "task-stranded-ok"]
    assert [f["binding_id"] for f in freed] == ["41"]


@pytest.mark.asyncio
async def test_no_reaping_when_escrow_is_off(db_session, autosettle, spy, monkeypatch):
    from services.chain import escrow_autosettle as mod

    monkeypatch.setattr(mod.escrow, "escrow_enabled", lambda: False)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add(_binding("50", task_id="task-stranded-cancel"))
    db_session.add(_settlement("cancelled", task_id="task-stranded-cancel"))
    await db_session.commit()

    assert await autosettle.reap_stranded(db_session) == []
    assert spy["cancel"] == []


# ------------------------------------------------- 锁钱之前先确认「回执写得进来」

@pytest.fixture
def settings_on(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "runtime_require_task_automation_readiness", True, raising=False)
    monkeypatch.setattr(settings, "receipt_require_signature", True, raising=False)
    return settings


@pytest.mark.asyncio
async def test_a_settlement_without_a_voucher_must_not_lock_real_money(db_session, settings_on):
    """没有凭证 = 回执永远写不进来 = 买方验收被永久挡住、链上预留谁也解不开。"""
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    db_session.add(_settlement("accepted"))
    await db_session.commit()

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.assert_receipt_path_exists(db_session, task_id=TASK)

    assert exc.value.status == 409
    assert "凭证" in exc.value.message


@pytest.mark.asyncio
async def test_a_settlement_with_an_accepted_voucher_locks_fine(db_session, settings_on):
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    db_session.add(_settlement("accepted", voucher_id="vch-1"))
    await db_session.commit()

    await bridge.assert_receipt_path_exists(db_session, task_id=TASK)


@pytest.mark.asyncio
async def test_offchain_deployments_are_not_blocked(db_session, monkeypatch):
    """非生产配置（回执可以不验签）本来就能写回执，不该被这道闸拦住。"""
    from config.settings import settings

    monkeypatch.setattr(settings, "runtime_require_task_automation_readiness", False, raising=False)
    monkeypatch.setattr(settings, "receipt_require_signature", False, raising=False)
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    db_session.add(_settlement("accepted"))
    await db_session.commit()

    await bridge.assert_receipt_path_exists(db_session, task_id=TASK)
