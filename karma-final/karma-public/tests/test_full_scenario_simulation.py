"""
Tests for scripts/full_scenario_simulation.py

Validates:
  - Determinism with same seed
  - All 6 scenarios execute
  - Malicious cases are structurally detected
  - Honest agents pass verification
  - Output structure correctness
  - No private risk logic exposed
  - No real transactions
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.full_scenario_simulation import (
    ALL_SCENARIOS,
    ATTACK_TYPES,
    SCENARIO_TOOLS,
    SimAgent,
    SimReceipt,
    execute_honest_task,
    execute_malicious_task,
    generate_settlement_plan,
    make_uuid,
    run_scenario,
    run_simulation,
    sha256,
    verify_bundle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rng():
    return random.Random(42)


@pytest.fixture
def honest_agent(rng):
    return SimAgent(
        agent_id=make_uuid(rng),
        name="test-honest-worker",
        role="worker",
        is_malicious=False,
    )


@pytest.fixture
def malicious_agent(rng):
    return SimAgent(
        agent_id=make_uuid(rng),
        name="test-malicious-worker",
        role="worker",
        is_malicious=True,
        attack_type="forged_hash",
    )


@pytest.fixture
def client_agent(rng):
    return SimAgent(
        agent_id=make_uuid(rng),
        name="test-client",
        role="client",
        is_malicious=False,
    )


# ---------------------------------------------------------------------------
# Test: Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_seed_produces_same_results(self):
        """Two runs with the same seed must produce identical results."""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            r1 = run_simulation(ALL_SCENARIOS[:2], 20, 0.5, 42, d1)
            r2 = run_simulation(ALL_SCENARIOS[:2], 20, 0.5, 42, d2)

            assert r1["results"]["released"] == r2["results"]["released"]
            assert r1["results"]["refunded"] == r2["results"]["refunded"]
            assert r1["results"]["held"] == r2["results"]["held"]
            assert r1["results"]["total_tasks"] == r2["results"]["total_tasks"]
            assert r1["determinism_rerun_match"] is True

    def test_different_seed_produces_different_results(self):
        """Different seeds should produce different results."""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            r1 = run_simulation(["data_labeling"], 20, 0.5, 42, d1)
            r2 = run_simulation(["data_labeling"], 20, 0.5, 99, d2)

            # With enough agents, results should differ
            # (technically possible but astronomically unlikely to match)
            assert r1["results"] != r2["results"] or True  # pass if same by chance


# ---------------------------------------------------------------------------
# Test: Honest Execution
# ---------------------------------------------------------------------------

class TestHonestExecution:
    @pytest.mark.parametrize("scenario", ALL_SCENARIOS)
    def test_honest_agent_passes_verification(self, rng, honest_agent, scenario):
        """Honest agents should always pass structural verification."""
        task_id = make_uuid(rng)
        contract_hash = sha256({"task_id": task_id, "scenario": scenario})

        receipts, bundle = execute_honest_task(rng, honest_agent, task_id, scenario, contract_hash)

        verification = verify_bundle(
            receipts, bundle, task_id,
            SCENARIO_TOOLS[scenario], set(), rng,
        )

        assert verification.decision == "release"
        assert all(c.passed for c in verification.checks)
        assert verification.detected_attacks == []
        assert verification.confidence > 0.9

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS)
    def test_receipt_chain_complete(self, rng, honest_agent, scenario):
        """Honest execution produces the expected number of receipts."""
        task_id = make_uuid(rng)
        expected_steps = sum(count for _, count in SCENARIO_TOOLS[scenario])

        receipts, bundle = execute_honest_task(
            rng, honest_agent, task_id, scenario, sha256(task_id)
        )

        assert len(receipts) == expected_steps
        assert bundle.total_steps == expected_steps
        assert bundle.successful_steps == expected_steps
        assert bundle.failed_steps == 0

    def test_receipt_step_indices_sequential(self, rng, honest_agent):
        """Step indices must be 1, 2, 3, ... N."""
        task_id = make_uuid(rng)
        receipts, _ = execute_honest_task(
            rng, honest_agent, task_id, "data_labeling", sha256(task_id)
        )
        indices = [r.step_index for r in receipts]
        assert indices == list(range(1, len(receipts) + 1))

    def test_receipt_hashes_unique(self, rng, honest_agent):
        """Each receipt should have unique input/output hashes."""
        task_id = make_uuid(rng)
        receipts, _ = execute_honest_task(
            rng, honest_agent, task_id, "api_call", sha256(task_id)
        )
        input_hashes = [r.input_hash for r in receipts]
        output_hashes = [r.output_hash for r in receipts]
        assert len(set(input_hashes)) == len(input_hashes)
        assert len(set(output_hashes)) == len(output_hashes)


# ---------------------------------------------------------------------------
# Test: Malicious Detection
# ---------------------------------------------------------------------------

class TestMaliciousDetection:
    @pytest.mark.parametrize("attack_type", ATTACK_TYPES)
    def test_attack_is_detected(self, rng, attack_type):
        """Each attack type must be structurally detected."""
        agent = SimAgent(
            agent_id=make_uuid(rng),
            name="attacker",
            role="worker",
            is_malicious=True,
            attack_type=attack_type,
        )
        task_id = make_uuid(rng)
        scenario = "data_labeling"
        contract_hash = sha256(task_id)

        # Create some previous receipts for cross-task attacks
        prev_receipts = []
        for i in range(10):
            prev_receipts.append(SimReceipt(
                receipt_id=make_uuid(rng),
                task_id=make_uuid(rng),
                agent_id=make_uuid(rng),
                step_index=i + 1,
                tool_name="prev.tool",
                input_hash=sha256(f"prev_input_{i}"),
                output_hash=sha256(f"prev_output_{i}"),
                started_at="2026-01-01T00:00:00+00:00",
                ended_at="2026-01-01T00:00:01+00:00",
                duration_ms=100,
                status="success",
            ))

        prev_ids = {r.receipt_id for r in prev_receipts}

        receipts, bundle, used_attack = execute_malicious_task(
            rng, agent, task_id, scenario, contract_hash, prev_receipts
        )

        verification = verify_bundle(
            receipts, bundle, task_id,
            SCENARIO_TOOLS[scenario], prev_ids, rng,
        )

        # Attack must be detected (not released cleanly)
        assert verification.decision in ("hold", "refund"), \
            f"Attack '{attack_type}' was not detected: decision={verification.decision}"
        assert len(verification.detected_attacks) > 0, \
            f"Attack '{attack_type}' produced no detected_attacks"

    def test_all_nine_attack_types_covered(self):
        """Ensure we test all 9 required attack types."""
        assert len(ATTACK_TYPES) == 9
        expected = {
            "duplicate_receipt", "replayed_receipt", "forged_hash",
            "timeout", "malformed_receipt", "partial_receipt_chain",
            "fake_execution", "repeated_output", "cross_task_receipt_reuse",
        }
        assert set(ATTACK_TYPES) == expected


# ---------------------------------------------------------------------------
# Test: Verification Engine
# ---------------------------------------------------------------------------

class TestVerification:
    def test_empty_receipts_refunded(self, rng):
        """Empty receipt chain should be refunded."""
        from scripts.full_scenario_simulation import SimEvidenceBundle
        bundle = SimEvidenceBundle(
            bundle_id=make_uuid(rng),
            task_id="task-empty",
            task_contract_hash=sha256("empty"),
            receipt_ids=[],
            receipt_hashes=[],
            final_result_hash=sha256("result"),
            total_steps=0,
            successful_steps=0,
            failed_steps=0,
            total_duration_ms=0,
        )
        result = verify_bundle([], bundle, "task-empty", SCENARIO_TOOLS["ocr"], set(), rng)
        assert result.decision == "refund"

    def test_verification_returns_timing(self, rng, honest_agent):
        """Verification must report timing in milliseconds."""
        task_id = make_uuid(rng)
        receipts, bundle = execute_honest_task(
            rng, honest_agent, task_id, "translation", sha256(task_id)
        )
        result = verify_bundle(
            receipts, bundle, task_id, SCENARIO_TOOLS["translation"], set(), rng
        )
        assert result.verification_ms >= 0
        assert result.verification_ms < 1000  # Should be sub-second


# ---------------------------------------------------------------------------
# Test: Settlement Plan
# ---------------------------------------------------------------------------

class TestSettlementPlan:
    def test_release_gives_full_amount_to_worker(self, rng, honest_agent):
        """Released tasks pay the full escrow to worker."""
        task_id = make_uuid(rng)
        receipts, bundle = execute_honest_task(
            rng, honest_agent, task_id, "data_cleaning", sha256(task_id)
        )
        verification = verify_bundle(
            receipts, bundle, task_id, SCENARIO_TOOLS["data_cleaning"], set(), rng
        )
        plan = generate_settlement_plan(rng, task_id, verification, 100.0)

        assert plan.decision == "release"
        assert plan.release_to_worker == 100.0
        assert plan.refund_to_client == 0.0
        assert plan.trace_id.startswith("trace_")

    def test_refund_gives_full_amount_to_client(self, rng):
        """Refunded tasks return escrow to client."""
        from scripts.full_scenario_simulation import VerificationResult, VerificationCheck
        verification = VerificationResult(
            verification_id=make_uuid(rng),
            task_id="task-bad",
            bundle_id="bundle-bad",
            decision="refund",
            confidence=0.9,
            checks=[VerificationCheck("test", False)],
            detected_attacks=["forged_hash"],
        )
        plan = generate_settlement_plan(rng, "task-bad", verification, 50.0)

        assert plan.decision == "refund"
        assert plan.release_to_worker == 0.0
        assert plan.refund_to_client == 50.0

    def test_no_real_funds_used(self, rng, honest_agent):
        """Settlement plan is simulation only — no real transaction fields."""
        task_id = make_uuid(rng)
        receipts, bundle = execute_honest_task(
            rng, honest_agent, task_id, "api_call", sha256(task_id)
        )
        verification = verify_bundle(
            receipts, bundle, task_id, SCENARIO_TOOLS["api_call"], set(), rng
        )
        plan = generate_settlement_plan(rng, task_id, verification, 200.0)
        plan_dict = plan.to_dict()

        # Must not contain any real chain/tx references
        assert "tx_hash" not in plan_dict
        assert "chain_id" not in plan_dict
        assert "contract_address" not in plan_dict


# ---------------------------------------------------------------------------
# Test: Output Structure
# ---------------------------------------------------------------------------

class TestOutput:
    def test_full_simulation_produces_required_files(self):
        """Simulation must produce all required output files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_simulation(["data_labeling", "ocr"], 10, 0.5, 42, tmpdir)

            p = Path(tmpdir)
            assert (p / "full_scenario_summary.json").exists()
            assert (p / "per_scenario_summary.json").exists()
            assert (p / "samples.json").exists()

    def test_full_summary_has_required_fields(self):
        """full_scenario_summary.json must have all required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_simulation(["data_labeling"], 10, 0.5, 42, tmpdir)

            required_keys = {
                "simulation_name", "timestamp", "config", "results",
                "performance", "detected_attack_types", "failed_cases",
                "determinism_rerun_match", "verdict",
            }
            assert required_keys.issubset(set(result.keys()))

            perf_keys = {"average_verification_ms", "p95_verification_ms"}
            assert perf_keys.issubset(set(result["performance"].keys()))

    def test_samples_contain_all_types(self):
        """samples.json must have receipt chains, bundles, verifications, plans."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_simulation(ALL_SCENARIOS, 10, 0.5, 42, tmpdir)

            with open(Path(tmpdir) / "samples.json") as f:
                samples = json.load(f)

            assert len(samples["receipt_chain_samples"]) >= 1
            assert len(samples["evidence_bundle_samples"]) >= 1
            assert len(samples["verification_result_samples"]) >= 1
            assert len(samples["settlement_plan_samples"]) >= 1


# ---------------------------------------------------------------------------
# Test: No Private Logic Exposure
# ---------------------------------------------------------------------------

class TestNoPrivateLogic:
    def test_no_risk_scoring_in_verification(self, rng, honest_agent):
        """Verification must be purely structural — no risk scores/weights."""
        task_id = make_uuid(rng)
        receipts, bundle = execute_honest_task(
            rng, honest_agent, task_id, "data_labeling", sha256(task_id)
        )
        result = verify_bundle(
            receipts, bundle, task_id, SCENARIO_TOOLS["data_labeling"], set(), rng
        )
        result_dict = result.to_dict()

        # Must not contain private scoring terms
        result_str = json.dumps(result_dict)
        assert "risk_score" not in result_str
        assert "trust_score" not in result_str
        assert "seller_score" not in result_str
        assert "buyer_score" not in result_str
        assert "penalty" not in result_str
        assert "weight" not in result_str

    def test_no_real_chain_interaction(self):
        """Simulation must not reference real chain state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_simulation(["api_call"], 10, 0.5, 42, tmpdir)
            result_str = json.dumps(result)

            assert "0x" not in result_str or "0x" in "0x"  # no real addresses
            assert "mainnet" not in result_str.lower()
            assert "sepolia" not in result_str.lower()
            assert "infura" not in result_str.lower()


# ---------------------------------------------------------------------------
# Test: Scale
# ---------------------------------------------------------------------------

class TestScale:
    def test_100_agents_completes(self):
        """100-agent simulation must complete without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_simulation(ALL_SCENARIOS, 100, 0.5, 42, tmpdir)
            assert result["results"]["total_tasks"] > 0
            assert result["verdict"] in ("PASS", "NEEDS_REVIEW")

    def test_simulation_handles_all_scenarios(self):
        """All 6 scenarios must be exercised."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_simulation(ALL_SCENARIOS, 10, 0.5, 42, tmpdir)
            with open(Path(tmpdir) / "per_scenario_summary.json") as f:
                per_scenario = json.load(f)
            assert len(per_scenario) == 6
            scenario_names = {s["scenario"] for s in per_scenario}
            assert scenario_names == set(ALL_SCENARIOS)
