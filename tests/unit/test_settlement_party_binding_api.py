"""Settlement party binding when auth enforcement is enabled."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from config.settings import settings
from db.session import get_db
from httptest import post_minimal_contract, post_success_execution_receipt


@pytest.mark.asyncio
async def test_settlement_partial_rejects_wrong_actor_when_party_binding_on(db_session):
    original_enforce = settings.auth_enforce_protected_routes
    original_party = settings.settlement_require_party_actor
    original_keys = settings.auth_api_keys
    try:
        settings.auth_enforce_protected_routes = True
        settings.settlement_require_party_actor = True
        settings.auth_api_keys = "buyer-1:buyer-secret-123456,seller-1:seller-secret-123456"

        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            task_id = "party-bind-task-1"
            await post_minimal_contract(
                client,
                task_id=task_id,
                client_agent_id="buyer-1",
                escrow_amount=10.0,
                expected_step_count=1,
                headers={"X-Karma-Api-Key": "karma_buyer-1_buyer-secret-123456"},
            )
            r = await client.post(
                "/v1/settlement/create",
                json={
                    "task_id": task_id,
                    "client_agent_id": "buyer-1",
                    "escrow_amount": 10.0,
                    "currency": "USD",
                },
                headers={"X-Karma-Api-Key": "karma_buyer-1_buyer-secret-123456"},
            )
            assert r.status_code == 201, r.text

            r2 = await client.post(
                f"/v1/settlement/{task_id}/pending",
                headers={"X-Karma-Api-Key": "karma_buyer-1_buyer-secret-123456"},
            )
            assert r2.status_code == 200, r2.text

            r3 = await client.post(
                f"/v1/settlement/{task_id}/lock",
                json={"worker_agent_id": "seller-1"},
                headers={"X-Karma-Api-Key": "karma_buyer-1_buyer-secret-123456"},
            )
            assert r3.status_code == 200, r3.text

            r4 = await client.post(
                f"/v1/settlement/{task_id}/start",
                headers={"X-Karma-Api-Key": "karma_seller-1_seller-secret-123456"},
            )
            assert r4.status_code == 200, r4.text

            await post_success_execution_receipt(
                client,
                task_id=task_id,
                agent_id="seller-1",
                headers={"X-Karma-Api-Key": "karma_seller-1_seller-secret-123456"},
            )

            bad = await client.post(
                f"/v1/settlement/{task_id}/partial",
                json={"settled_value_percent": 10.0, "reason": "x"},
                headers={"X-Karma-Api-Key": "karma_seller-1_seller-secret-123456"},
            )
            assert bad.status_code == 403

            ok = await client.post(
                f"/v1/settlement/{task_id}/partial",
                json={"settled_value_percent": 10.0, "reason": "x"},
                headers={"X-Karma-Api-Key": "karma_buyer-1_buyer-secret-123456"},
            )
            assert ok.status_code == 200, ok.text
    finally:
        settings.auth_enforce_protected_routes = original_enforce
        settings.settlement_require_party_actor = original_party
        settings.auth_api_keys = original_keys
        app.dependency_overrides.clear()
