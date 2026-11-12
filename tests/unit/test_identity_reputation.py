from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import AgentModel, Base, ReputationModel
from services.identity_reputation import attach_card_reputation, open_identity_ledger, role_for_identity_class


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/idrep.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_role_mapping():
    assert role_for_identity_class("user") == "client"
    assert role_for_identity_class("business") == "worker"
    assert role_for_identity_class("agent") == "worker"


@pytest.mark.asyncio
async def test_card_opens_ledger_at_starting_score(db_session):
    row = await open_identity_ledger(db_session, "kid_cardopen01", identity_class="user")
    await db_session.commit()
    assert row.score == 100.0
    assert row.successful_tasks == 0
    agent = await db_session.get(AgentModel, "kid_cardopen01")
    assert agent is not None
    assert agent.owner_identity_id == "kid_cardopen01"

    card = await attach_card_reputation(
        db_session,
        {"identity_id": "kid_cardopen01", "identity_class": "user", "status": "active"},
        identity_id="kid_cardopen01",
        identity_class="user",
    )
    assert card["reputation"]["ledger_opened"] is True
    assert card["reputation"]["fee_waiver"] is False
    assert card["reputation"]["pack_eligible"] is False
    assert card["reputation"]["score"] == 100.0


@pytest.mark.asyncio
async def test_open_ledger_does_not_reset_score(db_session):
    await open_identity_ledger(db_session, "kid_keepscore", identity_class="business")
    rep = await db_session.get(ReputationModel, "kid_keepscore")
    rep.score = 180.0
    await db_session.commit()
    again = await open_identity_ledger(db_session, "kid_keepscore", identity_class="business")
    assert again.score == 180.0
