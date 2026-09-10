#!/usr/bin/env bash
# Local agent↔agent land gate (off-chain Phase-1 trade launch).
#
# Does NOT run public_testnet_preflight (that gate is for invite/public deploy).
#
# Usage:
#   cp deploy/.env.local-openclaw.example .env
#   set -a && source .env && set +a
#   # Optional: start API yourself, or set KARMA_START_API=true
#   bash scripts/acceptance/local_dual_agent_gate.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ENV_FILE="${KARMA_LOCAL_ENV:-}"
if [[ -z "$ENV_FILE" && -f "$ROOT/.env" ]]; then
  ENV_FILE="$ROOT/.env"
fi
if [[ -z "$ENV_FILE" && -f "$ROOT/deploy/.env.local-openclaw.example" ]]; then
  ENV_FILE="$ROOT/deploy/.env.local-openclaw.example"
fi
if [[ -n "${ENV_FILE:-}" && -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  echo "==> Loaded ${ENV_FILE}"
fi

BUYER_ID="${KARMA_BUYER_IDENTITY_ID:-a2a-buyer}"
SELLER_ID="${KARMA_SELLER_IDENTITY_ID:-a2a-seller}"
PHASE1_ENV="${KARMA_PHASE1_ENV_OUT:-$ROOT/.env.phase1.local}"
API_PID=""
API_PORT="${KARMA_API_PORT:-8000}"

# When we start the API ourselves, bind a dedicated port so we share DATABASE_URL with seed.
if [[ "${KARMA_START_API:-false}" == "true" ]]; then
  API_PORT="${KARMA_API_PORT:-8010}"
  KARMA_RUNTIME_URL="http://127.0.0.1:${API_PORT}"
  export KARMA_RUNTIME_URL
fi
: "${KARMA_RUNTIME_URL:=http://127.0.0.1:8000}"

cleanup() {
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
    echo "==> Stopping API pid=${API_PID}"
    kill "${API_PID}" 2>/dev/null || true
    wait "${API_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "========================================"
echo " Local dual-agent (A2A) gate"
echo " Runtime: ${KARMA_RUNTIME_URL}"
echo " Buyer:   ${BUYER_ID}"
echo " Seller:  ${SELLER_ID}"
echo " DB:      ${DATABASE_URL:-'(settings default)'}"
echo "========================================"

echo ""
echo "== [1/4] Seed trade-ready buyer + seller =="
python3 scripts/seed_phase1_dual_agents.py \
  --buyer-id "$BUYER_ID" \
  --seller-id "$SELLER_ID" \
  --env-out "$PHASE1_ENV"
set -a
# shellcheck disable=SC1090
source "$PHASE1_ENV"
set +a
# Keep runtime URL from this gate (seed may rewrite from env defaults)
export KARMA_RUNTIME_URL

echo ""
echo "== [2/4] API health =="
if [[ "${KARMA_START_API:-false}" == "true" ]]; then
  echo "==> Starting uvicorn on :${API_PORT} (same DATABASE_URL as seed)"
  python3 -m uvicorn api.app:app --host 127.0.0.1 --port "${API_PORT}" >/tmp/karma-a2a-api.log 2>&1 &
  API_PID=$!
  for _ in $(seq 1 60); do
    if curl -sf "${KARMA_RUNTIME_URL%/}/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.25
  done
elif ! curl -sf "${KARMA_RUNTIME_URL%/}/health" >/dev/null 2>&1; then
  echo "ERR  API not reachable at ${KARMA_RUNTIME_URL}" >&2
  echo "     Start: uvicorn api.app:app --host 127.0.0.1 --port 8000" >&2
  echo "     Or re-run with KARMA_START_API=true" >&2
  exit 1
fi
if ! curl -sf "${KARMA_RUNTIME_URL%/}/health" >/dev/null 2>&1; then
  echo "ERR  API failed to become healthy — see /tmp/karma-a2a-api.log" >&2
  tail -n 40 /tmp/karma-a2a-api.log 2>/dev/null || true
  exit 1
fi
curl -sf "${KARMA_RUNTIME_URL%/}/health" | head -c 200
echo ""

echo ""
echo "== [3/4] Agent↔agent launch smoke (execution_started + idempotent) =="
export KARMA_API_KEY="${KARMA_BUYER_API_KEY:-${KARMA_API_KEY:-}}"
python3 scripts/acceptance/phase1_claw_manus_smoke.py \
  --base-url "$KARMA_RUNTIME_URL" \
  --buyer-id "$KARMA_BUYER_IDENTITY_ID" \
  --seller-id "$KARMA_SELLER_IDENTITY_ID" \
  --require-execution-started

echo ""
echo "== [4/4] Optional OpenClaw MCP hint =="
echo "  Buyer MCP:  KARMA_API_KEY=\$KARMA_BUYER_API_KEY karma-openclaw-mcp"
echo "  Seller MCP: KARMA_API_KEY=\$KARMA_SELLER_API_KEY karma-openclaw-mcp"
echo "  Env file:   ${PHASE1_ENV}"
echo ""
echo "LOCAL DUAL-AGENT GATE: PASS"
