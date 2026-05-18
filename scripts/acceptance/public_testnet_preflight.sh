#!/usr/bin/env bash
# Public testnet preflight — fail fast on unsafe or incomplete deploy env.
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

fail=0
warn=0

_check() {
  local name="$1"
  local val="${2:-}"
  if [[ -z "$val" ]]; then
    echo "FAIL  missing ${name}" >&2
    fail=$((fail + 1))
  else
    echo "OK    ${name}"
  fi
}

_warn_if() {
  local msg="$1"
  echo "WARN  ${msg}" >&2
  warn=$((warn + 1))
}

echo "========================================"
echo " Public testnet preflight"
echo "========================================"

# Unsafe for public testnet API
if [[ "${OPENCLAW_LOCAL_PHASE1_AUTO_RELAX:-false}" == "true" ]]; then
  echo "FAIL  OPENCLAW_LOCAL_PHASE1_AUTO_RELAX must be false on public testnet" >&2
  fail=$((fail + 1))
fi
if [[ "${AUTH_ENFORCE_PROTECTED_ROUTES:-true}" == "false" ]]; then
  echo "FAIL  AUTH_ENFORCE_PROTECTED_ROUTES must be true" >&2
  fail=$((fail + 1))
fi
if [[ "${APP_ENV:-development}" != "production" && "${REQUIRE_PRODUCTION_APP_ENV:-false}" == "true" ]]; then
  echo "FAIL  APP_ENV=production required (set REQUIRE_PRODUCTION_APP_ENV=false to skip)" >&2
  fail=$((fail + 1))
fi
if [[ "${APP_ENV:-}" == "production" && "${X402_PAYMENT_BACKEND:-mock}" == "mock" ]]; then
  echo "FAIL  X402_PAYMENT_BACKEND=mock not allowed when APP_ENV=production" >&2
  fail=$((fail + 1))
fi

_check "KARMA_RUNTIME_URL" "${KARMA_RUNTIME_URL:-}"
_check "KARMA_BUYER_IDENTITY_ID" "${KARMA_BUYER_IDENTITY_ID:-}"
_check "KARMA_SELLER_IDENTITY_ID" "${KARMA_SELLER_IDENTITY_ID:-}"

if [[ -z "${KARMA_BUYER_API_KEY:-}" && -z "${KARMA_API_KEY:-}" ]]; then
  _warn_if "KARMA_BUYER_API_KEY / KARMA_API_KEY unset — launch smoke will skip"
fi

if [[ "${SETTLEMENT_MODE:-}" == "testnet" && -z "${CHAIN_ANCHOR_HASH:-}" ]]; then
  echo "FAIL  SETTLEMENT_MODE=testnet requires CHAIN_ANCHOR_HASH" >&2
  fail=$((fail + 1))
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  _warn_if "DATABASE_URL unset — default may be SQLite (not recommended for public testnet)"
fi
if [[ -z "${REDIS_URL:-}" && -z "${RATE_LIMIT_REDIS_URL:-}" ]]; then
  _warn_if "Redis URL unset — rate limit may be in-process only"
fi

if [[ "${RUN_TESTNET_ONCHAIN:-false}" == "true" ]]; then
  _check "TESTNET_RPC_URL" "${TESTNET_RPC_URL:-}"
  _check "NONCUSTODIAL_AGENT_PAYMENT_ADDRESS" "${NONCUSTODIAL_AGENT_PAYMENT_ADDRESS:-}"
fi

echo ""
if [[ "$fail" -gt 0 ]]; then
  echo "PREFLIGHT: FAIL (${fail} errors, ${warn} warnings)" >&2
  exit 1
fi
echo "PREFLIGHT: PASS (${warn} warnings)"
exit 0
