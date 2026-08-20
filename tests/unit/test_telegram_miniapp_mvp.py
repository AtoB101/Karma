"""Tests for Telegram MiniApp MVP: initData, verification gate, settle gate."""
from __future__ import annotations

import os

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

# Ensure deterministic bot token for tests before app import side effects
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("KARMA_ENV", "test")
os.environ.setdefault("API_AUTH_DISABLED", "1")


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("KARMA_ENV", "test")
    from services.identity_gateway import siwe, store
    from services.miniapp_commerce import orders
    from services.telegram import reset_for_tests as reset_tg
    from services.verification_engine import reset_for_tests as reset_vr

    reset_tg()
    siwe.reset_for_tests()
    store.reset_for_tests()
    orders.reset_for_tests()
    reset_vr()

    from api.app import app

    return TestClient(app)


def _session(client):
    from services.telegram import build_dev_init_data

    init_data = build_dev_init_data(bot_token="test-bot-token", user_id=42, username="alice")
    r = client.post("/v1/telegram/session", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    return r.json()["session_id"], init_data


def test_init_data_rejects_tampered(client):
    from services.telegram import build_dev_init_data

    init_data = build_dev_init_data(bot_token="test-bot-token") + "x"
    r = client.post("/v1/telegram/session", json={"init_data": init_data})
    assert r.status_code == 401


def test_siwe_and_telegram_bind(client):
    acct = Account.create()
    sid, init_data = _session(client)
    ch = client.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    assert ch.status_code == 200
    msg = ch.json()["message"]
    sig = Account.sign_message(encode_defunct(text=msg), private_key=acct.key).signature.hex()
    ver = client.post(
        "/v1/auth/siwe/verify",
        json={"nonce": ch.json()["nonce"], "signature": sig, "address": acct.address},
    )
    assert ver.status_code == 200
    identity_id = ver.json()["identity_id"]
    bind = client.post(
        "/v1/telegram/bind",
        headers={"Authorization": f"Bearer {sid}"},
        json={"init_data": init_data, "identity_id": identity_id},
    )
    assert bind.status_code == 200
    assert bind.json()["telegram_user_id"] == 42


def test_verification_pass_required_before_settle(client):
    acct = Account.create()
    sid, init_data = _session(client)
    ch = client.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    msg = ch.json()["message"]
    sig = Account.sign_message(encode_defunct(text=msg), private_key=acct.key).signature.hex()
    ver = client.post(
        "/v1/auth/siwe/verify",
        json={"nonce": ch.json()["nonce"], "signature": sig, "address": acct.address},
    )
    identity_id = ver.json()["identity_id"]
    client.post(
        "/v1/telegram/bind",
        headers={"Authorization": f"Bearer {sid}"},
        json={"init_data": init_data, "identity_id": identity_id},
    )
    # refresh session binding by creating new session after bind
    sid, _ = _session(client)

    intent = client.post(
        "/v1/chat/intent",
        headers={"Authorization": f"Bearer {sid}"},
        json={"text": "buy API data for 100 USDC"},
    )
    assert intent.status_code == 200
    offers = intent.json()["offers"]
    assert offers
    order = client.post(
        "/v1/commerce/orders",
        headers={"Authorization": f"Bearer {sid}"},
        json={"intent": intent.json()["intent"], "offer_id": offers[0]["offer_id"]},
    )
    assert order.status_code == 200, order.text
    oid = order.json()["order_id"]
    h = {"Authorization": f"Bearer {sid}"}
    client.post("/v1/commerce/orders/sign", headers=h, json={"order_id": oid, "role": "buyer", "signature": "0xb"})
    client.post("/v1/commerce/orders/sign", headers=h, json={"order_id": oid, "role": "seller", "signature": "0xs"})
    assert client.post("/v1/commerce/orders/policy-check", headers=h, json={"order_id": oid}).status_code == 200
    assert client.post("/v1/settlement/lock", headers=h, json={"order_id": oid, "binding_id": 7}).status_code == 200

    # settle without verification → 403
    denied = client.post("/v1/settlement/finalize", headers=h, json={"order_id": oid})
    assert denied.status_code == 403

    # bad evidence → FAIL, still cannot settle
    client.post(
        "/v1/evidence/bundles",
        headers=h,
        json={"order_id": oid, "evidence": {"proof_hash": "bad", "amount_usdc": "1", "merchant_self_only": True}},
    )
    bad = client.post("/v1/verification/runs", headers=h, json={"order_id": oid})
    assert bad.status_code == 200
    assert bad.json()["status"] == "FAIL"
    assert client.post("/v1/settlement/finalize", headers=h, json={"order_id": oid}).status_code == 403

    # good evidence → PASS → settle
    # reset evidence path: submit good evidence and re-verify
    from services.miniapp_commerce import orders as order_store

    o = order_store.get_order(oid)
    o.status = order_store.OrderStatus.LOCKED
    client.post(
        "/v1/evidence/bundles",
        headers=h,
        json={
            "order_id": oid,
            "evidence": {
                "proof_hash": "0xok",
                "amount_usdc": order.json()["amount_usdc"],
                "independent_attestation": True,
            },
        },
    )
    # align intent expected proof if set
    o.intent["expected_proof_hash"] = "0xok"
    ok = client.post("/v1/verification/runs", headers=h, json={"order_id": oid})
    assert ok.status_code == 200
    assert ok.json()["status"] == "PASS"
    settled = client.post("/v1/settlement/finalize", headers=h, json={"order_id": oid})
    assert settled.status_code == 200, settled.text
    assert settled.json()["status"] == "SETTLED"
    assert settled.json()["fee_bridge"]["collectAndRecord"]["developer"]
    assert settled.json()["fee_bridge"]["collectAndRecord"]["binding_id"] == 7


def test_economy_surface_embed(client):
    sid, _ = _session(client)
    r = client.get("/v1/economy/surface", headers={"Authorization": f"Bearer {sid}"})
    assert r.status_code == 200
    body = r.json()
    assert "view=miniapp" in body["embed_url"]
    assert "feeBridge" in body["contracts"]
