"""
Tests for Verifier Network Celery tasks.
Uses monkeypatching to mock the database session for unit-level testing.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from decentralized_verifier.models import Attestation, Challenge, VerifierNode


# ═══════════════════════════════════════════════════════════════════
# auto_verify_bundle
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_auto_verify_bundle_creates_attestations(db_session, monkeypatch):
    """_async_auto_verify creates attestations for all active verifiers."""
    from contextlib import asynccontextmanager

    from decentralized_verifier.tasks import _async_auto_verify

    # Mock AsyncSessionLocal to return our test session
    @asynccontextmanager
    async def _mock_session():
        yield db_session

    monkeypatch.setattr("db.session.AsyncSessionLocal", _mock_session)

    # Create 2 active verifiers
    for i in range(2):
        db_session.add(
            VerifierNode(
                wallet_address=f"0x{i:040d}",
                is_active=True,
            )
        )
    await db_session.commit()

    result = await _async_auto_verify("task-av-001", "bundle-av-001")

    assert result["task_id"] == "task-av-001"
    assert result["attestation_count"] == 2
    assert result["verifiers_queried"] == 2

    # Verify attestations were created
    res = await db_session.execute(
        select(Attestation).where(Attestation.task_id == "task-av-001")
    )
    attestations = res.scalars().all()
    assert len(attestations) == 2
    for att in attestations:
        assert att.decision in ("ATTESTED_OK", "ATTESTED_FAIL", "FLAGGED")


@pytest.mark.anyio
async def test_auto_verify_bundle_no_verifiers(db_session, monkeypatch):
    """_async_auto_verify handles zero active verifiers gracefully."""
    from contextlib import asynccontextmanager

    from decentralized_verifier.tasks import _async_auto_verify

    @asynccontextmanager
    async def _mock_session():
        yield db_session

    monkeypatch.setattr("db.session.AsyncSessionLocal", _mock_session)

    result = await _async_auto_verify("task-no-v", "bundle-no-v")

    assert result["attestation_count"] == 0
    assert result["verifiers_queried"] == 0


# ═══════════════════════════════════════════════════════════════════
# check_challenge_expiry
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_expire_challenges(db_session, monkeypatch):
    """_async_expire_challenges expires challenges past their window."""
    from contextlib import asynccontextmanager

    from decentralized_verifier.tasks import _async_expire_challenges

    @asynccontextmanager
    async def _mock_session():
        yield db_session

    monkeypatch.setattr("db.session.AsyncSessionLocal", _mock_session)

    now = datetime.utcnow()

    # Active challenge past window
    expired = Challenge(
        task_id="task-exp-1",
        status="OPEN",
        window_start=now - timedelta(hours=2),
        window_end=now - timedelta(minutes=5),
    )
    # Active challenge still in window
    active = Challenge(
        task_id="task-exp-2",
        status="OPEN",
        window_start=now,
        window_end=now + timedelta(hours=1),
    )
    # Already resolved
    resolved = Challenge(
        task_id="task-exp-3",
        status="RESOLVED",
        window_start=now - timedelta(hours=2),
        window_end=now - timedelta(minutes=5),
    )
    db_session.add_all([expired, active, resolved])
    await db_session.commit()

    count = await _async_expire_challenges()

    assert count == 1
    await db_session.refresh(expired)
    assert expired.status == "EXPIRED"
    await db_session.refresh(active)
    assert active.status == "OPEN"  # unchanged
    await db_session.refresh(resolved)
    assert resolved.status == "RESOLVED"  # unchanged


# ═══════════════════════════════════════════════════════════════════
# update_verifier_reputation
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_update_reputation(db_session, monkeypatch):
    """_async_update_reputation recalculates scores based on success rate."""
    from contextlib import asynccontextmanager

    from decentralized_verifier.tasks import _async_update_reputation

    @asynccontextmanager
    async def _mock_session():
        yield db_session

    monkeypatch.setattr("db.session.AsyncSessionLocal", _mock_session)

    # Verifier with 100% success
    v1 = VerifierNode(
        wallet_address="0x1000000000000000000000000000000000000000",
        reputation_score=50.0,
        total_attestations=10,
        successful_attestations=10,
    )
    # Verifier with 50% success
    v2 = VerifierNode(
        wallet_address="0x2000000000000000000000000000000000000000",
        reputation_score=50.0,
        total_attestations=10,
        successful_attestations=5,
    )
    # Verifier with 0 attestations (score unchanged)
    v3 = VerifierNode(
        wallet_address="0x3000000000000000000000000000000000000000",
        reputation_score=75.0,
        total_attestations=0,
    )
    db_session.add_all([v1, v2, v3])
    await db_session.commit()

    count = await _async_update_reputation()

    assert count == 3
    await db_session.refresh(v1)
    await db_session.refresh(v2)
    await db_session.refresh(v3)

    # v1: 100% success → score should increase toward 100
    assert v1.reputation_score > 50.0
    # v2: 50% success → score should stay around 50
    assert v2.reputation_score <= 50.0
    # v3: no attestations → score unchanged
    assert v3.reputation_score == 75.0


# ═══════════════════════════════════════════════════════════════════
# sync_attestations_to_chain
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_sync_attestations_to_chain(db_session, monkeypatch):
    """_async_sync_to_chain counts attestations with signatures."""
    from contextlib import asynccontextmanager

    from decentralized_verifier.tasks import _async_sync_to_chain

    @asynccontextmanager
    async def _mock_session():
        yield db_session

    monkeypatch.setattr("db.session.AsyncSessionLocal", _mock_session)

    node = VerifierNode(wallet_address="0xabcd000000000000000000000000000000000001")
    db_session.add(node)
    await db_session.flush()

    # Attestation with signature
    db_session.add(
        Attestation(
            task_id="task-sync",
            verifier_id=node.id,
            decision="ATTESTED_OK",
            eip712_signature="0xabcdef1234567890",
        )
    )
    # Attestation without signature
    db_session.add(
        Attestation(
            task_id="task-sync",
            verifier_id=node.id,
            decision="ATTESTED_OK",
            eip712_signature=None,
        )
    )
    await db_session.commit()

    result = await _async_sync_to_chain("task-sync")

    assert result["task_id"] == "task-sync"
    assert result["synced_count"] == 1  # Only the one with signature
    assert result["total"] == 1  # Query filters to only signed attestations


@pytest.mark.anyio
async def test_sync_attestations_empty(db_session, monkeypatch):
    """_async_sync_to_chain handles no attestations gracefully."""
    from contextlib import asynccontextmanager

    from decentralized_verifier.tasks import _async_sync_to_chain

    @asynccontextmanager
    async def _mock_session():
        yield db_session

    monkeypatch.setattr("db.session.AsyncSessionLocal", _mock_session)

    result = await _async_sync_to_chain("task-nonexistent")

    assert result["task_id"] == "task-nonexistent"
    assert result["synced_count"] == 0
    assert result["total"] == 0
