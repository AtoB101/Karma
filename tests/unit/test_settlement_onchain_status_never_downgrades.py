# -*- coding: utf-8 -*-
"""``settlements.onchain_status`` 只升不降：一个 task 的钱只有一个结局。

2026-10-14 生产实测：孤儿绑定 92 / 161 / 171（task 3327dbc2 / 06797bd4 / 4538ae75）
各有一条被丢弃的老绑定，兄弟绑定早已把各自 task 结算完（链上 3=SETTLED，
台账 ``settled`` / ``settled``）。按 binding 收尾那三条孤儿时，链上 171 从 ACTIVE
变成 CANCELLED；而 ``reap_stranded`` 那一轮已经在跑了（tick 慢 9.8 秒），它读到链上
CANCELLED 就 ``_reconcile_from_chain`` → ``_record_final`` → ``reflect_final`` →
``_reflect``，把 task 4538ae75 那行结算单的 ``onchain_status`` 从 ``settled`` 盖成了
``cancelled`` —— 操作台上已放款的单子变成「已取消」，而同一行的 ``tx_hash`` 还指着真正
划走那笔钱的 ``finalizeSettlement``。

规矩钉在这里：``onchain_status`` 一旦记着钱按合约走完了（``settled`` / ``slashed``），
另一条绑定后来的 ``cancelled`` / ``finalizing`` / ``bound`` 都不许再写进去；
``onchain_binding_id`` 与 ``tx_hash`` 那一格同理，不许被孤儿改指。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete

from db.models.orm import EscrowBindingModel, SettlementModel
from services.chain import escrow_settlement as bridge

TASK = "task-downgrade"
ORPHAN = "171"
SIBLING = "173"
CONTRACT = "0x" + "11" * 20
FINALIZE_TX = "0x" + "c3" * 32


def _binding(binding_id: str, *, state: str = "active") -> EscrowBindingModel:
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
        client_agent_id="kid_buyer",
        worker_agent_id="kid_seller",
        onchain_status=onchain_status,
        onchain_binding_id=SIBLING,
        tx_hash=FINALIZE_TX,
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


async def _arm(db_session, *, status: str = "settled", onchain_status: str | None = "settled"):
    """一条 ACTIVE 的孤儿 + 一条已落定的兄弟 + 一张账面 settled 的结算单。"""
    orphan = _binding(ORPHAN)
    db_session.add_all([orphan, _binding(SIBLING, state="settled")])
    stl = _settlement(status=status, onchain_status=onchain_status)
    db_session.add(stl)
    await db_session.commit()
    return orphan, stl


@pytest.mark.asyncio
async def test_a_cancelled_orphan_cannot_overwrite_a_settled_settlement(db_session):
    orphan, stl = await _arm(db_session)

    wrote = await bridge._reflect(
        db_session, task_id=TASK, binding=orphan, onchain_status="cancelled"
    )
    await db_session.commit()

    assert wrote is True, "行在（只是拒了这次回写），调用方该拿到 True"
    assert stl.onchain_status == "settled", "兄弟绑定的结论被孤儿盖掉了"
    assert str(stl.onchain_binding_id) == SIBLING, "结算单不许被重新指到孤儿那条绑定上"
    assert stl.tx_hash == FINALIZE_TX, "真正划钱那笔交易不许被改"


@pytest.mark.asyncio
async def test_a_slashed_row_is_protected_too(db_session):
    _, stl = await _arm(db_session, status="refunded", onchain_status="slashed")

    await bridge._reflect(
        db_session, task_id=TASK, binding=_binding(ORPHAN), onchain_status="cancelled"
    )
    await db_session.commit()

    assert stl.onchain_status == "slashed"


@pytest.mark.asyncio
async def test_the_forward_move_still_lands(db_session):
    """只拦「往后退」：finalizing → settled 照常写进去。"""
    orphan, stl = await _arm(db_session, status="in_progress", onchain_status="finalizing")

    await bridge._reflect(
        db_session, task_id=TASK, binding=orphan, onchain_status="settled", tx_hash=FINALIZE_TX
    )
    await db_session.commit()

    assert stl.onchain_status == "settled"


@pytest.mark.asyncio
async def test_the_same_terminal_value_is_not_a_downgrade(db_session):
    """同一个结论再次回写不算降级（对账本来就是幂等地重放同一件事）。"""
    orphan, stl = await _arm(db_session)

    wrote = await bridge._reflect(
        db_session, task_id=TASK, binding=orphan, onchain_status="settled", tx_hash=FINALIZE_TX
    )
    await db_session.commit()

    assert wrote is True
    assert stl.onchain_status == "settled"
    assert str(stl.onchain_binding_id) == ORPHAN, "同一结局的回写照旧落字段"
