"""Full trade order launch — decompose, accept, settlement, execution kickoff."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from config.settings import settings
from db.models.orm import AgentAutomationPolicyModel, CapacityModel, RuntimeKeyModel
from services.agent_automation_policy import upsert_automation_policy


async def _seed_party(db, identity: str, *, seller: bool = False):
    await upsert_automation_policy(
        db,
        karma_identity_id=identity,
        auto_enabled=True,
        single_limit=100.0,
        daily_limit=500.0,
        permissions=["submit_receipt", "verify_voucher", "update_progress"],
        high_risk_mode="always",
        responsibility_acknowledged=True,
        preauth_enabled=True,
        auto_accept_incoming=seller,
        auto_execute_pipeline=True,
        allowed_task_types=["api.caption"],
        task_precision_min=0.5,
        task_precision_max=5.0,
        trusted_counterparty_ids=[],
        responsibility_boundary_id="scene-test",
    )
    db.add(
        RuntimeKeyModel(
            key_id=f"key-{identity}",
            secret_hash="$2b$12$testtesttesttesttesttesttesttesttesttesttest",
            wallet_address="0x" + "ab" * 20,
            karma_identity_id=identity,
            permissions=["submit_receipt", "verify_voucher", "update_progress"],
            single_limit=100.0,
            daily_limit=500.0,
            expire_at=datetime.utcnow() + timedelta(days=3),
            agent_name="test",
            status="active",
        )
    )


@pytest.mark.asyncio
async def test_launch_full_pipeline(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ledger_require_party_actor", False)
    buyer, seller = "buyer-launch-1", "seller-launch-1"
    db_session.add(
        CapacityModel(
            identity_id=buyer,
            total_locked_usdc=200.0,
            total_bill_credits=200.0,
            available_credits=200.0,
        )
    )
    await _seed_party(db_session, buyer, seller=False)
    await _seed_party(db_session, seller, seller=True)
    policy = await db_session.get(AgentAutomationPolicyModel, seller)
    if policy:
        policy.trusted_counterparty_ids = [buyer]
    await db_session.commit()

    resp = await client.post(
        "/v1/trade/orders/launch",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "requirement_text": "caption 字幕任务 金额 15 USDC 精度 1.2",
            "buyer_signature": "0xlaunch",
            "task_type": "api.caption",
        },
        headers={"Idempotency-Key": "trade-launch-full-pipeline-test"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "execution_started"
    assert body["decomposed"]["task_type"] == "api.caption"
    assert body["readiness"]["buyer"] is True
    assert body["readiness"]["seller"] is True


@pytest.mark.asyncio
async def test_launch_error_path_reads_status_of_expired_order(db_session):
    """管线中途回滚会让 order 过期；异常路径必须还能拿到状态，而不是变 500。

    链上闸门没过时 ``revert_chain_rejected_transition`` 会 ``db.rollback()``，
    而 rollback 会**无条件**把 session 上的实例标记过期（连主键一起）。此后读
    ``order.status`` 是一次同步重载，asyncpg/aiosqlite 直接抛 ``MissingGreenlet``；
    它发生在 ``except HTTPException`` 里，于是真正的 HTTPException 被换成裸 500，
    失败原因当场丢失（2026-10-01 生产实测）。
    """
    from sqlalchemy.exc import MissingGreenlet, StatementError

    from db.models.orm import TradeOrderModel
    from services.trade_order_pipeline import _order_status_without_lazy_load

    order = TradeOrderModel(
        order_id="expiry-order-0001",
        task_id="expiry-task-0001",
        buyer_identity_id="expiry-buyer",
        seller_identity_id="expiry-seller",
        requirement_text="caption",
        decomposed_spec={},
        status="settlement_locked",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(order)
    await db_session.commit()

    # expire() 连主键一起摘掉，所以 order_id 必须先取出来存好 ——
    # 这也正是修好之后调用方必须显式传 order_id 的原因。
    order_id = order.order_id

    # 与「管线中途 commit/rollback 之后」等价的状态
    db_session.expire(order)
    assert (
        await _order_status_without_lazy_load(db_session, order=order, order_id=order_id)
        == "settlement_locked"
    )

    # 内存里已经有值（比如 _mark_order_failed 刚写过）时不该再去查库
    order.status = "failed"
    assert (
        await _order_status_without_lazy_load(db_session, order=order, order_id=order_id)
        == "failed"
    )

    # 反过来证明「直接读」确实会炸。放最后：这次失败的同步 IO 会把 session 弄脏
    # （下面不会再碰它）。属性重载会发一条 SELECT，所以可能是 MissingGreenlet，
    # 也可能是包着它的 StatementError。
    db_session.expire(order)
    with pytest.raises((MissingGreenlet, StatementError)):
        _ = order.status
