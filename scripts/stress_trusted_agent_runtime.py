#!/usr/bin/env python3
"""Phase 4 — local structural stress for Trusted Agent Runtime (no testnet txs)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.stress_runner import StressConfig, run_stress


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agents", type=int, required=True)
    p.add_argument("--malicious-rate", type=float, default=0.1)
    p.add_argument("--output-dir", type=Path, default=Path("results/stress-test"))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    cfg = StressConfig(agents=args.agents, seed=args.seed, malicious_rate=args.malicious_rate)
    first = run_stress(cfg)
    second = run_stress(cfg)
    first["determinism_rerun_match"] = first["global_receipt_chain_fingerprint"] == second["global_receipt_chain_fingerprint"]
    first["determinism_second_fingerprint"] = second["global_receipt_chain_fingerprint"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / "stress_summary.json"
    out_path.write_text(json.dumps(first, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("OK  stress summary ->", out_path.resolve())
    print("    agents:", args.agents, "valid_receipts:", first["valid_receipts"], "invalid:", first["invalid_receipts"])
    print("    determinism_rerun_match:", first["determinism_rerun_match"])


if __name__ == "__main__":
    main()
