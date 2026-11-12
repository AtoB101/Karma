"""自成交脏单的出口（2026-10-14）：取消这条腿不许被「补绑」堵死。

背景：接单那一刻的自成交硬闸（``test_self_dealing_ban.py``）挡住了**新的**自成交；
但历史遗留的那张（settlement ``97f0dc0e``，2026-10-13）还卡在 ``in_progress`` —— 它每一格
出口都要先补绑，补绑必 409，于是永久没有出口。详见
``security/audit/2026-10-14-self-deal-settlement-recovery-plan.md``。

这组用例钉三件事：
1. 判定抽成 ``detect_self_dealing`` 之后，四条口径与 ``assert_...`` 的报文**一字未改**；
2. 自成交 + ``pending_bind`` 的单，取消时**跳过补绑**，直接走 ``cancel_for_task``；
3. 不是自成交的单，取消时**照旧补绑**（不许误伤）。
"""
from __future__ import annotations

import pytest

from core.schemas import SettlementState, TaskStatus
from services.identity_gateway import store

TASK = "task-self-deal-recovery"
WALLET = "0x" + "ab" * 20


@pytest.fixture(autouse=True)
def _isolate_identity_store():
    store.reset_for_tests()
    yield
    store.reset_for_tests()


def _state(client: str, worker: str, *, onchain_status: str | None) -> SettlementState:
    return SettlementState(
        task_id=TASK,
        escrow_amount=1.0,
        currency="USD",
        client_agent_id=client,
        worker_agent_id=worker,
        status=TaskStatus.IN_PROGRESS,
        onchain_status=onchain_status,
    )


# --------------------------- 1. 判定抽身后，报文一字未改


@pytest.mark.asyncio
async def test_detector_reports_the_same_party(db_session):
    from services.chain import escrow_settlement as bridge

    hit = await bridge.detect_self_dealing(
        db_session, buyer_identity_id="kid_same", seller_identity_id="kid_same"
    )
    assert hit is not None
    reason, detail, message = hit
    assert reason == "same_party_id"
    assert detail == "kid_same"
    assert "自成交" in message


@pytest.mark.asyncio
async def test_detector_reports_two_sub_identities_of_one_owner(db_session):
    from services.chain import escrow_settlement as bridge

    store.seed_identity("kid_main", "0x" + "01" * 20, twofa_code="111111")
    sub = store.create_sub_identity("kid_main", "0x" + "02" * 20)

    hit = await bridge.detect_self_dealing(
        db_session, buyer_identity_id="kid_main", seller_identity_id=sub.identity_id
    )
    assert hit is not None
    assert hit[0] == "same_owner_identity"
    assert "同一个钱包主身份" in hit[2]


@pytest.mark.asyncio
async def test_detector_reports_one_wallet_shared_by_two_owners(db_session):
    from services.chain import escrow_settlement as bridge

    store.seed_identity("kid_a", WALLET, twofa_code="111111")
    store.seed_identity("kid_b", WALLET, twofa_code="222222")

    hit = await bridge.detect_self_dealing(
        db_session, buyer_identity_id="kid_a", seller_identity_id="kid_b"
    )
    assert hit is not None
    assert hit[0] == "same_wallet"
    assert hit[1] == WALLET


@pytest.mark.asyncio
async def test_detector_returns_none_for_two_unrelated_parties(db_session):
    from services.chain import escrow_settlement as bridge

    store.seed_identity("kid_a", "0x" + "01" * 20, twofa_code="111111")
    store.seed_identity("kid_b", "0x" + "02" * 20, twofa_code="222222")

    assert (
        await bridge.detect_self_dealing(
            db_session, buyer_identity_id="kid_a", seller_identity_id="kid_b"
        )
        is None
    )


@pytest.mark.asyncio
async def test_assert_still_raises_409_with_the_same_wording(db_session):
    from services.chain import escrow_settlement as bridge

    with pytest.raises(bridge.EscrowSettlementError) as exc:
        await bridge.assert_parties_not_self_dealing(
            db_session, task_id=TASK, buyer_identity_id="kid_same", seller_identity_id="kid_same"
        )
    assert exc.value.status == 409
    assert "自成交" in exc.value.message


# --------------------------- 2/3. 取消这条腿的补绑闸


@pytest.mark.asyncio
async def test_a_self_deal_pending_bind_skips_the_deferred_bind_and_cancels(db_session, monkeypatch):
    from api.routes import settlement as routes
    from services.chain import escrow_settlement as bridge

    monkeypatch.setattr(bridge, "enabled", lambda: True)

    materialized: list[str] = []

    async def _materialize(db, *, task_id):
        materialized.append(task_id)
        raise bridge.EscrowSettlementError(409, "自己跟自己，链上 SameOwner()")

    cancelled: list[str] = []

    async def _cancel(db, *, task_id):
        cancelled.append(task_id)
        return {"status": "unbound"}

    monkeypatch.setattr(bridge, "materialize_pending_bind", _materialize)
    monkeypatch.setattr(bridge, "cancel_for_task", _cancel)

    # 买卖双方是同一个当事方（判定走真实实现，不需要替身）。
    state = _state("kid_same", "kid_same", onchain_status=bridge.PENDING_BIND)
    await routes._sync_escrow_settlement(
        db=db_session, state=state, target_status=TaskStatus.CANCELLED
    )

    assert materialized == [], "自成交的空头单不该去撞补绑那堵墙"
    assert cancelled == [TASK], "取消必须照常走到链上出口（对本单是 no-op）"


@pytest.mark.asyncio
async def test_a_normal_pending_bind_still_materializes_before_cancel(db_session, monkeypatch):
    from api.routes import settlement as routes
    from services.chain import escrow_settlement as bridge

    monkeypatch.setattr(bridge, "enabled", lambda: True)

    store.seed_identity("kid_a", "0x" + "01" * 20, twofa_code="111111")
    store.seed_identity("kid_b", "0x" + "02" * 20, twofa_code="222222")

    materialized: list[str] = []

    async def _materialize(db, *, task_id):
        materialized.append(task_id)

    cancelled: list[str] = []

    async def _cancel(db, *, task_id):
        cancelled.append(task_id)
        return {"status": "cancelled"}

    monkeypatch.setattr(bridge, "materialize_pending_bind", _materialize)
    monkeypatch.setattr(bridge, "cancel_for_task", _cancel)

    state = _state("kid_a", "kid_b", onchain_status=bridge.PENDING_BIND)
    await routes._sync_escrow_settlement(
        db=db_session, state=state, target_status=TaskStatus.CANCELLED
    )

    assert materialized == [TASK], "正常单取消前必须先把延迟的绑定补实"
    assert cancelled == [TASK]


@pytest.mark.asyncio
async def test_an_already_bound_self_deal_shape_is_not_special_cased(db_session, monkeypatch):
    """只有 ``pending_bind`` 才跳过：已经绑成的单走老路（这一格不该被这条出口影响）。"""
    from api.routes import settlement as routes
    from services.chain import escrow_settlement as bridge

    monkeypatch.setattr(bridge, "enabled", lambda: True)

    materialized: list[str] = []

    async def _materialize(db, *, task_id):
        materialized.append(task_id)

    async def _cancel(db, *, task_id):
        return {"status": "cancelled"}

    monkeypatch.setattr(bridge, "materialize_pending_bind", _materialize)
    monkeypatch.setattr(bridge, "cancel_for_task", _cancel)

    state = _state("kid_same", "kid_same", onchain_status="bound")
    await routes._sync_escrow_settlement(
        db=db_session, state=state, target_status=TaskStatus.CANCELLED
    )

    assert materialized == [TASK]
