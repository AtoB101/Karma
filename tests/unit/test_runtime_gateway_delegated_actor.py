"""Runtime Gateway mutators must act for the Runtime Key without a dev-only API key.

Two production-only defects on the agent channel are pinned here:

1. the gateway delegated to inner routes with a synthetic
   ``karma_<id>_devruntimekey12`` API key, which only resolved while
   ``AUTH_ALLOW_DEV_KEY_FALLBACK`` was on *and* auth enforcement was off, so in
   production every /runtime mutator (update-progress, submit-receipt,
   request-settlement, request-voucher, check-voucher) died with 401
   "authentication required for this operation";
2. it validated an incoming receipt *before* signing it, so
   RECEIPT_REQUIRE_SIGNATURE (on in production) rejected every agent receipt with
   400 "receipt signature is required" — the agent holds a Runtime Key, never the
   platform signing key.

The verified actor now travels on ``request.state``, which only in-process code can
set, so delegation cannot be forged from outside.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from httptest import post_minimal_contract

from api.middleware.auth import resolve_agent_id_from_request
from config.settings import settings
from services.runtime_synthetic_request import (
    RUNTIME_ACTOR_STATE_KEY,
    runtime_actor_id,
    synthetic_request,
)
from services.runtime_wallet import build_create_key_message


def test_synthetic_request_stamps_the_verified_actor():
    req = synthetic_request(path="/runtime/update-progress", actor_id="seller-1")
    assert runtime_actor_id(req) == "seller-1"
    assert resolve_agent_id_from_request(req) == "seller-1"


def test_synthetic_request_without_actor_has_no_delegated_actor():
    req = synthetic_request(headers={"X-Karma-Api-Key": "whatever"})
    assert runtime_actor_id(req) is None


def test_delegated_actor_beats_a_forged_identity_header():
    """A caller-supplied identity header must never outrank the gateway-stamped actor."""
    req = synthetic_request(path="/runtime/update-progress", actor_id="seller-1")
    req.scope["headers"] = list(req.scope["headers"]) + [
        (b"x-karma-identity-id", b"attacker")
    ]
    assert resolve_agent_id_from_request(req) == "seller-1"


def test_identity_header_is_ignored_when_enforcement_is_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    req = synthetic_request(headers={"X-Karma-Identity-Id": "attacker"})
    assert resolve_agent_id_from_request(req) is None


async def _seed_in_progress_settlement(
    client: AsyncClient,
    activate_identity,
    *,
    task_id: str,
    buyer: str,
    seller: str,
) -> None:
    # 未激活的主身份不能接单：先让卖家完成本人实名认证。
    await activate_identity(seller)
    lock = await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 100})
    assert lock.status_code == 200, lock.text
    await post_minimal_contract(
        client, task_id=task_id, client_agent_id=buyer, escrow_amount=100.0
    )
    voucher = await client.post(
        "/v1/vouchers",
        json={
            "buyer_identity_id": buyer,
            "seller_identity_id": seller,
            "amount": 100,
            "currency": "USDC",
            "bill_credit_amount": 100,
            "task_type": "agent.runtime_delegation",
            "task_description_hash": "a" * 64,
            "progress_rule_hash": "b" * 64,
            "evidence_requirement_hash": "c" * 64,
            "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "nonce": f"nonce-{task_id}",
            "buyer_signature": f"sig-{task_id}",
        },
    )
    assert voucher.status_code == 201, voucher.text
    vid = voucher.json()["voucher_id"]
    accepted = await client.post(
        f"/v1/vouchers/{vid}/accept", json={"seller_identity_id": seller}
    )
    assert accepted.status_code == 200, accepted.text
    create = await client.post(
        "/v1/settlement/create",
        json={
            "task_id": task_id,
            "client_agent_id": buyer,
            "escrow_amount": 100.0,
            "currency": "USD",
        },
    )
    assert create.status_code in (200, 201), create.text
    locked = await client.post(
        f"/v1/settlement/{task_id}/lock", json={"worker_agent_id": seller}
    )
    assert locked.status_code == 200, locked.text
    started = await client.post(f"/v1/settlement/{task_id}/start", json={})
    assert started.status_code == 200, started.text


async def _mint_runtime(client: AsyncClient, *, seller: str, perms: list[str]) -> str:
    acct = Account.create()
    expire = datetime.utcnow() + timedelta(days=7)
    msg = build_create_key_message(
        karma_identity_id=seller,
        wallet_address=acct.address,
        permissions=sorted(perms),
        single_limit=1000.0,
        daily_limit=1000.0,
        expire_time=expire,
        agent_name="runtime-gateway-delegation-test",
        agent_binding=None,
    )
    signed = acct.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": seller,
            "wallet_signature": signed.signature.hex(),
            "permissions": sorted(perms),
            "single_limit": 1000.0,
            "daily_limit": 1000.0,
            "expire_time": expire.isoformat(),
            "agent_name": "runtime-gateway-delegation-test",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["runtime_key"]


def _progress_body(*, task_id: str, seller: str, evidence: str, log: str) -> dict:
    return {
        "task_id": task_id,
        "seller_identity_id": seller,
        "progress_percent": 25,
        "claimed_value_percent": 25,
        "evidence_hash": evidence,
        "runtime_log_hash": log,
        "seller_signature": "placeholder",
        "validation_method": "buyer_confirm",
    }


@pytest.mark.asyncio
async def test_runtime_update_progress_works_with_enforcement_on(
    client: AsyncClient, monkeypatch, activate_identity
):
    """The exact production configuration that used to 401 every progress report."""
    task_id = "task-runtime-delegated-progress"
    buyer = "buyer-runtime-delegated"
    seller = "seller-runtime-delegated"

    await _seed_in_progress_settlement(
        client, activate_identity, task_id=task_id, buyer=buyer, seller=seller
    )
    runtime_key = await _mint_runtime(client, seller=seller, perms=["update_progress"])

    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    monkeypatch.setattr(settings, "auth_allow_dev_key_fallback", False)

    resp = await client.post(
        "/runtime/update-progress",
        headers={"X-Karma-Runtime-Key": runtime_key},
        json=_progress_body(task_id=task_id, seller=seller, evidence="d" * 64, log="e" * 64),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["task_id"] == task_id


@pytest.mark.asyncio
async def test_runtime_key_still_cannot_act_for_another_identity(
    client: AsyncClient, monkeypatch, activate_identity
):
    """Delegation must not become impersonation."""
    task_id = "task-runtime-delegated-cross"
    buyer = "buyer-runtime-cross"
    seller = "seller-runtime-cross"

    await _seed_in_progress_settlement(
        client, activate_identity, task_id=task_id, buyer=buyer, seller=seller
    )
    intruder_key = await _mint_runtime(
        client, seller="seller-runtime-intruder", perms=["update_progress"]
    )

    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    monkeypatch.setattr(settings, "auth_allow_dev_key_fallback", False)

    resp = await client.post(
        "/runtime/update-progress",
        headers={"X-Karma-Runtime-Key": intruder_key},
        json=_progress_body(task_id=task_id, seller=seller, evidence="f" * 64, log="1" * 64),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_runtime_key_submits_an_unsigned_receipt(
    client: AsyncClient, monkeypatch, activate_identity
):
    """The agent has no signing key, only a Runtime Key: the gateway must sign for it."""
    task_id = "task-runtime-delegated-receipt"
    buyer = "buyer-runtime-receipt"
    seller = "seller-runtime-receipt"

    await _seed_in_progress_settlement(
        client, activate_identity, task_id=task_id, buyer=buyer, seller=seller
    )
    runtime_key = await _mint_runtime(client, seller=seller, perms=["submit_receipt"])

    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    monkeypatch.setattr(settings, "auth_allow_dev_key_fallback", False)
    monkeypatch.setattr(settings, "receipt_require_signature", True)

    now = datetime.now(timezone.utc)
    resp = await client.post(
        "/runtime/submit-receipt",
        headers={"X-Karma-Runtime-Key": runtime_key},
        json={
            "task_id": task_id,
            "agent_id": seller,
            "step_index": 1,
            "tool_name": "tool.step",
            "input_hash": "a" * 64,
            "output_hash": "b" * 64,
            "started_at": now.isoformat(),
            "ended_at": (now + timedelta(milliseconds=50)).isoformat(),
            "duration_ms": 50,
            "status": "success",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["signature"], "the gateway must store a signed receipt"
    assert body["agent_id"] == seller


@pytest.mark.asyncio
async def test_runtime_key_submits_sequential_receipts(
    client: AsyncClient, monkeypatch, activate_identity
):
    """A second step receipt must compare against the stored timestamp without crashing.

    The stored ``ended_at`` comes back from the database timezone-naive while the
    incoming receipt is UTC-aware, so a raw ``<`` raised
    ``TypeError: can't compare offset-naive and offset-aware datetimes`` -> HTTP 500
    on every receipt after the first.
    """
    task_id = "task-runtime-delegated-sequential"
    buyer = "buyer-runtime-sequential"
    seller = "seller-runtime-sequential"

    await _seed_in_progress_settlement(
        client, activate_identity, task_id=task_id, buyer=buyer, seller=seller
    )
    runtime_key = await _mint_runtime(client, seller=seller, perms=["submit_receipt"])

    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    monkeypatch.setattr(settings, "auth_allow_dev_key_fallback", False)
    monkeypatch.setattr(settings, "receipt_require_signature", True)

    base = datetime.now(timezone.utc)
    for step in (1, 2):
        started = base + timedelta(seconds=step)
        resp = await client.post(
            "/runtime/submit-receipt",
            headers={"X-Karma-Runtime-Key": runtime_key},
            json={
                "task_id": task_id,
                "agent_id": seller,
                "step_index": step,
                "tool_name": f"tool.step{step}",
                "input_hash": "a" * 64,
                "output_hash": "b" * 64,
                "started_at": started.isoformat(),
                "ended_at": (started + timedelta(milliseconds=50)).isoformat(),
                "duration_ms": 50,
                "status": "success",
            },
        )
        assert resp.status_code == 201, f"step {step}: {resp.text}"
        assert resp.json()["step_index"] == step


def test_state_key_constant_is_stable():
    assert RUNTIME_ACTOR_STATE_KEY == "karma_runtime_actor_id"
