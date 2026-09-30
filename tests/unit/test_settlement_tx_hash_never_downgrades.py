# -*- coding: utf-8 -*-
"""`settlements.tx_hash` 只能指向「更权威」的那笔交易。

2026-10-01 的 L1 复跑里，10 笔结算有 1 笔的链上核对红了：结算行写的是
`submitSettlement`（那是开保护期窗口的交易，一分钱都不动），真正划钱的是随后那笔
`finalizeSettlement`（记在 `escrow_bindings.finalize_tx_hash`）。

事故链：回写 `settlements.tx_hash` 的地方有三处（请求路径 / autosettle / 只读对账
GET 里的 `reconcile_task`），各自手里那份 binding 未必是最新的。只读对账先落一次
（那会儿 finalize 还没记上，只能拿 submit 顶），autosettle 随后写上的 finalize 又被
后面某个握着旧 binding 的回写盖回 submit。

规矩钉在这里：权威度 finalize > submit > bind，只升不降。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from db.models.orm import EscrowBindingModel, SettlementModel
from services.chain import escrow_settlement as bridge

TASK = "task-txrank"
BIND = "901"
BIND_TX = "0x" + "a1" * 32
SUBMIT_TX = "0x" + "b2" * 32
FINALIZE_TX = "0x" + "c3" * 32


async def _seed(db, *, tx_hash: str | None, finalize: str | None = FINALIZE_TX):
    await db.execute(delete(EscrowBindingModel).where(EscrowBindingModel.binding_id == BIND))
    await db.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    db.add(EscrowBindingModel(
        binding_id=BIND,
        buyer_identity_id="kid_buyer",
        seller_identity_id="kid_seller",
        buyer_bill_id="1",
        seller_bill_id="2",
        scope_hash="0x" + "00" * 32,
        task_id=TASK,
        amount_usdc=4.0,
        stake_usdc=1.2,
        state="settled",
        bind_tx_hash=BIND_TX,
        submit_tx_hash=SUBMIT_TX,
        finalize_tx_hash=finalize,
    ))
    db.add(SettlementModel(
        settlement_id="stl-" + TASK,
        task_id=TASK,
        escrow_amount=4.0,
        currency="USD",
        status="settled",
        client_agent_id="kid_buyer",
        worker_agent_id="kid_seller",
        onchain_status="finalizing",
        tx_hash=tx_hash,
    ))
    await db.commit()


async def _tx_hash(db) -> str | None:
    row = (
        await db.execute(
            select(SettlementModel).where(SettlementModel.task_id == TASK)
        )
    ).scalars().first()
    return row.tx_hash


async def _binding(db) -> EscrowBindingModel:
    return (
        await db.execute(
            select(EscrowBindingModel).where(EscrowBindingModel.binding_id == BIND)
        )
    ).scalars().first()


@pytest.fixture(autouse=True)
async def _clean(db_session):
    yield
    await db_session.execute(delete(EscrowBindingModel).where(EscrowBindingModel.binding_id == BIND))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_stale_writer_cannot_downgrade_the_finalize_tx(db_session):
    """操作台已经指着 finalize 那笔了，一个手里还是旧 binding 的回写不许把它盖成 submit。"""
    await _seed(db_session, tx_hash=FINALIZE_TX)

    # 旧 binding：finalize_tx_hash 还没记上（finalize=None），手里只有 submit。
    await bridge._reflect(
        db_session,
        task_id=TASK,
        binding=await _binding(db_session),
        onchain_status="settled",
        tx_hash=FINALIZE_TX,
    )
    await db_session.commit()
    assert await _tx_hash(db_session) == FINALIZE_TX

    stale = await _binding(db_session)
    stale.finalize_tx_hash = None          # 模拟「这一份 binding 读得早」
    await bridge._reflect(
        db_session,
        task_id=TASK,
        binding=stale,
        onchain_status="settled",
        tx_hash=SUBMIT_TX,
    )
    await db_session.commit()
    assert await _tx_hash(db_session) == FINALIZE_TX, "finalize 交易被旧的 submit 盖掉了"


@pytest.mark.asyncio
async def test_a_higher_ranked_hash_still_wins(db_session):
    """只升不降：手里攥着 bind 那笔时，finalize 当然要写上去。"""
    await _seed(db_session, tx_hash=BIND_TX)

    await bridge._reflect(
        db_session,
        task_id=TASK,
        binding=await _binding(db_session),
        onchain_status="settled",
        tx_hash=FINALIZE_TX,
    )
    await db_session.commit()
    assert await _tx_hash(db_session) == FINALIZE_TX


@pytest.mark.asyncio
async def test_an_empty_row_still_gets_the_submit_tx_when_there_is_nothing_better(db_session):
    """没有任何交易记录时，submit 那笔总比空着强。"""
    await _seed(db_session, tx_hash=None)

    await bridge._reflect(
        db_session,
        task_id=TASK,
        binding=await _binding(db_session),
        onchain_status="finalizing",
        tx_hash=SUBMIT_TX,
    )
    await db_session.commit()
    assert await _tx_hash(db_session) == SUBMIT_TX

