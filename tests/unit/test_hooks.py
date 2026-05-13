"""
Tests — Hook Layer & Receipt Generation
"""
import asyncio
from datetime import datetime, timedelta

import pytest

from core.schemas import ApiExecutionReceiptExtension, ExecutionReceipt, TaskContract, ToolStatus
from core.hooks.hook_layer import (
    InMemoryReceiptStore,
    KarmaHookLayer,
    ToolCallContext,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    return InMemoryReceiptStore()


@pytest.fixture
def hooks(store):
    return KarmaHookLayer(agent_id="test-agent-001", receipt_store=store)


@pytest.fixture
def task_contract():
    return TaskContract(
        client_agent_id="client-001",
        title="Test Task",
        description="Unit test task",
        expected_output_schema={"type": "object"},
        expected_step_count=3,
        escrow_amount=10.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )


# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------

async def _success_tool(data):
    return {"result": f"processed:{data}"}


async def _failing_tool(data):
    raise ValueError("Tool error")


async def _slow_tool(data):
    await asyncio.sleep(0.05)
    return {"slow": True}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_tool_generates_receipt(hooks, store):
    result, receipt = await hooks.run_tool(
        task_id="task-001",
        tool_name="test.tool",
        tool_fn=_success_tool,
        input_data="hello",
    )
    assert result == {"result": "processed:hello"}
    assert receipt.status == ToolStatus.SUCCESS
    assert receipt.step_index == 1
    assert receipt.task_id == "task-001"
    assert receipt.agent_id == "test-agent-001"
    assert receipt.tool_name == "test.tool"
    assert receipt.input_hash  # SHA-256 present
    assert receipt.output_hash
    assert receipt.duration_ms >= 0


@pytest.mark.asyncio
async def test_failing_tool_generates_failure_receipt(hooks, store):
    result, receipt = await hooks.run_tool(
        task_id="task-001",
        tool_name="test.fail",
        tool_fn=_failing_tool,
        input_data="data",
    )
    assert result is None
    assert receipt.status == ToolStatus.FAILURE
    assert "Tool error" in (receipt.error_message or "")


@pytest.mark.asyncio
async def test_timeout_generates_timeout_receipt(hooks):
    async def _hang(data):
        await asyncio.sleep(10)

    _, receipt = await hooks.run_tool(
        task_id="task-001",
        tool_name="test.hang",
        tool_fn=_hang,
        input_data={},
        timeout=0.05,
    )
    assert receipt.status == ToolStatus.TIMEOUT


@pytest.mark.asyncio
async def test_step_counter_increments(hooks):
    for i in range(1, 4):
        _, receipt = await hooks.run_tool(
            task_id="task-abc",
            tool_name=f"tool.{i}",
            tool_fn=_success_tool,
            input_data=i,
        )
        assert receipt.step_index == i


@pytest.mark.asyncio
async def test_reset_clears_step_counter(hooks):
    _, r1 = await hooks.run_tool("task-x", "t", _success_tool, "a")
    assert r1.step_index == 1
    hooks.reset_task("task-x")
    _, r2 = await hooks.run_tool("task-x", "t", _success_tool, "b")
    assert r2.step_index == 1


@pytest.mark.asyncio
async def test_receipts_persisted_to_store(hooks, store):
    for _ in range(3):
        await hooks.run_tool("task-persist", "tool", _success_tool, "x")
    receipts = await store.list_by_task("task-persist")
    assert len(receipts) == 3
    assert [r.step_index for r in receipts] == [1, 2, 3]


@pytest.mark.asyncio
async def test_before_hook_called(hooks):
    called = []

    async def before(ctx: ToolCallContext):
        called.append(ctx.tool_name)

    hooks.on_before(before)
    await hooks.run_tool("task-h", "my.tool", _success_tool, {})
    assert "my.tool" in called


@pytest.mark.asyncio
async def test_after_hook_called_with_receipt(hooks):
    received = []

    async def after(ctx, receipt):
        received.append(receipt)

    hooks.on_after(after)
    _, receipt = await hooks.run_tool("task-h2", "my.tool", _success_tool, {})
    assert len(received) == 1
    assert received[0].receipt_id == receipt.receipt_id


@pytest.mark.asyncio
async def test_metadata_stored_in_receipt(hooks):
    _, receipt = await hooks.run_tool(
        task_id="task-meta",
        tool_name="tool",
        tool_fn=_success_tool,
        input_data="x",
        metadata={"batch_index": 5, "source": "test"},
    )
    assert receipt.metadata["batch_index"] == 5


@pytest.mark.asyncio
async def test_run_tool_with_api_extension(hooks, store):
    ext = ApiExecutionReceiptExtension(
        request_hash="11" * 32,
        response_hash="22" * 32,
        http_status_code=200,
        latency_ms=12,
    )
    _, receipt = await hooks.run_tool(
        task_id="task-ext",
        tool_name="http.get",
        tool_fn=_success_tool,
        input_data={"a": 1},
        extension=ext,
    )
    assert receipt.extension is not None
    assert receipt.extension.kind == "api"
    assert receipt.extension.request_hash == "11" * 32
