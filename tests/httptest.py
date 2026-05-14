"""Small HTTP helpers for integration tests (importable via pytest pythonpath)."""
from __future__ import annotations

from datetime import datetime, timedelta

from httpx import AsyncClient


async def post_minimal_contract(
    client: AsyncClient,
    *,
    task_id: str,
    client_agent_id: str,
    escrow_amount: float = 50.0,
    expected_step_count: int = 5,
    headers: dict[str, str] | None = None,
) -> dict:
    deadline = (datetime.utcnow() + timedelta(hours=3)).isoformat()
    r = await client.post(
        "/v1/contracts",
        json={
            "task_id": task_id,
            "client_agent_id": client_agent_id,
            "title": "Test contract",
            "description": "x",
            "expected_output_schema": {},
            "expected_step_count": expected_step_count,
            "escrow_amount": escrow_amount,
            "deadline_at": deadline,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()
