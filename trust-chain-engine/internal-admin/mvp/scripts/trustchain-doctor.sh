#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/trustchain-doctor.sh [--json]

Description:
  Checks whether the seller environment is ready for one-click integration:
  - required tools
  - required env vars
  - gateway health endpoint
  - charge amount sanity
EOF
}

JSON_MODE="0"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      JSON_MODE="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -f .env ]]; then
  export $(grep -v '^#' .env | xargs)
fi

MVP_HOST="${MVP_HOST:-127.0.0.1}"
MVP_PORT="${MVP_PORT:-${PORT:-8822}}"
BASE_URL="${TC_GATEWAY_URL:-http://${MVP_HOST}:${MVP_PORT}}"
CHARGE_WEI="${CHARGE_WEI:-0}"

ok=true
issues=()

check_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    ok=false
    issues+=("missing_command:${name}")
  fi
}

check_env() {
  local key="$1"
  local val="${!key:-}"
  if [[ -z "$val" ]]; then
    ok=false
    issues+=("missing_env:${key}")
  fi
}

check_cmd node
check_cmd npm
check_cmd curl
check_cmd python3

check_env RPC_URL
check_env USER_PRIVATE_KEY
check_env PROVIDER_WALLET

if [[ ! "$CHARGE_WEI" =~ ^[0-9]+$ ]] || [[ "$CHARGE_WEI" == "0" ]]; then
  ok=false
  issues+=("invalid_charge_wei:CHARGE_WEI must be positive integer")
fi

health_ok=false
if curl -sS "${BASE_URL}/api/health" >/tmp/tc-mvp-health.json 2>/dev/null; then
  if python3 - <<'PY'
import json
import pathlib
obj = json.loads(pathlib.Path("/tmp/tc-mvp-health.json").read_text())
assert obj.get("ok") is True
print("ok")
PY
  then
    health_ok=true
  fi
fi

if [[ "$health_ok" != true ]]; then
  ok=false
  issues+=("gateway_unreachable:${BASE_URL}/api/health")
fi

if [[ "$JSON_MODE" == "1" ]]; then
  python3 - "$ok" "$BASE_URL" "$CHARGE_WEI" "${issues[@]:-}" <<'PY'
import json
import sys

ok = sys.argv[1].lower() == "true"
base_url = sys.argv[2]
charge = sys.argv[3]
issues = sys.argv[4:]
print(json.dumps({
    "schemaVersion": "trustchain.seller.doctor.v1",
    "ok": ok,
    "gateway": base_url,
    "chargeWei": charge,
    "issues": issues,
}, indent=2))
PY
else
  if [[ "$ok" == true ]]; then
    echo "PASS: trustchain doctor"
    echo "  gateway: ${BASE_URL}"
    echo "  chargeWei: ${CHARGE_WEI}"
  else
    echo "FAIL: trustchain doctor"
    echo "  gateway: ${BASE_URL}"
    for issue in "${issues[@]}"; do
      echo "  - ${issue}"
    done
  fi
fi

if [[ "$ok" == true ]]; then
  exit 0
fi
exit 2
