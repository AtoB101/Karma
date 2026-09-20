"""违约罚没（finalizeBreach）—— 卖方质押必须真的会被划走。

没有这一层，「质押」就只是链上一次冻结再解冻：卖家违约零代价，买家拿不回任何补偿。
这些用例钉死四件事：

1. 判了违约之后 binding 绝不能停在 ``finalizing``（否则正常结算通道会把货款划给卖方）；
2. 窗口到点后由 ``escrow_autosettle`` 真的发 ``finalizeBreach``，卖方钱包 → 买方钱包；
3. 罚没失败要退避，链上已经落定要能自愈；
4. 业务状态机里 ``REFUNDED``（= 交付被裁定为一文不值）走罚没，``CANCELLED`` 才走撤销。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from core.schemas import TaskStatus
from config.settings import settings
from db.models.orm import AllowanceCommitModel, EscrowBindingModel, SettlementModel
from services.chain import allowance_escrow as escrow

TASK = "task-breach-slash"
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


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(AllowanceCommitModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()
    yield
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.execute(delete(AllowanceCommitModel))
    await db_session.execute(delete(SettlementModel).where(SettlementModel.task_id == TASK))
    await db_session.commit()


_commits: dict[str, list] = {}
_report: dict[str, dict] = {}
_available: dict[str, float] = {}


def arm(identity_id: str, rows: list):
    _commits[identity_id] = rows
    for r in rows:
        _available[str(r.bill_id)] = float(r.amount_usdc)
    secured = {str(r.bill_id): float(r.amount_usdc) for r in rows}
    _report[identity_id] = {
        "allowance_usdc": sum(secured.values()),
        "committed_usdc": sum(secured.values()),
        "secured_usdc": sum(secured.values()),
        "unsecured_usdc": 0.0,
        "chain_checked": True,
        "bills": {k: {"live_usdc": v, "secured_usdc": v} for k, v in secured.items()},
    }


@pytest.fixture(autouse=True)
def _reset_books():
    _commits.clear()
    _report.clear()
    _available.clear()
    yield
    _commits.clear()
    _report.clear()
    _available.clear()


@pytest.fixture
def chain(monkeypatch):
    from services.chain import escrow_settlement as bridge

    calls: dict[str, list] = {"bind": [], "submit": [], "cancel": [], "breach": []}

    async def _list_commits(db, identity_id):
        return list(_commits.get(identity_id, []))

    async def _backing_report(db, identity_id):
        return dict(_report.get(identity_id) or {"chain_checked": False, "bills": {}})

    def _open_order(
        *, buyer_bill_id, seller_bill_id, amount_usdc, stake_usdc, scope, task_id, **_kw
    ):
        calls["bind"].append((buyer_bill_id, seller_bill_id, amount_usdc, stake_usdc))
        return {
            "binding_id": 200 + len(calls["bind"]),
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
            "pull_after": int(time.time()) + 60,
        }

    def _cancel_binding(*, binding_id, **_kw):
        calls["cancel"].append(binding_id)
        return {"binding_id": binding_id, "cancel_tx_hash": "0xcancel%d" % len(calls["cancel"])}

    monkeypatch.setattr(escrow, "escrow_enabled", lambda: True)
    # 账单要落在「当前合约」上才会被挑中（旧合约的账单属于已退役的合约）。
    monkeypatch.setattr(settings, "allowance_escrow_address", "0x" + "11" * 20)
    monkeypatch.setattr(escrow, "list_commits", _list_commits)
    monkeypatch.setattr(escrow, "backing_report", _backing_report)
    monkeypatch.setattr(escrow, "open_order", _open_order)
    monkeypatch.setattr(escrow, "submit_settlement", _submit_settlement)
    monkeypatch.setattr(escrow, "cancel_binding", _cancel_binding)
    monkeypatch.setattr(escrow, "binding_state", lambda *, binding_id, **kw: None)
    monkeypatch.setattr(
        escrow, "bill_available", lambda *, bill_id, **kw: _available.get(str(bill_id))
    )
    return bridge, calls


async def _open(db_session, bridge):
    """开一张 ACTIVE 的 binding（走真实 bind_for_task）。

    账上先把这一单落成 ``refunded``：罚没要开结算窗口，而开窗的前提是「账上已经有
    一个验证结论」（见 escrow_settlement.assert_release_verified）。
    """
    db_session.add(
        SettlementModel(
            settlement_id="stl-" + TASK,
            task_id=TASK,
            escrow_amount=30.0,
            currency="USD",
            status="refunded",
            client_agent_id=BUYER,
            worker_agent_id=SELLER,
        )
    )
    await db_session.flush()
    arm(BUYER, [bill("1", BUYER, 50.0)])
    arm(SELLER, [bill("2", SELLER, 20.0)])
    await bridge.bind_for_task(
        db_session,
        task_id=TASK,
        buyer_identity_id=BUYER,
        seller_identity_id=SELLER,
        amount_usdc=30.0,
    )
    row = (await db_session.execute(select(EscrowBindingModel))).scalars().one()
    assert row.state == "active"
    return row


# --------------------------------------------------------------- 罚没：开窗

@pytest.mark.asyncio
async def test_slash_opens_the_window_and_never_leaves_it_finalizing(db_session, chain):
    """罚没要 submit 开窗，但状态绝不能停在 finalizing —— 否则 autosettle 会把货款划给卖方。"""
    bridge, calls = chain
    row = await _open(db_session, bridge)

    out = await bridge.slash_for_task(db_session, task_id=TASK)

    assert out["status"] == "breaching"
    assert len(calls["submit"]) == 1
    assert calls["cancel"] == []
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.state == "breaching"
    assert fresh.pull_after and fresh.pull_after > 0
    assert fresh.submit_tx_hash == "0xsubmit1"


@pytest.mark.asyncio
async def test_slash_reuses_an_open_window_without_submitting_again(db_session, chain):
    bridge, calls = chain
    row = await _open(db_session, bridge)
    row.state = "finalizing"
    row.pull_after = 1_700_000_000
    await db_session.commit()

    out = await bridge.slash_for_task(db_session, task_id=TASK)

    assert out["status"] == "breaching"
    assert calls["submit"] == []
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.state == "breaching"
    assert fresh.pull_after == 1_700_000_000


@pytest.mark.asyncio
async def test_slash_is_idempotent_and_never_touches_a_done_binding(db_session, chain):
    bridge, calls = chain
    row = await _open(db_session, bridge)
    await bridge.slash_for_task(db_session, task_id=TASK)

    second = await bridge.slash_for_task(db_session, task_id=TASK)
    assert second["status"] == "breaching"
    assert len(calls["submit"]) == 1  # 第二次没有重复开窗

    row.state = "slashed"
    await db_session.commit()
    third = await bridge.slash_for_task(db_session, task_id=TASK)
    assert third["status"] == "slashed"
    assert len(calls["submit"]) == 1


# ------------------------------------------------- 罚没中不许被当成「该付卖方」

@pytest.mark.asyncio
async def test_cancel_for_task_refuses_to_release_a_breaching_binding(db_session, chain):
    """breaching 的 binding 只能走罚没通道；撤销会把它变成「不罚了」，必须拒绝。"""
    bridge, calls = chain
    row = await _open(db_session, bridge)
    await bridge.slash_for_task(db_session, task_id=TASK)

    out = await bridge.cancel_for_task(db_session, task_id=TASK)

    assert out["status"] == "breaching"
    assert calls["cancel"] == []
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.state == "breaching"


@pytest.mark.asyncio
async def test_submit_for_task_will_not_pay_a_breaching_binding(db_session, chain):
    bridge, calls = chain
    row = await _open(db_session, bridge)
    await bridge.slash_for_task(db_session, task_id=TASK)
    calls["submit"].clear()

    out = await bridge.submit_for_task(db_session, task_id=TASK, released_amount=30.0)

    assert out["status"] == "breaching"
    assert calls["submit"] == []


@pytest.mark.asyncio
async def test_reconcile_task_reads_the_slash_back_from_chain(db_session, chain, monkeypatch):
    bridge, calls = chain
    row = await _open(db_session, bridge)
    await bridge.slash_for_task(db_session, task_id=TASK)
    monkeypatch.setattr(escrow, "binding_state", lambda *, binding_id, **kw: 4)  # SLASHED

    out = await bridge.reconcile_task(db_session, task_id=TASK)

    assert out["status"] == "slashed"
    fresh = await db_session.get(EscrowBindingModel, row.binding_id)
    assert fresh.state == "slashed"


# ------------------------------------------------------- 业务状态机：谁走哪条

@pytest.mark.asyncio
async def test_refunded_routes_to_slashing_and_cancelled_routes_to_release(db_session, monkeypatch):
    from api.routes import settlement as routes
    from services.chain import escrow_settlement as bridge

    seen: list[tuple] = []

    monkeypatch.setattr(bridge, "enabled", lambda: True)

    async def _slash(db, *, task_id):
        seen.append(("slash", task_id))
        return {}

    async def _cancel(db, *, task_id):
        seen.append(("cancel", task_id))
        return {}

    async def _bind(db, **kw):
        seen.append(("bind", kw["task_id"]))
        return {}

    async def _submit(db, *, task_id, released_amount=None):
        seen.append(("submit", task_id))
        return {}

    monkeypatch.setattr(bridge, "slash_for_task", _slash)
    monkeypatch.setattr(bridge, "cancel_for_task", _cancel)
    monkeypatch.setattr(bridge, "bind_for_task", _bind)
    monkeypatch.setattr(bridge, "submit_for_task", _submit)

    state = SimpleNamespace(task_id="task-x", client_agent_id=BUYER, worker_agent_id=SELLER,
                            escrow_amount=10.0, released_amount=0.0)

    await routes._sync_escrow_settlement(db=db_session, state=state, target_status=TaskStatus.REFUNDED)
    await routes._sync_escrow_settlement(db=db_session, state=state, target_status=TaskStatus.CANCELLED)
    await routes._sync_escrow_settlement(db=db_session, state=state, target_status=TaskStatus.ACCEPTED)
    await routes._sync_escrow_settlement(db=db_session, state=state, target_status=TaskStatus.SETTLED)

    assert seen == [
        ("slash", "task-x"),
        ("cancel", "task-x"),
        ("bind", "task-x"),
        ("submit", "task-x"),
    ]


# ------------------------------------------------ autosettle：到点真的划质押

def _binding(binding_id: str, *, state: str = "breaching", pull_after: int | None = None):
    return EscrowBindingModel(
        binding_id=binding_id,
        buyer_identity_id=BUYER,
        seller_identity_id=SELLER,
        buyer_bill_id="1",
        seller_bill_id="2",
        scope_hash="0x" + "00" * 32,
        task_id=TASK,
        amount_usdc=30.0,
        stake_usdc=9.0,
        state=state,
        pull_after=pull_after,
    )


@pytest.fixture(autouse=True)
def _autosettle(monkeypatch):
    from services.chain import escrow_autosettle as autosettle

    autosettle.reset_backoff()
    monkeypatch.setattr(autosettle.escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(autosettle.escrow, "can_server_settle", lambda: True)
    monkeypatch.setattr(autosettle.escrow, "binding_state", lambda *, binding_id, **kw: None)

    async def _noop_sync(db, identity_id):
        return []

    monkeypatch.setattr(autosettle.escrow, "sync_commits", _noop_sync)
    yield autosettle
    autosettle.reset_backoff()


@pytest.mark.asyncio
async def test_due_breach_bindings_picks_only_armed_and_elapsed(db_session, _autosettle):
    now = int(time.time())
    db_session.add_all(
        [
            _binding("1", pull_after=now - 30),
            _binding("2", pull_after=now + 3600),                 # 窗口还没到
            _binding("3", state="finalizing", pull_after=now - 30),  # 正常结算的单，不归罚没管
            _binding("4", state="settled", pull_after=now - 30),
            _binding("5", pull_after=None),
        ]
    )
    await db_session.commit()

    rows = await _autosettle.due_breach_bindings(db_session, now=now)

    assert [r.binding_id for r in rows] == ["1"]


@pytest.mark.asyncio
async def test_breach_due_executes_the_slash_and_records_the_tx(db_session, _autosettle, monkeypatch):
    seen: list[int] = []

    def _finalize_breach(*, binding_id: int, **_kw):
        seen.append(binding_id)
        return {"breach_tx_hash": "0xslash", "slashed_usdc": 9.0}

    monkeypatch.setattr(escrow, "finalize_breach", _finalize_breach)
    db_session.add(_binding("7", pull_after=int(time.time()) - 30))
    await db_session.commit()

    slashed = await _autosettle.breach_due(db_session)

    assert seen == [7]
    assert slashed[0]["finalize_tx_hash"] == "0xslash"
    row = await db_session.get(EscrowBindingModel, "7")
    assert row.state == "slashed"
    assert row.finalize_tx_hash == "0xslash"


@pytest.mark.asyncio
async def test_the_normal_settle_pass_never_touches_a_breaching_binding(
    db_session, _autosettle, monkeypatch
):
    """回归钉子：breaching 的单绝不能被正常结算通道划走货款。"""
    paid: list[int] = []
    monkeypatch.setattr(
        escrow, "finalize_settlement", lambda *, binding_id, **kw: paid.append(binding_id)
    )
    db_session.add(_binding("8", pull_after=int(time.time()) - 30))
    await db_session.commit()

    assert await _autosettle.settle_due(db_session) == []
    assert paid == []
    row = await db_session.get(EscrowBindingModel, "8")
    assert row.state == "breaching"


@pytest.mark.asyncio
async def test_a_failed_slash_backs_off(db_session, _autosettle, monkeypatch):
    attempts: list[int] = []

    def _boom(*, binding_id: int, **_kw):
        attempts.append(binding_id)
        raise RuntimeError("execution reverted")

    monkeypatch.setattr(escrow, "finalize_breach", _boom)
    db_session.add(_binding("9", pull_after=int(time.time()) - 30))
    await db_session.commit()

    assert await _autosettle.breach_due(db_session) == []
    assert await _autosettle.breach_due(db_session) == []
    assert attempts == [9]
    row = await db_session.get(EscrowBindingModel, "9")
    assert row.state == "breaching"


@pytest.mark.asyncio
async def test_chain_already_slashed_is_reconciled_without_another_tx(
    db_session, _autosettle, monkeypatch
):
    sent: list[int] = []
    monkeypatch.setattr(
        escrow, "finalize_breach", lambda *, binding_id, **kw: sent.append(binding_id)
    )
    monkeypatch.setattr(escrow, "binding_state", lambda *, binding_id, **kw: 4)  # SLASHED
    db_session.add(_binding("10", pull_after=int(time.time()) - 30))
    await db_session.commit()

    out = await _autosettle.breach_due(db_session)

    assert sent == []
    assert out[0]["binding_id"] == "10"
    row = await db_session.get(EscrowBindingModel, "10")
    assert row.state == "slashed"
