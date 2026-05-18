"""Integration — x402 pay-and-fetch API + receipt external_payment."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from config.settings import settings
from httptest import post_minimal_contract


@pytest.mark.asyncio
async def test_x402_pay_and_fetch_persists_external_payment(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "x402_enabled", True)
    monkeypatch.setattr(settings, "receipt_require_signature", False)
    monkeypatch.setattr(settings, "ledger_require_party_actor", False)

    import api.routes.x402 as x402_route
    from core.schemas import ExecutionReceipt, ExternalPaymentRecord, ToolStatus
    from db.stores.receipt_store import PostgresReceiptStore
    import hashlib

    task_id = "task-x402-001"
    buyer = "buyer-x402"
    await post_minimal_contract(
        client,
        task_id=task_id,
        client_agent_id=buyer,
        escrow_amount=10.0,
        expected_step_count=1,
    )

    async def _mock_audit(db, **kwargs):
        now = datetime.now(timezone.utc)
        ext = ExternalPaymentRecord(
            protocol="x402",
            tx_hash="0xmock_tx_integration",
            amount_usdc=1.0,
            resource_url=kwargs["url"],
            payment_proof="mock_sig",
            network="base-sepolia",
            asset="USDC",
        )
        r = ExecutionReceipt(
            task_id=kwargs["task_id"],
            agent_id=kwargs["agent_id"],
            step_index=1,
            tool_name="x402.fetch",
            input_hash=hashlib.sha256(kwargs["url"].encode()).hexdigest(),
            output_hash=hashlib.sha256(b'{"ok":true}').hexdigest(),
            started_at=now,
            ended_at=now,
            duration_ms=1,
            status=ToolStatus.SUCCESS,
            external_payment=ext,
            signature="0xtest_x402",
        )
        await PostgresReceiptStore(db).save(r)
        return {
            "status_code": 200,
            "body_preview": '{"ok":true}',
            "payment_attempts": 1,
            "external_payment": ext.model_dump(),
            "receipt_id": r.receipt_id,
            "funding_source_updated": False,
        }

    monkeypatch.setattr(x402_route, "pay_and_fetch_with_audit", _mock_audit)

    resp = await client.post(
        "/v1/x402/pay-and-fetch",
        json={
            "task_id": task_id,
            "agent_id": buyer,
            "url": "https://api.example.com/paid",
            "max_budget_usdc": 5.0,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["external_payment"]["tx_hash"] == "0xmock_tx_integration"

    listed = await client.get(f"/v1/receipts/task/{task_id}")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) >= 1
    assert rows[0]["external_payment"]["protocol"] == "x402"
