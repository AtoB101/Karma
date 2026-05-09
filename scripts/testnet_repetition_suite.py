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

_ROOT = Path(__file__).resolve().parents[1]


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
        runs_meta.append(
            {
                "index": i,
                "trace_id": trace,
                "output_dir": str(run_dir.resolve()),
                "exit_code": rc.returncode,
            }
        )

    summary = {
        "runs_requested": args.runs,
        "output_root": str(root.resolve()),
        "send": bool(args.send),
        "runs": runs_meta,
        "failures": [r for r in runs_meta if r["exit_code"] != 0],
    }
    out_path = root / "repetition_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("OK  repetition summary ->", out_path.resolve())
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
