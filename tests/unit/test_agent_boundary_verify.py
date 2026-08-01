"""P2 boundary verify — catalog alignment, scene coverage, fulfill gate."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base
from services import agent_boundary as ab
from services.agent_boundary import get_agent_boundary, materialize_agent_boundary
from services.agent_boundary_verify import (
    BoundaryVerifyError,
    assert_seller_boundary_for_fulfill,
    verify_boundary_card,
)
from services.agent_directory import connect_agent, refresh_p1_ready
from services.agent_onboarding_template import materialize_onboarding
from services.agent_p1_readiness import (
    attest_responsibility_ack,
    boundary_content_hash,
    canonical_responsibility_ack,
    ensure_owner_identity,
    evaluate_p1_readiness,
)
from services.agent_profile_store import clear_profile_cards
from services.human_confirmation_policy import load_policy_catalog, reset_confirmation_sessions
from services.intent_fulfillment import fulfill_intent


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/p2.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset():
    ab.load_boundary_catalog.cache_clear()
    load_policy_catalog.cache_clear()
    ab.clear_agent_boundaries()
    clear_profile_cards()
    reset_confirmation_sessions()
    yield
    ab.clear_agent_boundaries()
    clear_profile_cards()
    reset_confirmation_sessions()


async def _ready_merchant(db: AsyncSession, agent_id: str = "p2-food"):
    owner = f"owner-{agent_id}"
    await ensure_owner_identity(db, owner, display_hint="P2主人")
    mat = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": "P2面馆",
            "industry_ids": ["food_delivery"],
            "use_example_service_specs": True,
            "service_targets": ["consumer"],
            "service_area": {"mode": "local", "regions": ["上海"]},
            "capability_summary": "简餐",
            "boundaries": "不做跨境冷链",
        },
        agent_id=agent_id,
    )
    caps = list(mat["agent_connect"]["capabilities"] or []) + [
        "onboarding:merchant",
        "industry:food_delivery",
        "order_food",
    ]
    row = await connect_agent(
        db,
        agent_id=agent_id,
        name=mat["agent_connect"]["name"],
        role="worker",
        capabilities=caps,
        profile_card=mat["profile_card"],
        identity_class="merchant",
        owner_identity_id=owner,
        responsibility_acknowledged=True,
    )
    bhash = boundary_content_hash(get_agent_boundary(row.agent_id)) or ""
    ack = attest_responsibility_ack(
        {
            **canonical_responsibility_ack(
                agent_id=row.agent_id,
                owner_identity_id=owner,
                identity_class="merchant",
                boundary_hash=bhash,
                acknowledged_at="2026-08-01T00:00:00Z",
            ),
            "acknowledged": True,
        }
    )
    meta = dict(row.onboarding_meta or {})
    meta.update(
        {
            "responsibility_ack": ack,
            "boundary_hash": bhash,
            "used_example_service_specs": True,
            "owner_identity_id": owner,
        }
    )
    row.onboarding_meta = meta
    row.boundary_hash = bhash
    await db.flush()
    await refresh_p1_ready(db, row.agent_id)
    return row, owner


def test_policy_covers_all_onboarding_industries():
    from services.agent_onboarding_template import list_industries

    scenes = set((load_policy_catalog().get("scenes") or {}).keys())
    inds = {i["industry_id"] for i in list_industries()}
    assert inds <= scenes
    assert (load_policy_catalog()["scenes"]["financial_services"]).get("high_risk") is True
    assert (load_policy_catalog()["scenes"]["healthcare_medical"]).get("high_risk") is True


def test_verify_rejects_looser_confirmation():
    b = materialize_agent_boundary(
        agent_id="v-loose",
        profile_id="merchant",
        capabilities=["order_food"],
        scene_ids=["food_delivery"],
        profile_card={
            "service_specs": {
                "food_delivery": {"service_content": ["x"], "boundaries": "不做冷链"}
            },
            "boundaries": "不做冷链",
        },
    )
    b["boundary_complete"] = True
    b["confirmation_boundary"]["must_confirm_steps"] = []
    result = verify_boundary_card(
        b, agent_id="v-loose", identity_class="merchant", scene_id="food_delivery"
    )
    assert result["ok"] is False
    assert "confirmation_not_looser" in result["gaps"]


def test_assert_seller_requires_scene_coverage():
    b = materialize_agent_boundary(
        agent_id="v-scene",
        profile_id="merchant",
        capabilities=["order_food"],
        scene_ids=["food_delivery"],
        profile_card={
            "service_specs": {
                "food_delivery": {"service_content": ["x"], "boundaries": "不做冷链"}
            },
            "boundaries": "不做冷链",
        },
    )
    with pytest.raises(BoundaryVerifyError) as ei:
        assert_seller_boundary_for_fulfill(
            boundary=b,
            scene_id="flight_booking",
            identity_class="merchant",
            p1_ready=True,
            allow_demo_incomplete=True,
        )
    assert "scene_covered" in ei.value.gaps


@pytest.mark.asyncio
async def test_ack_drift_fails_p1_and_status_does_not_heal(db_session):
    row, _owner = await _ready_merchant(db_session, "p2-drift")
    assert row.p1_ready is True
    stored = row.boundary_hash
    # Mutate published boundary without re-ack
    b = get_agent_boundary(row.agent_id)
    assert b is not None
    b = dict(b)
    cap = dict(b["capability_boundary"])
    cap["do_not"] = "不做跨境冷链；另不做酒精"
    b["capability_boundary"] = cap
    # Align confirmation so save accepts
    ab.save_agent_boundary(row.agent_id, b, reject_looser_confirmation=True)
    live = boundary_content_hash(get_agent_boundary(row.agent_id))
    assert live != stored
    # Simulate bug: someone left stored hash stale (do not heal)
    row.boundary_hash = stored
    meta = dict(row.onboarding_meta or {})
    meta["boundary_hash"] = stored
    row.onboarding_meta = meta
    await db_session.flush()

    status = await evaluate_p1_readiness(db_session, row.agent_id)
    assert status["p1_ready"] is False
    assert status["checks"]["boundary_hash_consistent"] is False
    assert status["checks"]["ack_bound_to_live_boundary"] is False
    # refresh must not heal stored hash
    await refresh_p1_ready(db_session, row.agent_id)
    assert row.boundary_hash == stored


@pytest.mark.asyncio
async def test_boundary_change_invalidates_ack(db_session):
    row, owner = await _ready_merchant(db_session, "p2-reack")
    assert row.p1_ready is True
    # Re-connect with mutated profile → hash change → ack invalidated
    mat = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": "P2面馆改",
            "industry_ids": ["food_delivery"],
            "use_example_service_specs": True,
            "service_targets": ["consumer"],
            "service_area": {"mode": "local", "regions": ["上海", "苏州"]},
            "capability_summary": "简餐扩大",
            "boundaries": "不做跨境冷链；不做酒精",
        },
        agent_id=row.agent_id,
    )
    await connect_agent(
        db_session,
        agent_id=row.agent_id,
        name=mat["agent_connect"]["name"],
        role="worker",
        capabilities=list(mat["agent_connect"]["capabilities"] or []) + ["order_food"],
        profile_card=mat["profile_card"],
        identity_class="merchant",
        owner_identity_id=owner,
        responsibility_acknowledged=False,
    )
    ack = (row.onboarding_meta or {}).get("responsibility_ack") or {}
    assert ack.get("acknowledged") is False
    assert ack.get("invalidated_reason") == "boundary_changed"
    status = await evaluate_p1_readiness(db_session, row.agent_id)
    assert status["p1_ready"] is False


@pytest.mark.asyncio
async def test_fulfill_rejects_seller_outside_scene(db_session, monkeypatch):
    monkeypatch.setenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "1")
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    row, _ = await _ready_merchant(db_session, "p2-only-food")
    # Force fulfill against food merchant for a flight intent
    with pytest.raises(HTTPException) as ei:
        await fulfill_intent(
            db_session,
            requirement_text="帮我订一张去北京的机票 200 USDC",
            buyer_identity_id="buyer-p2-1",
            amount=200.0,
            seller_identity_id=row.agent_id,
            negotiate_a2a=False,
            require_owner_confirmation=False,
            auto_lock_important_fields=True,
        )
    assert ei.value.status_code == 403
    detail = ei.value.detail
    assert isinstance(detail, dict)
    assert detail.get("error") == "seller_boundary_verify_failed"
    assert "scene_covered" in (detail.get("gaps") or [])
