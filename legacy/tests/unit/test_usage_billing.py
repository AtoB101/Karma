"""按次计费与阈值结算：幂等、阈值、上限、以及"没真划走就不许叫已结算"。

这个模块最容易出的 bug 是「账上说出账了、钱没动」。所以下面每个失败分支都断言两件事：
结算单停在什么状态、账本恒等式（accrued + billed）有没有被破坏。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AllowanceCommitModel, EscrowBindingModel, SkillModel
from services import usage_billing
from services.chain import allowance_escrow as escrow

PAYER = "payer-usage-1"
PROVIDER = "provider-usage-1"


def _tag() -> str:
    return uuid.uuid4().hex[:10]


async def _skill(
    db: AsyncSession, *, price: float = 0.01, threshold: float = 0.02, cap: float | None = None
) -> SkillModel:
    row = SkillModel(
        owner_identity_id=PROVIDER,
        slug=f"ticker-{_tag()}",
        name="行情快照 API",
        category="data_api",
        summary="按次计费的行情快照",
        endpoint_url="https://data-example.com/v1/ticker",
        unit_price_usdc=price,
        settlement_threshold_usdc=threshold,
        default_cap_usdc=cap,
        verified_domain="data-example.com",
        status="published",
    )
    db.add(row)
    await db.flush()
    return row


async def _commit(db: AsyncSession, identity_id: str, amount: float, tag: str) -> None:
    db.add(
        AllowanceCommitModel(
            bill_id=f"bill-{tag}-{_tag()}",
            identity_id=identity_id,
            wallet_address="0x" + "ab" * 20,
            amount_usdc=amount,
            commit_tx_hash="0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            state=escrow.IDLE,
        )
    )
    await db.flush()


def _escrow_online(monkeypatch, *, sink: dict | None = None):
    monkeypatch.setattr(escrow, "can_server_settle", lambda: True)
    marker = sink if sink is not None else {}

    def _fake_open(**kwargs):
        marker.update(kwargs)
        return {
            "binding_id": int(uuid.uuid4().int % 900000) + 1000,
            "scope_hash": "0x" + "11" * 32,
            "bind_tx_hash": "0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            "submit_tx_hash": "0x" + uuid.uuid4().hex + uuid.uuid4().hex,
            "proof_hash": "0x" + "44" * 32,
            "pull_after": 1,
        }

    monkeypatch.setattr(escrow, "open_and_submit_order", _fake_open)
    return marker


async def _meter(db: AsyncSession, skill: SkillModel, payer: str = PAYER):
    return await usage_billing.get_meter(
        db, skill_id=skill.skill_id, payer_identity_id=payer
    )


@pytest.mark.asyncio
async def test_replay_same_request_id_is_not_charged_twice(db_session: AsyncSession):
    skill = await _skill(db_session)
    first = await usage_billing.record_usage(
        db_session, skill=skill, payer_identity_id=PAYER, request_id="req-1", units=3
    )
    assert first["duplicate"] is False
    assert first["amount_usdc"] == 0.03

    replay = await usage_billing.record_usage(
        db_session, skill=skill, payer_identity_id=PAYER, request_id="req-1", units=3
    )
    assert replay["duplicate"] is True
    assert replay["amount_usdc"] == 0.03
    assert replay["charge"]["charge_id"] == first["charge"]["charge_id"]

    meter = await _meter(db_session, skill)
    assert meter.calls == 3
    assert meter.accrued_usdc == 0.03


@pytest.mark.asyncio
async def test_below_threshold_stays_accrued(db_session: AsyncSession, monkeypatch):
    skill = await _skill(db_session, threshold=0.05)
    _escrow_online(monkeypatch)
    await usage_billing.record_usage(
        db_session, skill=skill, payer_identity_id=PAYER, request_id="req-1"
    )
    assert await usage_billing.settle_meter(db_session, skill=skill, payer_identity_id=PAYER) is None
    meter = await _meter(db_session, skill)
    assert meter.accrued_usdc == 0.01
    assert meter.billed_usdc == 0.0


@pytest.mark.asyncio
async def test_threshold_opens_a_settlement_and_links_charges(
    db_session: AsyncSession, monkeypatch
):
    skill = await _skill(db_session, threshold=0.02)
    for i in range(2):
        await usage_billing.record_usage(
            db_session, skill=skill, payer_identity_id=PAYER, request_id=f"req-{i}"
        )
    await _commit(db_session, PAYER, 100.0, "payer")
    await _commit(db_session, PROVIDER, 100.0, "provider")
    sent = _escrow_online(monkeypatch)

    result = await usage_billing.settle_meter(db_session, skill=skill, payer_identity_id=PAYER)
    assert result is not None and result["charged"] is True
    settlement = result["settlement"]
    assert settlement["amount_usdc"] == 0.02
    assert settlement["status"] == "submitted"
    assert settlement["mode"] == "escrow_allowance"
    # 卖方默认质押 30%
    assert settlement["stake_usdc"] == 0.006
    assert sent["amount_usdc"] == 0.02 and sent["stake_usdc"] == 0.006

    meter = await _meter(db_session, skill)
    assert meter.accrued_usdc == 0.0          # 已经出账，不再挂在待出账里
    assert meter.billed_usdc == 0.02
    assert meter.settled_usdc == 0.0          # 钱还没到 —— 不许提前喊结算

    charges = await usage_billing.unsettled_charges(
        db_session,
        skill_id=skill.skill_id,
        payer_identity_id=PAYER,
        cutoff=__import__("datetime").datetime.utcnow(),
    )
    assert charges == []                      # 两条流水都被钉进这张单子

    binding = await db_session.get(EscrowBindingModel, str(settlement["escrow_binding_id"]))
    assert binding is not None and binding.state == "finalizing"


@pytest.mark.asyncio
async def test_chain_rejection_never_claims_settled(db_session: AsyncSession, monkeypatch):
    skill = await _skill(db_session, threshold=0.02)
    for i in range(2):
        await usage_billing.record_usage(
            db_session, skill=skill, payer_identity_id=PAYER, request_id=f"req-{i}"
        )
    await _commit(db_session, PAYER, 100.0, "payer")
    await _commit(db_session, PROVIDER, 100.0, "provider")

    monkeypatch.setattr(escrow, "can_server_settle", lambda: True)

    def _boom(**kwargs):
        raise RuntimeError("operator declined")

    monkeypatch.setattr(escrow, "open_and_submit_order", _boom)

    result = await usage_billing.settle_meter(db_session, skill=skill, payer_identity_id=PAYER)
    assert result is not None and result["charged"] is False
    assert "链上提交失败" in result["reason"]
    assert result["settlement"]["status"] == "open"

    meter = await _meter(db_session, skill)
    assert meter.settled_usdc == 0.0
    assert meter.billed_usdc == 0.02
    assert meter.accrued_usdc + meter.billed_usdc == 0.02


@pytest.mark.asyncio
async def test_no_wallet_room_waits_for_funds(db_session: AsyncSession, monkeypatch):
    skill = await _skill(db_session, threshold=0.02)
    for i in range(2):
        await usage_billing.record_usage(
            db_session, skill=skill, payer_identity_id=PAYER, request_id=f"req-{i}"
        )
    _escrow_online(monkeypatch)  # 通道在线，但谁都没锁仓

    result = await usage_billing.settle_meter(db_session, skill=skill, payer_identity_id=PAYER)
    assert result is not None and result["charged"] is False
    assert "锁仓" in result["reason"]
    assert result["settlement"]["escrow_binding_id"] is None


@pytest.mark.asyncio
async def test_cap_blocks_further_calls(db_session: AsyncSession):
    skill = await _skill(db_session, threshold=100.0, cap=0.02)
    await usage_billing.record_usage(
        db_session, skill=skill, payer_identity_id=PAYER, request_id="req-1", units=2
    )
    with pytest.raises(usage_billing.UsageBillingError) as exc:
        await usage_billing.record_usage(
            db_session, skill=skill, payer_identity_id=PAYER, request_id="req-2", units=1
        )
    assert exc.value.status == 409 and "上限" in exc.value.message


@pytest.mark.asyncio
async def test_cannot_bill_your_own_skill(db_session: AsyncSession):
    skill = await _skill(db_session)
    with pytest.raises(usage_billing.UsageBillingError) as exc:
        await usage_billing.record_usage(
            db_session, skill=skill, payer_identity_id=PROVIDER, request_id="req-self"
        )
    assert exc.value.status == 409


@pytest.mark.asyncio
async def test_reconcile_moves_settled_and_reopens_slashed(
    db_session: AsyncSession, monkeypatch
):
    skill = await _skill(db_session, threshold=0.02)
    for i in range(2):
        await usage_billing.record_usage(
            db_session, skill=skill, payer_identity_id=PAYER, request_id=f"req-{i}"
        )
    await _commit(db_session, PAYER, 100.0, "payer")
    await _commit(db_session, PROVIDER, 100.0, "provider")
    _escrow_online(monkeypatch)

    result = await usage_billing.settle_meter(db_session, skill=skill, payer_identity_id=PAYER)
    binding = await db_session.get(EscrowBindingModel, str(result["settlement"]["escrow_binding_id"]))

    # 链上真的划走了 -> 才允许记 settled
    binding.state = "settled"
    binding.finalize_tx_hash = "0x" + "99" * 32
    changed = await usage_billing.reconcile_settlements(db_session)
    assert changed and changed[0]["status"] == "settled"
    meter = await _meter(db_session, skill)
    assert meter.settled_usdc == 0.02
    assert meter.billed_usdc == 0.02

    # 另一笔：链上被罚没 -> 结算单失败，调用退回待出账（不让任何一方白吞损失）
    other_skill = await _skill(db_session)
    for i in range(2):
        await usage_billing.record_usage(
            db_session, skill=other_skill, payer_identity_id=PAYER, request_id=f"o-{i}"
        )
    await _commit(db_session, PAYER, 100.0, "payer2")
    await _commit(db_session, PROVIDER, 100.0, "provider2")
    second = await usage_billing.settle_meter(
        db_session, skill=other_skill, payer_identity_id=PAYER
    )
    second_binding = await db_session.get(
        EscrowBindingModel, str(second["settlement"]["escrow_binding_id"])
    )
    second_binding.state = "slashed"
    await usage_billing.reconcile_settlements(db_session)

    other_meter = await _meter(db_session, other_skill)
    assert other_meter.settled_usdc == 0.0
    assert other_meter.billed_usdc == 0.0
    assert other_meter.accrued_usdc == 0.02
    reopened = await usage_billing.unsettled_charges(
        db_session,
        skill_id=other_skill.skill_id,
        payer_identity_id=PAYER,
        cutoff=__import__("datetime").datetime.utcnow(),
    )
    assert len(reopened) == 2