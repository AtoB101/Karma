#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ALLOW_NON_PROD=false
for arg in "$@"; do
  case "$arg" in
    --allow-non-prod)
      ALLOW_NON_PROD=true
      ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: $0 [--allow-non-prod]"
      exit 2
      ;;
  esac
done

echo "==> Public beta security gate check"

APP_ENV_VALUE="${APP_ENV:-}"
APP_SECRET_VALUE="${APP_SECRET_KEY:-}"
AUTH_ENFORCE_VALUE="${AUTH_ENFORCE_PROTECTED_ROUTES:-}"
AUTH_KEYS_VALUE="${AUTH_API_KEYS:-}"
ONCALL_PRIMARY_VALUE="${SECURITY_ONCALL_PRIMARY:-}"
ONCALL_BACKUP_VALUE="${SECURITY_ONCALL_BACKUP:-}"

if [[ "$ALLOW_NON_PROD" == "false" ]]; then
  if [[ "${APP_ENV_VALUE,,}" != "production" && "${APP_ENV_VALUE,,}" != "prod" ]]; then
    echo "ERR  APP_ENV must be production/prod (current: '${APP_ENV_VALUE:-unset}')"
    exit 1
  fi
fi

if [[ -z "$APP_SECRET_VALUE" || "$APP_SECRET_VALUE" == "change-me-in-production" ]]; then
  echo "ERR  APP_SECRET_KEY is missing or default"
  exit 1
fi

if [[ "${AUTH_ENFORCE_VALUE,,}" != "true" && "$ALLOW_NON_PROD" == "false" ]]; then
  echo "ERR  AUTH_ENFORCE_PROTECTED_ROUTES must be true"
  exit 1
fi

if [[ -z "$AUTH_KEYS_VALUE" ]]; then
  echo "ERR  AUTH_API_KEYS is missing"
  exit 1
fi

if [[ "$ALLOW_NON_PROD" == "false" ]]; then
  if [[ -z "$ONCALL_PRIMARY_VALUE" || -z "$ONCALL_BACKUP_VALUE" ]]; then
    echo "ERR  SECURITY_ONCALL_PRIMARY and SECURITY_ONCALL_BACKUP must be configured"
    exit 1
  fi
fi

echo "==> Running security baseline guard"
./scripts/security-baseline-guard.sh

echo "==> Running auth/security regression tests"
python3 -m pytest -q tests/unit/test_auth_security.py tests/unit/test_security_ops.py

echo "==> Running public acceptance checks"
./scripts/public-p0-acceptance.sh

echo "OK   public beta security gate passed."
