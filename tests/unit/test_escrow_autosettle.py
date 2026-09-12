"""Auto-settlement: the caller that makes "verify, then the money moves" true.

The chain has always allowed the pull - it is permissionless once the challenge
window elapses. What these tests pin down is that Karma's own process makes the
call, exactly once, records the tx, and backs off instead of hammering the
operator account when a binding cannot settle yet.
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import delete

from db.models.orm import EscrowBindingModel
from services.chain import escrow_autosettle as autosettle
from services.chain.wallet_lock import WalletLockError


def binding(
    binding_id: str,
    *,
    state: str = "finalizing",
    pull_after: int | None = None,
    buyer_identity_id: str = "kid_buyer",
    seller_identity_id: str | None = "kid_seller",
) -> EscrowBindingModel:
    return EscrowBindingModel(
        binding_id=binding_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        buyer_bill_id="10",
        seller_bill_id="11",
        scope_hash="0x" + "00" * 32,
        task_id="task-autosettle",
        amount_usdc=30.0,
        stake_usdc=9.0,
        state=state,
        pull_after=pull_after,
    )


async def _noop_sync(db, identity_id):  # bookkeeping only; the real one re-reads the chain
    return []


@pytest.fixture(autouse=True)
async def _armed(db_session, monkeypatch):
    """Every test starts armed, with the chain faked and the table empty."""
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.commit()
    autosettle.reset_backoff()
    monkeypatch.setattr(autosettle.escrow, "escrow_enabled", lambda: True)
    monkeypatch.setattr(autosettle.escrow, "can_server_settle", lambda: True)
    monkeypatch.setattr(autosettle.escrow, "sync_commits", _noop_sync)
    yield
    autosettle.reset_backoff()
    await db_session.execute(delete(EscrowBindingModel))
    await db_session.commit()


@pytest.mark.asyncio
async def test_due_bindings_picks_only_bindings_whose_window_elapsed(db_session):
    now = int(time.time())
    db_session.add_all(
        [
            binding("1", pull_after=now - 5),
            binding("2", pull_after=now + 3600),   # window still open
            binding("3", pull_after=None),          # never submitted
            binding("4", state="settled", pull_after=now - 5),   # already paid
            binding("5", state="active", pull_after=0),          # not yet finalizing
        ]
    )
    await db_session.commit()

    rows = await autosettle.due_bindings(db_session, now=now)

    assert [r.binding_id for r in rows] == ["1"]


@pytest.mark.asyncio
async def test_settle_due_executes_the_pull_and_records_the_tx(db_session, monkeypatch):
    seen: list[int] = []

    def _finalize(*, binding_id: int):
        seen.append(binding_id)
        return {"finalize_tx_hash": "0xdeadbeef"}

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _finalize)
    db_session.add(binding("7", pull_after=int(time.time()) - 1))
    await db_session.commit()

    settled = await autosettle.settle_due(db_session)

    assert seen == [7]
    assert settled == [
        {"binding_id": "7", "finalize_tx_hash": "0xdeadbeef", "amount_usdc": 30.0}
    ]
    row = await db_session.get(EscrowBindingModel, "7")
    assert row.state == "settled"
    assert row.finalize_tx_hash == "0xdeadbeef"


@pytest.mark.asyncio
async def test_a_binding_that_cannot_settle_yet_backs_off(db_session, monkeypatch):
    attempts: list[int] = []

    def _boom(*, binding_id: int):
        attempts.append(binding_id)
        raise RuntimeError("execution reverted: not funded yet")

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _boom)
    db_session.add(binding("9", pull_after=int(time.time()) - 1))
    await db_session.commit()

    assert await autosettle.settle_due(db_session) == []
    assert await autosettle.settle_due(db_session) == []
    assert attempts == [9]  # the second tick skipped it instead of paying twice
    row = await db_session.get(EscrowBindingModel, "9")
    assert row.state == "finalizing"

    autosettle.reset_backoff()
    assert await autosettle.settle_due(db_session) == []
    assert attempts == [9, 9]  # an explicit reset is what retries


@pytest.mark.asyncio
async def test_a_declined_pull_backs_off_too(db_session, monkeypatch):
    attempts: list[int] = []

    def _refuse(*, binding_id: int):
        attempts.append(binding_id)
        raise WalletLockError("allowance is not funded yet")

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _refuse)
    db_session.add(binding("12", pull_after=int(time.time()) - 1))
    await db_session.commit()

    assert await autosettle.settle_due(db_session) == []
    assert await autosettle.settle_due(db_session) == []
    assert attempts == [12]


@pytest.mark.asyncio
async def test_nothing_is_executed_without_the_operator_key(db_session, monkeypatch):
    monkeypatch.setattr(autosettle.escrow, "can_server_settle", lambda: False)
    called: list[int] = []
    monkeypatch.setattr(
        autosettle.escrow, "finalize_settlement", lambda *, binding_id: called.append(binding_id)
    )
    db_session.add(binding("14", pull_after=int(time.time()) - 1))
    await db_session.commit()

    assert await autosettle.settle_due(db_session) == []
    assert called == []


@pytest.mark.asyncio
async def test_a_settled_binding_is_never_pulled_twice(db_session, monkeypatch):
    calls: list[int] = []

    def _finalize(*, binding_id: int):
        calls.append(binding_id)
        return {"finalize_tx_hash": "0xfeed"}

    monkeypatch.setattr(autosettle.escrow, "finalize_settlement", _finalize)
    db_session.add(binding("16", pull_after=int(time.time()) - 5))
    await db_session.commit()

    assert len(await autosettle.settle_due(db_session)) == 1
    assert await autosettle.settle_due(db_session) == []
    assert calls == [16]
