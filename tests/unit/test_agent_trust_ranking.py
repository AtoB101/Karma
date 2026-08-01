"""Trust ranking: capability match then reputation / volume / success."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from datetime import datetime, timedelta

from db.models.orm import Base, ReputationModel, SettlementModel, TaskContractModel
from services.agent_directory import connect_agent
from services.agent_trust import apply_trust_rerank, record_worker_settlement_outcome
from services.intent_discovery import parse_intent_for_discovery, rank_candidates


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/trust.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_connect_makes_agent_discoverable(db_session):
    row = await connect_agent(
        db_session,
        agent_id="food-pro",
        name="Food Pro",
        role="worker",
        endpoint_url="http://food.local",
        capabilities=["order_food"],
    )
    await db_session.commit()
    assert row.is_active
    assert "karma_settle" in (row.capabilities or [])
    assert "order_food" in (row.capabilities or [])

    query = parse_intent_for_discovery("点外卖")
    cards = [{
        "agent_id": row.agent_id,
        "name": row.name,
        "capabilities": row.capabilities,
        "skills": [{"id": "order_food"}],
        "endpoint": row.endpoint_url,
        "karma": {"supports_voucher": True},
        "_source": "karma_directory",
    }]
    ranked = rank_candidates(cards, query, limit=5)
    assert ranked and ranked[0]["agent_id"] == "food-pro"


@pytest.mark.asyncio
async def test_trust_rerank_prefers_high_reputation_and_volume(db_session):
    await connect_agent(db_session, agent_id="newbie", name="Newbie", role="worker", capabilities=["order_food"])
    await connect_agent(db_session, agent_id="veteran", name="Veteran", role="worker", capabilities=["order_food"])
    await db_session.flush()

    # Veteran: high score + many successful settlements (connect already created reputation rows)
    vet_rep = await db_session.get(ReputationModel, "veteran")
    assert vet_rep is not None
    vet_rep.score = 220.0
    vet_rep.total_tasks = 20
    vet_rep.successful_tasks = 19
    vet_rep.disputed_tasks = 0

    for i in range(8):
        tid = f"t-vet-{i}"
        db_session.add(
            TaskContractModel(
                task_id=tid,
                client_agent_id="buyer",
                worker_agent_id="veteran",
                title="t",
                description="d",
                expected_output_schema={},
                expected_step_count=1,
                escrow_amount=20.0,
                currency="USD",
                deadline_at=datetime.utcnow() + timedelta(days=1),
                contract_hash="a" * 64,
            )
        )
        db_session.add(
            SettlementModel(
                settlement_id=f"s-vet-{i}",
                task_id=tid,
                escrow_amount=20.0,
                status="settled",
                client_agent_id="buyer",
                worker_agent_id="veteran",
                released_amount=20.0,
            )
        )
    await db_session.commit()

    query = parse_intent_for_discovery("order food please")
    cards = [
        {
            "agent_id": "newbie",
            "name": "Newbie",
            "capabilities": ["order_food", "karma_settle"],
            "skills": [{"id": "order_food"}],
            "karma": {"supports_voucher": True},
            "endpoint": "http://n",
        },
        {
            "agent_id": "veteran",
            "name": "Veteran",
            "capabilities": ["order_food", "karma_settle"],
            "skills": [{"id": "order_food"}],
            "karma": {"supports_voucher": True},
            "endpoint": "http://v",
        },
    ]
    matched = rank_candidates(cards, query, limit=10)
    ranked = await apply_trust_rerank(db_session, matched, limit=10)
    assert ranked[0]["agent_id"] == "veteran"
    assert ranked[0]["trust"]["settled_count"] >= 8
    assert ranked[0]["trust_bonus"] > ranked[1]["trust_bonus"]


@pytest.mark.asyncio
async def test_record_outcome_improves_score(db_session):
    await connect_agent(db_session, agent_id="w1", name="W", role="worker", capabilities=["karma_settle"])
    await db_session.commit()
    row = await record_worker_settlement_outcome(db_session, worker_agent_id="w1", success=True, volume=50)
    await db_session.commit()
    assert row.successful_tasks == 1
    assert row.score > 100.0
