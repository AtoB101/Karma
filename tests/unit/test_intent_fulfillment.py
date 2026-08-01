"""Service-level tests for intent fulfillment (no full FastAPI app import)."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base
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
    )
    await db_session.commit()
    assert result["status"] == "in_progress"
    assert result["next_steps"]
    assert any(t["stage"] == "settlement_in_progress" for t in result["timeline"])
