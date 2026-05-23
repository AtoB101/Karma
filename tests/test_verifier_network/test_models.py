"""
Tests for Verifier Network DB Models.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from decentralized_verifier.models import Attestation, Challenge, VerifierNode


@pytest.mark.anyio
async def test_create_verifier_node(db_session):
    """VerifierNode can be created and queried."""
    node = VerifierNode(
        wallet_address="0x1234567890123456789012345678901234567890",
        stake_amount=1000.0,
        reputation_score=75.0,
        endpoint_url="https://verifier1.example.com",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    assert node.id is not None
    assert node.wallet_address == "0x1234567890123456789012345678901234567890"
    assert node.stake_amount == 1000.0
    assert node.reputation_score == 75.0
    assert node.is_active is True
    assert node.endpoint_url == "https://verifier1.example.com"
    assert node.created_at is not None
    assert node.updated_at is not None

    # Query back
    result = await db_session.execute(
        select(VerifierNode).where(VerifierNode.id == node.id)
    )
    fetched = result.scalar_one()
    assert fetched.wallet_address == node.wallet_address


@pytest.mark.anyio
async def test_verifier_node_unique_wallet(db_session):
    """Wallet address must be unique."""
    node1 = VerifierNode(
        wallet_address="0x1234567890123456789012345678901234567890",
    )
    db_session.add(node1)
    await db_session.commit()

    node2 = VerifierNode(
        wallet_address="0x1234567890123456789012345678901234567890",
    )
    db_session.add(node2)
    with pytest.raises(Exception):  # IntegrityError
        await db_session.commit()


@pytest.mark.anyio
async def test_create_attestation(db_session):
    """Attestation can be created with FK to verifier."""
    node = VerifierNode(
        wallet_address="0xabcdef0123456789abcdef0123456789abcdef01",
    )
    db_session.add(node)
    await db_session.flush()

    attestation = Attestation(
        task_id="task-001",
        verifier_id=node.id,
        bundle_id="bundle-001",
        bundle_cid="QmTest123",
        decision="ATTESTED_OK",
        confidence=0.95,
        checks_passed=5,
        checks_total=5,
        eip712_signature="0xabcdef1234567890",
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)

    assert attestation.id is not None
    assert attestation.task_id == "task-001"
    assert attestation.verifier_id == node.id
    assert attestation.decision == "ATTESTED_OK"
    assert attestation.confidence == 0.95
    assert attestation.checks_passed == 5
    assert attestation.checks_total == 5
    assert attestation.eip712_signature == "0xabcdef1234567890"


@pytest.mark.anyio
async def test_attestation_query_by_task(db_session):
    """Multiple attestations for the same task can be queried."""
    node = VerifierNode(wallet_address="0x1111111111111111111111111111111111111111")
    db_session.add(node)
    await db_session.flush()

    for i in range(3):
        db_session.add(
            Attestation(
                task_id="task-query",
                verifier_id=node.id,
                decision="ATTESTED_OK" if i % 2 == 0 else "ATTESTED_FAIL",
                checks_passed=i + 1,
                checks_total=5,
            )
        )
    await db_session.commit()

    result = await db_session.execute(
        select(Attestation).where(Attestation.task_id == "task-query")
    )
    attestations = result.scalars().all()
    assert len(attestations) == 3


@pytest.mark.anyio
async def test_create_challenge(db_session):
    """Challenge can be created with default status OPEN."""
    challenge = Challenge(
        task_id="task-001",
        bundle_id="bundle-001",
        raised_by="agent-001",
        reason="Evidence hash mismatch",
        quorum_size=3,
    )
    db_session.add(challenge)
    await db_session.commit()
    await db_session.refresh(challenge)

    assert challenge.id is not None
    assert challenge.task_id == "task-001"
    assert challenge.status == "OPEN"
    assert challenge.quorum_size == 3
    assert challenge.reason == "Evidence hash mismatch"
    assert challenge.resolved_at is None


@pytest.mark.anyio
async def test_challenge_resolve(db_session):
    """Challenge can be resolved."""
    from datetime import datetime

    challenge = Challenge(task_id="task-002", status="OPEN")
    db_session.add(challenge)
    await db_session.commit()

    now = datetime.utcnow()
    challenge.status = "RESOLVED"
    challenge.resolution = "Challenge upheld — evidence verified"
    challenge.resolved_at = now
    await db_session.commit()
    await db_session.refresh(challenge)

    assert challenge.status == "RESOLVED"
    assert challenge.resolved_at is not None
    assert challenge.resolution == "Challenge upheld — evidence verified"
