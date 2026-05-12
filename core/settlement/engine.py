"""
Karma Trust Protocol — Settlement Interface (Public)
=====================================================
Defines the valid task lifecycle transitions and the store interface.

Decision logic (when to release vs refund vs dispute, partial split
calculations, arbitration win conditions) lives in the private runtime.

Usage
-----
    from karma.settlement import SettlementClient

    client = SettlementClient(runtime_url="https://runtime.karma.xyz")
    state  = await client.get_state(task_id)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.schemas import SettlementState, TaskStatus, VerificationResult


# ---------------------------------------------------------------------------
# Valid transition table (public reference)
# ---------------------------------------------------------------------------

LEGACY_TO_CANONICAL_STATUS: dict[TaskStatus, TaskStatus] = {
    TaskStatus.CREATED: TaskStatus.DRAFT,
    TaskStatus.LOCKED: TaskStatus.ACCEPTED,
    TaskStatus.RUNNING: TaskStatus.IN_PROGRESS,
    TaskStatus.SUBMITTED: TaskStatus.DELIVERED,
    TaskStatus.BUYER_REGRET: TaskStatus.SETTLED,
    TaskStatus.VERIFYING: TaskStatus.DELIVERED,
    TaskStatus.VERIFIED: TaskStatus.DELIVERED,
    TaskStatus.RELEASED: TaskStatus.SETTLED,
    TaskStatus.FAILED: TaskStatus.CANCELLED,
    TaskStatus.ARBITRATION: TaskStatus.ARBITRATED,
    TaskStatus.BUYER_WINS: TaskStatus.REFUNDED,
    TaskStatus.SELLER_WINS: TaskStatus.SETTLED,
    TaskStatus.PARTIAL: TaskStatus.SETTLED,
}

VALID_TRANSITIONS: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.DRAFT: [TaskStatus.PENDING, TaskStatus.ACCEPTED, TaskStatus.CANCELLED],
    TaskStatus.PENDING: [TaskStatus.ACCEPTED, TaskStatus.CANCELLED],
    TaskStatus.ACCEPTED: [TaskStatus.IN_PROGRESS, TaskStatus.DISPUTED, TaskStatus.CANCELLED],
    TaskStatus.IN_PROGRESS: [TaskStatus.PROGRESS_SUBMITTED, TaskStatus.DELIVERED, TaskStatus.SETTLED, TaskStatus.DISPUTED, TaskStatus.CANCELLED],
    TaskStatus.PROGRESS_SUBMITTED: [TaskStatus.PROGRESS_CONFIRMED, TaskStatus.DELIVERED, TaskStatus.SETTLED, TaskStatus.DISPUTED],
    TaskStatus.PROGRESS_CONFIRMED: [TaskStatus.DELIVERED, TaskStatus.DISPUTED, TaskStatus.SETTLED],
    TaskStatus.DELIVERED: [TaskStatus.SETTLED, TaskStatus.DISPUTED, TaskStatus.REFUNDED],
    TaskStatus.DISPUTED: [TaskStatus.ARBITRATED],
    TaskStatus.ARBITRATED: [TaskStatus.SETTLED, TaskStatus.REFUNDED],
    TaskStatus.SETTLED: [],
    TaskStatus.REFUNDED: [],
    TaskStatus.CANCELLED: [],
}

STATUS_ORDER: dict[TaskStatus, int] = {
    TaskStatus.DRAFT: 1,
    TaskStatus.PENDING: 2,
    TaskStatus.ACCEPTED: 3,
    TaskStatus.IN_PROGRESS: 4,
    TaskStatus.PROGRESS_SUBMITTED: 5,
    TaskStatus.PROGRESS_CONFIRMED: 6,
    TaskStatus.DELIVERED: 7,
    TaskStatus.DISPUTED: 8,
    TaskStatus.ARBITRATED: 9,
    TaskStatus.SETTLED: 10,
    TaskStatus.REFUNDED: 10,
    TaskStatus.CANCELLED: 10,
}


def canonical_task_status(status: TaskStatus | str) -> TaskStatus:
    parsed = status if isinstance(status, TaskStatus) else TaskStatus(status)
    return LEGACY_TO_CANONICAL_STATUS.get(parsed, parsed)


def is_terminal(status: TaskStatus) -> bool:
    canonical = canonical_task_status(status)
    return VALID_TRANSITIONS.get(canonical, []) == []


def can_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    from_canonical = canonical_task_status(from_status)
    to_canonical = canonical_task_status(to_status)
    return to_canonical in VALID_TRANSITIONS.get(from_canonical, [])


def is_post_accepted(status: TaskStatus | str) -> bool:
    canonical = canonical_task_status(status)
    return STATUS_ORDER.get(canonical, 0) >= STATUS_ORDER[TaskStatus.ACCEPTED]


# ---------------------------------------------------------------------------
# Settlement Store Interface
# ---------------------------------------------------------------------------

class SettlementStore(ABC):
    """Abstract persistence layer for settlement states."""

    @abstractmethod
    async def save(self, state: SettlementState) -> None: ...

    @abstractmethod
    async def get(self, task_id: str) -> Optional[SettlementState]: ...

    @abstractmethod
    async def list_by_status(self, status: TaskStatus) -> list[SettlementState]: ...


class InMemorySettlementStore(SettlementStore):
    """Development-only settlement store. Not for production."""

    def __init__(self) -> None:
        self._store: dict[str, SettlementState] = {}

    async def save(self, state: SettlementState) -> None:
        self._store[state.task_id] = state

    async def get(self, task_id: str) -> Optional[SettlementState]:
        return self._store.get(task_id)

    async def list_by_status(self, status: TaskStatus) -> list[SettlementState]:
        return [s for s in self._store.values() if s.status == status]


# ---------------------------------------------------------------------------
# Settlement Engine Interface
# ---------------------------------------------------------------------------

class SettlementEngine(ABC):
    """
    Interface for applying verification results to settlement state.
    Implementation (release/refund/dispute thresholds) is private.
    """

    @abstractmethod
    async def create(
        self,
        task_id: str,
        client_agent_id: str,
        escrow_amount: float,
        currency: str = "USD",
    ) -> SettlementState: ...

    @abstractmethod
    async def lock(self, task_id: str, worker_agent_id: str) -> SettlementState: ...

    @abstractmethod
    async def start(self, task_id: str) -> SettlementState: ...

    @abstractmethod
    async def submit(self, task_id: str) -> SettlementState: ...

    @abstractmethod
    async def apply_verification(
        self,
        task_id: str,
        result: VerificationResult,
    ) -> SettlementState: ...

    @abstractmethod
    async def fail(self, task_id: str) -> SettlementState: ...

    @abstractmethod
    async def get(self, task_id: str) -> Optional[SettlementState]: ...


# ---------------------------------------------------------------------------
# HTTP Client
# ---------------------------------------------------------------------------

class SettlementClient(SettlementEngine):
    """Calls the Karma runtime settlement API."""

    def __init__(self, runtime_url: str, api_key: str = ""):
        self.base = runtime_url.rstrip("/")
        self.headers = {"X-Karma-Api-Key": api_key} if api_key else {}

    async def _post(self, path: str, body: dict) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(f"{self.base}{path}", json=body, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def _get(self, path: str) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{self.base}{path}", headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def create(self, task_id, client_agent_id, escrow_amount, currency="USD"):
        data = await self._post("/v1/settlement/create", {
            "task_id": task_id,
            "client_agent_id": client_agent_id,
            "escrow_amount": escrow_amount,
            "currency": currency,
        })
        return SettlementState(**data)

    async def lock(self, task_id, worker_agent_id):
        data = await self._post(f"/v1/settlement/{task_id}/lock", {"worker_agent_id": worker_agent_id})
        return SettlementState(**data)

    async def pending(self, task_id):
        data = await self._post(f"/v1/settlement/{task_id}/pending", {})
        return SettlementState(**data)

    async def start(self, task_id):
        data = await self._post(f"/v1/settlement/{task_id}/start", {})
        return SettlementState(**data)

    async def submit(self, task_id):
        data = await self._post(f"/v1/settlement/{task_id}/submit", {})
        return SettlementState(**data)

    async def apply_verification(self, task_id, result):
        data = await self._post(f"/v1/settlement/{task_id}/apply-verification", result.model_dump(mode="json"))
        return SettlementState(**data)

    async def fail(self, task_id):
        data = await self._post(f"/v1/settlement/{task_id}/fail", {})
        return SettlementState(**data)

    async def get(self, task_id):
        data = await self._get(f"/v1/settlement/{task_id}")
        return SettlementState(**data)

    async def list_transitions(self, task_id, limit: int = 100):
        return await self._get(f"/v1/settlement/{task_id}/transitions?limit={limit}")
