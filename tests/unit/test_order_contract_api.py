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
from db.models.orm import AgentModel, IdentityProfileModel, TaskContractModel
from db.session import get_db
from services import order_contract


async def _seed_buyer_identity(db, agent_id: str, buyer_address: str) -> None:
    db.add(IdentityProfileModel(
        identity_id=f"owner-{agent_id}",
        display_id=f"owner-{agent_id}",
        bound_wallet_address=buyer_address,
    ))
    db.add(AgentModel(
        agent_id=agent_id,
        name=agent_id,
        role="buyer",
        public_key="",
        owner_identity_id=f"owner-{agent_id}",
    ))
    await db.commit()


async def _seed_worker_agent(db, agent_id: str, public_key_b64: str) -> None:
    db.add(AgentModel(
        agent_id=agent_id,
        name=agent_id,
        role="worker",
        public_key=public_key_b64,
    ))
    await db.commit()


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
            buyer = Account.create()
            await _seed_buyer_identity(db_session, "buyer-1", buyer.address)
            r = await client.post("/v1/contracts", json=_body())
            assert r.status_code == 201, r.text
            created = r.json()
            task_id = created["task_id"]
            terms_hash = created["terms_hash"]
            assert created["contract_status"] == "draft"
            assert len(terms_hash) == 64

            # buyer signs with a fresh wallet
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
            await _seed_worker_agent(db_session, "worker-1", w_pub)
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

@pytest.mark.asyncio
async def test_dispute_anchor_gate_contract_checks(db_session, relaxed):
    # missing contract → 404
    with pytest.raises(Exception) as exc:
        await bilateral_routes._require_contract_anchor(db_session, "missing-contract", 1)
    assert exc.value.status_code == 404

    # draft (unsigned) contract → 409, before any on-chain read
    db_session.add(
        TaskContractModel(
            task_id="draft-anchor-1",
            client_agent_id="buyer-x",
            title="t",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=1.0,
            currency="USD",
            deadline_at=datetime.utcnow(),
            terms_hash="ab" * 32,
            contract_status="draft",
        )
    )
    await db_session.commit()
    with pytest.raises(Exception) as exc:
        await bilateral_routes._require_contract_anchor(db_session, "draft-anchor-1", 1)
    assert exc.value.status_code == 409

@pytest.mark.asyncio
async def test_contract_revise_flow_requires_resign(db_session, relaxed):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            buyer = Account.create()
            await _seed_buyer_identity(db_session, "buyer-1", buyer.address)
            r = await client.post("/v1/contracts", json=_body("task-revise-1"))
            assert r.status_code == 201, r.text
            task_id = r.json()["task_id"]
            terms_hash = r.json()["terms_hash"]
            r = await client.post(
                f"/v1/contracts/{task_id}/sign",
                json={"role": "buyer", "signature": order_contract.sign_buyer(
                    private_key=buyer.key, terms_hash=terms_hash, task_id=task_id, chain_id=84532,
                ), "address": buyer.address},
            )
            assert r.status_code == 200, r.text

            row = await db_session.get(TaskContractModel, task_id)
            row.worker_agent_id = "worker-1"
            await db_session.commit()

            worker_key = Ed25519PrivateKey.generate()
            w_sig, w_pub = order_contract.sign_worker(terms_hash, worker_key)
            await _seed_worker_agent(db_session, "worker-1", w_pub)
            r = await client.post(
                f"/v1/contracts/{task_id}/sign",
                json={"role": "worker", "signature": w_sig, "public_key": w_pub},
            )
            assert r.json()["contract_status"] == "signed"

            # worker counter-proposes: revise amount + add a delivery criterion
            r = await client.post(
                f"/v1/contracts/{task_id}/revise",
                json={"escrow_amount": 5100.0, "delivery_criteria": "within 20 days"},
            )
            assert r.status_code == 200, r.text
            rev = r.json()
            assert rev["version"] == 2
            assert rev["contract_status"] == "draft"
            assert rev["terms_hash"] != terms_hash
            new_hash = rev["terms_hash"]

            # old signatures are invalidated; both parties must re-sign
            r = await client.post(
                f"/v1/contracts/{task_id}/sign",
                json={"role": "buyer", "signature": order_contract.sign_buyer(
                    private_key=buyer.key, terms_hash=new_hash, task_id=task_id, chain_id=84532,
                ), "address": buyer.address},
            )
            assert r.json()["contract_status"] == "buyer_signed"
            w_sig2, w_pub2 = order_contract.sign_worker(new_hash, worker_key)
            r = await client.post(
                f"/v1/contracts/{task_id}/sign",
                json={"role": "worker", "signature": w_sig2, "public_key": w_pub2},
            )
            assert r.json()["contract_status"] == "signed"
            assert r.json()["version"] == 2

            # bind gate now validates against the new terms_hash
            await bilateral_routes._require_signed_contract_for_bind(
                db_session, task_id, "0x" + new_hash
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_contract_revise_locked_after_onchain_bind(db_session, relaxed):
    """A contract anchored by the bilateral bind path (binding id on the contract
    row) must reject revision with 409, even without a settlement row."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/v1/contracts", json=_body("task-revise-locked"))
            assert r.status_code == 201, r.text
            task_id = r.json()["task_id"]

            row = await db_session.get(TaskContractModel, task_id)
            row.onchain_binding_id = 42
            await db_session.commit()

            r = await client.post(
                f"/v1/contracts/{task_id}/revise",
                json={"escrow_amount": 5100.0},
            )
            assert r.status_code == 409, r.text
            assert "already anchored on-chain" in r.text
    finally:
        app.dependency_overrides.clear()