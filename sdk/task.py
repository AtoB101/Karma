"""
Karma SDK — TaskRunner
Convenience class for building tasks that call multiple tools in sequence.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.schemas import ExecutionReceipt, TaskContract


class TaskRunner:
    """
    Helper for executing a sequence of tool calls inside a task function.

    Usage
    -----
        async def my_task(contract, client):
            runner = TaskRunner(contract, client)
            r1 = await runner.call("tool.a", fn_a, input_a)
            r2 = await runner.call("tool.b", fn_b, input_b)
            return runner.results()

        result = await client.run_task(contract, my_task)
    """

    def __init__(self, contract: TaskContract, client: "KarmaClient"):  # type: ignore[name-defined]
        self.contract = contract
        self.client = client
        self._results: list[dict[str, Any]] = []
        self._receipts: list[ExecutionReceipt] = []

    async def call(
        self,
        tool_name: str,
        tool_fn: Callable,
        input_data: Any,
        metadata: Optional[dict] = None,
    ) -> Any:
        """Execute one tool call. Returns tool output."""
        result, receipt = await self.client.run_tool(
            task_id=self.contract.task_id,
            tool_name=tool_name,
            tool_fn=tool_fn,
            input_data=input_data,
            metadata=metadata,
        )
        self._results.append({"tool": tool_name, "output": result})
        self._receipts.append(receipt)
        return result

    def results(self) -> dict[str, Any]:
        """Return aggregated task results."""
        return {
            "steps":    self._results,
            "total":    len(self._results),
            "receipts": [r.receipt_id for r in self._receipts],
        }

    @property
    def receipts(self) -> list[ExecutionReceipt]:
        return self._receipts
