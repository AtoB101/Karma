"""Proof data availability — store / retrieve / verify the bytes behind a hash."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from api.app import app
from db.session import get_db
from services import proof_availability

PAYLOAD = '{"delivery": "POD-2026-001", "inspected": true}'
HASH = proof_availability.compute_proof_hash(PAYLOAD)


@pytest.mark.asyncio
async def test_store_and_retrieve(db_session):
    rec = await proof_availability.store_proof(db_session, payload=PAYLOAD)
    await db_session.commit()
    assert rec.proof_hash == HASH

    got = await proof_availability.retrieve_proof(db_session, HASH)
    assert got["payload"] == PAYLOAD
    assert await proof_availability.proof_available(db_session, HASH) is True


@pytest.mark.asyncio
async def test_store_verifies_expected_hash(db_session):
    await proof_availability.store_proof(db_session, payload=PAYLOAD, proof_hash=HASH)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await proof_availability.store_proof(
            db_session, payload="different", proof_hash=HASH
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_retrieve_missing_is_404(db_session):
    with pytest.raises(HTTPException) as exc:
        await proof_availability.retrieve_proof(db_session, "0x" + "ab" * 32)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_assert_proof_available_rejects_bare_hash(db_session):
    with pytest.raises(HTTPException) as exc:
        await proof_availability.assert_proof_available(db_session, HASH)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_proof_routes_end_to_end(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            store = await client.post(
                "/v1/proofs", json={"payload": PAYLOAD, "proof_hash": HASH}
            )
            assert store.status_code == 201, store.text
            assert store.json()["proof_hash"] == HASH

            fetch = await client.get(f"/v1/proofs/{HASH}")
            assert fetch.status_code == 200, fetch.text
            assert fetch.json()["payload"] == PAYLOAD

            avail = await client.get(f"/v1/proofs/{HASH}/available")
            assert avail.status_code == 200
            assert avail.json()["available"] is True
    finally:
        app.dependency_overrides.clear()
