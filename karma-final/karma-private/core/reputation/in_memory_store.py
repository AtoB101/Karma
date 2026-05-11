"""
PRIVATE — In-memory store for tests (appended to reputation system)
"""
from core.reputation.system import ReputationStore, _ReputationRecord
from typing import Optional


class InMemoryPrivateReputationStore(ReputationStore):
    def __init__(self):
        self._store: dict[str, _ReputationRecord] = {}

    async def save(self, record: _ReputationRecord) -> None:
        self._store[record.agent_id] = record

    async def get(self, agent_id: str) -> Optional[_ReputationRecord]:
        return self._store.get(agent_id)

    async def top_n(self, n: int) -> list[_ReputationRecord]:
        return sorted(self._store.values(), key=lambda r: r.score, reverse=True)[:n]
