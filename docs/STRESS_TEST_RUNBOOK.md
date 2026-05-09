# Stress test runbook — Trusted Agent Runtime (Phase 4)

Fully **local**, **single-process**, **deterministic** structural stress.  
**No testnet transactions.** No new contracts. No private risk scoring.

## Install

Phase 4 uses only the Python standard library plus existing `trusted_agent_runtime` modules (same as Phase 2).  
Optional: keep `requirements-testnet.txt` separate — stress does **not** require `web3`.

## Commands

```bash
# 100 agents (default malicious rate 0.1, seed 42)
python3 scripts/stress_trusted_agent_runtime.py --agents 100 --malicious-rate 0.1 --seed 42 --output-dir results/stress-test

# 500 agents
python3 scripts/stress_trusted_agent_runtime.py --agents 500 --malicious-rate 0.1 --seed 42 --output-dir results/stress-test-500
```

Output: `<output-dir>/stress_summary.json` with counters, timing, and `failed_cases[]`.

## What is tested (structural only)

- Receipt / chain / schema anomalies (malformed, timeout order, forged `prev_receipt_hash`, duplicate `receipt_id`, replayed structural hash).
- Evidence bundle + `proofHash` + settlement plan **self-consistency** (double-hash stable) for agents that pass structural gates.
- **Mixed honest / malicious** traffic via `--malicious-rate`.

## CI / unittest

```bash
python3 -m unittest tests.test_trusted_agent_stress -v
```
