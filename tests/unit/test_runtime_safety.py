from __future__ import annotations

from datetime import datetime

import pytest

from db.models.orm import CapacityModel


@pytest.mark.asyncio
async def test_runtime_safety_mode_blocks_new_lock_operations(client_sec):
    enabled = await client_sec.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": True, "reason": "manual drill", "actor_id": "sec-admin"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    blocked = await client_sec.post("/v1/capacity/safety-block-user/lock", json={"amount": 10})
    assert blocked.status_code == 503
    assert "safety mode active" in blocked.json()["detail"]

    disabled = await client_sec.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": False, "reason": "drill complete", "actor_id": "sec-admin"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    lock = await client_sec.post("/v1/capacity/safety-block-user/lock", json={"amount": 10})
    assert lock.status_code == 200
    assert lock.json()["total_locked_usdc"] == 10.0


@pytest.mark.asyncio
async def test_anchor_audit_trips_runtime_safety_mode_on_breach(client_sec, db_session):
    await client_sec.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": False, "reason": "test setup", "actor_id": "test-suite"},
    )
    db_session.add(
        CapacityModel(
            identity_id="anchor-breach-001",
            total_locked_usdc=50.0,
            total_bill_credits=80.0,
            available_credits=80.0,
            reserved_credits=0.0,
            in_progress_credits=0.0,
            confirmed_progress_credits=0.0,
            disputed_credits=0.0,
            pending_settlement_credits=0.0,
            burned_credits=0.0,
            released_credits=0.0,
            updated_at=datetime.utcnow(),
        )
    )
    await db_session.flush()

    audit = await client_sec.post("/v1/security/runtime/anchor-audit?actor_id=anchor-monitor", json={})
    assert audit.status_code == 503
    assert "anchor breach" in audit.json()["detail"]

    state = await client_sec.get("/v1/security/runtime/safety-mode")
    assert state.status_code == 200
    payload = state.json()
    assert payload["enabled"] is True
    assert payload["total_bill_credits"] > payload["total_locked_usdc"]

    disabled = await client_sec.post(
        "/v1/security/runtime/safety-mode",
        json={"enabled": False, "reason": "test cleanup", "actor_id": "test-suite"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
