"""Detect simple buyer→worker chains that would close a directed payment cycle (KSA2-034)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import TaskStatus
from db.models.orm import SettlementModel


def _terminal_status_strings() -> tuple[str, ...]:
    return (
        TaskStatus.SETTLED.value,
        TaskStatus.REFUNDED.value,
        TaskStatus.CANCELLED.value,
    )


def worker_reaches_buyer_on_edges(edges: list[tuple[str, str]], worker_id: str, buyer_id: str) -> bool:
    """True iff there is a directed path worker_id → … → buyer_id following (client, worker) edges."""
    if worker_id == buyer_id:
        return False
    stack = [worker_id]
    seen: set[str] = set()
    while stack:
        n = stack.pop()
        if n == buyer_id:
            return True
        if n in seen:
            continue
        seen.add(n)
        for c, w in edges:
            if c == n:
                stack.append(w)
    return False


async def assert_lock_does_not_close_payment_cycle(
    db: AsyncSession,
    *,
    task_id: str,
    buyer_id: str,
    worker_id: str,
) -> None:
    """
    If an active settlement already forms a chain …→worker, locking buyer→worker can close a cycle
    (layering / round-tripping). Reject when the new edge would complete a directed cycle.
    """
    if not settings.settlement_block_buyer_worker_payment_cycle:
        return
    terminals = _terminal_status_strings()
    res = await db.execute(
        select(SettlementModel.client_agent_id, SettlementModel.worker_agent_id).where(
            SettlementModel.worker_agent_id.isnot(None),
            SettlementModel.task_id != task_id,
            SettlementModel.status.not_in(terminals),
        )
    )
    edges = [(row[0], row[1]) for row in res.all()]
    if worker_reaches_buyer_on_edges(edges, worker_id, buyer_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "locking this worker would close a directed buyer→worker payment cycle across active "
                "settlements; choose a different worker or complete/terminalize related settlements first"
            ),
        )
