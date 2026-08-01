"""Service-level tests for intent fulfillment (no full FastAPI app import)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base
from services import human_confirmation_policy as hcp
from services.human_confirmation_policy import decide_confirmation_session
from services.intent_fulfillment import fulfill_intent


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/f.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_confirmations():
    hcp.reset_confirmation_sessions()
    yield
    hcp.reset_confirmation_sessions()


@pytest.mark.asyncio
async def test_fulfill_intent_auto_complete_settles(db_session, monkeypatch):
    monkeypatch.setenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "0")
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    result = await fulfill_intent(
        db_session,
        requirement_text="帮我点一份披萨外卖 15 USDC",
        buyer_identity_id="buyer-fulfill-1",
        amount=15.0,
        auto_complete=True,
        negotiate_a2a=False,
        auto_fund_capacity=True,
        require_owner_confirmation=False,
    )
    await db_session.commit()
    assert result["status"] == "settled"
    assert result["seller_identity_id"]
    assert result["voucher_id"]
    assert result["task_id"]
    assert result["receipt_id"]
    stages = [t["stage"] for t in result["timeline"]]
    assert "discover" in stages
    assert "voucher_accepted" in stages
    assert "settled" in stages
    assert "order_food" in result["intent"]["skills"]


@pytest.mark.asyncio
async def test_fulfill_intent_stops_at_in_progress(db_session, monkeypatch):
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    result = await fulfill_intent(
        db_session,
        requirement_text="translate this document please",
        buyer_identity_id="buyer-fulfill-2",
        amount=8.0,
        auto_complete=False,
        negotiate_a2a=False,
        require_owner_confirmation=False,
    )
    await db_session.commit()
    assert result["status"] == "in_progress"
    assert result["next_steps"]
    assert any(t["stage"] == "settlement_in_progress" for t in result["timeline"])


@pytest.mark.asyncio
async def test_fulfill_pauses_for_owner_confirmation(db_session, monkeypatch):
    monkeypatch.setenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "0")
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    paused = await fulfill_intent(
        db_session,
        requirement_text="帮我点一份披萨外卖 12 USDC",
        buyer_identity_id="buyer-confirm-1",
        amount=12.0,
        auto_complete=False,
        negotiate_a2a=False,
        require_owner_confirmation=True,
    )
    assert paused["status"] == "awaiting_owner_confirmation"
    assert paused["scene_id"] == "food_delivery"
    assert paused["owner_prompt_zh"]
    sid = paused["confirmation"]["session_id"]
    decide_confirmation_session(sid, confirm=True, actor_agent_id="buyer-confirm-1")

    result = await fulfill_intent(
        db_session,
        requirement_text="帮我点一份披萨外卖 12 USDC",
        buyer_identity_id="buyer-confirm-1",
        amount=12.0,
        auto_complete=True,
        negotiate_a2a=False,
        require_owner_confirmation=True,
        confirmation_session_id=sid,
    )
    await db_session.commit()
    assert result["status"] == "settled"
    assert any(t["stage"] == "owner_confirmation" and t["ok"] for t in result["timeline"])
