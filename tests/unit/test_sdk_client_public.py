from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sdk.client import KarmaClient


class _MockResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _MockHTTP:
    def __init__(self, routes: dict[tuple[str, str], dict]):
        self._routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str):
        self.calls.append(("GET", url, None))
        return _MockResponse(self._routes[("GET", url)])

    async def post(self, url: str, json: dict):
        self.calls.append(("POST", url, json))
        return _MockResponse(self._routes[("POST", url)])


@pytest.mark.asyncio
async def test_capacity_sdk_methods():
    base = "http://runtime"
    identity_id = "buyer-1"
    updated_at = datetime.utcnow().isoformat()
    routes = {
        ("GET", f"{base}/v1/capacity/{identity_id}"): {
            "identity_id": identity_id,
            "total_locked_usdc": 0,
            "total_bill_credits": 0,
            "available_credits": 0,
            "reserved_credits": 0,
            "in_progress_credits": 0,
            "confirmed_progress_credits": 0,
            "disputed_credits": 0,
            "pending_settlement_credits": 0,
            "burned_credits": 0,
            "released_credits": 0,
            "updated_at": updated_at,
        },
        ("POST", f"{base}/v1/capacity/{identity_id}/lock"): {
            "identity_id": identity_id,
            "total_locked_usdc": 100,
            "total_bill_credits": 100,
            "available_credits": 100,
            "reserved_credits": 0,
            "in_progress_credits": 0,
            "confirmed_progress_credits": 0,
            "disputed_credits": 0,
            "pending_settlement_credits": 0,
            "burned_credits": 0,
            "released_credits": 0,
            "updated_at": updated_at,
        },
        ("POST", f"{base}/v1/capacity/{identity_id}/release"): {
            "identity_id": identity_id,
            "total_locked_usdc": 80,
            "total_bill_credits": 80,
            "available_credits": 80,
            "reserved_credits": 0,
            "in_progress_credits": 0,
            "confirmed_progress_credits": 0,
            "disputed_credits": 0,
            "pending_settlement_credits": 0,
            "burned_credits": 0,
            "released_credits": 20,
            "updated_at": updated_at,
        },
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    cap0 = await client.get_capacity(identity_id)
    assert cap0.identity_id == identity_id
    cap1 = await client.lock_capacity(identity_id, 100)
    assert cap1.available_credits == 100
    cap2 = await client.release_capacity(identity_id, 20)
    assert cap2.released_credits == 20

    assert ("POST", f"{base}/v1/capacity/{identity_id}/lock", {"amount": 100}) in mock_http.calls
    assert ("POST", f"{base}/v1/capacity/{identity_id}/release", {"amount": 20}) in mock_http.calls


@pytest.mark.asyncio
async def test_voucher_sdk_methods():
    base = "http://runtime"
    voucher_id = "v-1"
    expiry = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    created = datetime.utcnow().isoformat()
    voucher_payload = {
        "voucher_id": voucher_id,
        "buyer_identity_id": "buyer-1",
        "seller_identity_id": "seller-1",
        "amount": 50,
        "currency": "USDC",
        "bill_credit_amount": 50,
        "task_type": "api-call",
        "task_description_hash": "a" * 64,
        "progress_rule_hash": "b" * 64,
        "evidence_requirement_hash": "c" * 64,
        "expiry_time": expiry,
        "nonce": "n-1",
        "buyer_signature": "sig",
        "status": "created",
        "buyer_sub_identity_id": None,
        "seller_sub_identity_id": None,
        "accepted_at": None,
        "created_at": created,
    }
    verify_payload = {
        "voucher_id": voucher_id,
        "is_authentic": True,
        "is_expired": False,
        "is_used": False,
        "amount_matches": True,
        "seller_matches": True,
        "has_sufficient_capacity": True,
        "can_start": True,
        "status": "created",
    }
    accepted_payload = dict(voucher_payload)
    accepted_payload["status"] = "accepted"
    accepted_payload["accepted_at"] = created

    routes = {
        ("POST", f"{base}/v1/vouchers"): voucher_payload,
        ("GET", f"{base}/v1/vouchers/{voucher_id}"): voucher_payload,
        ("POST", f"{base}/v1/vouchers/{voucher_id}/verify"): verify_payload,
        ("POST", f"{base}/v1/vouchers/{voucher_id}/accept"): accepted_payload,
    }
    mock_http = _MockHTTP(routes)
    client = KarmaClient(agent_id="a1", runtime_url=base)
    client._http = lambda: mock_http  # type: ignore[method-assign]

    created_voucher = await client.create_voucher(
        buyer_identity_id="buyer-1",
        seller_identity_id="seller-1",
        amount=50,
        bill_credit_amount=50,
        task_type="api-call",
        task_description_hash="a" * 64,
        progress_rule_hash="b" * 64,
        evidence_requirement_hash="c" * 64,
        expiry_time=expiry,
        nonce="n-1",
        buyer_signature="sig",
    )
    assert created_voucher.voucher_id == voucher_id

    fetched_voucher = await client.get_voucher(voucher_id)
    assert fetched_voucher.seller_identity_id == "seller-1"

    verification = await client.verify_voucher(voucher_id, "seller-1", expected_amount=50)
    assert verification.can_start is True

    accepted = await client.accept_voucher(voucher_id, "seller-1")
    assert accepted.status.value == "accepted"

