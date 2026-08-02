"""In-memory idempotency book for settlement *intents* (adapter / orchestration layer).

On-chain idempotency remains the contracts' nonces and bill state; this ledger only
deduplicates repeated adapter submissions in a single runtime process.
"""

from __future__ import annotations


class SettlementIdempotencyBook:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def try_once(self, key: str) -> bool:
        """Return True if this is the first time `key` is recorded; False if duplicate."""
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def settlement_step_key(trace_id: str, bundle_id: str, function_name: str) -> str:
    tid = trace_id or "<no_trace>"
    return f"{tid}|{bundle_id}|{function_name}"
