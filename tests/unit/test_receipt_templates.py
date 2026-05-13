"""Unit tests for P1 execution receipt template binding."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.schemas import (
    AgentExecutionReceiptExtension,
    ApiExecutionReceiptExtension,
    ExecutionReceipt,
    McpExecutionReceiptExtension,
    ToolStatus,
)
from services.receipt_templates import (
    task_type_template_family,
    validate_extension_vs_task_type,
)


def _base_receipt(**kwargs) -> ExecutionReceipt:
    t0 = datetime.utcnow().replace(microsecond=0)
    return ExecutionReceipt(
        task_id="t1",
        agent_id="ag1",
        step_index=1,
        tool_name="x",
        input_hash="ab" * 32,
        output_hash="cd" * 32,
        started_at=t0,
        ended_at=t0 + timedelta(milliseconds=50),
        duration_ms=50,
        status=ToolStatus.SUCCESS,
        **kwargs,
    )


def test_task_type_family():
    assert task_type_template_family(None) == "generic"
    assert task_type_template_family("p0.acceptance") == "generic"
    assert task_type_template_family("api.echo") == "api"
    assert task_type_template_family("MCP.fetch") == "mcp"
    assert task_type_template_family("agent.llm") == "agent"


def test_generic_rejects_extension():
    r = _base_receipt(extension=ApiExecutionReceiptExtension(request_hash="aa" * 32, response_hash="bb" * 32, http_status_code=200, latency_ms=1))
    with pytest.raises(ValueError, match="only allowed"):
        validate_extension_vs_task_type(task_type="p0.acceptance", receipt=r)


def test_api_requires_matching_extension():
    r = _base_receipt(extension=None)
    with pytest.raises(ValueError, match="requires"):
        validate_extension_vs_task_type(task_type="api.echo", receipt=r)

    r2 = _base_receipt(
        extension=McpExecutionReceiptExtension(
            mcp_server_id="s",
            mcp_tool_name="t",
            trace_hash="11" * 32,
            result_hash="22" * 32,
        )
    )
    with pytest.raises(ValueError, match="kind=api"):
        validate_extension_vs_task_type(task_type="api.echo", receipt=r2)


def test_agent_extension_ok():
    r = _base_receipt(
        extension=AgentExecutionReceiptExtension(
            model_used="gpt-test",
            tool_calls_hash="11" * 32,
            step_log_hash="22" * 32,
            runtime_trace_hash="33" * 32,
        )
    )
    validate_extension_vs_task_type(task_type="agent.workflow", receipt=r)
