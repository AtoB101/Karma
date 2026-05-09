from __future__ import annotations

import json
import unittest
from pathlib import Path

from trusted_agent_runtime.schemas import ExecutionReceipt, TaskContract
from trusted_agent_runtime.stress_runner import (
    StressConfig,
    _duplicate_extra_count,
    _replay_event_count,
    run_stress,
)


class TrustedAgentStressTests(unittest.TestCase):
    def test_replay_event_count(self) -> None:
        t = TaskContract(task_id="t", agent_id="a", runtime_id="r", description="")
        r1 = ExecutionReceipt(
            receipt_id="id-a",
            task_id=t.task_id,
            agent_id=t.agent_id,
            runtime_id=t.runtime_id,
            step_index=0,
            tool_name="x",
            input_hash="h1",
            output_hash="h2",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash="",
        )
        r2 = ExecutionReceipt(
            receipt_id="id-b",
            task_id=r1.task_id,
            agent_id=r1.agent_id,
            runtime_id=r1.runtime_id,
            step_index=r1.step_index,
            tool_name=r1.tool_name,
            input_hash=r1.input_hash,
            output_hash=r1.output_hash,
            started_at=r1.started_at,
            ended_at=r1.ended_at,
            duration_ms=r1.duration_ms,
            status=r1.status,
            error_code=r1.error_code,
            evidence_refs=list(r1.evidence_refs),
            signer=r1.signer,
            signature=r1.signature,
            schema_version=r1.schema_version,
            prev_receipt_hash=r1.prev_receipt_hash,
        )
        self.assertEqual(_replay_event_count([r1, r2]), 1)

    def test_duplicate_extra_count(self) -> None:
        t = TaskContract(task_id="t", agent_id="a", runtime_id="r", description="")
        r = ExecutionReceipt(
            receipt_id="same",
            task_id=t.task_id,
            agent_id=t.agent_id,
            runtime_id=t.runtime_id,
            step_index=0,
            tool_name="x",
            input_hash="i",
            output_hash="o",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            duration_ms=1,
            status="ok",
            error_code="",
            prev_receipt_hash="",
        )
        self.assertEqual(_duplicate_extra_count([r, ExecutionReceipt(**r.__dict__)]), 1)

    def test_stress_summary_schema(self) -> None:
        s = run_stress(StressConfig(agents=15, seed=7, malicious_rate=0.2))
        for key in (
            "receipts_count",
            "evidence_bundles_count",
            "valid_receipts",
            "invalid_receipts",
            "replay_detected",
            "duplicate_detected",
            "timeout_detected",
            "malformed_detected",
            "forged_hash_detected",
            "settlement_plan_count",
            "average_verification_ms",
            "p95_verification_ms",
            "failed_cases",
        ):
            self.assertIn(key, s)
        self.assertIsInstance(s["failed_cases"], list)

    def test_determinism_two_runs(self) -> None:
        cfg = StressConfig(agents=25, seed=99, malicious_rate=0.15)
        a = run_stress(cfg)
        b = run_stress(cfg)
        self.assertEqual(a["global_receipt_chain_fingerprint"], b["global_receipt_chain_fingerprint"])
        self.assertEqual(a["receipts_count"], b["receipts_count"])

    def test_agents_100(self) -> None:
        s = run_stress(StressConfig(agents=100, seed=42, malicious_rate=0.1))
        self.assertEqual(s["config"]["agents"], 100)
        self.assertGreater(s["receipts_count"], 100)
        self.assertGreaterEqual(s["invalid_receipts"], 0)

    def test_agents_500(self) -> None:
        s = run_stress(StressConfig(agents=500, seed=42, malicious_rate=0.1))
        self.assertEqual(s["config"]["agents"], 500)
        self.assertGreater(s["receipts_count"], 500)

    def test_script_writes_summary(self) -> None:
        import subprocess
        import sys

        out = Path("/tmp/karma-stress-unitest-out")
        if out.exists():
            for p in out.glob("*"):
                p.unlink()
        out.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts" / "stress_trusted_agent_runtime.py"),
                "--agents",
                "30",
                "--malicious-rate",
                "0.2",
                "--seed",
                "1",
                "--output-dir",
                str(out),
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        data = json.loads((out / "stress_summary.json").read_text(encoding="utf-8"))
        self.assertTrue(data["determinism_rerun_match"])
        self.assertIn("receipts_count", data)


if __name__ == "__main__":
    unittest.main()
