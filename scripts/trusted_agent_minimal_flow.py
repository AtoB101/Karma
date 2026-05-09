#!/usr/bin/env python3
"""
Minimal Trusted Agent flow (Phase 2) — offchain, InMemory receipts only.

create task → simulate tools → receipts → chain → evidence bundle →
proofHash mapping → structural verify → settlement plan (no chain tx).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.demo_payload import build_demo_offchain_bundle
from trusted_agent_runtime.schemas import EvidenceBundle, TaskContract, VerificationResult
from trusted_agent_runtime.settlement_adapter import SettlementAdapter


def _write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--output-dir",
        default="results/trusted-agent-demo",
        help="Directory for JSON artifacts (default: results/trusted-agent-demo)",
    )
    p.add_argument("--trace-id", default="", help="Optional correlation id (default: trace-<task_id>)")
    args = p.parse_args()
    out = Path(args.output_dir)

    tid = args.trace_id.strip() or None
    payload = build_demo_offchain_bundle(trace_id=tid)
    settlement = SettlementAdapter()

    _write(out / "task_contract.json", payload["task"])
    _write(out / "receipt_chain.json", payload["receipt_chain"])
    _write(out / "evidence_bundle.json", payload["evidence_bundle"])
    _write(out / "verification_result.json", payload["verification"])

    task = TaskContract(**payload["task"])
    bundle = EvidenceBundle(**payload["evidence_bundle"])
    verify = VerificationResult(**payload["verification"])
    plan = settlement.build_offchain_plan(
        task,
        bundle,
        payload["proof_hash"],
        payload["scope_hex"],
        seller="0x000000000000000000000000000000000000dEaD",
        token="0x000000000000000000000000000000000000c0ffee",
        amount_wei=1_000_000,
        deadline_unix=2_000_000_000,
        verify=verify,
    )
    _write(out / "settlement_result.json", plan)

    print("OK  Trusted Agent minimal flow")
    print(f"    output: {out.resolve()}")
    print(f"    proof_hash: {payload['proof_hash']}")
    print(f"    bundle_digest: {payload['bundle_digest']}")
    print(f"    verification: {verify.decision} {verify.public_reasons}")


if __name__ == "__main__":
    main()
