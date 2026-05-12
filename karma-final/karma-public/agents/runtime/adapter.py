"""
Karma Trust Protocol — Runtime Adapter (Public)
================================================
Wraps a generic agent runtime so every tool call is intercepted by
KarmaHookLayer and produces a signed ExecutionReceipt.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from core.hooks.hook_layer import KarmaHookLayer
from core.schemas import ExecutionReceipt


class KarmaRuntimeAgent:
    """Runtime-agnostic execution wrapper with receipt instrumentation."""

    def __init__(self, agent_id: str, hook_layer: KarmaHookLayer):
        self.agent_id = agent_id
        self.hook_layer = hook_layer
        self._receipts: dict[str, list[ExecutionReceipt]] = {}

    async def run_tool(
        self,
        task_id: str,
        tool_name: str,
        tool_fn: Callable,
        input_data: Any,
        metadata: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> tuple[Any, ExecutionReceipt]:
        result, receipt = await self.hook_layer.run_tool(
            task_id=task_id,
            tool_name=tool_name,
            tool_fn=tool_fn,
            input_data=input_data,
            metadata=metadata,
            timeout=timeout,
        )
        self._receipts.setdefault(task_id, []).append(receipt)
        return result, receipt

    def get_receipts(self, task_id: str) -> list[ExecutionReceipt]:
        return self._receipts.get(task_id, [])

    def reset(self, task_id: str) -> None:
        self._receipts.pop(task_id, None)
        self.hook_layer.reset_task(task_id)
