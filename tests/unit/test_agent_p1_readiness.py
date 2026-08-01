"""P1 readiness — identity / responsibility / capability / anti-forgery."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base
from services.agent_boundary import clear_agent_boundaries, get_agent_boundary
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
from services.human_confirmation_policy import reset_confirmation_sessions


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/p1.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_stores():
    clear_agent_boundaries()
    clear_profile_cards()
    reset_confirmation_sessions()
    yield
    clear_agent_boundaries()
    clear_profile_cards()


async def _p1_merchant(db: AsyncSession, agent_id: str = "m-food-1"):
    owner = f"owner-{agent_id}"
    await ensure_owner_identity(db, owner, display_hint="面馆主人")
    mat = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": "面馆Bot",
            "industry_ids": ["food_delivery"],
            "use_example_service_specs": True,
            "service_targets": ["consumer"],
            "service_area": {"mode": "local", "regions": ["上海"]},
            "capability_summary": "简餐外卖",
            "boundaries": "不做跨境冷链",
        },
        agent_id=agent_id,
    )
    caps = list(mat["agent_connect"]["capabilities"] or []) + ["onboarding:merchant", "industry:food_delivery"]
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
    return row, owner


@pytest.mark.asyncio
async def test_p1_merchant_ready_against_records(db_session):
    row, owner = await _p1_merchant(db_session)
    status = await refresh_p1_ready(db_session, row.agent_id)
    assert status["p1_ready"] is True
    assert status["identity_class"] == "merchant"
    assert status["owner_identity_id"] == owner
    assert status["checks"]["service_specs_valid"] is True
    assert status["checks"]["responsibility_attestation_valid"] is True
    assert status["checks"]["boundary_complete"] is True
    assert row.p1_ready is True


@pytest.mark.asyncio
async def test_plain_connect_not_p1_ready(db_session):
    row = await connect_agent(
        db_session,
        agent_id="plain-worker",
        name="Plain",
        role="worker",
        capabilities=["order_food"],
    )
    status = await evaluate_p1_readiness(db_session, row.agent_id)
    assert status["p1_ready"] is False
    assert "identity_class_set" in status["gaps"]
    assert "owner_identity_bound" in status["gaps"]


@pytest.mark.asyncio
async def test_anti_hijack_different_owner(db_session):
    row, owner = await _p1_merchant(db_session, agent_id="m-owned")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        await connect_agent(
            db_session,
            agent_id=row.agent_id,
            name="Hijacker",
            role="worker",
            capabilities=["order_food"],
            identity_class="merchant",
            owner_identity_id="intruder-owner",
        )
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_forged_ack_fails_attestation(db_session):
    row, owner = await _p1_merchant(db_session, agent_id="m-forge-ack")
    meta = dict(row.onboarding_meta or {})
    meta["responsibility_ack"] = {
        "acknowledged": True,
        "agent_id": row.agent_id,
        "owner_identity_id": owner,
        "identity_class": "merchant",
        "boundary_hash": row.boundary_hash,
        "attestation": {"mode": "platform_ed25519", "signature": "invalid", "public_key": "x"},
    }
    row.onboarding_meta = meta
    await db_session.flush()
    status = await evaluate_p1_readiness(db_session, row.agent_id)
    assert status["p1_ready"] is False
    assert status["checks"]["responsibility_attestation_valid"] is False
