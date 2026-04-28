#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

use_env=0
quiet=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/preflight.sh [--from-env] [--quiet]

Checks:
  - Required binaries: forge, cast, python3
  - Required environment variables:
      ETH_RPC_URL
      DEPLOYER_PRIVATE_KEY
      ADMIN_ADDRESS
  - Optional warnings:
      TOKEN_ADDRESS
      PAYEE_ADDRESS
      BUYER_PRIVATE_KEY
      SELLER_PRIVATE_KEY

Options:
  --from-env   Load variables from .env in repository root
  --quiet      Reduce non-essential output
  -h, --help   Show this help message
EOF
}

log() {
  if [[ "$quiet" -eq 0 ]]; then
    echo "$@"
  fi
}

ok() { echo "OK   $*"; }
warn() { echo "WARN $*"; }
err() { echo "ERR  $*"; }

for arg in "$@"; do
  case "$arg" in
    --from-env) use_env=1 ;;
    --quiet) quiet=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      err "Unknown argument: $arg"
      usage
      exit 1
      ;;
  esac
done

if [[ "$use_env" -eq 1 ]]; then
  if [[ ! -f "$ENV_FILE" ]]; then
    err "Missing .env file at ${ENV_FILE}. Create it from .env.example first."
    exit 1
  fi
  log "Loading environment from .env"
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

missing=0

check_cmd() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    ok "binary available: ${name}"
  else
    err "binary missing: ${name}"
    missing=1
  fi
}

check_env_required() {
  local name="$1"
  if [[ -n "${!name:-}" ]]; then
    ok "env set: ${name}"
  else
    err "env missing: ${name}"
    missing=1
  fi
}

check_env_optional() {
  local name="$1"
  if [[ -n "${!name:-}" ]]; then
    ok "env set (optional): ${name}"
  else
    warn "env not set (optional): ${name}"
  fi
}

log "=== Binary checks ==="
check_cmd forge
check_cmd cast
check_cmd python3

log
log "=== Required environment checks ==="
check_env_required ETH_RPC_URL
check_env_required DEPLOYER_PRIVATE_KEY
check_env_required ADMIN_ADDRESS

log
log "=== Optional environment checks ==="
check_env_optional TOKEN_ADDRESS
check_env_optional PAYEE_ADDRESS
check_env_optional BUYER_PRIVATE_KEY
check_env_optional SELLER_PRIVATE_KEY

if [[ "$missing" -ne 0 ]]; then
  echo
  err "Preflight failed. Fix errors above and run again."
  exit 1
fi

echo
ok "Preflight passed."
ok "Next step: ./scripts/dev-up.sh --from-env"
