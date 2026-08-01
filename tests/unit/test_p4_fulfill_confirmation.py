"""P4 fulfill confirmation — multi-step buyer + seller OWNER_CONFIRM."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base
from services import human_confirmation_policy as hcp
from services.agent_boundary import clear_agent_boundaries, get_agent_boundary
from services.agent_directory import connect_agent, refresh_p1_ready
from services.agent_onboarding_template import materialize_onboarding
from services.agent_p1_readiness import (
    attest_responsibility_ack,
    boundary_content_hash,
    canonical_responsibility_ack,
    ensure_owner_identity,
)
from services.agent_profile_store import clear_profile_cards
from services.human_confirmation_policy import decide_confirmation_session
from services.intent_fulfillment import fulfill_intent


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/p4.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset():
    clear_agent_boundaries()
    clear_profile_cards()
    hcp.reset_confirmation_sessions()
    hcp.load_policy_catalog.cache_clear()
    yield
    clear_agent_boundaries()
    clear_profile_cards()
    hcp.reset_confirmation_sessions()


async def _p1_merchant(db: AsyncSession, *, agent_id: str, industry: str, capability: str):
    owner = f"owner-{agent_id}"
    await ensure_owner_identity(db, owner, display_hint=owner)
    mat = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": agent_id,
            "industry_ids": [industry],
            "use_example_service_specs": True,
            "service_targets": ["consumer"],
            "service_area": {"mode": "local", "regions": ["上海"]},
            "capability_summary": industry,
            "boundaries": "超范围不接单",
        },
        agent_id=agent_id,
    )
    caps = list(mat["agent_connect"]["capabilities"] or []) + [
        "onboarding:merchant",
        f"industry:{industry}",
        capability,
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
    return row


@pytest.mark.asyncio
async def test_food_single_buyer_step(db_session, monkeypatch):
    monkeypatch.setenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "1")
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    await _p1_merchant(
        db_session, agent_id="p4-food", industry="food_delivery", capability="order_food"
    )
    paused = await fulfill_intent(
        db_session,
        requirement_text="帮我点一份披萨外卖 20 USDC",
        buyer_identity_id="buyer-p4-food",
        amount=20.0,
        seller_identity_id="p4-food",
        negotiate_a2a=False,
        require_owner_confirmation=True,
        auto_lock_important_fields=True,
    )
    assert paused["status"] == "awaiting_owner_confirmation"
    assert paused["confirmation"]["step"] == "accept_order"
    sid = paused["confirmation"]["session_id"]
    decide_confirmation_session(sid, confirm=True, actor_agent_id="buyer-p4-food")
    settled = await fulfill_intent(
        db_session,
        requirement_text="帮我点一份披萨外卖 20 USDC",
        buyer_identity_id="buyer-p4-food",
        amount=20.0,
        seller_identity_id="p4-food",
        negotiate_a2a=False,
        auto_complete=True,
        require_owner_confirmation=True,
        confirmation_session_id=sid,
        auto_lock_important_fields=True,
    )
    assert settled["status"] == "settled"


@pytest.mark.asyncio
async def test_b2b_multi_step_buyer_and_seller(db_session, monkeypatch):
    monkeypatch.setenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "1")
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    await _p1_merchant(
        db_session,
        agent_id="p4-b2b",
        industry="b2b_procurement",
        capability="b2b_procurement",
    )
    buyer = "buyer-p4-b2b"
    req = "企业采购一批耗材，预算 1500 USDC"
    buyer_sid = None
    seller_sid = None
    final = None
    for _ in range(8):
        result = await fulfill_intent(
            db_session,
            requirement_text=req,
            buyer_identity_id=buyer,
            amount=1500.0,
            seller_identity_id="p4-b2b",
            negotiate_a2a=False,
            auto_complete=True,
            require_owner_confirmation=True,
            confirmation_session_id=buyer_sid,
            seller_confirmation_session_id=seller_sid,
            auto_lock_important_fields=True,
        )
        st = result.get("status")
        if st == "awaiting_owner_confirmation":
            buyer_sid = result["confirmation"]["session_id"]
            step = result["confirmation"]["step"]
            assert step in {"select_offer", "accept_order"}
            decide_confirmation_session(buyer_sid, confirm=True, actor_agent_id=buyer)
            continue
        if st == "awaiting_seller_confirmation":
            seller_sid = result["confirmation"]["session_id"]
            assert result["confirmation"]["role"] == "seller"
            decide_confirmation_session(seller_sid, confirm=True, actor_agent_id="p4-b2b")
            continue
        final = result
        break
    assert final and final["status"] == "settled"
    stages = [t["stage"] for t in final["timeline"]]
    assert "seller_confirmation" in stages
    assert stages.count("owner_confirmation") >= 2
