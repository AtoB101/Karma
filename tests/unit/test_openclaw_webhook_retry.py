"""OpenClaw webhook delivery retries (P1-6)."""

from __future__ import annotations

import pytest

from config.settings import settings
from services import openclaw_webhook as ow


@pytest.mark.asyncio
async def test_webhook_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_webhook_url", "https://example.com/hook")
    monkeypatch.setattr(settings, "openclaw_webhook_secret", "")
    monkeypatch.setattr(settings, "openclaw_webhook_max_retries", 3)

    calls = {"n": 0}

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("transient")
            return FakeResp()

    monkeypatch.setattr(ow.httpx, "AsyncClient", FakeClient)

    async def _noop_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(ow.asyncio, "sleep", _noop_sleep)

    await ow._post_webhook({"event_type": "test.event", "payload": {}})
    assert calls["n"] == 3
