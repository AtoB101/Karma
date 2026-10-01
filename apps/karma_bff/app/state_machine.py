"""Task lifecycle for OpenManus <-> Karma BFF (server-side gate, not on-chain).

Invariants this table has to keep:

* OpenManus must not execute paid work until ``EXECUTE_ALLOWED``.
* Every non-terminal state has a way out, *including* a failure exit, so a
  broken trace can never sit in the table forever waiting for a transition that
  does not exist.
* ``SETTLED`` / ``FAILED`` / ``CANCELLED`` have no out-edges at all. They are
  listed explicitly (with an empty set) so ``is_terminal`` is a table lookup
  rather than an accident of a missing key.
* ``CANCELLED`` is only reachable *before* funds are locked: cancelling a task
  whose escrow is already committed would claim something the chain does not
  agree with. After ``LOCKED`` the only way out, other than finishing, is
  ``FAILED`` -- which is an orchestration verdict and moves no money.

``FAILED`` never moves money. Escrow is driven exclusively by chain events
(``POST /v1/webhooks/chain``) and the settlement API; this table only decides
whether the orchestrator may keep going.
"""

from __future__ import annotations

# OpenManus must not execute paid work until EXECUTE_ALLOWED.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "PLANNED": {"SNAPSHOT_RECORDED", "CANCELLED", "FAILED"},
    "SNAPSHOT_RECORDED": {"LOCK_PENDING", "CANCELLED", "FAILED"},
    # Indexer may emit LOCK_CONFIRMED once funds + bill preconditions are satisfied.
    "LOCK_PENDING": {"LOCKED", "EXECUTE_ALLOWED", "CANCELLED", "FAILED"},
    "LOCKED": {"EXECUTE_ALLOWED", "FAILED"},
    # Enter execution either after first receipt append or explicit orchestration step.
    "EXECUTE_ALLOWED": {"EXECUTING", "FAILED"},
    "EXECUTING": {"EVIDENCE_BUILT", "FAILED"},
    "EVIDENCE_BUILT": {"AWAIT_ONCHAIN", "FAILED"},
    "AWAIT_ONCHAIN": {"SETTLED", "FAILED"},
    # Final states -- no outgoing edge, listed so the table says so out loud.
    "SETTLED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}

#: The one exit every non-terminal state must have (orchestration only).
FAILURE_STATE = "FAILED"

#: Abort before any funds are locked.
CANCEL_STATE = "CANCELLED"

#: States with no outgoing edge: nothing moves a task out of these.
TERMINAL_STATES = frozenset({"SETTLED", FAILURE_STATE, CANCEL_STATE})

#: The state whose job is to let OpenManus run.
EXECUTE_STATE = "EXECUTE_ALLOWED"


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in VALID_TRANSITIONS.get(from_state, set())


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES
