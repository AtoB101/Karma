#!/usr/bin/env bash
# Validate production-oriented env before go-live (public Karma API).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${1:-}"
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  echo "==> Loaded env from ${ENV_FILE}"
fi

echo "==> Receipt signature enforcement (unit)"
python3 -m pytest -q tests/unit/test_production_receipt_signature.py tests/unit/test_production_settings_gates.py

echo "==> Production settings validator (APP_ENV=production)"
APP_ENV=production python3 <<'PY'
import os
import sys

# Ensure production flags unless explicitly set in environment
defaults = {
    "AUTH_ENFORCE_PROTECTED_ROUTES": "true",
    "AUTH_ALLOW_DEV_KEY_FALLBACK": "false",
    "RATE_LIMIT_REDIS_FAIL_CLOSED": "true",
    "RECEIPT_REQUIRE_SIGNATURE": "true",
    "LEDGER_REQUIRE_PARTY_ACTOR": "true",
    "SETTLEMENT_REQUIRE_PARTY_ACTOR": "true",
    "RUNTIME_REQUIRE_SAVED_AUTOMATION_POLICY": "true",
    "RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS": "true",
    "RUNTIME_REQUIRE_HANDOFF_ATTESTATION": "true",
    "RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING": "true",
    "RUNTIME_DAILY_SPEND_PERSIST": "true",
    "TRADE_LAUNCH_REQUIRE_EIP712": "true",
    "KARMA_SIGNING_BACKEND": "client_only",
}
for k, v in defaults.items():
    os.environ.setdefault(k, v)

if not os.environ.get("APP_SECRET_KEY") or os.environ.get("APP_SECRET_KEY") == "change-me-in-production":
    os.environ["APP_SECRET_KEY"] = os.environ.get("APP_SECRET_KEY") or "gate-check-secret-min-32-chars-long!!"
if not os.environ.get("AUTH_API_KEYS"):
    os.environ["AUTH_API_KEYS"] = "gate-agent:gate-secret-minimum"

from config.settings import Settings

try:
    Settings()
except ValueError as e:
    print(f"ERR  production settings rejected: {e}", file=sys.stderr)
    sys.exit(1)

print("OK   Settings() accepts production configuration")
PY

if [[ -x ./scripts/public-beta-security-gate.sh ]]; then
  echo "==> Public beta security gate (requires full production env in shell)"
  if [[ -n "${SECURITY_ONCALL_PRIMARY:-}" && -n "${SECURITY_ONCALL_BACKUP:-}" ]]; then
    ./scripts/public-beta-security-gate.sh
  else
    echo "SKIP public-beta-security-gate (set SECURITY_ONCALL_* to run)"
  fi
fi

echo "OK   production prelaunch gate finished"
