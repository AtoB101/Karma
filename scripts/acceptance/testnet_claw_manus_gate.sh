#!/usr/bin/env bash
# Testnet + OpenClaw / OpenManus live acceptance (requires running API and credentials).
#
# Usage:
#   cp deploy/.env.testnet-claw-manus.example .env.testnet.local
#   # fill RPC, keys, buyer/seller identities, API keys
#   set -a && source .env.testnet.local && set +a
#   uvicorn api.app:app --host 0.0.0.0 --port 8000   # separate terminal
#   bash scripts/acceptance/testnet_claw_manus_gate.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ENV_FILE="${KARMA_TESTNET_ENV:-}"
if [[ -z "$ENV_FILE" && -f "$ROOT/.env.testnet.local" ]]; then
  ENV_FILE="$ROOT/.env.testnet.local"
fi
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  echo "==> Loaded ${ENV_FILE}"
fi

: "${KARMA_RUNTIME_URL:=http://127.0.0.1:8000}"
: "${KARMA_BUYER_IDENTITY_ID:?set KARMA_BUYER_IDENTITY_ID}"
: "${KARMA_SELLER_IDENTITY_ID:?set KARMA_SELLER_IDENTITY_ID}"

echo "========================================"
echo " Testnet Claw + Manus acceptance"
echo " Runtime: ${KARMA_RUNTIME_URL}"
echo "========================================"

echo ""
echo "== [1/5] Off-chain full-chain audit (no RPC) =="
bash scripts/acceptance/full_chain_audit_gate.sh

echo ""
echo "== [2/5] API health =="
curl -sf "${KARMA_RUNTIME_URL%/}/health" | head -c 200
echo ""

echo ""
echo "== [3/5] OpenManus / Runtime smoke (launch + idempotency) =="
export KARMA_API_KEY="${KARMA_BUYER_API_KEY:-${KARMA_API_KEY:-}}"
if [[ -z "${KARMA_API_KEY:-}" ]]; then
  echo "WARN  KARMA_BUYER_API_KEY / KARMA_API_KEY unset — skipping launch smoke"
else
  CHAIN_ARGS=()
  if [[ -n "${CHAIN_ANCHOR_HASH:-}" ]]; then
    CHAIN_ARGS=(--chain-anchor-hash "$CHAIN_ANCHOR_HASH")
  fi
  python3 scripts/acceptance/phase1_claw_manus_smoke.py \
    --base-url "$KARMA_RUNTIME_URL" \
    --buyer-id "$KARMA_BUYER_IDENTITY_ID" \
    --seller-id "$KARMA_SELLER_IDENTITY_ID" \
    "${CHAIN_ARGS[@]}"
fi

echo ""
echo "== [4/5] Optional EIP-712 launch smoke =="
if [[ "${RUN_EIP712_SMOKE:-false}" == "true" ]]; then
  python3 scripts/acceptance/phase1_eip712_launch_smoke.py \
    --base-url "$KARMA_RUNTIME_URL" \
    --buyer-id "$KARMA_BUYER_IDENTITY_ID" \
    --seller-id "$KARMA_SELLER_IDENTITY_ID"
else
  echo "SKIP  set RUN_EIP712_SMOKE=true to run phase1_eip712_launch_smoke.py"
fi

echo ""
echo "== [5/5] Optional on-chain hybrid (Sepolia) =="
if [[ "${RUN_TESTNET_ONCHAIN:-false}" == "true" ]]; then
  if [[ -z "${TESTNET_RPC_URL:-}" || -z "${NONCUSTODIAL_AGENT_PAYMENT_ADDRESS:-}" ]]; then
    echo "ERR  RUN_TESTNET_ONCHAIN=true requires TESTNET_RPC_URL and NONCUSTODIAL_AGENT_PAYMENT_ADDRESS" >&2
    exit 1
  fi
  if [[ -f requirements-testnet.txt ]]; then
    python3 -m pip install -q -r requirements-testnet.txt 2>/dev/null || true
  fi
  if [[ -f scripts/testnet_full_flow.py ]]; then
    python3 scripts/testnet_full_flow.py --send
  else
    echo "WARN  scripts/testnet_full_flow.py not found"
  fi
else
  echo "SKIP  set RUN_TESTNET_ONCHAIN=true for scripts/testnet_full_flow.py --send"
fi

echo ""
echo "== Manual MCP (OpenClaw) =="
echo "  pip install -e './packages/karma-openclaw[dev]'"
echo "  KARMA_RUNTIME_URL=$KARMA_RUNTIME_URL KARMA_API_KEY=<key> karma-openclaw-mcp"
echo "  See docs/PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md paths A/B/C"
echo ""
echo "TESTNET CLAW+MANUS GATE: off-chain PASS; live steps as configured above"
