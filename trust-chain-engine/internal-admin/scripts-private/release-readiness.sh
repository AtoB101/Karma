#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/release-readiness.sh

Description:
  Runs the full release readiness gate chain (fail-fast):
    1) commercialization gate
    2) proof/evidence CI gates
    3) strict proof patrol
    4) guardian snapshot
    5) output contract validation
    6) system status aggregation
    7) ops alert export
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

mkdir -p "$RESULTS_DIR"
cd "$ROOT_DIR"

release_status="PASS"
failed_stages=()

echo "==> [1/7] commercialization gate"
./scripts/commercialization-gate.sh --output "$RESULTS_DIR/commercialization-gate-latest.json" --format text

echo "==> [2/7] proof/evidence CI gates"
./scripts/ci-proof-gates.sh --format json >/dev/null

echo "==> [3/8] slither static analysis"
if ! ./scripts/slither-gate.sh --format text --output "$RESULTS_DIR/slither-gate-latest.txt"; then
  release_status="FAIL"
  failed_stages+=("slither-gate")
fi

echo "==> [4/8] proof patrol"
if ! ./scripts/proof-patrol.sh \
  --profile lenient \
  --batch-output "$RESULTS_DIR/proof-patrol-batch-latest.json" \
  --alert-output "$RESULTS_DIR/proof-patrol-alert-latest.json" \
  --no-summary >/dev/null; then
  release_status="FAIL"
  failed_stages+=("proof-patrol")
fi

echo "==> [5/8] guardian snapshot"
./scripts/agent-safety-guardian.sh \
  --profile balanced \
  --skip-support-bundle \
  --skip-proof-gates \
  --skip-patrol \
  --output "$RESULTS_DIR/agent-safety-guardian-latest.json" \
  --register "$RESULTS_DIR/agent-risk-register.json" >/dev/null

echo "==> [6/8] output contract validation"
./scripts/validate-output-contracts.sh --format json > "$RESULTS_DIR/output-contracts-validation-latest.json" || true
if ! ./scripts/validate-output-contracts.sh --format text; then
  release_status="FAIL"
  failed_stages+=("output-contracts")
fi

echo "==> [7/8] system status"
./scripts/system-status.sh --output "$RESULTS_DIR/system-status-latest.json" --format text

echo "==> [8/8] ops alert export"
./scripts/ops-alert.sh --input "$RESULTS_DIR/system-status-latest.json" --output "$RESULTS_DIR/ops-alert-latest.json" --format text

echo
if [[ "$release_status" != "PASS" ]]; then
  echo "release-readiness: FAIL (stages=${failed_stages[*]})"
  echo "runbook: inspect results/ops-alert-latest.json and results/system-status-latest.json"
  exit 2
fi

echo "release-readiness: PASS"
echo "artifacts:"
echo "  - $RESULTS_DIR/commercialization-gate-latest.json"
echo "  - $RESULTS_DIR/proof-patrol-alert-latest.json"
echo "  - $RESULTS_DIR/agent-safety-guardian-latest.json"
echo "  - $RESULTS_DIR/system-status-latest.json"
echo "  - $RESULTS_DIR/ops-alert-latest.json"
