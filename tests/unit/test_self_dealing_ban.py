"""自成交硬禁（2026-10-14）：买方和卖方必须是两个不同的人、两把不同的钱包。

为什么单独钉这一组：线上那条脏单（settlement ``97f0dc0e-4748-41fe-8ad8-fe71e195b832``）
就是「延迟绑定」这条路**没有自成交闸**的产物 —— 单子被接受、买方额度被占住，之后
autosettle 每个退避周期拿一笔 operator gas 去撞链上的 ``SameOwner()``。链上注定
revert 的形状，不许在业务层被放行。

判定只有一份实现（``escrow_settlement.assert_parties_not_self_dealing``），四条口径：
同一个 id / 同一个主身份 / 同一把钱包 / 库里认领的钱包。接单的**两个**入口都要调它。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from config.settings import settings
from db.models.orm import AllowanceCommitModel, EscrowBindingModel, SettlementModel
from services.chain import allowance_escrow as escrow
from services.identity_gateway import store
from services.miniapp_commerce import orders

TASK = "task-self-dealing-ban"
BUYER = "kid_buyer"
SELLER = "kid_seller"
CURRENT_CONTRACT = "0x" + "11" * 20
SHARED_WALLET = "0x" + "ab" * 20


def bill(
    bill_id: str,
    identity_id: str,
    amount: float,
    *,
    wallet: str | None = None,
) -> AllowanceCommitModel:
    """一张「链上真划得动」的账单：落在当前合约上，额度覆盖得住。"""
    return AllowanceCommitModel(
        bill_id=bill_id,
        identity_id=identity_id,
        wallet_address=wallet or ("0x" + bill_id.rjust(40, "0")),
        chain_id=11155111,
        contract_address=CURRENT_CONTRACT,
        token_address="0x" + "22" * 20,
        operator="0x" + "33" * 20,
        amount_wei=str(int(amount * 10**6)),
        amount_usdc=amount,
        spent_usdc=0.0,
        reserved_usdc=0.0,
        backed=True,
        state="open",
    )


def settlement_row(task_id: str = TASK) -> SettlementModel:
    return SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=30.0,
        currency="USD",
        status="accepted",
        client_agent_id=BUYER,
        worker_agent_id=SELLER,
    )


@pytest.fixture(autouse=True)
def _isolate():
    """身份库是进程内全局的：本组用例自己种身份，别让别的用例的钱包漏进来。"""
    store.reset_for_tests()
    orders.reset_for_tests()
    yield
    store.reset_for_tests()
    orders.reset_for_tests()


@pytest.fixture(autouse=True)
async def _clean_tables(db_session):
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(AllowanceCommitModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()
    yield
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(AllowanceCommitModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()


@pytest.fixture
def chain(monkeypatch):
    """最小链条替身：只让 ``_pick_bill`` 挑得出账单，交易一笔都不发。"""
    from services.chain import escrow_settlement as bridge

    calls: dict[str, list] = {"bind": []}
    books: dict[str, list] = {}
    available: dict[str, float] = {}

    async def _list_commits(db, identity_id):
        return list(books.get(identity_id, []))

    async def _backing_report(db, identity_id, *, rows=None):
        rows = rows if rows is not None else books.get(identity_id, [])
        secured = {str(r.bill_id): float(r.amount_usdc) for r in rows}
        return {
            "allowance_usdc": sum(secured.values()),
            "committed_usdc": sum(secured.values()),
            "secured_usdc": sum(secured.values()),
            "unsecured_usdc": 0.0,
            "enforced": True,
            "chain_checked": True,
            "bills": {k: {"live_usdc": v, "secured_usdc": v} for k, v in secured.items()},
        }

    def _open_order(**_kw):
        calls["bind"].append(_kw)
        raise AssertionError("自成交闸没拦住，居然要去发 bind 交易")

    monkeypatch.setattr(escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(settings, "allowance_escrow_address", CURRENT_CONTRACT)
    monkeypatch.setattr(escrow, "list_commits", _list_commits)
    monkeypatch.setattr(escrow, "backing_report", _backing_report)
    monkeypatch.setattr(
        escrow, "bill_available", lambda *, bill_id, **kw: available.get(str(bill_id))
    )
    monkeypatch.setattr(escrow, "open_order", _open_order)

    def arm(identity_id: str, rows: list) -> None:
        books[identity_id] = rows
        for r in rows:
            available[str(r.bill_id)] = float(r.amount_usdc)

    return bridge, calls, arm


# ------------------------------- 口径 1：同一个 id


@pytest.mark.asyncio
async def test_the_same_party_on_both_sides_is_refused(db_session):
    from services.chain import escrow_settlement as bridge

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.assert_parties_not_self_dealing(
            db_session, task_id=TASK, buyer_identity_id=BUYER, seller_identity_id=BUYER
        )

    assert exc.value.status == 409
    assert "自成交" in exc.value.message


# ------------------------------- 口径 2：同一个主身份（链上看钱包看不出来）


@pytest.mark.asyncio
async def test_two_sub_identities_of_one_owner_are_refused(db_session):
    from services.chain import escrow_settlement as bridge

    store.seed_identity("kid_main", "0x" + "01" * 20, twofa_code="111111")
    sub = store.create_sub_identity("kid_main", "0x" + "02" * 20)

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.assert_parties_not_self_dealing(
            db_session,
            task_id=TASK,
            buyer_identity_id="kid_main",
            seller_identity_id=sub.identity_id,
        )

    assert exc.value.status == 409
    assert "同一个钱包主身份" in exc.value.message


# ------------------------------- 口径 3：同一把钱包（合约 bind 真正比的那个）


@pytest.mark.asyncio
async def test_deferred_bind_refuses_a_shared_wallet_and_writes_no_pending_bind(
    db_session, chain, monkeypatch
):
    """延迟绑定这条路（``bind_for_task_deferred``）是线上脏单的形状。

    必须：① 接单那一刻就 409；② 一个字都不写回结算单（``pending_bind`` 不许落）；
    ③ 不留 binding 行；④ 留一条可追溯的安全事件。
    """
    bridge, calls, arm = chain
    db_session.add(settlement_row())
    await db_session.flush()
    arm(BUYER, [bill("20", BUYER, 40.0, wallet=SHARED_WALLET)])
    arm(SELLER, [bill("21", SELLER, 20.0, wallet=SHARED_WALLET)])

    seen: list = []
    import services.security_monitoring as monitoring

    monkeypatch.setattr(
        monitoring, "record_security_event", lambda et, **kw: seen.append((et, kw))
    )

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.bind_for_task_deferred(
            db_session,
            task_id=TASK,
            buyer_identity_id=BUYER,
            seller_identity_id=SELLER,
            amount_usdc=30.0,
        )

    assert exc.value.status == 409
    assert "同一个钱包" in exc.value.message
    assert calls["bind"] == []

    settlement = (
        await db_session.execute(
            select(SettlementModel).where(SettlementModel.task_id == TASK)
        )
    ).scalars().one()
    assert settlement.settlement_mode != "escrow_allowance", "延迟绑定不该被写进去"
    assert settlement.onchain_status is None
    rows = (await db_session.execute(select(EscrowBindingModel))).scalars().all()
    assert rows == []

    assert seen, "拒单必须留下可追溯的安全事件"
    assert seen[0][0] is monitoring.SecurityMonitoringEventType.SELF_DEAL_REFUSED


# ------------------------------- 两个不同的人 + 两把不同的钱包：放行


@pytest.mark.asyncio
async def test_two_distinct_parties_with_distinct_wallets_pass(db_session, chain):
    bridge, _calls, arm = chain
    store.seed_identity(BUYER, "0x" + "01" * 20, twofa_code="111111")
    store.seed_identity(SELLER, "0x" + "02" * 20, twofa_code="222222")
    db_session.add(settlement_row())
    await db_session.flush()
    arm(BUYER, [bill("20", BUYER, 40.0, wallet="0x" + "01" * 20)])
    arm(SELLER, [bill("21", SELLER, 20.0, wallet="0x" + "02" * 20)])

    info = await bridge.bind_for_task_deferred(
        db_session,
        task_id=TASK,
        buyer_identity_id=BUYER,
        seller_identity_id=SELLER,
        amount_usdc=30.0,
    )

    assert info["status"] == "pending_bind"


# ------------------------------- 纵深防御：状态机自己也拒


def test_mark_settled_refuses_a_self_dealing_order():
    order = orders.create_order(
        buyer_identity_id=BUYER,
        intent={"amount_usdc": "1"},
        buyer_wallet=SHARED_WALLET,
    )
    orders.attach_offer(order.order_id, {"amount_usdc": "1"}, seller_identity_id=SELLER,
                        seller_wallet=SHARED_WALLET)
    orders.mark_verified(order.order_id, run_id="run-1")

    with pytest.raises(ValueError) as exc:
        orders.mark_settled(order.order_id)

    assert "self-dealing" in str(exc.value)
    assert orders.get_order(order.order_id).status is orders.OrderStatus.VERIFIED


# ------------------------------- 纵深防御：MiniApp 结算路由


def test_miniapp_route_refuses_a_self_dealing_order():
    from fastapi import HTTPException

    from api.routes.telegram_miniapp_commerce import _refuse_self_dealing

    order = orders.create_order(
        buyer_identity_id=BUYER,
        intent={"amount_usdc": "1"},
        buyer_wallet=SHARED_WALLET,
    )
    orders.attach_offer(order.order_id, {"amount_usdc": "1"}, seller_identity_id=SELLER,
                        seller_wallet=SHARED_WALLET)

    with pytest.raises(HTTPException) as exc:
        _refuse_self_dealing(order)

    assert exc.value.status_code == 409