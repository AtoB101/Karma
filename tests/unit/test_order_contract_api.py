"""API-level tests for order contract dual signing and the bind gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eth_account import Account
from httpx import ASGITransport, AsyncClient

from api.app import app
from api.routes import bilateral as bilateral_routes
from config.settings import settings
from db.models.orm import TaskContractModel
from db.session import get_db
from services import order_contract


def _body(task_id: str = "task-sign-1") -> dict:
    return {
        "task_id": task_id,
        "client_agent_id": "buyer-1",
        "title": "Buy 100 widgets",
        "description": "Inspect and clear customs",
        "expected_output_schema": {"type": "object"},
        "expected_step_count": 3,
        "escrow_amount": 5000.0,
        "currency": "USD",
        "deadline_at": (datetime(2026, 12, 1, 12, 0, 0, tzinfo=timezone.utc)).isoformat(),
    }


@pytest.fixture
def relaxed(monkeypatch):
    monkeypatch.setattr(settings, "spending_grant_enforced", False)
    monkeypatch.setattr(settings, "auth_enforce_protected_routes", False)
    monkeypatch.setattr(settings, "order_contract_eip712_chain_id", 84532)


@pytest.mark.asyncio
async def test_contract_sign_flow_and_bind_gate(db_session, relaxed):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/v1/contracts", json=_body())
            assert r.status_code == 201, r.text
            created = r.json()
            task_id = created["task_id"]
            terms_hash = created["terms_hash"]
            assert created["contract_status"] == "draft"
            assert len(terms_hash) == 64

            # buyer signs with a fresh wallet
            buyer = Account.create()
            sig = order_contract.sign_buyer(
                private_key=buyer.key, terms_hash=terms_hash, task_id=task_id, chain_id=84532,
            )
            r = await client.post(
                f"/v1/contracts/{task_id}/sign",
                json={"role": "buyer", "signature": sig, "address": buyer.address},
            )
            assert r.status_code == 200, r.text
            assert r.json()["contract_status"] == "buyer_signed"

            # assign a worker directly, then worker signs with a fresh Ed25519 key
            row = await db_session.get(TaskContractModel, task_id)
            row.worker_agent_id = "worker-1"
            await db_session.commit()

            worker_key = Ed25519PrivateKey.generate()
            w_sig, w_pub = order_contract.sign_worker(terms_hash, worker_key)
            r = await client.post(
                f"/v1/contracts/{task_id}/sign",
                json={"role": "worker", "signature": w_sig, "public_key": w_pub},
            )
            assert r.status_code == 200, r.text
            assert r.json()["contract_status"] == "signed"

            # terms endpoint returns the ruling artifact
            r = await client.get(f"/v1/contracts/{task_id}/terms")
            assert r.status_code == 200, r.text
            assert r.json()["terms_hash"] == terms_hash

            # anchor endpoint: no on-chain binding yet → not anchored
            r = await client.get(f"/v1/contracts/{task_id}/anchor")
            assert r.status_code == 200, r.text
            anchor = r.json()
            assert anchor["terms_hash"] == terms_hash
            assert anchor["anchored"] is False
            assert anchor["note"] == "binding not yet on-chain"

        # bind gate: unsigned contract rejected
        draft = await db_session.get(TaskContractModel, "task-sign-2")
        if draft is None:
            draft = TaskContractModel(
                task_id="task-sign-2",
                client_agent_id="buyer-2",
                title="t",
                description="d",
                expected_output_schema={},
                expected_step_count=1,
                escrow_amount=10.0,
                currency="USD",
                deadline_at=datetime.utcnow(),
                terms_hash="ab" * 32,
                contract_status="draft",
            )
            db_session.add(draft)
            await db_session.commit()
        with pytest.raises(Exception) as exc:
            await bilateral_routes._require_signed_contract_for_bind(
                db_session, "task-sign-2", "0x" + "ab" * 32
            )
        assert exc.value.status_code == 409

        # bind gate: signed but scope_hash mismatch rejected
        row = await db_session.get(TaskContractModel, task_id)
        assert row is not None
        with pytest.raises(Exception) as exc:
            await bilateral_routes._require_signed_contract_for_bind(
                db_session, task_id, "0x" + "cd" * 32
            )
        assert exc.value.status_code == 409

        # bind gate: signed and matching scope_hash passes
        await bilateral_routes._require_signed_contract_for_bind(
            db_session, task_id, "0x" + terms_hash
        )
    finally:
        app.dependency_overrides.clear()
