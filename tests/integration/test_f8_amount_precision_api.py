"""金额精度必须在 API 入口就被拦住（线上实测：NaN 会 500、3 位小数会账实不符）。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


def _body(task_id: str, buyer: str, amount) -> dict:
    return {
        "task_id": task_id,
        "client_agent_id": buyer,
        "title": "amount precision",
        "description": "x",
        "expected_output_schema": {},
        "expected_step_count": 3,
        "escrow_amount": amount,
        "deadline_at": (datetime.utcnow() + timedelta(hours=3)).isoformat(),
    }


@pytest.mark.asyncio
async def test_chain_representable_three_decimals_is_accepted(client: AsyncClient, activate_identity):
    """12.345 有 3 位小数，链上表示得了，就不该被拦。"""
    r = await client.post("/v1/contracts", json=_body("task-f8-prec-ok", "buyer-f8-prec-ok", 12.345))
    assert r.status_code == 201, r.text
    assert abs(r.json()["escrow_amount"] - 12.345) < 1e-9


@pytest.mark.asyncio
async def test_excess_decimals_rejected(client: AsyncClient, activate_identity):
    r = await client.post(
        "/v1/contracts", json=_body("task-f8-prec-bad", "buyer-f8-prec-bad", 1.0000001)
    )
    assert r.status_code == 400, r.text
    assert "more decimals" in str(r.json()["detail"])


def _raw_body(task_id: str, buyer: str, amount_literal: str) -> str:
    """httpx 的 json= 不允许 NaN/Infinity，只能手写裸 JSON（跟真实攻击者一样）。"""
    import json

    body = _body(task_id, buyer, 1.0)
    body["escrow_amount"] = amount_literal
    return json.dumps(body)


@pytest.mark.asyncio
async def test_nan_is_a_400_not_a_500(client: AsyncClient, activate_identity):
    """NaN 能同时躲过 min 和 max 两个比较，历史上会一路走到 500。"""
    r = await client.post(
        "/v1/contracts",
        content=_raw_body("task-f8-nan", "buyer-f8-nan", "NaN"),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400, r.text
    assert "finite" in str(r.json()["detail"])


@pytest.mark.asyncio
async def test_infinity_is_rejected(client: AsyncClient, activate_identity):
    r = await client.post(
        "/v1/contracts",
        content=_raw_body("task-f8-inf", "buyer-f8-inf", "Infinity"),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400, r.text
