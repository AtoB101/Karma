#!/usr/bin/env bash
# Phase 1 Open Wallet / TradeLaunch EIP-712 acceptance gate (no live RPC).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "==> Phase 1 EIP-712 + voucher commitment + security + OpenClaw relax tests"
python3 -m pytest -q \
  tests/unit/test_trade_launch_eip712.py \
  tests/unit/test_voucher_buyer_commitment.py \
  tests/unit/test_trade_launch_security.py \
  tests/unit/test_spending_policy.py \
  tests/unit/test_openclaw_delivery_signature_relax.py \
  tests/integration/test_trade_launch_eip712_launch.py \
  packages/karma-openclaw/tests/test_dev_delivery_signatures.py

echo "==> Production trade EIP-712 settings (APP_ENV=production)"
APP_ENV=production python3 <<'PY'
import os
import sys

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
    "TRADE_LAUNCH_RECORD_RUNTIME_DAILY_SPEND": "true",
}
for k, v in defaults.items():
    os.environ.setdefault(k, v)

os.environ.setdefault("APP_SECRET_KEY", "gate-check-secret-min-32-chars-long!!")
os.environ.setdefault("AUTH_API_KEYS", "gate-agent:gate-secret-minimum")

from config.settings import Settings

try:
    Settings()
except ValueError as e:
    print(f"ERR  production trade EIP-712 settings rejected: {e}", file=sys.stderr)
    sys.exit(1)

print("OK   Settings() accepts production trade EIP-712 configuration")
PY

echo "OK   phase1 open wallet gate finished"
