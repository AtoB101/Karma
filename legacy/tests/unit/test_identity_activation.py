from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.orm import Base, IdentityVerificationModel
from services.identity_activation import (
    activation_of,
    activation_view,
    assert_activated,
    inactive_identities,
    is_activated,
)


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/activation.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_view_without_row_is_not_activated():
    view = activation_view(None, "kid_missing")
    assert view["activated"] is False
    assert view["status"] == "none"
    assert view["source"] == "master_identity_verification"


def test_view_only_verified_activates():
    for status in ("none", "pending", "rejected"):
        row = IdentityVerificationModel(identity_id="kid_x", status=status)
        assert activation_view(row, "kid_x")["activated"] is False
    row = IdentityVerificationModel(identity_id="kid_x", status="verified", level="basic")
    row.verified_at = datetime(2026, 9, 15, 12, 0, 0)
    view = activation_view(row, "kid_x")
    assert view["activated"] is True
    assert view["verified_at"] == "2026-09-15T12:00:00"


@pytest.mark.asyncio
async def test_activation_reads_master_verification_row(db_session):
    assert await is_activated(db_session, "kid_none") is False

    db_session.add(IdentityVerificationModel(identity_id="kid_pending", status="pending"))
    db_session.add(IdentityVerificationModel(identity_id="kid_ok", status="verified", level="basic"))
    await db_session.commit()

    assert (await activation_of(db_session, "kid_pending"))["activated"] is False
    assert (await activation_of(db_session, "kid_ok"))["activated"] is True
    assert await is_activated(db_session, "kid_ok") is True


@pytest.mark.asyncio
async def test_inactive_identities_is_batched_and_ignores_blanks(db_session):
    db_session.add(IdentityVerificationModel(identity_id="kid_ok", status="verified", level="basic"))
    db_session.add(IdentityVerificationModel(identity_id="kid_pending", status="pending"))
    await db_session.commit()

    blocked = await inactive_identities(db_session, ["kid_ok", "kid_pending", "kid_none", "", "  "])
    assert blocked == {"kid_pending", "kid_none"}
    assert await inactive_identities(db_session, []) == set()


@pytest.mark.asyncio
async def test_assert_activated_raises_403_with_action(db_session):
    with pytest.raises(Exception) as exc:
        await assert_activated(db_session, "kid_none", action="accepting an order")
    assert getattr(exc.value, "status_code", None) == 403
    assert "accepting an order" in str(exc.value.detail)

    db_session.add(IdentityVerificationModel(identity_id="kid_ok", status="verified", level="basic"))
    await db_session.commit()
    view = await assert_activated(db_session, "kid_ok", action="accepting an order")
    assert view["activated"] is True
