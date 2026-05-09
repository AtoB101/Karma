from __future__ import annotations

from trusted_agent_runtime.hashing import canonical_json_bytes, sha256_hex
from trusted_agent_runtime.schemas import ExecutionReceipt


def _receipt_fingerprint(receipt: ExecutionReceipt) -> str:
    return sha256_hex(canonical_json_bytes(receipt.to_canonical_dict()))


class InMemoryReceiptStore:
    """Test / demo receipt persistence only (not production)."""

    def __init__(self) -> None:
        self._by_id: dict[str, ExecutionReceipt] = {}

    def save_receipt(self, receipt: ExecutionReceipt) -> None:
        existing = self._by_id.get(receipt.receipt_id)
        if existing is not None:
            if _receipt_fingerprint(existing) != _receipt_fingerprint(receipt):
                raise ValueError(f"receipt_id collision with different payload: {receipt.receipt_id}")
            return
        self._by_id[receipt.receipt_id] = receipt

    def get_receipt(self, receipt_id: str) -> ExecutionReceipt | None:
        return self._by_id.get(receipt_id)

    def list_receipts_by_task(self, task_id: str) -> list[ExecutionReceipt]:
        return sorted((r for r in self._by_id.values() if r.task_id == task_id), key=lambda r: r.step_index)

    def get_receipt_chain(self, task_id: str) -> list[ExecutionReceipt]:
        return self.list_receipts_by_task(task_id)
