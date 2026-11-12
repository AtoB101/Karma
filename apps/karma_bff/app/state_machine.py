"""Task lifecycle for OpenManus ↔ Karma BFF (server-side gate, not on-chain)."""

from __future__ import annotations

# OpenManus must not execute paid work until EXECUTE_ALLOWED.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "PLANNED": {"SNAPSHOT_RECORDED"},
    "SNAPSHOT_RECORDED": {"LOCK_PENDING"},
    # Indexer may emit LOCK_CONFIRMED once funds + bill preconditions are satisfied.
    "LOCK_PENDING": {"LOCKED", "EXECUTE_ALLOWED"},
    "LOCKED": {"EXECUTE_ALLOWED"},
    # Enter execution either after first receipt append or explicit orchestration step.
    "EXECUTE_ALLOWED": {"EXECUTING"},
    "EXECUTING": {"EVIDENCE_BUILT"},
    "EVIDENCE_BUILT": {"AWAIT_ONCHAIN"},
    "AWAIT_ONCHAIN": {"SETTLED"},
}


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in VALID_TRANSITIONS.get(from_state, set())
