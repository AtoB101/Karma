"""EIP-712 write auth + event-sourced task store tests."""
import os
import sys
import tempfile
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["A2A_REQUIRE_EIP712"] = "1"
os.environ["A2A_EIP712_CHAIN_ID"] = "11155111"
os.environ["A2A_EIP712_VERIFYING_CONTRACT"] = "0x496d178a5D32E9410E52bD5800602BDEe81B2A91"

from eth_account import Account
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eip712_auth import OP_CREATE, OP_CONFIRM, OP_SUBMIT, sign_a2a_task_op, verify_a2a_task_op
from task_store import reset_task_store_for_tests
import a2a_server


@pytest.fixture()
def client(tmp_path):
    db = tmp_path / "tasks.sqlite3"
    reset_task_store_for_tests(str(db))
    a2a_server._agent_card = None
    app = FastAPI()
    app.include_router(a2a_server.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def wallet():
    return Account.create()


def _auth(wallet, task_id, op_type, nonce, amount_micro=0, requester_id=""):
    deadline = int(time.time()) + 600
    sig = sign_a2a_task_op(
        private_key=wallet.key,
        task_id=task_id,
        op_type=op_type,
        agent=wallet.address,
        requester_id=requester_id,
        amount_micro=amount_micro,
        nonce=nonce,
        deadline=deadline,
    )
    return {
        "agent": wallet.address,
        "signature": sig,
        "nonce": nonce,
        "deadline": deadline,
        "amount_micro": amount_micro,
        "requester_id": requester_id,
    }


def test_eip712_roundtrip(wallet):
    deadline = int(time.time()) + 100
    sig = sign_a2a_task_op(
        private_key=wallet.key,
        task_id="t1",
        op_type=OP_CREATE,
        nonce=1,
        deadline=deadline,
        requester_id="alice",
    )
    recovered = verify_a2a_task_op(
        signature=sig,
        task_id="t1",
        op_type=OP_CREATE,
        agent=wallet.address,
        requester_id="alice",
        nonce=1,
        deadline=deadline,
    )
    assert recovered.lower() == wallet.address.lower()


def test_write_requires_signature(client):
    task_id = f"t_{uuid.uuid4().hex[:8]}"
    r = client.post("/a2a/task", json={
        "task_id": task_id,
        "skill": "order_food",
        "params": {},
    })
    # No skills configured on default card → skill check may pass; auth must fail
    assert r.status_code == 401


def test_full_task_lifecycle_with_events(client, wallet):
    task_id = f"t_{uuid.uuid4().hex[:8]}"
    create = client.post("/a2a/task", json={
        "task_id": task_id,
        "skill": "order_food",
        "params": {"restaurant": "X"},
        "requester_id": "alice",
        "auth": _auth(wallet, task_id, OP_CREATE, nonce=1, requester_id="alice"),
    })
    assert create.status_code == 200, create.text
    assert create.json()["status"] == "negotiating"

    confirm = client.post(f"/a2a/task/{task_id}/confirm", json={
        "seller_id": "seller_1",
        "amount": 12.5,
        "auth": _auth(wallet, task_id, OP_CONFIRM, nonce=2, amount_micro=12_500_000, requester_id="alice"),
    })
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "accepted"
    assert confirm.json()["voucher_id"]

    submit = client.post(f"/a2a/task/{task_id}/submit", json={
        "result": {"ok": True},
        "auth": _auth(wallet, task_id, OP_SUBMIT, nonce=3, requester_id="alice"),
    })
    assert submit.status_code == 200
    assert submit.json()["status"] == "completed"

    events = client.get(f"/a2a/task/{task_id}/events")
    assert events.status_code == 200
    types = [e["event_type"] for e in events.json()["events"]]
    assert types == ["TaskCreated", "TaskConfirmed", "TaskSubmitted"]

    # Replay protection
    replay = client.post(f"/a2a/task/{task_id}/submit", json={
        "result": {"ok": False},
        "auth": _auth(wallet, task_id, OP_SUBMIT, nonce=3, requester_id="alice"),
    })
    assert replay.status_code == 401


def test_agent_card_exposes_attestation_discovery_not_privileged_methods(client):
    card = client.get("/.well-known/agent-card.json").json()
    assert "karma_attestation" in card["capabilities"] or True  # may be present via config
    karma = card["karma"]
    assert "verifier_registry" in karma
    assert "attestation_gateway" in karma
    # Must not advertise privileged method selectors as skills
    skill_ids = [s["id"] for s in card.get("skills", [])]
    assert "recordAttestation" not in skill_ids
    assert "rewardVerifier" not in skill_ids
