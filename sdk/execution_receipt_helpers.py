"""P1 — helpers to build typed ExecutionReceipt extensions using canonical SHA-256 digests.

Uses the same canonical JSON serialization as ``core.hooks.hook_layer.sha256_of`` so
request/response digests align with other Karma hashing utilities.
"""
from __future__ import annotations

from typing import Any

from core.hooks.hook_layer import sha256_of
from core.schemas import (
    AgentExecutionReceiptExtension,
    ApiExecutionReceiptExtension,
    McpExecutionReceiptExtension,
)


def api_extension_from_roundtrip(
    *,
    request_body: Any,
    response_body: Any,
    http_status_code: int,
    latency_ms: int,
    error_code: str | None = None,
) -> ApiExecutionReceiptExtension:
    """Build ``kind=api`` extension from HTTP bodies (serialized to JSON for hashing)."""
    return ApiExecutionReceiptExtension(
        request_hash=sha256_of(request_body),
        response_hash=sha256_of(response_body),
        http_status_code=http_status_code,
        latency_ms=latency_ms,
        error_code=error_code,
    )


def mcp_extension_from_payloads(
    *,
    mcp_server_id: str,
    mcp_tool_name: str,
    tool_call_trace: Any,
    normalized_result: Any,
) -> McpExecutionReceiptExtension:
    """Build ``kind=mcp`` extension from a trace object and a normalized result object."""
    return McpExecutionReceiptExtension(
        mcp_server_id=mcp_server_id,
        mcp_tool_name=mcp_tool_name,
        trace_hash=sha256_of(tool_call_trace),
        result_hash=sha256_of(normalized_result),
    )


def agent_extension_from_payloads(
    *,
    model_used: str,
    tool_calls_summary: Any,
    step_log: Any,
    runtime_trace_envelope: Any,
) -> AgentExecutionReceiptExtension:
    """Build ``kind=agent`` extension from runtime summaries (no raw chain-of-thought)."""
    return AgentExecutionReceiptExtension(
        model_used=model_used,
        tool_calls_hash=sha256_of(tool_calls_summary),
        step_log_hash=sha256_of(step_log),
        runtime_trace_hash=sha256_of(runtime_trace_envelope),
    )
