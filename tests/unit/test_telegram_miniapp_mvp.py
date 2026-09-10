"""Tests for Telegram MiniApp MVP: initData, verification gate, settle gate, registry, bot."""
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
    from services.miniapp_commerce import orders, pipeline
    from services.miniapp_registry import store as registry
    from services.miniapp_trust import reputation, risk_dispute
    from services.telegram import reset_for_tests as reset_tg
    from services.verification_engine import reset_for_tests as reset_vr

    reset_tg()
    siwe.reset_for_tests()
    store.reset_for_tests()
    orders.reset_for_tests()
    pipeline.reset_for_tests()
    registry.reset_for_tests()
    risk_dispute.reset_for_tests()
    reputation.reset_for_tests()
    reset_vr()

    from api.app import app

    return TestClient(app)


def _session(client):
    from services.telegram import build_dev_init_data

    init_data = build_dev_init_data(bot_token="test-bot-token", user_id=42, username="alice")
    r = client.post("/v1/telegram/session", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    return r.json()["session_id"], init_data


def _bind_wallet(client, sid, init_data):
    acct = Account.create()
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
    sid2, _ = _session(client)
    return sid2, identity_id, acct


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
    # Console wallet login must issue a short-lived JWT for protected routes.
    assert ver.json().get("access_token")
    assert ver.json().get("token_type") == "bearer"
    bind = client.post(
        "/v1/telegram/bind",
        headers={"Authorization": f"Bearer {sid}"},
        json={"init_data": init_data, "identity_id": identity_id},
    )
    assert bind.status_code == 200
    assert bind.json()["telegram_user_id"] == 42


def test_verification_pass_required_before_settle(client):
    sid, init_data = _session(client)
    sid, identity_id, _acct = _bind_wallet(client, sid, init_data)
    h = {"Authorization": f"Bearer {sid}"}

    intent = client.post("/v1/chat/intent", headers=h, json={"text": "buy API data for 100 USDC"})
    assert intent.status_code == 200
    offers = intent.json()["offers"]
    assert offers
    order = client.post(
        "/v1/commerce/orders",
        headers=h,
        json={"intent": intent.json()["intent"], "offer_id": offers[0]["offer_id"]},
    )
    assert order.status_code == 200, order.text
    oid = order.json()["order_id"]
    assert order.json().get("bill_id")

    client.post("/v1/commerce/orders/sign", headers=h, json={"order_id": oid, "role": "buyer", "signature": "0xb"})
    client.post("/v1/commerce/orders/sign", headers=h, json={"order_id": oid, "role": "seller", "signature": "0xs"})
    assert client.post("/v1/commerce/orders/policy-check", headers=h, json={"order_id": oid}).status_code == 200
    assert client.post("/v1/settlement/lock", headers=h, json={"order_id": oid, "binding_id": 7}).status_code == 200

    denied = client.post("/v1/settlement/finalize", headers=h, json={"order_id": oid})
    assert denied.status_code == 403

    client.post(
        "/v1/evidence/bundles",
        headers=h,
        json={"order_id": oid, "evidence": {"proof_hash": "bad", "amount_usdc": "1", "merchant_self_only": True}},
    )
    bad = client.post("/v1/verification/runs", headers=h, json={"order_id": oid})
    assert bad.status_code == 200
    assert bad.json()["status"] == "FAIL"
    assert client.post("/v1/settlement/finalize", headers=h, json={"order_id": oid}).status_code == 403

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
    o.intent["expected_proof_hash"] = "0xok"
    ok = client.post("/v1/verification/runs", headers=h, json={"order_id": oid})
    assert ok.status_code == 200
    assert ok.json()["status"] == "PASS"
    settled = client.post("/v1/settlement/finalize", headers=h, json={"order_id": oid})
    assert settled.status_code == 200, settled.text
    assert settled.json()["status"] == "SETTLED"
    fb = settled.json()["fee_bridge"]["collectAndRecord"]
    assert fb["developer"]
    assert fb["orderId"] == "0x" + (7).to_bytes(32, "big").hex()
    assert fb["feeUsdc"] == "MUST_EQUAL_quoteFee_RESULT"
    assert settled.json().get("execution_record_id")
    assert settled.json()["settle_plan"]["steps"][1]["method"].startswith("settle")
    assert settled.json()["self_deal"] is False

    rep = client.get(f"/v1/miniapp/reputation/{identity_id}", headers=h)
    assert rep.status_code == 200
    assert rep.json()["settled_count"] >= 1


def test_economy_surface_embed(client):
    sid, _ = _session(client)
    r = client.get("/v1/economy/surface", headers={"Authorization": f"Bearer {sid}"})
    assert r.status_code == 200
    body = r.json()
    assert "view=miniapp" in body["embed_url"]
    assert "feeBridge" in body["contracts"]


def test_registry_quote_intent_package_and_bot(client):
    sid, init_data = _session(client)
    sid, _identity_id, acct = _bind_wallet(client, sid, init_data)
    h = {"Authorization": f"Bearer {sid}"}

    biz = client.post("/v1/registry/businesses", headers=h, json={"legal_name": "Acme", "country": "SG"})
    assert biz.status_code == 200, biz.text
    agt = client.post(
        "/v1/registry/agents",
        headers=h,
        json={
            "endpoint": "https://agent.example",
            "capabilities": ["digital"],
            "business_id": biz.json()["business_id"],
            "builder_address": acct.address,
            "wallet": acct.address,
        },
    )
    assert agt.status_code == 200, agt.text
    cap = client.post(
        "/v1/registry/capabilities",
        headers=h,
        json={"name": "Fetch", "category": "digital"},
    )
    assert cap.status_code == 200
    off = client.post(
        "/v1/registry/offers",
        headers=h,
        json={
            "agent_id": agt.json()["agent_id"],
            "capability_id": cap.json()["capability_id"],
            "title": "Fetch pack",
            "price_usdc": "50",
            "category": "digital",
        },
    )
    assert off.status_code == 200, off.text
    offer_id = off.json()["offer_id"]

    q = client.post("/v1/commerce/quotes", headers=h, json={"offer_id": offer_id, "amount_usdc": "45"})
    assert q.status_code == 200
    neg = client.post("/v1/commerce/negotiations", headers=h, json={"quote_id": q.json()["quote_id"]})
    assert neg.status_code == 200
    client.post(
        "/v1/commerce/negotiations/propose",
        headers=h,
        json={"negotiation_id": neg.json()["negotiation_id"], "role": "buyer", "amount_usdc": "40"},
    )
    agreed = client.post(
        "/v1/commerce/negotiations/agree",
        headers=h,
        json={"negotiation_id": neg.json()["negotiation_id"], "amount_usdc": "40"},
    )
    assert agreed.json()["status"] == "agreed"

    intent = {"scene_id": "digital", "amount_usdc": "40", "raw_text": "buy"}
    order = client.post(
        "/v1/commerce/orders",
        headers=h,
        json={"intent": intent, "offer_id": offer_id},
    )
    assert order.status_code == 200
    oid = order.json()["order_id"]
    from services.miniapp_commerce import orders as order_store

    o = order_store.get_order(oid)
    if not o.seller_wallet:
        o.seller_wallet = "0x9999999999999999999999999999999999999999"
    if not o.buyer_wallet:
        o.buyer_wallet = acct.address.lower()

    pkg = client.post("/v1/commerce/intent-packages", headers=h, json={"order_id": oid})
    assert pkg.status_code == 200, pkg.text
    assert pkg.json()["typed_data"]["primaryType"] == "KarmaIntent"
    signed = client.post(
        "/v1/commerce/intent-packages/sign",
        headers=h,
        json={"intent_id": pkg.json()["intent_id"], "role": "buyer", "signature": "0xsig"},
    )
    assert signed.status_code == 200

    bot = client.post(
        "/v1/telegram/bot/webhook",
        json={"message": {"text": "/start bind_kid1", "chat": {"id": 1}, "from": {"id": 42}}},
    )
    assert bot.status_code == 200
    assert bot.json()["action"] == "bind"
    assert "miniapp_url" in bot.json()

    dl = client.get("/v1/telegram/bot/deeplink", params={"identity_id": "kid_x", "action": "bind"})
    assert dl.status_code == 200
    assert "t.me" in dl.json()["bot_start"]


def test_daily_limit_policy(client):
    sid, init_data = _session(client)
    sid, identity_id, _ = _bind_wallet(client, sid, init_data)
    h = {"Authorization": f"Bearer {sid}"}
    # Unauthenticated policy update must be rejected
    unauth = client.post(
        "/v1/identity/policy",
        json={
            "identity_id": identity_id,
            "policy": {"single_limit_usdc": "1000", "daily_limit_usdc": "30", "spent_today_usdc": "0"},
        },
    )
    assert unauth.status_code == 401
    client.post(
        "/v1/identity/policy",
        headers=h,
        json={
            "identity_id": identity_id,
            "policy": {"single_limit_usdc": "1000", "daily_limit_usdc": "30", "spent_today_usdc": "0"},
        },
    )
    intent = client.post("/v1/chat/intent", headers=h, json={"text": "buy API data for 100 USDC"})
    order = client.post(
        "/v1/commerce/orders",
        headers=h,
        json={"intent": intent.json()["intent"], "offer_id": intent.json()["offers"][0]["offer_id"]},
    )
    oid = order.json()["order_id"]
    client.post("/v1/commerce/orders/sign", headers=h, json={"order_id": oid, "role": "buyer", "signature": "0xb"})
    client.post("/v1/commerce/orders/sign", headers=h, json={"order_id": oid, "role": "seller", "signature": "0xs"})
    denied = client.post("/v1/commerce/orders/policy-check", headers=h, json={"order_id": oid})
    assert denied.status_code == 403
    assert "daily_limit" in denied.json()["detail"]


# ── /disputes/resolve arbitrator gate ────────────────────────────────────────

class _FakeSession:
    def __init__(self, identity_id=None, telegram_user_id=None):
        self.identity_id = identity_id
        self.telegram_user_id = telegram_user_id


class TestDisputeArbitratorGate:
    """_require_arbitrator: /disputes/resolve must only be callable by whitelisted arbitrators."""

    def test_whitelisted_identity_passes(self, monkeypatch):
        from api.routes import telegram_miniapp_commerce as route
        from config.settings import settings

        monkeypatch.setattr(settings, "arbitrator_actor_ids", "arb-1, arb-2")
        route._require_arbitrator(_FakeSession(identity_id="arb-1"))

    def test_whitelisted_telegram_user_id_passes(self, monkeypatch):
        from api.routes import telegram_miniapp_commerce as route
        from config.settings import settings

        monkeypatch.setattr(settings, "arbitrator_actor_ids", "777001")
        route._require_arbitrator(_FakeSession(telegram_user_id=777001))

    def test_non_whitelisted_session_rejected(self, monkeypatch):
        from fastapi import HTTPException

        from api.routes import telegram_miniapp_commerce as route
        from config.settings import settings

        monkeypatch.setattr(settings, "arbitrator_actor_ids", "arb-1")
        with pytest.raises(HTTPException) as exc:
            route._require_arbitrator(_FakeSession(identity_id="mallory", telegram_user_id=666))
        assert exc.value.status_code == 403

    def test_empty_whitelist_rejects_outside_dev(self, monkeypatch):
        from fastapi import HTTPException

        from api.routes import telegram_miniapp_commerce as route
        from config.settings import settings

        monkeypatch.setattr(settings, "arbitrator_actor_ids", "")
        monkeypatch.setattr(settings, "app_env", "production")
        with pytest.raises(HTTPException) as exc:
            route._require_arbitrator(_FakeSession(identity_id="anyone"))
        assert exc.value.status_code == 403

    def test_empty_whitelist_allows_dev_env(self, monkeypatch):
        from api.routes import telegram_miniapp_commerce as route
        from config.settings import settings

        monkeypatch.setattr(settings, "arbitrator_actor_ids", "")
        monkeypatch.setattr(settings, "app_env", "development")
        route._require_arbitrator(_FakeSession(identity_id="local-dev"))
