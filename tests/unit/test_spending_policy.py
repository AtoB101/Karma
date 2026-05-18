"""Pre-launch daily spending policy."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException

from db.models.orm import AgentAutomationPolicyModel, TradeOrderModel
from services.spending_policy import assert_pre_launch_spending_policy


@pytest.mark.asyncio
async def test_daily_limit_blocks_additional_launch(db_session):
    buyer = "buyer-daily-cap"
    policy = AgentAutomationPolicyModel(
        karma_identity_id=buyer,
        auto_enabled=True,
        single_limit=50.0,
        daily_limit=20.0,
        permissions=[],
        high_risk_mode="always",
        responsibility_acknowledged=True,
    )
    db_session.add(policy)
    db_session.add(
        TradeOrderModel(
            order_id="ord-1",
            task_id="task-1",
            buyer_identity_id=buyer,
            seller_identity_id="seller-x",
            requirement_text="x",
            decomposed_spec={"amount": 15.0},
            status="decomposed",
            pipeline_version="v2",
            created_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await assert_pre_launch_spending_policy(
            db_session,
            buyer_policy=policy,
            additional_amount=10.0,
        )
    assert exc.value.status_code == 409
    assert "daily_limit" in str(exc.value.detail).lower()
