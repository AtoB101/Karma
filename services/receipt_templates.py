"""P1 — Execution receipt template validation (API / MCP / Agent) + voucher task_type binding."""
from __future__ import annotations

import re
from typing import Any, Literal

from core.schemas import (
    AgentExecutionReceiptExtension,
    ApiExecutionReceiptExtension,
    ExecutionReceipt,
    ExecutionReceiptExtension,
    McpExecutionReceiptExtension,
)
from pydantic import TypeAdapter

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_extension_adapter = TypeAdapter(ExecutionReceiptExtension)


def parse_execution_receipt_extension(raw: dict[str, Any] | None) -> ExecutionReceiptExtension | None:
    if not raw:
        return None
    return _extension_adapter.validate_python(raw)


def _hex64(name: str, value: str) -> None:
    if not _HEX64.fullmatch((value or "").lower()):
        raise ValueError(f"{name} must be 64 lowercase hex chars")


def validate_extension_payloads(ext: ApiExecutionReceiptExtension | McpExecutionReceiptExtension | AgentExecutionReceiptExtension) -> None:
    """Structural checks on template-specific hash fields (no private scoring)."""
    if isinstance(ext, ApiExecutionReceiptExtension):
        _hex64("request_hash", ext.request_hash)
        _hex64("response_hash", ext.response_hash)
        return
    if isinstance(ext, McpExecutionReceiptExtension):
        _hex64("trace_hash", ext.trace_hash)
        _hex64("result_hash", ext.result_hash)
        return
    if isinstance(ext, AgentExecutionReceiptExtension):
        _hex64("tool_calls_hash", ext.tool_calls_hash)
        _hex64("step_log_hash", ext.step_log_hash)
        _hex64("runtime_trace_hash", ext.runtime_trace_hash)
        return
    raise TypeError("unsupported extension type")


def task_type_template_family(task_type: str | None) -> Literal["generic", "api", "mcp", "agent"]:
    if not task_type or not str(task_type).strip():
        return "generic"
    head = str(task_type).strip().split(".", 1)[0].lower()
    if head in ("api", "mcp", "agent"):
        return head  # type: ignore[return-value]
    return "generic"


def validate_extension_vs_task_type(
    *,
    task_type: str | None,
    receipt: ExecutionReceipt,
) -> None:
    """
    When voucher task_type declares api.* / mcp.* / agent.*, require the matching
    extension on the receipt. Generic tasks must not carry a typed extension.

    Security: deterministic protocol rule only — no fraud scoring here.
    """
    fam = task_type_template_family(task_type)
    ext = receipt.extension

    if fam == "generic":
        if ext is not None:
            raise ValueError("execution receipt extension is only allowed for task_type prefix api.* / mcp.* / agent.*")
        return

    if ext is None:
        raise ValueError(f"task_type {task_type!r} requires a matching execution receipt extension (kind={fam})")

    if fam == "api" and not isinstance(ext, ApiExecutionReceiptExtension):
        raise ValueError("task_type api.* requires extension.kind=api")
    if fam == "mcp" and not isinstance(ext, McpExecutionReceiptExtension):
        raise ValueError("task_type mcp.* requires extension.kind=mcp")
    if fam == "agent" and not isinstance(ext, AgentExecutionReceiptExtension):
        raise ValueError("task_type agent.* requires extension.kind=agent")

    validate_extension_payloads(ext)
