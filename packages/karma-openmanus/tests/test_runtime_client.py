"""KarmaRuntimeClient unit tests."""

from __future__ import annotations

import pytest

from karma_openmanus.runtime_client import KarmaRuntimeClient


@pytest.mark.asyncio
async def test_launch_trade_order_sends_idempotency_header(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 201

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"order_id": "o1", "status": "execution_started"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, content, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("karma_openmanus.runtime_client.httpx.AsyncClient", FakeClient)

    client = KarmaRuntimeClient("http://localhost:8000", "test-key")
    await client.launch_trade_order(
        buyer_identity_id="b",
        seller_identity_id="s",
        requirement_text="test",
        idempotency_key="idem-abc",
    )
    assert captured["headers"]["Idempotency-Key"] == "idem-abc"
    assert "/v1/trade/orders/launch" in captured["url"]


@pytest.mark.asyncio
async def test_sign_with_backend_posts_correct_path(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"buyer_signature": "0xabc"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, content, headers):
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr("karma_openmanus.runtime_client.httpx.AsyncClient", FakeClient)

    client = KarmaRuntimeClient("http://localhost:8000", "test-key")
    out = await client.trade_launch_sign_with_backend(
        buyer_identity_id="b",
        seller_identity_id="s",
        requirement_text="test",
        idempotency_key="idem-b",
    )
    assert out["buyer_signature"] == "0xabc"
    assert "/v1/trade/orders/launch/sign-with-backend" in captured["url"]
