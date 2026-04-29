#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

./scripts/ops-doctor-json.sh >/dev/null 2>&1 || true
./scripts/commercialization-gate.sh --output results/commercialization-gate-latest.json --format text >/dev/null
./scripts/proof-patrol.sh --profile strict --batch-output results/proof-patrol-batch-latest.json --alert-output results/proof-patrol-alert-latest.json --no-summary >/dev/null || true
./scripts/agent-safety-guardian.sh --profile balanced --skip-support-bundle --skip-proof-gates --skip-patrol --output results/agent-safety-guardian-latest.json --register results/agent-risk-register.json >/dev/null || true
./scripts/validate-output-contracts.sh --format json > results/output-contracts-validation-latest.json || true
./scripts/system-status.sh --output results/system-status-latest.json --format text

python3 - <<'PY'
import json
from pathlib import Path
p = Path('results/system-status-latest.json')
if not p.exists():
    raise SystemExit(1)
obj = json.loads(p.read_text(encoding='utf-8'))
print("--- ops summary ---")
print(f"overall={obj['summary']['overall']}")
print(f"alertSeverity={obj['summary'].get('alertSeverity')}")
print(f"commercialReady={obj['summary']['commercialReady']}")
print(f"patrolHealthy={obj['summary']['patrolHealthy']}")
print(f"contractsHealthy={obj['summary']['contractsHealthy']}")
print(f"traceId={obj['traceId']}")
print("nextActions:")
for idx, action in enumerate(obj.get("summary", {}).get("nextActions", []), 1):
    print(f"  {idx}. {action}")
PY
