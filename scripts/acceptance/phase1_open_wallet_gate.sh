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

# 生产必填项的唯一来源：config/production_gates.py。
# tests/unit/test_production_gate_manifest_parity.py 会保证这张清单不漏项
# （新增闸门没写进去 = CI 直接红），所以脚本里不要再手抄一份。
from config.production_gates import PRODUCTION_GATE_DEFAULTS

defaults = dict(PRODUCTION_GATE_DEFAULTS)
# 这一条不是生产闸门（Settings 在 production 下不校验它），是 Phase 1 验收要求：
# runtime daily spend 必须落库，否则「花钱不记账」的验收过不去。
defaults["TRADE_LAUNCH_RECORD_RUNTIME_DAILY_SPEND"] = "true"
for k, v in defaults.items():
    os.environ.setdefault(k, v)

from config.settings import Settings

try:
    Settings()
except ValueError as e:
    print(f"ERR  production trade EIP-712 settings rejected: {e}", file=sys.stderr)
    sys.exit(1)

print("OK   Settings() accepts production trade EIP-712 configuration")
PY

echo "OK   phase1 open wallet gate finished"
