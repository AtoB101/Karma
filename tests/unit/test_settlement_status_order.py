"""Contract tests for the settlement status order and the guard it feeds.

``core.settlement.engine.is_post_accepted`` is the single predicate behind the
immutable-field guard in ``db.stores.settlement_store.PostgresSettlementStore.save``:
once a settlement has been accepted, ``escrow_amount`` / ``currency`` /
``client_agent_id`` / ``worker_agent_id`` may no longer change. That guard is
only as good as ``STATUS_ORDER`` -- a missing key makes ``dict.get`` fall back
to 0 and the guard silently switches itself off for that status.

Historically ``SETTLED`` was missing from the table and ``FROZEN`` was pinned to
0, so the belt was off for the two most money-relevant states. These tests pin
the invariant instead of the numbers, so renumbering stays safe but dropping a
state does not.
"""
from __future__ import annotations

from core.schemas import TaskStatus
from core.settlement.engine import (
    LEGACY_TO_CANONICAL_STATUS,
    STATUS_ORDER,
    VALID_TRANSITIONS,
    can_transition,
    canonical_task_status,
    is_post_accepted,
    is_terminal,
)

#: Statuses that legitimately exist *before* the worker is locked in. Anything
#: else must be classified as post-accepted.
PRE_ACCEPTED = {TaskStatus.DRAFT, TaskStatus.PENDING, TaskStatus.AUTHORIZED}


def _canonical_states() -> set[TaskStatus]:
    """Every canonical (non-legacy) status the settlement table can hold."""
    return {
        s for s in TaskStatus
        if LEGACY_TO_CANONICAL_STATUS.get(s, s) == s
    }


#: The only canonical statuses allowed to be absent from STATUS_ORDER: they are
#: pre-acceptance states whose ``.get(..., 0)`` fallback is the correct answer.
#: Anything else missing would silently disable the immutable-field guard.
ALLOWED_MISSING = {TaskStatus.AUTHORIZED}


def test_status_order_covers_every_canonical_status():
    missing = {
        s for s in _canonical_states()
        if s not in STATUS_ORDER and s not in ALLOWED_MISSING
    }
    assert missing == set(), (
        "STATUS_ORDER is missing "
        f"{sorted(s.value for s in missing)}; .get() would fall back to 0 and "
        "turn the immutable-field guard off for them"
    )


def test_only_pre_acceptance_statuses_are_absent():
    absent = {s for s in _canonical_states() if s not in STATUS_ORDER}
    assert absent == ALLOWED_MISSING, sorted(s.value for s in absent)


def test_post_accepted_accepts_every_reachable_status():
    """BFS from ACCEPTED: every status reachable on a legal edge is post-accepted.

    This is the invariant the guard relies on. If someone adds a new edge or a
    new canonical status without a STATUS_ORDER entry, this fails.
    """
    seen = {TaskStatus.ACCEPTED}
    frontier = [canonical_task_status(TaskStatus.ACCEPTED)]
    while frontier:
        current = frontier.pop()
        for nxt in VALID_TRANSITIONS.get(current, []):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    not_post_accepted = sorted(
        s.value for s in seen if not is_post_accepted(s)
    )
    assert not_post_accepted == [], (
        "statuses reachable from ACCEPTED are treated as pre-acceptance, so the "
        f"immutable-field guard is off for them: {not_post_accepted}"
    )


def test_pre_acceptance_statuses_are_not_post_accepted():
    for status in PRE_ACCEPTED:
        assert not is_post_accepted(status), status


def test_terminal_states_are_post_accepted():
    for status in (
        TaskStatus.SETTLED,
        TaskStatus.REFUNDED,
        TaskStatus.CANCELLED,
        TaskStatus.PARTIALLY_SETTLED,
        TaskStatus.FROZEN,
    ):
        assert is_post_accepted(status), f"{status.value} must be post-accepted"


def test_legacy_aliases_inherit_the_guard():
    """Legacy rows must not lose the guard through the canonical mapping."""
    for legacy in (
        TaskStatus.RELEASED,
        TaskStatus.SELLER_WINS,
        TaskStatus.PARTIAL,
        TaskStatus.BUYER_REGRET,
    ):
        assert canonical_task_status(legacy) is TaskStatus.SETTLED
        assert is_post_accepted(legacy), legacy
    for legacy in (TaskStatus.LOCKED, TaskStatus.RUNNING, TaskStatus.VERIFIED):
        assert is_post_accepted(legacy), legacy
    assert not is_post_accepted(TaskStatus.CREATED)


def test_status_order_is_strictly_increasing_per_lifecycle():
    """The table must not lie about order with duplicate numbers."""
    accepted = STATUS_ORDER[TaskStatus.ACCEPTED]
    assert STATUS_ORDER[TaskStatus.DRAFT] < STATUS_ORDER[TaskStatus.PENDING] < accepted
    assert STATUS_ORDER[TaskStatus.DELIVERED] > accepted
    assert STATUS_ORDER[TaskStatus.ARBITRATED] > STATUS_ORDER[TaskStatus.DISPUTED]
    assert STATUS_ORDER[TaskStatus.SETTLED] > STATUS_ORDER[TaskStatus.DELIVERED]
    for lower, higher in (
        (TaskStatus.PROGRESS_CONFIRMED, TaskStatus.AUTO_CONFIRMED),
        (TaskStatus.ARBITRATED, TaskStatus.PARTIALLY_SETTLED),
        (TaskStatus.PARTIALLY_SETTLED, TaskStatus.SETTLED),
        (TaskStatus.SETTLED, TaskStatus.FROZEN),
    ):
        assert STATUS_ORDER[lower] < STATUS_ORDER[higher], (lower, higher)


def test_settled_has_no_route_back_into_dispute():
    """Regression: the money-terminal states must not reopen a dispute."""
    for terminal in (TaskStatus.SETTLED, TaskStatus.REFUNDED, TaskStatus.CANCELLED):
        assert not can_transition(terminal, TaskStatus.DISPUTED)
    assert can_transition(TaskStatus.SETTLED, TaskStatus.FROZEN)


def test_is_terminal_matches_the_edge_table():
    """``is_terminal`` is defined by "no outgoing edge", not by the docstring."""
    for status, edges in VALID_TRANSITIONS.items():
        assert is_terminal(status) == (edges == []), status
