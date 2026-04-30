#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${ROOT_DIR}/logs/paid-calls.jsonl"

usage() {
  cat <<'EOF'
Usage:
  ./verify-first-paid-call.sh [--log <path>] [--min-delta-wei <int>] [--json]

Description:
  Verifies the latest paid-call record has:
  1) non-empty txHash
  2) positive chargedWei
  3) user balance decreased by at least min-delta-wei
  4) provider balance increased by at least min-delta-wei

Options:
  --log <path>          Custom paid-calls log file path.
  --min-delta-wei <n>   Minimum wei delta expected (default: 1).
  --json                Print machine-readable JSON result.
  -h, --help            Show help.
EOF
}

MIN_DELTA_WEI="1"
JSON_MODE="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --log)
      [[ $# -lt 2 ]] && { echo "Error: --log requires value" >&2; exit 1; }
      LOG_FILE="$2"
      shift 2
      ;;
    --min-delta-wei)
      [[ $# -lt 2 ]] && { echo "Error: --min-delta-wei requires value" >&2; exit 1; }
      MIN_DELTA_WEI="$2"
      shift 2
      ;;
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

if [[ ! "$MIN_DELTA_WEI" =~ ^[0-9]+$ ]]; then
  echo "Error: --min-delta-wei must be non-negative integer" >&2
  exit 1
fi

if [[ ! -f "$LOG_FILE" ]]; then
  if [[ "$JSON_MODE" == "1" ]]; then
    printf '{"ok":false,"reason":"log_not_found","logFile":"%s"}\n' "$LOG_FILE"
  else
    echo "FAIL: log file not found: $LOG_FILE"
  fi
  exit 2
fi

python3 - "$LOG_FILE" "$MIN_DELTA_WEI" "$JSON_MODE" <<'PY'
import json
import pathlib
import sys

log_file = pathlib.Path(sys.argv[1])
min_delta = int(sys.argv[2])
json_mode = sys.argv[3] == "1"

lines = [ln.strip() for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
if not lines:
    payload = {"ok": False, "reason": "log_empty", "logFile": str(log_file)}
    print(json.dumps(payload) if json_mode else f"FAIL: log file is empty: {log_file}")
    sys.exit(2)

try:
    rec = json.loads(lines[-1])
except Exception as e:
    payload = {"ok": False, "reason": "invalid_json_line", "error": str(e)}
    print(json.dumps(payload) if json_mode else f"FAIL: invalid JSON in latest line: {e}")
    sys.exit(2)

def to_int(v, name):
    try:
        return int(v)
    except Exception:
        raise ValueError(f"{name} is not an integer: {v}")

tx_hash = str(rec.get("txHash", "")).strip()
charged_wei = to_int(rec.get("chargedWei", "0"), "chargedWei")

u_before = to_int(rec.get("balances", {}).get("user", {}).get("beforeWei", "0"), "user.beforeWei")
u_after = to_int(rec.get("balances", {}).get("user", {}).get("afterWei", "0"), "user.afterWei")
p_before = to_int(rec.get("balances", {}).get("provider", {}).get("beforeWei", "0"), "provider.beforeWei")
p_after = to_int(rec.get("balances", {}).get("provider", {}).get("afterWei", "0"), "provider.afterWei")

user_delta = u_before - u_after
provider_delta = p_after - p_before

checks = {
    "txHashPresent": len(tx_hash) > 0,
    "chargedWeiPositive": charged_wei > 0,
    "userBalanceDecreased": user_delta >= min_delta,
    "providerBalanceIncreased": provider_delta >= min_delta,
}
ok = all(checks.values())

result = {
    "ok": ok,
    "schemaVersion": "karma.mvp.first-paid-call.verify.v1",
    "logFile": str(log_file),
    "callId": rec.get("callId"),
    "txHash": tx_hash,
    "chargedWei": str(charged_wei),
    "userDeltaWei": str(user_delta),
    "providerDeltaWei": str(provider_delta),
    "minDeltaWei": str(min_delta),
    "checks": checks,
}

if json_mode:
    print(json.dumps(result, ensure_ascii=True))
else:
    status = "PASS" if ok else "FAIL"
    print(f"{status}: first-paid-call verification")
    print(f"  txHash: {tx_hash}")
    print(f"  chargedWei: {charged_wei}")
    print(f"  userDeltaWei: {user_delta}")
    print(f"  providerDeltaWei: {provider_delta}")
    for k, v in checks.items():
        print(f"  - {k}: {'ok' if v else 'fail'}")

sys.exit(0 if ok else 2)
PY
