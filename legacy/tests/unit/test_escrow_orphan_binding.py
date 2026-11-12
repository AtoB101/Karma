"""孤儿绑定按 binding 收尾：链上闸与 ``cancel_for_task`` 同口径，但**不回写 settlements**。

线上实测（2026-10-14）：task 3327dbc2 / 06797bd4 / 4538ae75 各有一条被丢弃的老绑定
（92 / 161 / 171），各自 task 上的兄弟绑定已经 settled。收尾动作按 task 只会碰最新那条
（``_find_binding(task_id)``），于是老的那条每轮 tick 打一条 ``escrow_stranded_reap_noop`` ——
链上占着买方的授权额，永远解不开。

这一路唯一必须守住的东西：**不能把兄弟绑定写好的 ``settlements`` 那一格盖掉**。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete

from db.models.orm import EscrowBindingModel, SettlementModel
from services.chain import allowance_escrow as escrow
from services.chain import escrow_settlement as bridge

TASK = "task-orphan"
CONTRACT = "0x" + "11" * 20


def _binding(binding_id: str = "92", *, state: str = "active") -> EscrowBindingModel:
    return EscrowBindingModel(
        binding_id=binding_id,
        buyer_identity_id="kid_buyer",
        seller_identity_id="kid_seller",
        buyer_bill_id="1",
        seller_bill_id="2",
        contract_address=CONTRACT,
        scope_hash="0x" + "00" * 32,
        task_id=TASK,
        amount_usdc=0.1,
        stake_usdc=0.03,
        state=state,
    )


def _settlement(
    *, status: str = "settled", onchain_status: str | None = "settled"
) -> SettlementModel:
    return SettlementModel(
        settlement_id="stl-" + TASK,
        task_id=TASK,
        escrow_amount=0.1,
        currency="USD",
        status=status,
        onchain_status=onchain_status,
        client_agent_id="kid_buyer",
        worker_agent_id="kid_seller",
    )


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()
    yield
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()


@pytest.fixture
def chain(monkeypatch):
    """链上全用假的：默认「链上还是 ACTIVE」，记下 cancel_binding 拿了哪个 binding id。"""
    calls: dict[str, list] = {"cancel": [], "sync": []}
    monkeypatch.setattr(escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(escrow, "binding_snapshot", lambda *, binding_id, **kw: {"state": 1})

    def _cancel(*, binding_id, contract_address=None):
        calls["cancel"].append((binding_id, contract_address))
        return {"binding_id": binding_id, "cancel_tx_hash": "0xdead", "status": 1}

    async def _sync(db, identity_id):
        calls["sync"].append(identity_id)
        return []

    monkeypatch.setattr(escrow, "cancel_binding", _cancel)
    monkeypatch.setattr(escrow, "sync_commits", _sync)
    return calls


async def _arm(db_session, *, state: str = "active", onchain_status: str | None = "settled"):
    """落一条 ACTIVE 的绑定 + 一张账面上已经 settled 的结算单。"""
    await db_session.execute(delete(EscrowBindingModel))
    row = _binding(state=state)
    stl = _settlement(onchain_status=onchain_status)
    db_session.add(row)
    db_session.add(stl)
    await db_session.commit()
    return row, stl


@pytest.mark.asyncio
async def test_a_row_the_chain_has_a_payee_for_is_refused(db_session, chain, monkeypatch):
    """链上窗口已开（FINALIZING）：钱有受款人，撤不得 —— 而且不把 settlements 改掉。"""
    row, stl = await _arm(db_session)
    monkeypatch.setattr(
        escrow, "binding_snapshot", lambda *, binding_id, **kw: {"state": 2, "settle_after": 1}
    )

    with pytest.raises(bridge.EscrowSettlementError) as err:
        await bridge.cancel_binding_row(db_session, row=row)

    assert err.value.status == 409
    assert chain["cancel"] == [], "链上一个字都不许发"
    assert row.state == "active", "台账也不许被改成 finalizing（那会连带回写 settlements）"
    assert stl.onchain_status == "settled", "兄弟绑定写好的结论不许被盖"


@pytest.mark.asyncio
async def test_a_row_with_an_owner_in_the_ledger_is_refused(db_session, chain):
    """台账自己就停在责任状态：直接拒，连链都不问。"""
    row, _stl = await _arm(db_session, state="finalizing")

    with pytest.raises(bridge.EscrowSettlementError) as err:
        await bridge.cancel_binding_row(db_session, row=row)

    assert err.value.status == 409
    assert chain["cancel"] == []
    assert row.state == "finalizing"


@pytest.mark.asyncio
async def test_an_already_final_row_is_a_noop(db_session, chain):
    row, _stl = await _arm(db_session, state="settled")

    out = await bridge.cancel_binding_row(db_session, row=row)

    assert out == {"status": "settled", "binding_id": "92"}
    assert chain["cancel"] == []


@pytest.mark.asyncio
async def test_a_chain_that_already_moved_gets_the_ledger_aligned_not_cancelled(
    db_session, chain, monkeypatch
):
    """链上早就落定（这里 CANCELLED）：对齐这一条，不再发交易，也不回写 settlements。"""
    row, stl = await _arm(db_session)
    monkeypatch.setattr(escrow, "binding_snapshot", lambda *, binding_id, **kw: {"state": 5})

    out = await bridge.cancel_binding_row(db_session, row=row)

    assert out["status"] == "cancelled" and out["reconciled"] is True
    assert chain["cancel"] == []
    assert row.state == "cancelled"
    assert stl.onchain_status == "settled"


@pytest.mark.asyncio
async def test_an_unreadable_chain_state_is_refused(db_session, chain, monkeypatch):
    row, _stl = await _arm(db_session)
    monkeypatch.setattr(escrow, "binding_snapshot", lambda *, binding_id, **kw: {"state": 9})

    with pytest.raises(bridge.EscrowSettlementError) as err:
        await bridge.cancel_binding_row(db_session, row=row)

    assert err.value.status == 409
    assert chain["cancel"] == []
    assert row.state == "active"


@pytest.mark.asyncio
async def test_a_chain_active_orphan_is_cancelled_by_its_own_binding_id(db_session, chain):
    """主路径：链上 ACTIVE → 按**这一条**绑定的 id 发 cancelBinding，台账落 cancelled。"""
    row, stl = await _arm(db_session)

    out = await bridge.cancel_binding_row(db_session, row=row, reason="orphan")

    assert out == {"status": "cancelled", "binding_id": "92"}
    assert chain["cancel"] == [(92, CONTRACT)], "发的是这一条绑定的链上 id + 它自己那台合约"
    assert chain["sync"] == ["kid_buyer"], "链上放开的额度要让镜像跟上"
    assert row.state == "cancelled"
    assert row.updated_at is not None
    assert stl.onchain_status == "settled", "整个收尾过程 settlements 一个字节没动"


@pytest.mark.asyncio
async def test_an_rpc_hiccup_does_not_block_the_release(db_session, chain, monkeypatch):
    """读不到链（RPC 抖动 / 旧合约）时照旧发 —— 链上的状态机才是最后那道闸。

    与 ``cancel_for_task`` 同口径：读不出来不等于「还没到可以撤的时候」，
    合约自己会用 ``WrongBindingState`` 拒掉不该撤的。
    """
    row, _stl = await _arm(db_session)
    monkeypatch.setattr(escrow, "binding_snapshot", lambda *, binding_id, **kw: None)

    out = await bridge.cancel_binding_row(db_session, row=row)

    assert out["status"] == "cancelled"
    assert chain["cancel"] == [(92, CONTRACT)]


@pytest.mark.asyncio
async def test_a_chain_refusal_surfaces_as_409(db_session, chain, monkeypatch):
    """链上拒了（比如其实已经开窗）：翻成 409，台账一个字节不动。"""
    row, _stl = await _arm(db_session)

    def _boom(*, binding_id, contract_address=None):
        # cancel_binding 是同步的（走 asyncio.to_thread 调），替身也必须是普通函数。
        raise RuntimeError("WrongBindingState")

    monkeypatch.setattr(escrow, "cancel_binding", _boom)

    with pytest.raises(bridge.EscrowSettlementError) as err:
        await bridge.cancel_binding_row(db_session, row=row)

    assert err.value.status == 409
    assert row.state == "active"
