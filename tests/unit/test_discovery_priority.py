"""P3 discovery priority — scene-aware selection on verifiable trust."""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base, ReputationModel, SettlementModel, TaskContractModel
from services.agent_directory import connect_agent
from services.agent_trust import apply_trust_rerank
from services.discovery_priority import (
    apply_priority_ranking,
    classify_trust_tier,
    evaluate_candidate_priority,
    get_scene_priority_policy,
    load_priority_catalog,
    priority_sort_key,
)
from services.agent_trust import AgentTrustStats, load_trust_stats_batch
from services.intent_discovery import parse_intent_for_discovery, rank_candidates
from services.human_confirmation_policy import load_policy_catalog


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/p3.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clear_caches():
    load_priority_catalog.cache_clear()
    load_policy_catalog.cache_clear()
    yield
    load_priority_catalog.cache_clear()


def test_catalog_covers_confirmation_scenes():
    pri = load_priority_catalog()
    conf = load_policy_catalog()
    assert pri["schema_version"] == "karma-discovery-priority-v1"
    assert set(conf["scenes"]) <= set(pri["scenes"])
    assert pri["scenes"]["financial_services"]["high_risk"] is True
    assert pri["scenes"]["b2b_procurement"]["require_p1_ready"] is True


def test_intent_includes_scene_id():
    q = parse_intent_for_discovery("帮我点一份披萨外卖")
    assert q.scene_id == "food_delivery"
    assert q.to_dict()["scene_id"] == "food_delivery"


def test_priority_prefers_p1_and_scene_over_raw_score():
    stats_ok = AgentTrustStats(agent_id="a", reputation_score=100, cold_start=True)
    stats_hot = AgentTrustStats(
        agent_id="b",
        reputation_score=300,
        settled_count=20,
        settled_volume=500,
        total_tasks=20,
        successful_tasks=19,
        success_rate=0.95,
        cold_start=False,
    )
    # Hot but no P1 / no scene / incomplete boundary
    hot = {
        "agent_id": "hot-generic",
        "score": 20.0,
        "p1_ready": False,
        "boundary_complete": False,
        "scene_ids": [],
        "match_reasons": ["skill:order_food"],
    }
    # Ready partner covering the scene, lower raw capability
    ready = {
        "agent_id": "ready-food",
        "score": 8.0,
        "p1_ready": True,
        "boundary_complete": True,
        "scene_ids": ["food_delivery"],
        "identity_class": "merchant",
        "boundary_hash": "sha256:abc",
        "match_reasons": ["skill:order_food"],
    }
    ranked = apply_priority_ranking(
        [hot, ready],
        {"hot-generic": stats_hot, "ready-food": stats_ok},
        scene_id="food_delivery",
        drop_ineligible=False,
        enforce_scene_policy=False,
    )
    assert ranked[0]["agent_id"] == "ready-food"
    assert ranked[0]["scene_covered"] is True
    assert ranked[0]["priority"]["order"][0] == "eligible"
    assert ranked[0]["trust_evidence"]["verify_urls"]["p1_status"]


def test_b2b_policy_drops_cold_non_p1():
    policy = get_scene_priority_policy("b2b_procurement")
    assert policy["require_p1_ready"] is True
    cold = AgentTrustStats(agent_id="c", cold_start=True)
    card = {
        "agent_id": "c",
        "score": 15.0,
        "p1_ready": False,
        "boundary_complete": False,
        "scene_ids": [],
    }
    pri = evaluate_candidate_priority(
        card, stats=cold, scene_id="b2b_procurement", policy=policy
    )
    assert pri["eligible"] is False
    assert "require_p1_ready" in pri["drop_reasons"]


def test_trust_tier_proven_vs_cold():
    policy = get_scene_priority_policy("food_delivery")
    proven = AgentTrustStats(
        agent_id="p",
        settled_count=5,
        total_tasks=5,
        successful_tasks=5,
        success_rate=1.0,
        dispute_rate=0.0,
        cold_start=False,
    )
    cold = AgentTrustStats(agent_id="c", cold_start=True)
    assert classify_trust_tier(proven, policy=policy) == "proven"
    assert classify_trust_tier(cold, policy=policy) == "cold"
    assert priority_sort_key(
        {"eligible": True, "p1_ready": True, "boundary_complete": True,
         "scene_covered": True, "trust_tier_rank": 3, "score": 1, "trust": {}, "agent_id": "p"}
    ) < priority_sort_key(
        {"eligible": True, "p1_ready": True, "boundary_complete": True,
         "scene_covered": True, "trust_tier_rank": 1, "score": 99, "trust": {}, "agent_id": "c"}
    )


@pytest.mark.asyncio
async def test_rank_preserves_boundary_signals_for_priority(db_session):
    await connect_agent(
        db_session,
        agent_id="food-a",
        name="A",
        role="worker",
        capabilities=["order_food"],
    )
    await connect_agent(
        db_session,
        agent_id="food-b",
        name="B",
        role="worker",
        capabilities=["order_food"],
    )
    # Give B proven settlements
    rep = await db_session.get(ReputationModel, "food-b")
    rep.score = 200
    rep.total_tasks = 10
    rep.successful_tasks = 10
    for i in range(4):
        tid = f"tb-{i}"
        db_session.add(
            TaskContractModel(
                task_id=tid,
                client_agent_id="buyer",
                worker_agent_id="food-b",
                title="t",
                description="d",
                expected_output_schema={},
                expected_step_count=1,
                escrow_amount=10.0,
                currency="USD",
                deadline_at=datetime.utcnow() + timedelta(days=1),
                contract_hash="b" * 64,
            )
        )
        db_session.add(
            SettlementModel(
                settlement_id=f"sb-{i}",
                task_id=tid,
                escrow_amount=10.0,
                status="settled",
                client_agent_id="buyer",
                worker_agent_id="food-b",
                released_amount=10.0,
            )
        )
    await db_session.commit()

    query = parse_intent_for_discovery("点外卖")
    cards = [
        {
            "agent_id": "food-a",
            "name": "A",
            "capabilities": ["order_food", "karma_settle"],
            "skills": [{"id": "order_food"}],
            "karma": {"supports_voucher": True},
            "p1_ready": False,
            "boundary_complete": False,
            "scene_ids": ["food_delivery"],
        },
        {
            "agent_id": "food-b",
            "name": "B",
            "capabilities": ["order_food", "karma_settle"],
            "skills": [{"id": "order_food"}],
            "karma": {"supports_voucher": True},
            "p1_ready": True,
            "boundary_complete": True,
            "scene_ids": ["food_delivery"],
            "boundary_hash": "sha256:x",
            "identity_class": "merchant",
        },
    ]
    matched = rank_candidates(cards, query, limit=10)
    assert matched[0].get("p1_ready") in (True, False)  # preserved from cards
    ranked = await apply_trust_rerank(
        db_session,
        matched,
        limit=10,
        scene_id="food_delivery",
        drop_ineligible=False,
        enforce_scene_policy=False,
    )
    assert ranked[0]["agent_id"] == "food-b"
    assert ranked[0]["trust_tier"] in {"proven", "emerging"}
    assert ranked[0]["scene_covered"] is True


@pytest.mark.asyncio
async def test_existing_trust_rerank_still_prefers_volume(db_session):
    """Regression: without P1/scene diffs, volume/reputation still wins."""
    await connect_agent(db_session, agent_id="newbie", name="Newbie", role="worker", capabilities=["order_food"])
    await connect_agent(db_session, agent_id="veteran", name="Veteran", role="worker", capabilities=["order_food"])
    vet_rep = await db_session.get(ReputationModel, "veteran")
    vet_rep.score = 220.0
    vet_rep.total_tasks = 20
    vet_rep.successful_tasks = 19
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
            "capabilities": ["order_food", "karma_settle"],
            "skills": [{"id": "order_food"}],
            "karma": {"supports_voucher": True},
            "endpoint": "http://n",
        },
        {
            "agent_id": "veteran",
            "capabilities": ["order_food", "karma_settle"],
            "skills": [{"id": "order_food"}],
            "karma": {"supports_voucher": True},
            "endpoint": "http://v",
        },
    ]
    matched = rank_candidates(cards, query, limit=10)
    ranked = await apply_trust_rerank(db_session, matched, limit=10, scene_id="food_delivery")
    assert ranked[0]["agent_id"] == "veteran"
