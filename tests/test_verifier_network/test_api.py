"""
Tests for Verifier Network API endpoints.
Uses the FastAPI TestClient with SQLite in-memory DB.
"""
from __future__ import annotations

import pytest

from decentralized_verifier.models import Attestation, Challenge, VerifierNode


# ═══════════════════════════════════════════════════════════════════
# Verifier Registration
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_register_verifier(client):
    """POST /v1/verifiers/register creates a verifier node."""
    resp = await client.post(
        "/v1/verifiers/register",
        json={
            "wallet_address": "0x1234567890123456789012345678901234567890",
            "stake_amount": 500.0,
            "endpoint_url": "https://verifier.karma.network",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["wallet_address"] == "0x1234567890123456789012345678901234567890"
    assert data["stake_amount"] == 500.0
    assert data["endpoint_url"] == "https://verifier.karma.network"
    assert data["is_active"] is True
    assert data["id"] is not None


@pytest.mark.anyio
async def test_register_duplicate_wallet(client, db_session):
    """Duplicate wallet registration returns 409."""
    node = VerifierNode(
        wallet_address="0x1234567890123456789012345678901234567890",
    )
    db_session.add(node)
    await db_session.commit()

    resp = await client.post(
        "/v1/verifiers/register",
        json={"wallet_address": "0x1234567890123456789012345678901234567890"},
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_list_verifiers(client, db_session):
    """GET /v1/verifiers lists registered verifiers."""
    for i in range(3):
        db_session.add(
            VerifierNode(
                wallet_address=f"0x{i:040d}",
                stake_amount=100.0 * (i + 1),
                reputation_score=10.0 * (i + 1),
            )
        )
    await db_session.commit()

    resp = await client.get("/v1/verifiers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    assert len(data["verifiers"]) >= 3


@pytest.mark.anyio
async def test_list_verifiers_active_only(client, db_session):
    """GET /v1/verifiers?active_only=true filters inactive."""
    db_session.add(VerifierNode(wallet_address="0x1000000000000000000000000000000000000000", is_active=True))
    db_session.add(VerifierNode(wallet_address="0x2000000000000000000000000000000000000000", is_active=False))
    await db_session.commit()

    resp = await client.get("/v1/verifiers?active_only=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["verifiers"][0]["wallet_address"] == "0x1000000000000000000000000000000000000000"


@pytest.mark.anyio
async def test_get_verifier(client, db_session):
    """GET /v1/verifiers/{id} returns verifier details."""
    node = VerifierNode(wallet_address="0x1234567890123456789012345678901234567899")
    db_session.add(node)
    await db_session.commit()

    resp = await client.get(f"/v1/verifiers/{node.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == node.id
    assert data["wallet_address"] == node.wallet_address


@pytest.mark.anyio
async def test_get_verifier_not_found(client):
    """GET /v1/verifiers/{id} returns 404 for unknown verifier."""
    resp = await client.get("/v1/verifiers/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_update_stake(client, db_session):
    """POST /v1/verifiers/{id}/stake updates stake."""
    node = VerifierNode(
        wallet_address="0x1234567890123456789012345678901234567898",
        stake_amount=100.0,
    )
    db_session.add(node)
    await db_session.commit()

    resp = await client.post(
        f"/v1/verifiers/{node.id}/stake",
        json={"stake_amount": 500.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stake_amount"] == 500.0


# ═══════════════════════════════════════════════════════════════════
# Attestations
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_submit_attestation(client, db_session):
    """POST /v1/verifiers/attestations submits an attestation."""
    node = VerifierNode(
        wallet_address="0xaaaa1111aaaa1111aaaa1111aaaa1111aaaa1111",
        is_active=True,
    )
    db_session.add(node)
    await db_session.commit()

    resp = await client.post(
        "/v1/verifiers/attestations",
        json={
            "task_id": "task-test-001",
            "verifier_id": node.id,
            "bundle_id": "bundle-001",
            "decision": "ATTESTED_OK",
            "confidence": 0.95,
            "checks_passed": 5,
            "checks_total": 5,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["task_id"] == "task-test-001"
    assert data["verifier_id"] == node.id
    assert data["decision"] == "ATTESTED_OK"
    assert data["checks_passed"] == 5

    # Verify verifier stats updated
    await db_session.refresh(node)
    assert node.total_attestations == 1
    assert node.successful_attestations == 1


@pytest.mark.anyio
async def test_submit_attestation_inactive_verifier(client, db_session):
    """Cannot submit attestation from inactive verifier."""
    node = VerifierNode(
        wallet_address="0xbbbb2222bbbb2222bbbb2222bbbb2222bbbb2222",
        is_active=False,
    )
    db_session.add(node)
    await db_session.commit()

    resp = await client.post(
        "/v1/verifiers/attestations",
        json={
            "task_id": "task-test-002",
            "verifier_id": node.id,
            "decision": "ATTESTED_OK",
            "checks_passed": 1,
            "checks_total": 1,
        },
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_get_attestation(client, db_session):
    """GET /v1/verifiers/attestations/{id} returns attestation."""
    node = VerifierNode(wallet_address="0xcccc3333cccc3333cccc3333cccc3333cccc3333")
    db_session.add(node)
    await db_session.flush()

    att = Attestation(
        task_id="task-get",
        verifier_id=node.id,
        decision="ATTESTED_FAIL",
        checks_passed=2,
        checks_total=5,
    )
    db_session.add(att)
    await db_session.commit()

    resp = await client.get(f"/v1/verifiers/attestations/{att.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == att.id
    assert data["task_id"] == "task-get"
    assert data["decision"] == "ATTESTED_FAIL"


@pytest.mark.anyio
async def test_list_attestations_for_task(client, db_session):
    """GET /v1/verifiers/attestations/task/{task_id} lists attestations."""
    node = VerifierNode(wallet_address="0xdddd4444dddd4444dddd4444dddd4444dddd4444")
    db_session.add(node)
    await db_session.flush()

    for i in range(2):
        db_session.add(
            Attestation(
                task_id="task-list",
                verifier_id=node.id,
                decision="ATTESTED_OK",
                checks_passed=3,
                checks_total=3,
            )
        )
    await db_session.commit()

    resp = await client.get("/v1/verifiers/attestations/task/task-list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "task-list"
    assert data["total"] == 2
    assert len(data["attestations"]) == 2


# ═══════════════════════════════════════════════════════════════════
# Challenges
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_open_challenge(client):
    """POST /v1/verifiers/challenges creates a challenge."""
    resp = await client.post(
        "/v1/verifiers/challenges",
        json={
            "task_id": "task-ch-001",
            "bundle_id": "bundle-001",
            "raised_by": "agent-a",
            "reason": "Suspicious evidence",
            "quorum_size": 3,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["task_id"] == "task-ch-001"
    assert data["status"] == "OPEN"
    assert data["quorum_size"] == 3
    assert data["window_start"] is not None
    assert data["window_end"] is not None


@pytest.mark.anyio
async def test_get_challenge(client, db_session):
    """GET /v1/verifiers/challenges/{id} returns challenge."""
    challenge = Challenge(task_id="task-ch-002", status="OPEN")
    db_session.add(challenge)
    await db_session.commit()

    resp = await client.get(f"/v1/verifiers/challenges/{challenge.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == challenge.id
    assert data["task_id"] == "task-ch-002"


@pytest.mark.anyio
async def test_resolve_challenge(client, db_session):
    """POST /v1/verifiers/challenges/{id}/resolve resolves a challenge."""
    challenge = Challenge(task_id="task-ch-003", status="OPEN")
    db_session.add(challenge)
    await db_session.commit()

    resp = await client.post(
        f"/v1/verifiers/challenges/{challenge.id}/resolve",
        json={
            "resolution": "Evidence verified, challenge dismissed",
            "status": "DISMISSED",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "DISMISSED"
    assert data["resolved_at"] is not None


@pytest.mark.anyio
async def test_resolve_already_resolved_challenge(client, db_session):
    """Cannot re-resolve an already resolved challenge."""
    challenge = Challenge(task_id="task-ch-004", status="RESOLVED", resolved_at=None)
    db_session.add(challenge)
    await db_session.commit()

    resp = await client.post(
        f"/v1/verifiers/challenges/{challenge.id}/resolve",
        json={"resolution": "Try again", "status": "DISMISSED"},
    )
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Network Stats
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_network_stats(client, db_session):
    """GET /v1/verifiers/network/stats returns network stats."""
    for i in range(2):
        db_session.add(
            VerifierNode(
                wallet_address=f"0x{i:040d}",
                reputation_score=50.0 + i * 25.0,
                is_active=(i == 0),
            )
        )
    await db_session.commit()

    resp = await client.get("/v1/verifiers/network/stats")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_verifiers"] == 2
    assert data["active_verifiers"] == 1
    assert data["total_attestations"] == 0
    assert data["total_challenges"] == 0
    assert "average_reputation" in data
