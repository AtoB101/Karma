from __future__ import annotations

from trusted_agent_runtime.schemas import ExecutionReceipt


class InMemoryReceiptStore:
    """Test / demo receipt persistence only (not production)."""

    def __init__(self) -> None:
        self._by_id: dict[str, ExecutionReceipt] = {}

    def save_receipt(self, receipt: ExecutionReceipt) -> None:
        self._by_id[receipt.receipt_id] = receipt

    def get_receipt(self, receipt_id: str) -> ExecutionReceipt | None:
        return self._by_id.get(receipt_id)

    def list_receipts_by_task(self, task_id: str) -> list[ExecutionReceipt]:
        return sorted((r for r in self._by_id.values() if r.task_id == task_id), key=lambda r: r.step_index)

    def get_receipt_chain(self, task_id: str) -> list[ExecutionReceipt]:
        return self.list_receipts_by_task(task_id)
