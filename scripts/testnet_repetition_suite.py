#!/usr/bin/env python3
"""
Run N sequential hybrid testnet flows (thin wrapper around testnet_full_flow.py).

  python3 scripts/testnet_repetition_suite.py --runs 10 --output-root results/ta-rep [--send]

Each run uses a distinct --trace-id for audit correlation. Requires the same env as
`scripts/testnet_full_flow.py` when using --send.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def collect_run_snapshot(run_dir: Path) -> dict[str, Any]:
    """
    Best-effort read of artifacts from testnet_full_flow.py for operational validation
    (trace alignment, settlement plan shape, tx writeback when --send).
    """
    snap: dict[str, Any] = {"run_dir": str(run_dir.resolve())}
    task = _read_json(run_dir / "task_contract.json")
    if task:
        snap["artifact_task_trace_id"] = task.get("trace_id")
        snap["task_id"] = task.get("task_id")
    verify = _read_json(run_dir / "verification_result.json")
    if verify:
        snap["verification_decision"] = verify.get("decision")
        snap["verification_trace_id"] = verify.get("trace_id")
    bundle = _read_json(run_dir / "evidence_bundle.json")
    if bundle:
        snap["bundle_trace_id"] = bundle.get("trace_id")
        snap["bundle_id"] = bundle.get("bundle_id")
    hybrid = _read_json(run_dir / "hybrid_settlement_result.json")
    if hybrid:
        snap["hybrid_trace_id"] = hybrid.get("trace_id")
        plan = hybrid.get("offchain_plan") or {}
        snap["settlement_onchain_status"] = plan.get("onchain_status")
        calls = plan.get("recommended_calls") or []
        snap["recommended_calls_count"] = len(calls)
        keys = plan.get("settlement_step_keys") or []
        snap["settlement_step_keys_count"] = len(keys)
        idem = [k.get("idempotency_key") for k in keys if isinstance(k, dict)]
        snap["idempotency_key_unique"] = len(set(idem)) == len(idem) if idem else True
        oc = hybrid.get("onchain") or {}
        txs = oc.get("onchain_transactions") or []
        snap["tx_count"] = len(txs) if isinstance(txs, list) else 0
        snap["tx_hashes"] = [t.get("tx_hash") for t in txs if isinstance(t, dict) and t.get("tx_hash")]
        if hybrid.get("tx_log_path"):
            snap["tx_log_path"] = hybrid.get("tx_log_path")
    # Trace integrity: all non-empty trace ids that appear should match task trace when present
    t_trace = snap.get("artifact_task_trace_id") or ""
    if t_trace:
        mismatches = []
        for k in ("verification_trace_id", "bundle_trace_id", "hybrid_trace_id"):
            v = snap.get(k)
            if v and v != t_trace:
                mismatches.append(f"{k}:{v}!={t_trace}")
        snap["trace_correlation_ok"] = len(mismatches) == 0
        if mismatches:
            snap["trace_correlation_mismatches"] = mismatches
    else:
        snap["trace_correlation_ok"] = None
    return snap


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=10, help="Number of end-to-end repetitions (default 10)")
    p.add_argument("--output-root", type=Path, default=Path("results/ta-repetition"))
    p.add_argument("--send", action="store_true", help="Forward --send to testnet_full_flow.py")
    p.add_argument("--prefix", default="rep", help="Prefix for per-run trace_id")
    args = p.parse_args()

    if args.runs < 1 or args.runs > 200:
        raise SystemExit("--runs must be between 1 and 200")

    root = args.output_root
    root.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    runs_meta: list[dict] = []
    op_log_path = root / "operational_log.jsonl"
    if op_log_path.exists():
        op_log_path.unlink()

    extra = ["--send"] if args.send else []
    for i in range(args.runs):
        run_dir = root / f"run-{i:04d}"
        trace = f"{args.prefix}-{stamp}-run{i:04d}"
        cmd = [
            sys.executable,
            str(_ROOT / "scripts" / "testnet_full_flow.py"),
            "--output-dir",
            str(run_dir),
            "--trace-id",
            trace,
            *extra,
        ]
        rc = subprocess.run(cmd, cwd=str(_ROOT))
        row: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "index": i,
            "trace_id": trace,
            "output_dir": str(run_dir.resolve()),
            "exit_code": rc.returncode,
            "send": bool(args.send),
        }
        snap = collect_run_snapshot(run_dir)
        row.update(snap)
        runs_meta.append(row)
        with open(op_log_path, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(row, sort_keys=True) + "\n")

    trace_ok_count = sum(1 for r in runs_meta if r.get("trace_correlation_ok") is True)
    trace_na = sum(1 for r in runs_meta if r.get("trace_correlation_ok") is None)
    tx_total = sum(int(r.get("tx_count") or 0) for r in runs_meta)

    summary = {
        "runs_requested": args.runs,
        "output_root": str(root.resolve()),
        "send": bool(args.send),
        "aggregates": {
            "runs_with_trace_correlation_ok": trace_ok_count,
            "runs_without_task_trace_id": trace_na,
            "total_onchain_transactions_recorded": tx_total,
        },
        "runs": runs_meta,
        "failures": [r for r in runs_meta if r.get("exit_code") != 0],
        "operational_log": str(op_log_path.resolve()),
    }
    out_path = root / "repetition_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("OK  repetition summary ->", out_path.resolve())
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
