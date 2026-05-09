"""Minimal composable operational gates (pause / freeze) for the public runtime adapter.

These flags do not change Karma contracts; they only gate adapter-side verification
and recommended on-chain call lists used by demos and orchestration scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trusted_agent_runtime.schemas import TaskContract


@dataclass(frozen=True)
class OperationalControls:
    pause_settlement: bool = False
    pause_payout: bool = False
    pause_verification: bool = False
    frozen_task_ids: frozenset[str] = field(default_factory=frozenset)
    frozen_agent_ids: frozenset[str] = field(default_factory=frozenset)

    def verification_block_reason(self, task: TaskContract) -> str | None:
        if self.pause_verification:
            return "pause_verification"
        if task.task_id in self.frozen_task_ids:
            return "freeze_task"
        if task.agent_id in self.frozen_agent_ids:
            return "freeze_agent"
        return None

    def settlement_block_reason(self, task: TaskContract) -> str | None:
        if self.pause_settlement:
            return "pause_settlement"
        if task.task_id in self.frozen_task_ids:
            return "freeze_task"
        if task.agent_id in self.frozen_agent_ids:
            return "freeze_agent"
        return None
