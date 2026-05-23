"""Predefined state transition maps and per-scenario allowed paths.

Every transition must be in BILLING_STATE_TRANSITIONS to be honoured by the
ImmutableBillingStateMachine.  Transitions outside the map are rejected, and
the attempt is logged as a CRITICAL security event.

Per-scenario allowed paths further restrict which subset of the global
transition map is legal for a specific scenario.
"""

from typing import FrozenSet, Dict, List

from packages.karma_billing.schema import BillingState, ScenarioType

# ── Global Transition Map ─────────────────────────────────────────────────────

# For each current state, which target states are reachable in a single transition.
# This map is exhaustive — any transition not listed here is illegal.
BILLING_STATE_TRANSITIONS: Dict[BillingState, FrozenSet[BillingState]] = {
    BillingState.INITIATED: frozenset({
        BillingState.INTENT_RECEIVED,
    }),
    BillingState.INTENT_RECEIVED: frozenset({
        BillingState.INTENT_VALIDATED,
    }),
    BillingState.INTENT_VALIDATED: frozenset({
        BillingState.DELEGATION_ACCEPTED,
        BillingState.BID_EVALUATING,
        BillingState.PIPELINE_STAGING,
    }),
    BillingState.DELEGATION_ACCEPTED: frozenset({
        BillingState.TASK_STARTED,
    }),
    BillingState.TASK_STARTED: frozenset({
        BillingState.STEP_IN_PROGRESS,
        BillingState.TASK_COMPLETED,
    }),
    BillingState.STEP_IN_PROGRESS: frozenset({
        BillingState.STEP_COMPLETED,
        BillingState.TASK_COMPLETED,
    }),
    BillingState.STEP_COMPLETED: frozenset({
        BillingState.STEP_IN_PROGRESS,
        BillingState.TASK_COMPLETED,
    }),
    BillingState.TASK_COMPLETED: frozenset({
        BillingState.INVOICE_GENERATED,
    }),
    BillingState.BID_EVALUATING: frozenset({
        BillingState.BID_ACCEPTED,
        BillingState.INVOICE_GENERATED,
    }),
    BillingState.BID_ACCEPTED: frozenset({
        BillingState.TASK_STARTED,
    }),
    BillingState.PIPELINE_STAGING: frozenset({
        BillingState.TASK_STARTED,
        BillingState.STEP_IN_PROGRESS,
        BillingState.TASK_COMPLETED,
    }),
    BillingState.INVOICE_GENERATED: frozenset({
        BillingState.PAYMENT_AUTHORIZED,
        BillingState.PAYMENT_SETTLING,
    }),
    BillingState.PAYMENT_AUTHORIZED: frozenset({
        BillingState.PAYMENT_PENDING,
        BillingState.PAYMENT_SETTLING,
    }),
    BillingState.PAYMENT_PENDING: frozenset({
        BillingState.PAYMENT_SETTLING,
    }),
    BillingState.PAYMENT_SETTLING: frozenset({
        BillingState.SETTLED,
        BillingState.REFUND_PENDING,
    }),
    BillingState.REFUND_PENDING: frozenset({
        BillingState.SETTLED,
    }),
    BillingState.SETTLED: frozenset({
        # Terminal state — no further transitions allowed
    }),
}


# ── States That REQUIRE Immediate Anchoring ───────────────────────────────────

# When the state machine enters one of these states, the billing runtime MUST
# trigger an on-chain anchor before proceeding further.
REQUIRE_IMMEDIATE_ANCHOR: FrozenSet[BillingState] = frozenset({
    BillingState.INTENT_VALIDATED,
    BillingState.TASK_COMPLETED,
    BillingState.INVOICE_GENERATED,
    BillingState.PAYMENT_AUTHORIZED,
    BillingState.SETTLED,
    BillingState.REFUND_PENDING,
})


# ── Per-Scenario Allowed State Paths ──────────────────────────────────────────

# Each scenario specifies its own ordered state path(s).
# The state machine validates that every transition stays on the scenario's path.

ALLOWED_STATE_PATHS: Dict[ScenarioType, List[List[BillingState]]] = {
    # S1 — Simple delegation: main path + branch sub-paths for all valid forks
    ScenarioType.S1_DELEGATION: [
        # Main path (with STEP_COMPLETED and PAYMENT_PENDING)
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.STEP_IN_PROGRESS,
            BillingState.STEP_COMPLETED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_PENDING,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
        # Branch: Step loop (STEP_COMPLETED → STEP_IN_PROGRESS for multi-step tasks)
        [BillingState.STEP_COMPLETED, BillingState.STEP_IN_PROGRESS],
        # Branch: Direct completion (STEP_IN_PROGRESS → TASK_COMPLETED, single-step tasks)
        [BillingState.STEP_IN_PROGRESS, BillingState.TASK_COMPLETED],
        # Branch: Step completed then task completed
        [BillingState.STEP_COMPLETED, BillingState.TASK_COMPLETED],
        # Branch: Direct settlement (PAYMENT_AUTHORIZED → PAYMENT_SETTLING, skip PENDING)
        [BillingState.PAYMENT_AUTHORIZED, BillingState.PAYMENT_SETTLING],
    ],
    # S2 — Bidding: branches at INTENT_VALIDATED → BID_EVALUATING
    ScenarioType.S2_BIDDING: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.BID_EVALUATING,
            BillingState.BID_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.STEP_IN_PROGRESS,
            BillingState.STEP_COMPLETED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
        # Alternate path: BID_EVALUATING → INVOICE_GENERATED (no acceptance)
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.BID_EVALUATING,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
    # S3 — Pipeline: multiple stage loops
    ScenarioType.S3_PIPELINE: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.PIPELINE_STAGING,
            BillingState.STEP_IN_PROGRESS,
            BillingState.STEP_COMPLETED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
    # S4 — Multi-Delegation: similar to S1 but may have parallel subtasks
    ScenarioType.S4_MULTI_DELEGATION: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.STEP_IN_PROGRESS,
            BillingState.STEP_COMPLETED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
    # S5 — Data Marketplace
    ScenarioType.S5_DATA: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
    # S6 — Conditional
    ScenarioType.S6_CONDITIONAL: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
    # S7 — Recurring
    ScenarioType.S7_RECURRING: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
    # S8 — Dispute: includes REFUND_PENDING path
    ScenarioType.S8_DISPUTE: [
        # Normal resolution path
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
        # Dispute → refund path
        [
            BillingState.PAYMENT_SETTLING,
            BillingState.REFUND_PENDING,
            BillingState.SETTLED,
        ],
    ],
    # S9 — Intent-Based
    ScenarioType.S9_INTENT: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
    # S10 — Cross-Chain
    ScenarioType.S10_CROSS_CHAIN: [
        [
            BillingState.INITIATED,
            BillingState.INTENT_RECEIVED,
            BillingState.INTENT_VALIDATED,
            BillingState.DELEGATION_ACCEPTED,
            BillingState.TASK_STARTED,
            BillingState.TASK_COMPLETED,
            BillingState.INVOICE_GENERATED,
            BillingState.PAYMENT_AUTHORIZED,
            BillingState.PAYMENT_SETTLING,
            BillingState.SETTLED,
        ],
    ],
}


def get_legal_targets(from_state: BillingState) -> FrozenSet[BillingState]:
    """Return the set of legal target states from a given state."""
    return BILLING_STATE_TRANSITIONS.get(from_state, frozenset())


def is_transition_allowed(
    scenario: ScenarioType,
    from_state: BillingState,
    to_state: BillingState,
) -> bool:
    """Check whether a transition is allowed for a specific scenario.

    The transition must appear in both:
    1.  The global BILLING_STATE_TRANSITIONS map
    2.  At least one of the scenario's allowed state paths
    """
    # Global check
    legal_targets = BILLING_STATE_TRANSITIONS.get(from_state)
    if legal_targets is None or to_state not in legal_targets:
        return False

    # Scenario path check
    paths = ALLOWED_STATE_PATHS.get(scenario)
    if paths is None:
        return False

    for path in paths:
        try:
            idx = path.index(from_state)
            if idx + 1 < len(path) and path[idx + 1] == to_state:
                return True
        except ValueError:
            continue

    return False
