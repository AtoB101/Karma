from __future__ import annotations

from datetime import datetime, timedelta

from sdk.adapters import APIExecutionAdapter, AgentRuntimeExecutionAdapter, MCPExecutionAdapter


def test_api_execution_adapter_builds_success_receipt():
    started = datetime.utcnow()
    ended = started + timedelta(milliseconds=120)

    receipt = APIExecutionAdapter.build(
        task_id="task-1",
        agent_id="agent-1",
        step_index=1,
        tool_name="http.fetch",
        request_payload={"url": "https://example.com"},
        response_payload={"status": "ok"},
        status_code=200,
        started_at=started,
        ended_at=ended,
    )

    assert receipt.status.value == "success"
    assert receipt.metadata["template"] == "api"
    assert receipt.duration_ms == 120


def test_mcp_execution_adapter_builds_failure_receipt():
    started = datetime.utcnow()
    ended = started + timedelta(milliseconds=80)

    receipt = MCPExecutionAdapter.build(
        task_id="task-2",
        agent_id="agent-2",
        step_index=2,
        mcp_server_id="notion",
        tool_name="search",
        tool_input={"query": "karma"},
        tool_output={"error": "timeout"},
        started_at=started,
        ended_at=ended,
        success=False,
        error_message="timeout",
    )

    assert receipt.status.value == "failure"
    assert receipt.tool_name == "mcp.search"
    assert receipt.metadata["template"] == "mcp"
    assert receipt.error_message == "timeout"


def test_runtime_execution_adapter_includes_trace_metadata():
    started = datetime.utcnow()
    ended = started + timedelta(milliseconds=300)

    receipt = AgentRuntimeExecutionAdapter.build(
        task_id="task-3",
        agent_id="agent-3",
        step_index=3,
        node_name="planner",
        input_payload={"goal": "draft"},
        output_payload={"plan": ["a", "b"]},
        started_at=started,
        ended_at=ended,
        success=True,
        model_used="gpt-4o",
        runtime_trace_hash="0xabc",
    )

    assert receipt.metadata["template"] == "agent_runtime"
    assert receipt.metadata["model_used"] == "gpt-4o"
    assert receipt.metadata["runtime_trace_hash"] == "0xabc"
    assert receipt.status.value == "success"

