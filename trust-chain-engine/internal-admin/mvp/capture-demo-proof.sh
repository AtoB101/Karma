#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

OUT_DIR="logs/proofs"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_PATH="${OUT_DIR}/demo-proof-${TIMESTAMP}.json"
SUMMARY_PATH="logs/external-user-call-summary.json"
CALL_LOG_PATH="logs/paid-calls.jsonl"

usage() {
  cat <<'EOF'
Usage:
  ./capture-demo-proof.sh [--summary <path>] [--calls <path>] [--out <path>]

Description:
  Captures a compact, auditable demo proof artifact from the latest paid call:
  - external user summary (if exists)
  - latest paid call record
  - balance deltas + txHash

Options:
  --summary <path>  External summary JSON path (default: logs/external-user-call-summary.json)
  --calls <path>    Paid calls JSONL path (default: logs/paid-calls.jsonl)
  --out <path>      Output proof JSON path (default: logs/proofs/demo-proof-<timestamp>.json)
  -h, --help        Show help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --summary)
      [[ $# -lt 2 ]] && { echo "Error: --summary requires a value" >&2; exit 1; }
      SUMMARY_PATH="$2"
      shift 2
      ;;
    --calls)
      [[ $# -lt 2 ]] && { echo "Error: --calls requires a value" >&2; exit 1; }
      CALL_LOG_PATH="$2"
      shift 2
      ;;
    --out)
      [[ $# -lt 2 ]] && { echo "Error: --out requires a value" >&2; exit 1; }
      OUT_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f "$CALL_LOG_PATH" ]]; then
  echo "Missing paid call log: $CALL_LOG_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT_PATH")"

python3 - "$SUMMARY_PATH" "$CALL_LOG_PATH" "$OUT_PATH" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

summary_path = pathlib.Path(sys.argv[1])
calls_path = pathlib.Path(sys.argv[2])
out_path = pathlib.Path(sys.argv[3])

summary_obj = None
if summary_path.exists():
    try:
        summary_obj = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        summary_obj = {"warning": "invalid-summary-json", "path": str(summary_path)}

lines = [ln.strip() for ln in calls_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
if not lines:
    raise SystemExit(f"No call records found in: {calls_path}")

latest = json.loads(lines[-1])

user_before = int(latest["balances"]["user"]["beforeWei"])
user_after = int(latest["balances"]["user"]["afterWei"])
provider_before = int(latest["balances"]["provider"]["beforeWei"])
provider_after = int(latest["balances"]["provider"]["afterWei"])

artifact = {
    "schemaVersion": "trustchain.mvp.demo-proof.v1",
    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "source": "script:capture-demo-proof.sh",
    "traceId": f"proof-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    "proof": {
        "callId": latest.get("callId"),
        "txHash": latest.get("txHash"),
        "chainId": latest.get("chainId"),
        "symbol": latest.get("symbol"),
        "base": latest.get("base"),
        "quote": latest.get("quote"),
        "exchange": latest.get("exchange"),
        "chargedWei": latest.get("chargedWei"),
        "price": latest.get("price"),
        "userBalanceDeltaWei": str(user_after - user_before),
        "providerBalanceDeltaWei": str(provider_after - provider_before),
        "userBalanceBeforeWei": str(user_before),
        "userBalanceAfterWei": str(user_after),
        "providerBalanceBeforeWei": str(provider_before),
        "providerBalanceAfterWei": str(provider_after),
        "completedAt": latest.get("completedAt"),
    },
    "externalSummary": summary_obj,
}

out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
print(json.dumps({
    "ok": True,
    "output": str(out_path),
    "txHash": artifact["proof"]["txHash"],
    "chargedWei": artifact["proof"]["chargedWei"],
}, indent=2))
PY
