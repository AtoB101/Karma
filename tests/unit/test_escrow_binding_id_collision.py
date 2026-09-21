"""链上 binding id 是**每台合约各自计数**的 —— 账上主键必须是跨合约唯一的。

2026-09-21 F13 链上动钱实测（真钱）撞到的 P0：v3 的第 9 条绑定撞上 v2 的第 9 条。
链上 ``bind`` 已经成功（买方账单被占住 0.2 USDC），账上 INSERT 被主键唯一约束打回：

    UniqueViolationError: duplicate key value violates unique constraint
    "escrow_bindings_pkey"  DETAIL: Key (binding_id)=(9) already exists.

``/v1/settlement/{task}/lock`` 直接 500，链上留下一条谁也不认的绑定；而且从那一刻
起**每一条新锁仓都会撞**（v3 的 id 只会继续往上走）。

这里钉三件事：
1. 裸 id 没被占就用裸的（好看、也顺手），被别的合约占了才加合约地址前缀；
2. 加前缀之后 ``chain_binding_id()`` 还能还原出链上 id（autosettle 靠它收尾）；
3. 改名前的历史引用（裸 id）仍然能取到行 —— 老链接不许 404。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from db.models.orm import (
    AllowanceCommitModel,
    CapacityModel,
    EscrowBindingModel,
    SettlementModel,
    VoucherModel,
)
from services.chain import escrow_settlement as bridge
from tests.unit.test_escrow_settlement import BUYER, SELLER, TASK, arm, bill, settlement_row
from tests.unit.test_escrow_settlement import chain as upstream_chain  # noqa: F401


@pytest.fixture
def chain(upstream_chain):  # noqa: F811
    """沿用 test_escrow_settlement 里那套「链上换成记账本」的假链。"""
    return upstream_chain

CURRENT_CONTRACT = "0x" + "11" * 20
RETIRED_CONTRACT = "0x" + "fe" * 20


def _retired_row(binding_id: str, *, state: str = "cancelled") -> EscrowBindingModel:
    return EscrowBindingModel(
        binding_id=binding_id,
        buyer_identity_id="kid_old_buyer",
        seller_identity_id="kid_old_seller",
        buyer_bill_id="9",
        seller_bill_id="8",
        contract_address=RETIRED_CONTRACT,
        scope_hash="0x" + "cd" * 32,
        state=state,
    )


async def _wipe(db_session) -> None:
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(AllowanceCommitModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.execute(delete(VoucherModel).where(VoucherModel.buyer_identity_id == BUYER))
    await db_session.execute(delete(CapacityModel).where(CapacityModel.identity_id == BUYER))
    await db_session.commit()


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await _wipe(db_session)
    yield
    await _wipe(db_session)


@pytest.mark.asyncio
async def test_local_binding_id_keeps_the_plain_id_when_free(db_session):
    assert await bridge.local_binding_id(db_session, chain_id=42, contract=CURRENT_CONTRACT) == "42"


@pytest.mark.asyncio
async def test_local_binding_id_namespaces_when_a_retired_contract_took_it(db_session):
    db_session.add(_retired_row("42", state="settled"))
    await db_session.flush()

    local = await bridge.local_binding_id(db_session, chain_id=42, contract=CURRENT_CONTRACT)

    assert local == f"{CURRENT_CONTRACT}:42"
    assert bridge.chain_binding_id(SimpleNamespace(binding_id=local)) == 42


@pytest.mark.asyncio
async def test_bind_survives_an_id_already_taken_by_a_retired_contract(db_session, chain):
    """回归：这就是那天把 /lock 打成 500 的那一条。"""
    calls = chain[1]
    db_session.add(settlement_row())
    db_session.add(_retired_row("101", state="settled"))
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])

    info = await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER, seller_identity_id=SELLER,
        amount_usdc=30.0,
    )

    assert info["status"] == "bound"
    assert calls["bind"] == [("1", "2", 30.0, 9.0)]
    rows = {row.binding_id: row for row in (await db_session.execute(select(EscrowBindingModel))).scalars().all()}
    assert rows["101"].state == "settled"          # 退役合约那条一动没动
    fresh = rows[f"{CURRENT_CONTRACT}:101"]        # 新绑定落在带前缀的主键上
    assert fresh.state == "active"
    assert bridge.chain_binding_id(fresh) == 101   # 链上 id 还还原得出来


@pytest.mark.asyncio
async def test_find_binding_resolves_a_pre_rename_reference(db_session):
    row = _retired_row("9", state="settled")
    db_session.add(row)
    await db_session.flush()

    assert (await bridge.find_binding(db_session, "9")).binding_id == row.binding_id
    assert (await bridge.find_binding(db_session, row.binding_id)).binding_id == row.binding_id
    assert await bridge.find_binding(db_session, "404") is None


def test_chain_binding_id_reads_both_forms():
    assert bridge.chain_binding_id(SimpleNamespace(binding_id="7")) == 7
    assert bridge.chain_binding_id(SimpleNamespace(binding_id=f"{RETIRED_CONTRACT}:7")) == 7
    assert bridge.chain_binding_id(f"{RETIRED_CONTRACT}:7") == 7
