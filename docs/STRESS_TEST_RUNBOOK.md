# Stress test runbook

## 1) Offline structural stress (no API, no chain)

```bash
python3 scripts/stress_evidence_runtime.py --agents 100 --malicious-rate 0.1 --seed 42 --output-dir results/stress-100
python3 scripts/stress_evidence_runtime.py --agents 500 --malicious-rate 0.1 --seed 42 --output-dir results/stress-500
```

Checks receipt/bundle consistency, malicious mix, and determinism (`determinism_rerun_match`).

```bash
python3 -m unittest tests.test_trusted_agent_stress -v
```

## 2) Acceptance + adversarial (recommended CI-local)

```bash
bash scripts/run_public_acceptance_tests.sh -q
bash scripts/acceptance/full_chain_audit_gate.sh
python3 scripts/acceptance/adversarial_whole_project_suite.py
```

## 3) Live HTTP stress (needs running API)

```bash
# Example local API (SQLite). Raise rate limits only for dedicated stress envs.
APP_ENV=test SETTLEMENT_MODE=offchain \
  DATABASE_URL=sqlite+aiosqlite:////tmp/karma-stress.db \
  uvicorn api.app:app --host 127.0.0.1 --port 8000

python3 scripts/stress_attack_test.py
# Optional heavier: scripts/stress_test.py, scripts/biz_stress.py
# Note: default register_agent limit is 5/min — use a stress profile or expect 429s.
```

## 4) Contracts

```bash
forge test -q
```
