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


def _settlement(
    status: str,
    *,
    task_id: str = TASK,
    voucher_id: str | None = None,
    updated_at: datetime | None = None,
) -> SettlementModel:
    return SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=4.0,
        currency="USD",
        status=status,
        client_agent_id=BUYER,
        worker_agent_id=SELLER,
        voucher_id=voucher_id,
        updated_at=updated_at,
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

    calls: dict[str, list] = {"cancel": [], "slash": [], "submit": [], "cancel_row": []}

    async def _cancel(db, *, task_id):
        calls["cancel"].append(task_id)
        return {"status": "cancelled"}

    async def _cancel_row(db, *, row, reason=None):
        calls["cancel_row"].append((row.binding_id, reason))
        return {"status": "cancelled", "binding_id": row.binding_id}

    async def _slash(db, *, task_id):
        calls["slash"].append(task_id)
        return {"status": "breaching"}

    async def _submit(db, *, task_id, released_amount=None):
        calls["submit"].append(task_id)
        return {"status": "finalizing"}

    monkeypatch.setattr(mod.escrow_settlement, "cancel_for_task", _cancel)
    monkeypatch.setattr(mod.escrow_settlement, "slash_for_task", _slash)
    monkeypatch.setattr(mod.escrow_settlement, "submit_for_task", _submit)
    monkeypatch.setattr(mod.escrow_settlement, "cancel_binding_row", _cancel_row)
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
async def test_a_live_binding_must_not_block_the_batch_window(
    db_session, autosettle, spy, monkeypatch
):
    """窗口是「按 created_at 升序取 batch 条」：更老的「还在跑」的绑定会一直占着窗口，
    后面真正待收尾的永远轮不到 —— 固定批量 + 只按 state 过滤就是一个会饿死的队列。

    2026-10-01 生产实测：ESCROW_AUTOSETTLE_BATCH=5 而 active 有 104 条，最老的 5 条全是
    in_progress / delivered / disputed，reap_stranded 每轮耗 3 秒、连着 6 分钟 0 产出，
    10 条「结算单已结算、链上还占着」的绑定（合计 1.00 USDC 额度）一条都没解开。
    """
    from config.settings import settings

    monkeypatch.setattr(settings, "escrow_autosettle_batch", 2, raising=False)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add_all([
        _binding("60", task_id="task-stranded-live-1", age_seconds=900),
        _binding("61", task_id="task-stranded-live-2", age_seconds=800),
        _binding("62", task_id="task-stranded-cancel", age_seconds=700),
    ])
    db_session.add_all([
        _settlement("in_progress", task_id="task-stranded-live-1"),
        _settlement("delivered", task_id="task-stranded-live-2"),
        _settlement("cancelled", task_id="task-stranded-cancel"),
    ])
    await db_session.commit()

    freed = await autosettle.reap_stranded(db_session)

    assert [f["binding_id"] for f in freed] == ["62"]
    assert spy["cancel"] == ["task-stranded-cancel"]

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
async def test_an_action_landing_on_a_sibling_binding_is_not_a_reap(db_session, autosettle, monkeypatch):
    """决定按绑定下、动作按 task 找 —— 一个 task 有多条绑定时两者会错开。

    ``submit_for_task`` / ``cancel_for_task`` / ``slash_for_task`` 都走
    ``_find_binding(task_id)``，只挑最新那条。于是「收尾」可能落在兄弟绑定上，
    这一条一个字节都没动；不把这种情况记进 ``freed``，否则 ``reaped`` 就成了
    会撒谎的指标（生产实测：92/161/171 每 20 秒刷一条 reaped，state 永远 active）。
    """
    from services.chain import escrow_autosettle as mod

    async def _submit(db, *, task_id, released_amount=None):
        return {"status": "settled", "binding_id": "999"}

    monkeypatch.setattr(mod.escrow_settlement, "submit_for_task", _submit)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add(_binding("62", task_id="task-stranded-settled"))
    db_session.add(_settlement("settled", task_id="task-stranded-settled"))
    await db_session.commit()

    assert await autosettle.reap_stranded(db_session) == []

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


@pytest.mark.asyncio
async def test_a_reverted_auto_confirm_stops_holding_the_buyers_allowance(
    db_session, autosettle, spy
):
    """退回到 ``auto_confirmed`` 的单：没有任何流程会再推进它，绑定必须解开。

    2026-10-13 线上：25 张 0.1 USDC 的单在链上放款失败后退回 ``auto_confirmed``，
    而 ``auto_confirm_expired_settlements`` 只扫 ``DELIVERED`` —— 它们每一轮都不会被
    再碰，买方被占住的授权额成了死账。
    """
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add(_binding("70", task_id="task-stranded-autoconf"))
    db_session.add(
        _settlement(
            "auto_confirmed",
            task_id="task-stranded-autoconf",
            updated_at=datetime.utcnow() - timedelta(hours=2),
        )
    )
    await db_session.commit()

    freed = await autosettle.reap_stranded(db_session)

    assert [f["binding_id"] for f in freed] == ["70"]
    assert spy["cancel"] == ["task-stranded-autoconf"]
    assert spy["slash"] == [] and spy["submit"] == []


@pytest.mark.asyncio
async def test_a_fresh_auto_confirm_is_left_alone(db_session, autosettle, spy):
    """``auto_confirmed`` 可能只是自动放款路上的一瞬间：推进到 settled 之前不许动它。"""
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add(_binding("71", task_id="task-stranded-autoconf-fresh"))
    db_session.add(
        _settlement(
            "auto_confirmed",
            task_id="task-stranded-autoconf-fresh",
            updated_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    assert await autosettle.reap_stranded(db_session) == []
    assert spy["cancel"] == []


# ------------------------- 孤儿绑定：按 binding 收尾（2026-10-14）
# 一个 task 有多条绑定时，cancel/submit/slash_for_task 只会碰**最新那条**（内部都是
# _find_binding(task_id)）。老的那条链上还占着买方的授权额，谁也解不开 —— 线上实测
# task 3327dbc2 / 06797bd4 / 4538ae75 各有一条（92 / 161 / 171），每轮只留一条 noop。


def test_the_orphan_gate_only_opens_when_the_money_has_a_conclusion():
    """够格自动收的前提：这个 task 的钱要么不用动，要么已经在**另一条**绑定上落定。"""
    from services.chain import escrow_autosettle as mod

    allowed = mod._orphan_cancel_allowed
    # 没有任何钱要动：直接放行，链上什么状态都收。
    for s in ("cancelled", "failed", "expired"):
        assert allowed(s, None) is True
        assert allowed(s, "bound") is True
    # settled：链上那一步必须真的落定（放款 / 罚没 / 撤销都算）。
    for onchain in ("settled", "slashed", "cancelled"):
        assert allowed("settled", onchain) is True
    for onchain in ("finalizing", "bound", None):
        assert allowed("settled", onchain) is False
    # 钱还要动、或者还没结论：一律不碰。
    for s in ("in_progress", "delivered", "disputed", "refunded", "auto_confirmed", None):
        assert allowed(s, "settled") is False


@pytest.mark.asyncio
async def test_an_orphan_binding_is_reaped_by_binding_not_by_task(
    db_session, autosettle, spy, monkeypatch
):
    """同一 task 的兄弟绑定已经 settled：孤儿要按 binding 收掉，而不是每轮 noop。"""
    monkeypatch.setattr(autosettle.settings, "escrow_orphan_binding_cancel_enabled", True)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add_all([
        _binding("92", task_id="task-stranded-orphan", age_seconds=900),
        _binding("94", task_id="task-stranded-orphan", state="settled", age_seconds=800),
    ])
    stl = _settlement("settled", task_id="task-stranded-orphan")
    stl.onchain_status = "settled"
    db_session.add(stl)
    await db_session.commit()

    freed = await autosettle.reap_stranded(db_session)

    assert spy["cancel_row"] == [("92", "orphan")], "孤儿要按 binding 收"
    assert spy["cancel"] == [] and spy["submit"] == [] and spy["slash"] == []
    assert [f["binding_id"] for f in freed] == ["92"]
    assert freed[0]["orphan"] is True


@pytest.mark.asyncio
async def test_an_orphan_is_left_alone_while_the_money_still_has_to_move(
    db_session, autosettle, spy, monkeypatch
):
    """结算单说 settled、链上却还没落定：钱还要动，孤儿不许收（走老路）。"""
    monkeypatch.setattr(autosettle.settings, "escrow_orphan_binding_cancel_enabled", True)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add_all([
        _binding("96", task_id="task-stranded-orphan-pending", age_seconds=900),
        _binding("97", task_id="task-stranded-orphan-pending", state="finalizing", age_seconds=800),
    ])
    stl = _settlement("settled", task_id="task-stranded-orphan-pending")
    stl.onchain_status = "finalizing"
    db_session.add(stl)
    await db_session.commit()

    await autosettle.reap_stranded(db_session)

    assert spy["cancel_row"] == [], "链上还没落定，孤儿不能收"
    assert spy["submit"] == ["task-stranded-orphan-pending"], "该走的还是老路"


@pytest.mark.asyncio
async def test_the_orphan_sweep_is_off_by_default(db_session, autosettle, spy):
    """默认关：一个 task 一条绑定的常规世界里，行为与从前一字不差。"""
    assert autosettle.settings.escrow_orphan_binding_cancel_enabled is False
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add_all([
        _binding("98", task_id="task-stranded-flag-off", age_seconds=900),
        _binding("99", task_id="task-stranded-flag-off", state="settled", age_seconds=800),
    ])
    db_session.add(_settlement("cancelled", task_id="task-stranded-flag-off"))
    await db_session.commit()

    await autosettle.reap_stranded(db_session)

    assert spy["cancel_row"] == []
    assert spy["cancel"] == ["task-stranded-flag-off"]


@pytest.mark.asyncio
async def test_the_newest_binding_still_takes_the_task_scoped_road(
    db_session, autosettle, spy, monkeypatch
):
    """只有一条绑定（它**就是**最新那条）时：走的还是 cancel_for_task，不是孤儿那条路。"""
    monkeypatch.setattr(autosettle.settings, "escrow_orphan_binding_cancel_enabled", True)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add(_binding("95", task_id="task-stranded-solo", age_seconds=900))
    db_session.add(_settlement("cancelled", task_id="task-stranded-solo"))
    await db_session.commit()

    await autosettle.reap_stranded(db_session)

    assert spy["cancel_row"] == []
    assert spy["cancel"] == ["task-stranded-solo"]


@pytest.mark.asyncio
async def test_a_cancelled_orphan_never_downgrades_a_settled_settlement(
    db_session, autosettle, monkeypatch
):
    """孤儿绑定链上被撤（5=CANCELLED）：这一条照样收尾，但兄弟绑定写好的结论不许被盖。

    2026-10-14 生产实测：按 binding 收尾 92 / 161 / 171 的那一轮，正好撞上一轮还在跑的
    ``reap_stranded``（tick 慢 9.8 秒）。它读到链上 CANCELLED 就 ``_record_final`` →
    ``reflect_final`` → ``_reflect``，把 task 4538ae75 结算单的 ``onchain_status`` 从
    ``settled`` 写成 ``cancelled``，而同一行的 ``tx_hash`` 还指着真正划钱那笔
    ``finalizeSettlement`` —— 操作台上的「已结算」变成「已取消」。
    """
    from services.chain import escrow_autosettle as mod

    monkeypatch.setattr(mod.escrow, "binding_state", lambda *, binding_id, **kw: 5)
    await db_session.execute(delete(EscrowBindingModel))
    db_session.add(_binding("171", task_id="task-stranded-settled"))
    stl = _settlement("settled", task_id="task-stranded-settled")
    stl.onchain_status = "settled"
    db_session.add(stl)
    await db_session.commit()

    freed = await autosettle.reap_stranded(db_session)

    assert [f["binding_id"] for f in freed] == ["171"], "孤儿绑定本身照样收尾"
    await db_session.refresh(stl)
    assert stl.onchain_status == "settled", "兄弟绑定写好的结论被孤儿盖回去了"
