#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${ROOT_DIR}/logs/paid-calls.jsonl"
SUMMARY_FILE="${ROOT_DIR}/logs/external-user-call-summary.json"

usage() {
  cat <<'EOF'
Usage:
  ./simulate-external-user-call.sh [--host <url>] [--output <path>]

Description:
  Simulates one external user paid call by invoking:
    POST /api/price-paid?symbol=<pair>
  Then runs verify-first-paid-call.sh and writes a compact summary.

Options:
  --host <url>     API host base URL (default: http://127.0.0.1:8822)
  --symbol <pair>  Trading pair symbol, e.g. BTCUSDT (default: BTCUSDT)
  --output <path>  Output summary path (default: logs/external-user-call-summary.json)
  -h, --help       Show help.
EOF
}

HOST_URL="http://127.0.0.1:8822"
SYMBOL="BTCUSDT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      [[ $# -lt 2 ]] && { echo "Error: --host requires a value"; exit 1; }
      HOST_URL="$2"
      shift 2
      ;;
    --output)
      [[ $# -lt 2 ]] && { echo "Error: --output requires a value"; exit 1; }
      SUMMARY_FILE="$2"
      shift 2
      ;;
    --symbol)
      [[ $# -lt 2 ]] && { echo "Error: --symbol requires a value"; exit 1; }
      SYMBOL="$2"
      shift 2
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

mkdir -p "$(dirname "$SUMMARY_FILE")"

health_json="$(curl -sS "${HOST_URL}/api/health")"
if ! printf "%s" "$health_json" | python3 -c 'import json,sys; obj=json.load(sys.stdin); assert obj.get("ok") is True'; then
  echo "Health check failed at ${HOST_URL}/api/health"
  exit 2
fi

echo "Calling paid endpoint as external user simulation..."
paid_json="$(curl -sS -X POST "${HOST_URL}/api/price-paid?symbol=${SYMBOL}")"
if ! printf "%s" "$paid_json" | python3 -c 'import json,sys; obj=json.load(sys.stdin); assert obj.get("settlement",{}).get("txHash")'; then
  echo "Paid call failed or txHash missing."
  printf '%s\n' "$paid_json"
  exit 2
fi

verify_json="$("${ROOT_DIR}/verify-first-paid-call.sh" --json --log "$LOG_FILE")"

PAID_JSON="$paid_json" VERIFY_JSON="$verify_json" SYMBOL="$SYMBOL" python3 - "$SUMMARY_FILE" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

summary_path = pathlib.Path(sys.argv[1])
paid = json.loads(__import__("os").environ["PAID_JSON"])
verify = json.loads(__import__("os").environ["VERIFY_JSON"])
symbol = __import__("os").environ["SYMBOL"]

summary = {
    "schemaVersion": "karma.mvp.external-user-sim.v1",
    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "symbol": symbol,
    "callId": paid.get("callId"),
    "txHash": paid.get("settlement", {}).get("txHash"),
    "chargedWei": paid.get("settlement", {}).get("chargedWei"),
    "price": {
        "symbol": paid.get("price", {}).get("symbol"),
        "usd": paid.get("price", {}).get("usd"),
        "source": paid.get("price", {}).get("source"),
    },
    "verification": verify,
}
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
PY
