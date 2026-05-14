"""Small HTTP helpers for integration tests (importable via pytest pythonpath)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


async def post_success_execution_receipt(
    client: AsyncClient,
    *,
    task_id: str,
    agent_id: str,
    step_index: int = 1,
    headers: dict[str, str] | None = None,
) -> dict:
    """One signed SUCCESS execution receipt (for settlement release guards in tests)."""
    from core.schemas import ExecutionReceipt, ToolStatus
    from services.signing import signing_service

    now = datetime.now(timezone.utc)
    receipt = ExecutionReceipt(
        task_id=task_id,
        agent_id=agent_id,
        step_index=step_index,
        tool_name="tool.step",
        input_hash="a" * 64,
        output_hash="b" * 64,
        started_at=now,
        ended_at=now + timedelta(milliseconds=50),
        duration_ms=50,
        status=ToolStatus.SUCCESS,
    )
    receipt.signature = signing_service.sign_receipt(receipt)
    r = await client.post("/v1/receipts", json=receipt.model_dump(mode="json"), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
