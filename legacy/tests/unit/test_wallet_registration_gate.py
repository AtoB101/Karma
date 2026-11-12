"""One wallet = one identity, and the funding gate in front of registration.

Product rule under test:
  1. a wallet address can hold exactly one Karma identity;
  2. a wallet must hold funds before it may register — but an unfunded wallet is
     throttled rather than rejected, on a dimension the caller cannot forge.
"""
from __future__ import annotations

import os

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from config.settings import settings
from services.identity_gateway import siwe, store
from services import wallet_funding
from services.wallet_funding import FundingProbe, enforce_registration_funding_gate


def _request(ip: str = "203.0.113.9") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/auth/siwe/verify",
            "headers": [(b"x-real-ip", ip.encode())],
            "client": (ip, 12345),
        }
    )


@pytest.fixture()
def clean_identity_store():
    siwe.reset_for_tests()
    store.reset_for_tests()
    yield
    siwe.reset_for_tests()
    store.reset_for_tests()


def _set_gate(
    monkeypatch,
    *,
    funded: bool,
    per_ip: int = 3,
    global_max: int = 20,
    window: int = 3600,
) -> None:
    monkeypatch.setattr(settings, "registration_require_funding", True)
    monkeypatch.setattr(settings, "registration_zero_funding_max_per_ip", per_ip)
    monkeypatch.setattr(settings, "registration_zero_funding_max_global", global_max)
    monkeypatch.setattr(settings, "registration_zero_funding_window_seconds", window)
    monkeypatch.setattr(
        wallet_funding,
        "probe_wallet_funding",
        lambda address: FundingProbe(True, funded, 1 if funded else 0, 0, "ok"),
    )


# ---------------------------------------------------------------------------
# Rule 1 — one wallet, one identity
# ---------------------------------------------------------------------------


def test_wallet_maps_to_exactly_one_identity(clean_identity_store):
    acct = Account.create()
    first = store.get_or_create_by_wallet(acct.address)
    second = store.get_or_create_by_wallet(acct.address.lower())
    assert first.identity_id == second.identity_id
    assert store.get_by_wallet(acct.address.upper()).identity_id == first.identity_id


def test_sub_identity_cannot_reuse_an_existing_wallet(clean_identity_store):
    parent = store.get_or_create_by_wallet(Account.create().address)
    taken = Account.create()
    store.create_sub_identity(parent.identity_id, taken.address)
    with pytest.raises(ValueError):
        store.create_sub_identity(parent.identity_id, taken.address.lower())


def test_sub_identity_cannot_steal_a_main_identity_wallet(clean_identity_store):
    holder = store.get_or_create_by_wallet(Account.create().address)
    other = store.get_or_create_by_wallet(Account.create().address)
    with pytest.raises(ValueError):
        store.create_sub_identity(other.identity_id, holder.wallet)


# ---------------------------------------------------------------------------
# Rule 2 — funding gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_funded_wallet_is_never_throttled(monkeypatch, clean_identity_store):
    _set_gate(monkeypatch, funded=True, per_ip=1, global_max=1)
    req = _request()
    for _ in range(5):
        await enforce_registration_funding_gate(req, "0x" + "a" * 40)


@pytest.mark.asyncio
async def test_unfunded_wallet_is_throttled_per_ip(monkeypatch, clean_identity_store):
    _set_gate(monkeypatch, funded=False, per_ip=3, global_max=100)
    req = _request("198.51.100.7")
    for _ in range(3):
        await enforce_registration_funding_gate(req, "0x" + "b" * 40)
    with pytest.raises(HTTPException) as exc:
        await enforce_registration_funding_gate(req, "0x" + "b" * 40)
    assert exc.value.status_code == 429
    assert "no funds" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_unfunded_budget_is_per_ip_not_global(monkeypatch, clean_identity_store):
    _set_gate(monkeypatch, funded=False, per_ip=1, global_max=100)
    await enforce_registration_funding_gate(_request("198.51.100.10"), "0x" + "c" * 40)
    # A different client IP gets its own budget.
    await enforce_registration_funding_gate(_request("198.51.100.11"), "0x" + "c" * 40)


@pytest.mark.asyncio
async def test_unfunded_global_budget_brakes_the_platform(monkeypatch, clean_identity_store):
    _set_gate(monkeypatch, funded=False, per_ip=100, global_max=1)
    await enforce_registration_funding_gate(_request("198.51.100.20"), "0x" + "d" * 40)
    with pytest.raises(HTTPException) as exc:
        await enforce_registration_funding_gate(_request("198.51.100.21"), "0x" + "e" * 40)
    assert exc.value.status_code == 429
    assert "platform-wide" in str(exc.value.detail)


def test_dev_env_skips_the_probe(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    probe = wallet_funding.probe_wallet_funding("0x" + "f" * 40)
    assert probe.checked is False
    assert probe.funded is True
    assert probe.reason == "dev_env_skipped"


def test_missing_rpc_is_reported_as_unfunded_not_an_error(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "testnet_rpc_url", "")
    probe = wallet_funding.probe_wallet_funding("0x" + "f" * 40)
    assert probe.checked is False
    assert probe.funded is False
    assert probe.reason == "rpc_not_configured"


def test_rpc_failure_is_reported_as_unfunded_not_raised(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "testnet_rpc_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "registration_funding_rpc_timeout_seconds", 1)
    probe = wallet_funding.probe_wallet_funding("0x" + "f" * 40)
    assert probe.checked is False
    assert probe.funded is False
    assert probe.reason.startswith("probe_error")


# ---------------------------------------------------------------------------
# Rule 1 + 2 together, through the real registration endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("KARMA_ENV", "test")
    os.environ.setdefault("API_AUTH_DISABLED", "1")
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


def _register(client, acct, ip: str):
    ch = client.post("/v1/auth/siwe/challenge", json={"address": acct.address})
    assert ch.status_code == 200, ch.text
    msg = ch.json()["message"]
    sig = Account.sign_message(encode_defunct(text=msg), private_key=acct.key).signature.hex()
    return client.post(
        "/v1/auth/siwe/verify",
        json={"nonce": ch.json()["nonce"], "signature": sig, "address": acct.address},
        headers={"X-Real-IP": ip},
    )


def test_registration_gate_end_to_end(monkeypatch, client):
    """Unfunded wallets share one budget per IP; a returning wallet is free."""
    _set_gate(monkeypatch, funded=False, per_ip=1, global_max=100)
    monkeypatch.setattr(settings, "app_env", "production")

    first = Account.create()
    r1 = _register(client, first, "203.0.113.50")
    assert r1.status_code == 200, r1.text

    # Same IP, a different wallet, budget already spent -> throttled.
    second = Account.create()
    r2 = _register(client, second, "203.0.113.50")
    assert r2.status_code == 429, r2.text

    # The wallet that already has an identity is a returning user, not a new
    # registration: it must never be throttled by the sybil budget.
    r3 = _register(client, first, "203.0.113.50")
    assert r3.status_code == 200, r3.text
    assert r3.json()["identity_id"] == r1.json()["identity_id"]


def test_funded_wallet_registers_even_when_unfunded_budget_is_spent(monkeypatch, client):
    _set_gate(monkeypatch, funded=False, per_ip=1, global_max=1)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(
        wallet_funding,
        "probe_wallet_funding",
        lambda address: FundingProbe(True, False, 0, 0, "ok"),
    )
    assert _register(client, Account.create(), "203.0.113.60").status_code == 200

    # A funded wallet is not part of the unfunded budget at all.
    monkeypatch.setattr(
        wallet_funding,
        "probe_wallet_funding",
        lambda address: FundingProbe(True, True, 10**18, 0, "ok"),
    )
    assert _register(client, Account.create(), "203.0.113.61").status_code == 200
