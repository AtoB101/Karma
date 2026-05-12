"""
Karma SDK — Execution receipt adapters.
Builds standardized ExecutionReceipt payloads for API, MCP, and agent-runtime calls.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from core.schemas import ExecutionReceipt, ToolStatus


def _sha256(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _status_from_success(success: bool) -> ToolStatus:
    return ToolStatus.SUCCESS if success else ToolStatus.FAILURE


class APIExecutionAdapter:
    """Adapter for HTTP/API provider calls."""

    @staticmethod
    def build(
        *,
        task_id: str,
        agent_id: str,
        step_index: int,
        tool_name: str,
        request_payload: Any,
        response_payload: Any,
        status_code: int,
        started_at: datetime,
        ended_at: datetime,
        error_message: str | None = None,
        provider_signature: str | None = None,
    ) -> ExecutionReceipt:
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        success = 200 <= status_code < 300
        return ExecutionReceipt(
            task_id=task_id,
            agent_id=agent_id,
            step_index=step_index,
            tool_name=tool_name,
            input_hash=_sha256(request_payload),
            output_hash=_sha256(response_payload),
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            status=_status_from_success(success),
            error_message=error_message if not success else None,
            metadata={
                "template": "api",
                "status_code": status_code,
                "request_hash": _sha256(request_payload),
                "response_hash": _sha256(response_payload),
                "provider_signature": provider_signature,
            },
        )


class MCPExecutionAdapter:
    """Adapter for MCP tool calls."""

    @staticmethod
    def build(
        *,
        task_id: str,
        agent_id: str,
        step_index: int,
        mcp_server_id: str,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        started_at: datetime,
        ended_at: datetime,
        success: bool,
        runtime_receipt: str | None = None,
        error_message: str | None = None,
    ) -> ExecutionReceipt:
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        return ExecutionReceipt(
            task_id=task_id,
            agent_id=agent_id,
            step_index=step_index,
            tool_name=f"mcp.{tool_name}",
            input_hash=_sha256(tool_input),
            output_hash=_sha256(tool_output),
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            status=_status_from_success(success),
            error_message=error_message if not success else None,
            metadata={
                "template": "mcp",
                "mcp_server_id": mcp_server_id,
                "tool_name": tool_name,
                "input_digest": _sha256(tool_input),
                "output_digest": _sha256(tool_output),
                "result_hash": _sha256({"output": tool_output, "ok": success}),
                "mcp_runtime_receipt": runtime_receipt,
            },
        )


class AgentRuntimeExecutionAdapter:
    """Adapter for internal agent runtime/workflow steps."""

    @staticmethod
    def build(
        *,
        task_id: str,
        agent_id: str,
        step_index: int,
        node_name: str,
        input_payload: Any,
        output_payload: Any,
        started_at: datetime,
        ended_at: datetime,
        success: bool,
        model_used: str | None = None,
        runtime_trace_hash: str | None = None,
        error_message: str | None = None,
    ) -> ExecutionReceipt:
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        return ExecutionReceipt(
            task_id=task_id,
            agent_id=agent_id,
            step_index=step_index,
            tool_name=f"runtime.{node_name}",
            input_hash=_sha256(input_payload),
            output_hash=_sha256(output_payload),
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            status=_status_from_success(success),
            error_message=error_message if not success else None,
            metadata={
                "template": "agent_runtime",
                "node_name": node_name,
                "model_used": model_used,
                "runtime_trace_hash": runtime_trace_hash,
                "input_digest": _sha256(input_payload),
                "output_digest": _sha256(output_payload),
            },
        )

