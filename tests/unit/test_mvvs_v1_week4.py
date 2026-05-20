"""
MVVS V1 Week 4 — Scene 5 A2A Responsibility Chain Tests
"""

import pytest
from core.mvvs_schemas import AgentSubtaskEvidence


class TestAgentSubtaskEvidence:
    def test_full_chain_pass(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            subtask_input_hash="a" * 64,
            subtask_output_hash="b" * 64,
            upstream_signature="sig-A",
            downstream_signature="sig-B",
            subtask_evidence_hash="e" * 64,
            final_output_binding_hash="f" * 64,
            responsibility_chain=["buyer-1", "seller-A", "subcontractor-B", "tool-provider-C"],
        )
        assert ase.auto_verdict() == "review"
        assert all(ase.auto_pass_checks().values())

    def test_self_delegation_fails(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-A",  # Same agent!
            subtask_price=25.0,
        )
        fail = ase.auto_fail_checks()
        assert fail["self_delegation"] is True

    def test_missing_subtask_id_fails(self):
        ase = AgentSubtaskEvidence(
            subtask_id="",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
        )
        assert ase.auto_fail_checks()["no_subtask_id"] is True

    def test_default_weight_is_one(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
        )
        assert ase.responsibility_weight == 1.0

    def test_chain_is_valid(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            responsibility_chain=["buyer", "seller", "sub-1"],
        )
        assert ase.chain_is_valid()

    def test_chain_invalid_self_ref(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            responsibility_chain=["buyer", "seller", "seller"],  # duplicate
        )
        assert not ase.chain_is_valid()

    def test_chain_too_short(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            responsibility_chain=["buyer"],  # only 1
        )
        assert not ase.chain_is_valid()

    def test_responsible_party_default(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            responsibility_chain=["buyer-1", "primary-seller", "subcontractor-X"],
        )
        assert ase.responsible_party() == "primary-seller"  # default = index 1

    def test_responsible_party_on_failure(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            responsibility_chain=["buyer-1", "primary-seller", "subcontractor-X"],
        )
        # Failure at subcontractor (index 2)
        assert ase.responsible_party(failure_point=2) == "subcontractor-X"
        # Failure at buyer (index 0)
        assert ase.responsible_party(failure_point=0) == "buyer-1"
        # Failure at seller (index 1)
        assert ase.responsible_party(failure_point=1) == "primary-seller"

    def test_empty_chain_falls_back_to_upstream(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
        )
        assert ase.responsible_party() == "agent-A"

    def test_missing_evidence_fails(self):
        ase = AgentSubtaskEvidence(
            subtask_id="sub-1",
            upstream_agent_id="agent-A",
            downstream_agent_id="agent-B",
            subtask_price=25.0,
            subtask_evidence_hash="",  # empty
        )
        assert ase.auto_fail_checks()["no_evidence"] is True
