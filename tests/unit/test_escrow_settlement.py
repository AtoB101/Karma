"""任务结算 → 非托管授权托管：这一层必须让「已结算」在链上有对应的钱。

这些用例钉死四件事：

1. 没有链上账单就不许接单 —— 额度不能凭空记；
2. 授权额读不到（RPC 抖动）时宁可拒单，也不假装担保成立；
3. 每一次「业务往前走一步」都对应一笔真实交易（bind / submit / cancel）；
4. 链上先落定时台账要自愈（钱已经划走，状态机不能停在半路）。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select

from config.settings import settings
from db.models.orm import (
    AllowanceCommitModel,
    CapacityModel,
    EscrowBindingModel,
    SettlementModel,
    VoucherModel,
)
from services.chain import allowance_escrow as escrow

TASK = "task-escrow-settlement"
BUYER = "kid_buyer"
SELLER = "kid_seller"


def bill(bill_id: str, identity_id: str, amount: float, *, state: str = "open") -> AllowanceCommitModel:
    return AllowanceCommitModel(
        bill_id=bill_id,
        identity_id=identity_id,
        wallet_address="0x" + bill_id.rjust(40, "0"),
        chain_id=11155111,
        contract_address="0x" + "11" * 20,
        token_address="0x" + "22" * 20,
        operator="0x" + "33" * 20,
        amount_wei=str(int(amount * 10**6)),
        amount_usdc=amount,
        spent_usdc=0.0,
        reserved_usdc=0.0,
        backed=True,
        state=state,
    )


def settlement_row(task_id: str = TASK, *, status: str = "accepted") -> SettlementModel:
    """账上的结算行。``status`` 就是「验证结论」：放款要 settled，罚没要 refunded。"""
    return SettlementModel(
        settlement_id="stl-" + task_id,
        task_id=task_id,
        escrow_amount=30.0,
        currency="USD",
        status=status,
        client_agent_id=BUYER,
        worker_agent_id=SELLER,
    )


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(AllowanceCommitModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.execute(delete(VoucherModel).where(VoucherModel.buyer_identity_id == BUYER))
    await db_session.execute(delete(CapacityModel).where(CapacityModel.identity_id == BUYER))
    await db_session.commit()
    yield
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(AllowanceCommitModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.execute(delete(VoucherModel).where(VoucherModel.buyer_identity_id == BUYER))
    await db_session.execute(delete(CapacityModel).where(CapacityModel.identity_id == BUYER))
    await db_session.commit()


@pytest.fixture
def chain(monkeypatch):
    """把链换成记账本 —— 每一次「上链」都被记下来，用来断言业务步骤 == 交易笔数。"""
    from services.chain import escrow_settlement as bridge

    calls: dict[str, list] = {"bind": [], "submit": [], "cancel": [], "confirm": []}

    # 回执门禁另有专门用例（test_the_receipt_gate_really_blocks_a_payout_with_no_receipt）：
    # 这里把它关掉 —— 等价于「这一单已经有成功回执」，免得每条用例都要先造一张回执。
    monkeypatch.setattr(
        settings, "settlement_requires_success_execution_receipt_for_seller_release", False
    )
    async def _list_commits(db, identity_id):
        return list(_commits.get(identity_id, []))

    async def _backing_report(db, identity_id):
        return dict(_report.get(identity_id) or {"chain_checked": False, "bills": {}})

    monkeypatch.setattr(escrow, "escrow_enabled", lambda: True)
    # 账单要落在「当前合约」上才会被挑中（旧合约的账单属于已退役的合约）。
    monkeypatch.setattr(settings, "allowance_escrow_address", "0x" + "11" * 20)
    monkeypatch.setattr(escrow, "list_commits", _list_commits)
    monkeypatch.setattr(escrow, "backing_report", _backing_report)

    def _open_order(
        *, buyer_bill_id, seller_bill_id, amount_usdc, stake_usdc, scope, task_id, **_kw
    ):
        calls["bind"].append((buyer_bill_id, seller_bill_id, amount_usdc, stake_usdc))
        return {
            "binding_id": 100 + len(calls["bind"]),
            "bind_tx_hash": "0xbind%d" % len(calls["bind"]),
            "amount_usdc": amount_usdc,
            "stake_usdc": stake_usdc,
            "scope_hash": "0x" + "aa" * 32,
        }

    def _submit_settlement(*, binding_id, proof, **_kw):
        calls["submit"].append((binding_id, proof))
        return {
            "binding_id": binding_id,
            "submit_tx_hash": "0xsubmit%d" % len(calls["submit"]),
            "proof_hash": "0x" + "bb" * 32,
            "pull_after": 1_700_000_000,
        }

    def _cancel_binding(*, binding_id, **_kw):
        calls["cancel"].append(binding_id)
        return {"binding_id": binding_id, "cancel_tx_hash": "0xcancel%d" % len(calls["cancel"])}

    def _buyer_confirm(*, binding_id, **_kw):
        calls["confirm"].append(binding_id)
        return {
            "binding_id": binding_id,
            "buyer_confirmed": True,
            "confirm_tx_hash": "0xconfirm%d" % len(calls["confirm"]),
            "status": "confirmed",
        }

    monkeypatch.setattr(escrow, "open_order", _open_order)
    monkeypatch.setattr(escrow, "submit_settlement", _submit_settlement)
    monkeypatch.setattr(escrow, "cancel_binding", _cancel_binding)
    monkeypatch.setattr(escrow, "binding_state", lambda *, binding_id, **kw: None)
    # 链上快照：默认「读不到」（等价于 RPC 抖动）。要模拟链上真的开着窗的用例
    # 自己覆盖这一条（见 v4 那组）。
    monkeypatch.setattr(escrow, "binding_snapshot", lambda *, binding_id, **kw: None)
    monkeypatch.setattr(escrow, "buyer_confirm", _buyer_confirm)
    monkeypatch.setattr(
        escrow, "bill_available", lambda *, bill_id, **kw: _available.get(str(bill_id))
    )
    return bridge, calls


# 每个用例自己往里塞账单：钱包 → 账单列表
_commits: dict[str, list] = {}
_report: dict[str, dict] = {}
#: 合约自己记的「这张账单还剩多少」—— 链上的事实，可能比台账小
_available: dict[str, float] = {}


def arm(identity_id: str, rows: list, *, chain_checked: bool = True, secured: dict | None = None):
    _commits[identity_id] = rows
    for r in rows:
        _available[str(r.bill_id)] = float(secured.get(str(r.bill_id), r.amount_usdc)) if secured else float(r.amount_usdc)
    secured = secured if secured is not None else {str(r.bill_id): float(r.amount_usdc) for r in rows}
    _report[identity_id] = {
        "allowance_usdc": sum(secured.values()),
        "committed_usdc": sum(secured.values()),
        "secured_usdc": sum(secured.values()),
        "unsecured_usdc": 0.0,
        "enforced": True,
        "chain_checked": chain_checked,
        "bills": {k: {"live_usdc": v, "secured_usdc": v} for k, v in secured.items()},
    }


def bounds(db):
    return (db.execute(select(EscrowBindingModel))).scalars().all()


@pytest.fixture(autouse=True)
def _reset_books():
    _commits.clear()
    _report.clear()
    _available.clear()
    yield
    _commits.clear()
    _report.clear()
    _available.clear()


@pytest.mark.asyncio
async def test_bind_refuses_without_a_real_onchain_lock(db_session, chain):
    bridge, calls = chain
    arm(BUYER, [])
    arm(SELLER, [])

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.bind_for_task(
            db_session, task_id=TASK, buyer_identity_id=BUYER,
            seller_identity_id=SELLER, amount_usdc=30.0,
        )
    assert exc.value.status == 409
    assert "锁仓" in exc.value.message
    assert calls["bind"] == []          # 一分工都没动


@pytest.mark.asyncio
async def test_bind_refuses_when_the_chain_cannot_be_read(db_session, chain):
    bridge, calls = chain
    arm(BUYER, [bill("1", BUYER, 50.0)], chain_checked=False)
    arm(SELLER, [bill("2", SELLER, 20.0)], chain_checked=False)

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.bind_for_task(
            db_session, task_id=TASK, buyer_identity_id=BUYER,
            seller_identity_id=SELLER, amount_usdc=30.0,
        )
    assert exc.value.status == 503
    assert calls["bind"] == []


@pytest.mark.asyncio
async def test_bind_ignores_a_bill_the_allowance_cannot_cover(db_session, chain):
    """台账上有 50，但授权额只分给这张账单 10 —— 划不动的额度不算额度。"""
    bridge, calls = chain
    arm(BUYER, [bill("1", BUYER, 50.0)], secured={"1": 10.0})
    arm(SELLER, [bill("2", SELLER, 20.0)])

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.bind_for_task(
            db_session, task_id=TASK, buyer_identity_id=BUYER,
            seller_identity_id=SELLER, amount_usdc=30.0,
        )
    assert exc.value.status == 409
    assert "10.0" in exc.value.message
    assert calls["bind"] == []


@pytest.mark.asyncio
async def test_bind_puts_the_stake_on_the_seller_and_reflects_on_the_settlement(db_session, chain):
    bridge, calls = chain
    db_session.add(settlement_row())
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])

    info = await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    assert info["status"] == "bound"
    assert calls["bind"] == [("1", "2", 30.0, 9.0)]     # 30% 质押，来自服务端规则
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert (row.buyer_bill_id, row.seller_bill_id, row.amount_usdc, row.stake_usdc) == ("1", "2", 30.0, 9.0)
    assert row.state == "active"

    model = (await db_session.execute(
        select(SettlementModel).where(SettlementModel.task_id == TASK)
    )).scalars().one()
    assert model.settlement_mode == "escrow_allowance"
    assert model.onchain_binding_id == 101
    assert model.onchain_status == "bound"
    assert model.tx_hash == "0xbind1"
    assert model.onchain_buyer_bill_id == 1
    assert model.onchain_agent_bill_id == 2


@pytest.mark.asyncio
async def test_bind_is_idempotent_for_one_task(db_session, chain):
    bridge, calls = chain
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])

    first = await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )
    second = await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    assert second["status"] == "already_bound"
    assert second["binding_id"] == first["binding_id"]
    assert len(calls["bind"]) == 1                     # 同一单只绑一次


@pytest.mark.asyncio
async def test_settle_submits_the_binding_and_opens_the_window(db_session, chain):
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))     # 账上：验收通过
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    out = await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)

    assert out["status"] == "finalizing"
    assert len(calls["submit"]) == 1
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert row.state == "finalizing"
    assert row.submit_tx_hash == "0xsubmit1"
    assert row.pull_after == 1_700_000_000
    model = (await db_session.execute(
        select(SettlementModel).where(SettlementModel.task_id == TASK)
    )).scalars().one()
    assert model.onchain_status == "finalizing"
    assert model.tx_hash == "0xsubmit1"


@pytest.mark.asyncio
async def test_partial_settlement_rebinds_for_the_amount_actually_released(db_session, chain):
    """链上没有「少划一点」的入口，所以少结必须撤掉重绑，不能按全额划走。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    await bridge.submit_for_task(db_session, task_id=TASK, released_amount=12.0)

    assert calls["cancel"] == [101]
    assert [c[2] for c in calls["bind"]] == [30.0, 12.0]
    assert calls["bind"][1][3] == 3.6                  # 12 的 30%
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert row.amount_usdc == 12.0
    assert row.state == "finalizing"


@pytest.mark.asyncio
async def test_cancel_puts_the_buyers_allowance_back(db_session, chain):
    bridge, calls = chain
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    out = await bridge.cancel_for_task(db_session, task_id=TASK)

    assert out["status"] == "cancelled"
    assert calls["cancel"] == [101]
    assert calls["submit"] == []
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert row.state == "cancelled"


@pytest.mark.asyncio
async def test_reconcile_adopts_the_chain_verdict_when_we_missed_the_receipt(db_session, chain, monkeypatch):
    """钱已经划走了，台账不能停在半路 —— 链说了算。"""
    bridge, calls = chain
    db_session.add(settlement_row())
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    row.state = "finalizing"
    row.finalize_tx_hash = "0xfinal1"
    await db_session.flush()
    monkeypatch.setattr(escrow, "binding_state", lambda *, binding_id, **kw: 3)   # settled

    out = await bridge.reconcile_task(db_session, task_id=TASK)

    assert out["status"] == "settled"
    model = (await db_session.execute(
        select(SettlementModel).where(SettlementModel.task_id == TASK)
    )).scalars().one()
    assert model.onchain_status == "settled"
    assert model.tx_hash == "0xfinal1"


@pytest.mark.asyncio
async def test_route_translates_the_gate_into_a_409(db_session, chain, monkeypatch):
    from fastapi import HTTPException
    from api.routes import settlement as route
    from core.schemas import TaskStatus

    bridge, _ = chain
    arm(BUYER, [])
    arm(SELLER, [])
    state = settlement_row()
    state.worker_agent_id = SELLER
    from core.schemas import SettlementState

    view = SettlementState(
        settlement_id=state.settlement_id,
        task_id=state.task_id,
        escrow_amount=state.escrow_amount,
        currency="USD",
        status=TaskStatus.ACCEPTED,
        client_agent_id=BUYER,
        worker_agent_id=SELLER,
    )
    with pytest.raises(HTTPException) as exc:
        await route._sync_escrow_settlement(db=db_session, state=view, target_status=TaskStatus.ACCEPTED)
    assert exc.value.status_code == 409

@pytest.mark.asyncio
async def test_the_api_view_exposes_the_binding_that_backs_the_money(db_session, chain):
    """操作台/API 必须看得见「这一单的钱由哪个 binding 背书」，否则又是数字。"""
    from db.stores.settlement_store import PostgresSettlementStore

    bridge, _ = chain
    db_session.add(settlement_row())
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )
    await db_session.flush()

    view = await PostgresSettlementStore(db_session).get(TASK)

    assert view.settlement_mode == "escrow_allowance"
    assert view.onchain_binding_id == 101
    assert view.onchain_buyer_bill_id == 1
    assert view.onchain_agent_bill_id == 2
    assert view.onchain_status == "bound"

@pytest.mark.asyncio
async def test_bind_trusts_the_chain_over_a_stale_ledger(db_session, chain):
    """台账是回执回写出来的，两个结算挨得近时会高估 —— 以合约自己记的为准。

    这条是实测打出来的：外卖单结完 30 秒又来一单，台账说还剩 11 USDC，链上其实
    只剩 5，bind 直接 revert 成一串 hex 丢给用户。
    """
    bridge, calls = chain
    arm(BUYER, [bill("1", BUYER, 50.0)])          # 台账：剩 50
    arm(SELLER, [bill("2", SELLER, 20.0)])
    _available["1"] = 5.0                          # 链上：只剩 5

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.bind_for_task(
            db_session, task_id=TASK, buyer_identity_id=BUYER,
            seller_identity_id=SELLER, amount_usdc=8.0,
        )
    assert exc.value.status == 409
    assert "5.0" in exc.value.message
    assert calls["bind"] == []


@pytest.mark.asyncio
async def test_bind_picks_the_bill_the_chain_can_still_cover(db_session, chain):
    """两张账单：链上只剩 2 的那张不能用，得挑还剩 20 的那张。"""
    bridge, calls = chain
    arm(BUYER, [bill("1", BUYER, 10.0), bill("3", BUYER, 20.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    _available["1"] = 2.0
    _available["3"] = 20.0

    info = await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=8.0,
    )

    assert info["status"] == "bound"
    assert calls["bind"][0][0] == "3"


# ------------------------------------------- F11：开窗之前先问账本（验证结论门禁）


@pytest.mark.asyncio
async def test_pay_refuses_when_the_books_have_no_settlement_at_all(db_session, chain):
    """账上连结算行都没有 —— 没有验证结论，链上不许开结算窗口。"""
    bridge, calls = chain
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)

    assert exc.value.status == 409
    assert calls["submit"] == []                         # 一扇窗都没打开


@pytest.mark.asyncio
async def test_pay_refuses_while_the_books_still_say_accepted(db_session, chain):
    """账上还停在 accepted（交付了、验收没走完）：钱一步都不能挪。"""
    bridge, calls = chain
    db_session.add(settlement_row())                     # status="accepted"
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)

    assert exc.value.status == 409
    assert "accepted" in exc.value.message
    assert calls["submit"] == []
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert row.state == "active"                         # 退回绑定期：钱还占着，但没动


@pytest.mark.asyncio
async def test_slash_refuses_unless_the_books_say_refunded(db_session, chain):
    """罚没同样是动钱：账上没落成 refunded，就不许开窗去划卖方的质押。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.slash_for_task(db_session, task_id=TASK)

    assert exc.value.status == 409
    assert calls["submit"] == []


@pytest.mark.asyncio
async def test_pay_refuses_when_the_receipt_guard_says_no(db_session, chain, monkeypatch):
    """路由层那道回执门禁，在钱这一步也必须生效（有人绕过路由直接调这一层时）。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    async def _refuse(db, *, task_id, amount_usdc):
        raise bridge.EscrowSettlementError(409, "没有成功执行回执，钱不划")

    monkeypatch.setattr(bridge, "_assert_success_receipt", _refuse)
    with pytest.raises(bridge.EscrowSettlementError):
        await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)
    assert calls["submit"] == []


@pytest.mark.asyncio
async def test_the_receipt_gate_really_blocks_a_payout_with_no_receipt(db_session):
    """真调用回执门禁（不 mock）：这一单一条成功回执都没有，就不许放款。"""
    from services.chain import escrow_settlement as bridge

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge._assert_success_receipt(db_session, task_id=TASK, amount_usdc=30.0)

    assert exc.value.status == 409
    # 金额是 0 时这道门不管（这一层只处理「要付给卖方」的钱）。
    await bridge._assert_success_receipt(db_session, task_id=TASK, amount_usdc=0.0)


@pytest.mark.asyncio
async def test_pay_refuses_when_delivery_verification_is_not_passed(db_session, chain, monkeypatch):
    """交付验证没过（P7 门禁）：钱留在买方钱包里，链上一扇窗都不开。"""
    from services import delivery_verification as dv

    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    monkeypatch.setattr(dv, "get_verification_for_task", lambda task_id: {"status": "PENDING"})

    def _boom(**kwargs):
        raise dv.DeliveryVerificationError("delivery not VERIFIED (status=PENDING)")

    monkeypatch.setattr(dv, "require_verified_for_settle", _boom)

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)

    assert exc.value.status == 409
    assert "验证" in exc.value.message
    assert calls["submit"] == []


@pytest.mark.asyncio
async def test_a_partial_release_is_rebound_in_chain_minor_units(db_session, chain):
    """12.345 这种金额：链上是整数最小单位，账上是 float —— 只认链上那个口径。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    await bridge.submit_for_task(db_session, task_id=TASK, released_amount=12.345)

    assert calls["bind"][1][2] == 12.345                 # 重绑按最小单位换算回来
    assert calls["submit"][0][1] == f"karma-settlement:{TASK}:12.345000"
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert round(row.amount_usdc * 10 ** 6) == 12_345_000


@pytest.mark.asyncio
async def test_cancel_gives_the_vouchers_reserved_credits_back(db_session, chain):
    """取消订单 = 链上授权放开 + 账上可用额度立刻回来（F10-1）。

    实测（2026-09-20）：W1 的 40.00 USDC 可用额度被 12 张「订单已取消」的授权码占着 ——
    链上早撤销了，账上却要等授权码自己过期（默认 7 天）才回来。
    """
    from core.schemas import VoucherStatus

    bridge, calls = chain
    db_session.add(
        VoucherModel(
            voucher_id="v-cancel",
            buyer_identity_id=BUYER,
            seller_identity_id=SELLER,
            amount=8.0,
            currency="USDC",
            bill_credit_amount=8.0,
            task_type="f11-cancel",
            task_description_hash="0" * 64,
            progress_rule_hash="0" * 64,
            evidence_requirement_hash="0" * 64,
            expiry_time=datetime.utcnow() + timedelta(days=7),
            nonce="v-cancel",
            buyer_signature="0x" + "00" * 65,
            status=VoucherStatus.ACCEPTED.value,
        )
    )
    db_session.add(
        CapacityModel(
            identity_id=BUYER,
            total_locked_usdc=50.0,
            total_bill_credits=50.0,
            available_credits=42.0,
            reserved_credits=8.0,
        )
    )
    row = settlement_row()
    row.voucher_id = "v-cancel"
    db_session.add(row)
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    out = await bridge.cancel_for_task(db_session, task_id=TASK)

    assert out["status"] == "cancelled"
    assert calls["cancel"] == [101]
    assert out["voucher"]["released_usdc"] == 8.0
    cap = await db_session.get(CapacityModel, BUYER)
    assert (cap.available_credits, cap.reserved_credits) == (50.0, 0.0)
    voucher = await db_session.get(VoucherModel, "v-cancel")
    assert voucher.status == VoucherStatus.CANCELLED.value


# -------------------------------------- 合约升级：绑定必须记得自己在哪台合约上

RETIRED = "0x" + "77" * 20


@pytest.mark.asyncio
async def test_a_bill_on_a_retired_contract_can_never_open_an_order(db_session, chain):
    """2026-09-20 实测：v2 换 v3 之后，旧账单把 ``/lock`` 打成了 500。

    回来的必须是「这是旧合约的账单，请重新锁仓」这句话，而不是一串 revert 的 hex；
    而且绝不能把旧账单挑出来去 bind。
    """
    bridge, calls = chain
    stale = bill("37", BUYER, 40.0)
    stale.contract_address = RETIRED
    arm(BUYER, [stale])
    arm(SELLER, [bill("4", SELLER, 1.0)])

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.bind_for_task(
            db_session, task_id=TASK, buyer_identity_id=BUYER,
            seller_identity_id=SELLER, amount_usdc=1.2,
        )

    assert exc.value.status == 409
    assert "旧" in exc.value.message and "重新锁仓" in exc.value.message
    assert RETIRED in exc.value.message      # 说清是哪台合约
    assert calls["bind"] == []


@pytest.mark.asyncio
async def test_a_binding_records_the_contract_it_was_opened_on(db_session, chain):
    """这一行之后要在**它自己那台**合约上 submit / finalize / cancel。"""
    bridge, _calls = chain
    db_session.add(settlement_row())
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])

    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )

    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert row.contract_address == settings.allowance_escrow_address


@pytest.mark.asyncio
async def test_a_binding_on_a_retired_contract_is_read_back_from_that_contract(
    db_session, chain, monkeypatch
):
    """升级之后旧绑定必须在旧合约上收尾：拿它去新合约就是 UnknownBinding revert，
    那笔钱会永久卡死（finalize 推不动、cancel 也推不动）。"""
    bridge, _calls = chain
    db_session.add(settlement_row())
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    row.contract_address = RETIRED
    row.state = "finalizing"
    row.bind_tx_hash = "0xbind-retired"
    await db_session.flush()

    seen: dict[str, object] = {}

    def _state(*, binding_id, contract_address=None):
        seen["binding_id"] = binding_id
        seen["contract_address"] = contract_address
        return 3  # SETTLED

    monkeypatch.setattr(escrow, "binding_state", _state)

    out = await bridge.reconcile_task(db_session, task_id=TASK)

    assert out["status"] == "settled"
    assert seen["contract_address"] == RETIRED
    refreshed = await db_session.get(EscrowBindingModel, row.binding_id)
    assert refreshed.state == "settled"


# ─────────────────────────── v4：买方确认（缩短窗口）+ 取消的状态机闸

async def _open_active(db_session, bridge) -> EscrowBindingModel:
    """开一张 ACTIVE 的绑定（钱还没动，谁都能撤）。"""
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session, task_id=TASK, buyer_identity_id=BUYER,
        seller_identity_id=SELLER, amount_usdc=30.0,
    )
    return (await db_session.execute(select(EscrowBindingModel))).scalars().one()


@pytest.mark.asyncio
async def test_buyer_confirm_marks_the_chain_and_makes_the_payout_due_now(db_session, chain):
    """验证已过 + 买方自己确认 -> 划款立刻到期，不再等争议窗口。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    row = await _open_active(db_session, bridge)
    await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)
    assert row.state == bridge.FINALIZING
    assert row.pull_after == 1_700_000_000          # 链上给的窗口
    assert row.buyer_confirmed_at is None

    out = await bridge.buyer_confirm_for_task(db_session, task_id=TASK)

    assert out["confirmed"] is True
    assert calls["confirm"] == [101]
    assert row.buyer_confirmed_at is not None
    assert row.pull_after <= int(time.time())       # 窗口不再挡路

    again = await bridge.buyer_confirm_for_task(db_session, task_id=TASK)
    assert again["already"] is True
    assert len(calls["confirm"]) == 1               # 不会重复发第二笔


@pytest.mark.asyncio
async def test_buyer_accept_path_marks_the_chain_in_the_same_request(db_session, chain):
    """验收（buyer-accept / partial / regret）走的是同一条：开窗 + 买方确认一起做完。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    row = await _open_active(db_session, bridge)

    await bridge.submit_for_task(
        db_session, task_id=TASK, released_amount=30.0, buyer_confirmed=True
    )

    assert calls["confirm"] == [101]
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.buyer_confirmed_at is not None
    assert fresh.pull_after <= int(time.time())


@pytest.mark.asyncio
async def test_cancel_is_refused_once_the_money_has_an_owner_in_waiting(db_session, chain):
    """取消的判据是**责任状态**，不是时间：窗口开着就不许撤（v4 的状态机闸）。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    row = await _open_active(db_session, bridge)
    await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.cancel_for_task(db_session, task_id=TASK)

    assert exc.value.status == 409
    assert "责任状态" in exc.value.message
    assert calls["cancel"] == []                    # 一笔都没发
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.state == bridge.FINALIZING         # 状态机不许被改写


@pytest.mark.asyncio
async def test_cancel_follows_the_chain_when_the_ledger_is_behind(db_session, chain, monkeypatch):
    """账上写 active、链上其实已经开窗：按链上拉齐，并且拒绝这次取消。"""
    bridge, calls = chain
    row = await _open_active(db_session, bridge)
    monkeypatch.setattr(
        escrow,
        "binding_snapshot",
        lambda *, binding_id, **kw: {
            "state": 2,                             # FINALIZING
            "buyer_confirmed": False,
            "confirmed_at": 0,
            "settle_after": 1_700_000_060,
            "closed_at": 0,
        },
    )

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.cancel_for_task(db_session, task_id=TASK)

    assert exc.value.status == 409
    assert calls["cancel"] == []
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.state == bridge.FINALIZING         # 台账按链上拉齐
    assert fresh.pull_after == 1_700_000_060        # 窗口也跟着链上走


@pytest.mark.asyncio
async def test_submit_does_not_re_send_when_the_chain_already_opened_the_window(
    db_session, chain, monkeypatch
):
    """submit 的交易上链了、写库断在中间：不重发，直接把台账拉到链上。"""
    bridge, calls = chain
    db_session.add(settlement_row(status="settled"))
    await db_session.flush()
    row = await _open_active(db_session, bridge)
    monkeypatch.setattr(
        escrow,
        "binding_snapshot",
        lambda *, binding_id, **kw: {
            "state": 2,
            "buyer_confirmed": False,
            "confirmed_at": 0,
            "settle_after": 1_700_000_060,
            "closed_at": 0,
        },
    )

    await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)

    assert calls["submit"] == []                    # 没有第二笔 submit
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.state == bridge.FINALIZING
    assert fresh.pull_after == 1_700_000_060
