"""
Karma Trust Protocol — OpenManus Adapter (Public)
==================================================
Wraps an OpenManus agent so every tool call it makes is intercepted
by the KarmaHookLayer and produces a signed ExecutionReceipt.

Usage
-----
    from karma.agents.openmanus import KarmaOpenManusAgent

    agent = KarmaOpenManusAgent(
        agent_id="worker-001",
        hook_layer=hooks,
    )
    result, receipts = await agent.run_task(task_id, task_spec)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from core.schemas import ExecutionReceipt
from core.hooks.hook_layer import ExecutionReceiptExtensionConcrete, KarmaHookLayer


class KarmaOpenManusAgent:
    """
    Drop-in wrapper for an OpenManus agent that instruments every tool call.

    Parameters
    ----------
    agent_id:    Unique identifier for this agent in the Karma network.
    hook_layer:  Configured KarmaHookLayer instance.
    """

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
        extension: Optional[ExecutionReceiptExtensionConcrete] = None,
    ) -> tuple[Any, ExecutionReceipt]:
        """
        Execute a single tool call with Karma instrumentation.

        Returns (result, receipt).
        """
        result, receipt = await self.hook_layer.run_tool(
            task_id=task_id,
            tool_name=tool_name,
            tool_fn=tool_fn,
            input_data=input_data,
            metadata=metadata,
            timeout=timeout,
            extension=extension,
        )
        self._receipts.setdefault(task_id, []).append(receipt)
        return result, receipt

    def get_receipts(self, task_id: str) -> list[ExecutionReceipt]:
        """Return all receipts collected for a task so far."""
        return self._receipts.get(task_id, [])

    def reset(self, task_id: str) -> None:
        """Clear collected receipts and step counter for a task."""
        self._receipts.pop(task_id, None)
        self.hook_layer.reset_task(task_id)
