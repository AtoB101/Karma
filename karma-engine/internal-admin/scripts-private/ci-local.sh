#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
FROM_ENV=0
SKIP_PREFLIGHT=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/ci-local.sh [--from-env] [--skip-preflight]

Description:
  Runs local CI checks in sequence:
    1) preflight (optional)
    2) forge build
    3) focused non-custodial tests
    4) proof/evidence CI gates

Options:
  --from-env        Load .env before checks
  --skip-preflight  Skip preflight step
  -h, --help        Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-env)
      FROM_ENV=1
      shift
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

cd "$ROOT_DIR"

if [[ "$FROM_ENV" -eq 1 ]]; then
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing .env file at ${ENV_FILE}"
    exit 1
  fi
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
  echo "Loaded .env"
fi

if [[ "$SKIP_PREFLIGHT" -eq 0 ]]; then
  echo "==> Running preflight"
  ./scripts/preflight.sh --mode local $([[ "$FROM_ENV" -eq 1 ]] && echo "--from-env")
fi

if ! command -v forge >/dev/null 2>&1; then
  echo "Missing forge. Install Foundry first."
  exit 1
fi

echo
echo "==> forge build"
forge build

echo
echo "==> forge test (focused suites)"
forge test --match-path "contracts/test/NonCustodialAgentPayment.t.sol" -q
forge test --match-path "contracts/test/NonCustodialAgentPaymentReentrancy.t.sol" -q
forge test --match-path "contracts/test/NonCustodialAgentPayment.invariant.t.sol" -q

echo
echo "==> proof/evidence gates"
./scripts/ci-proof-gates.sh

echo
echo "Local CI checks passed."
