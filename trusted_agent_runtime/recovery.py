"""Deterministic diagnostics for interrupted or crash-partial receipt chains."""

from __future__ import annotations

from trusted_agent_runtime.evidence_adapter import receipt_record_hash
from trusted_agent_runtime.schemas import ExecutionReceipt


def describe_receipt_chain_gaps(chain: list[ExecutionReceipt]) -> list[str]:
    """
    Return stable, human-readable gap reasons (empty list == no structural gaps detected).

    This does not mutate state; callers use it after reload from persistence to decide
    whether verification / bundle build should proceed.
    """
    if not chain:
        return ["empty_chain"]
    msgs: list[str] = []
    sorted_rs = sorted(chain, key=lambda r: (r.step_index, r.receipt_id))
    for i, r in enumerate(sorted_rs):
        if r.step_index != i:
            msgs.append(f"non_contiguous_step_index:expected_{i}_got_{r.step_index}")
    for i, r in enumerate(sorted_rs):
        if i == 0:
            if r.step_index == 0 and r.prev_receipt_hash not in ("",):
                msgs.append("unexpected_prev_hash_on_first_step")
            continue
        prev = sorted_rs[i - 1]
        if r.prev_receipt_hash != receipt_record_hash(prev):
            msgs.append(f"prev_hash_mismatch_at_step_{r.step_index}")
    return msgs
