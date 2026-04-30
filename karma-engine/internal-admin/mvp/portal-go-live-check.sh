#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${MVP_PORT:-8822}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT}}"
TMP_DIR="${ROOT_DIR}/logs/go-live"
mkdir -p "${TMP_DIR}"

echo "[portal-go-live] base=${BASE_URL}"

check() {
  local name="$1"
  local cmd="$2"
  echo "- ${name}"
  if eval "${cmd}" >/dev/null 2>&1; then
    echo "  ok"
  else
    echo "  FAIL: ${name}" >&2
    return 1
  fi
}

check "dashboard reachable" "curl -fsS '${BASE_URL}/api/dashboard'"
check "agents endpoint reachable" "curl -fsS '${BASE_URL}/api/agents'"
check "bills endpoint reachable" "curl -fsS '${BASE_URL}/api/bills'"
check "deploy-readiness reachable" "curl -fsS '${BASE_URL}/api/deploy-readiness'"

python3 - <<'PY'
import json, urllib.request
base = "http://127.0.0.1:%s" % __import__("os").environ.get("MVP_PORT", "8822")
def req(path, method="GET", body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=8) as resp:
        return json.loads(resp.read().decode())

report = {"base": base, "checks": {}}

snap1 = req("/api/dashboard")["data"]
report["checks"]["initial_bills"] = len(snap1.get("bills", []))

created = req("/api/agents", "POST", {
    "name": "GoLiveCheckAgent",
    "description": "go-live check",
    "serviceType": "测试",
    "endpoint": "https://example.com",
    "price": 0.01,
    "token": "USDC",
    "wallet": "0xTEST"
})["data"]["item"]["id"]

snap2 = req("/api/dashboard")["data"]
report["checks"]["agent_create_reflected"] = any(a["id"] == created for a in snap2.get("agents", []))

pending = [b for b in snap2.get("bills", []) if b.get("status") == "PendingConfirm"]
if pending:
    bid = pending[0]["id"]
    req(f"/api/bills/{bid}/confirm", "POST", {})
    snap3 = req("/api/dashboard")["data"]
    report["checks"]["bill_confirm_to_settle"] = any(b["id"] == bid and b["status"] == "PendingSettle" for b in snap3.get("bills", []))
else:
    report["checks"]["bill_confirm_to_settle"] = True

before = snap2["summary"]["allowance"]["allowance"]
req("/api/allowance/increase", "POST", {"amount": 1})
after = req("/api/dashboard")["data"]["summary"]["allowance"]["allowance"]
report["checks"]["allowance_increase_reflected"] = (after - before) >= 1

ok = all(report["checks"].values())
report["readyForGoLive"] = ok
print(json.dumps(report, ensure_ascii=False, indent=2))

if not ok:
    raise SystemExit(2)
PY

echo "[portal-go-live] PASS"
