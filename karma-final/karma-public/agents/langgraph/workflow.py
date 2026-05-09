"""
Karma Trust Protocol — LangGraph Adapter (Public)
==================================================
A typed LangGraph state graph that wires the Karma task lifecycle:

    create_contract → lock_escrow → run_agent
        → build_bundle → verify → settle → update_reputation

Each node calls the appropriate Karma interface. The actual decision
logic (verify, settle) is delegated to the private runtime via HTTP.

Usage
-----
    from karma.agents.langgraph import build_karma_graph

    graph  = build_karma_graph(settlement, verification, builder, agent)
    result = await graph.ainvoke(initial_state)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from core.schemas import (
    EvidenceBundle,
    SettlementState,
    TaskContract,
    TaskStatus,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class KarmaTaskState(TypedDict):
    """Typed state passed between LangGraph nodes."""

    # Identifiers
    task_id: str
    agent_id: str

    # Core objects (populated progressively)
    task_contract: Optional[TaskContract]
    settlement: Optional[SettlementState]
    evidence_bundle: Optional[EvidenceBundle]
    verification_result: Optional[VerificationResult]
    final_result: Optional[Any]

    # Runtime tracking
    error: Optional[str]
    completed_at: Optional[str]


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------

def make_lock_node(settlement_engine) -> Any:
    async def lock_escrow(state: KarmaTaskState) -> KarmaTaskState:
        contract = state["task_contract"]
        assert contract is not None

        settlement = await settlement_engine.create(
            task_id=contract.task_id,
            client_agent_id=contract.client_agent_id,
            escrow_amount=contract.escrow_amount,
            currency=contract.currency,
        )
        settlement = await settlement_engine.lock(
            task_id=contract.task_id,
            worker_agent_id=state["agent_id"],
        )
        return {**state, "settlement": settlement}

    return lock_escrow


def make_run_node(karma_agent, task_runner) -> Any:
    """
    task_runner: async callable(task_contract) → final_result
    Uses karma_agent to call tools inside.
    """
    async def run_agent(state: KarmaTaskState) -> KarmaTaskState:
        contract = state["task_contract"]
        assert contract is not None

        await karma_agent.hook_layer.receipt_store.list_by_task(contract.task_id)

        try:
            final_result = await task_runner(contract, karma_agent)
            return {**state, "final_result": final_result, "error": None}
        except Exception as exc:
            return {**state, "final_result": None, "error": str(exc)}

    return run_agent


def make_bundle_node(bundle_builder) -> Any:
    async def build_bundle(state: KarmaTaskState) -> KarmaTaskState:
        contract = state["task_contract"]
        final_result = state.get("final_result") or {}
        assert contract is not None

        bundle = await bundle_builder.build(contract, final_result)
        return {**state, "evidence_bundle": bundle}

    return build_bundle


def make_verify_node(verification_engine, settlement_engine) -> Any:
    async def verify(state: KarmaTaskState) -> KarmaTaskState:
        bundle = state["evidence_bundle"]
        contract = state["task_contract"]
        assert bundle and contract

        await settlement_engine.submit(contract.task_id)
        result = await verification_engine.verify(bundle, contract)
        return {**state, "verification_result": result}

    return verify


def make_settle_node(settlement_engine) -> Any:
    async def settle(state: KarmaTaskState) -> KarmaTaskState:
        result = state["verification_result"]
        contract = state["task_contract"]
        assert result and contract

        settlement = await settlement_engine.apply_verification(contract.task_id, result)
        return {
            **state,
            "settlement": settlement,
            "completed_at": datetime.utcnow().isoformat(),
        }

    return settle


def make_fail_node(settlement_engine) -> Any:
    async def handle_failure(state: KarmaTaskState) -> KarmaTaskState:
        contract = state["task_contract"]
        if contract:
            settlement = await settlement_engine.fail(contract.task_id)
            return {**state, "settlement": settlement}
        return state

    return handle_failure


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def route_after_run(state: KarmaTaskState) -> str:
    """Route to failure node if agent errored, else continue to bundle."""
    return "handle_failure" if state.get("error") else "build_bundle"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_karma_graph(
    settlement_engine,
    verification_engine,
    bundle_builder,
    karma_agent,
    task_runner,
) -> StateGraph:
    """
    Build and compile the full Karma task LangGraph.

    Parameters
    ----------
    settlement_engine:   SettlementEngine implementation.
    verification_engine: VerificationEngine implementation.
    bundle_builder:      EvidenceBundleBuilder instance.
    karma_agent:         KarmaOpenManusAgent instance.
    task_runner:         async fn(contract, agent) → result
    """
    graph = StateGraph(KarmaTaskState)

    graph.add_node("lock_escrow",    make_lock_node(settlement_engine))
    graph.add_node("run_agent",      make_run_node(karma_agent, task_runner))
    graph.add_node("build_bundle",   make_bundle_node(bundle_builder))
    graph.add_node("verify",         make_verify_node(verification_engine, settlement_engine))
    graph.add_node("settle",         make_settle_node(settlement_engine))
    graph.add_node("handle_failure", make_fail_node(settlement_engine))

    graph.set_entry_point("lock_escrow")

    graph.add_edge("lock_escrow",  "run_agent")
    graph.add_conditional_edges("run_agent", route_after_run)
    graph.add_edge("build_bundle", "verify")
    graph.add_edge("verify",       "settle")
    graph.add_edge("settle",       END)
    graph.add_edge("handle_failure", END)

    return graph.compile()
