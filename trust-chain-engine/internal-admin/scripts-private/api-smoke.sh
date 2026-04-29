#!/usr/bin/env bash
set -euo pipefail

HOST="127.0.0.1"
PORT="8811"
TOKEN="${TRUSTCHAIN_API_TOKEN:-dev-token}"
BASE_URL="http://${HOST}:${PORT}"
API_PREFIX="${API_PREFIX:-/api/v1}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/api-smoke.sh [--host <host>] [--port <port>] [--token <token>]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"; BASE_URL="http://${HOST}:${PORT}"; shift 2 ;;
    --port)
      PORT="$2"; BASE_URL="http://${HOST}:${PORT}"; shift 2 ;;
    --token)
      TOKEN="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

curl_json() {
  local method="$1"
  local url="$2"
  local data="${3:-}"
  if [[ -n "$data" ]]; then
    curl -sS -X "$method" "$url" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -H "Idempotency-Key: smoke-test-123456" \
      -d "$data"
  else
    curl -sS -X "$method" "$url" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json"
  fi
}

HEALTH="$(curl -sS "${BASE_URL}${API_PREFIX}/health")"
python3 - <<'PY' "$HEALTH"
import json,sys
obj=json.loads(sys.argv[1])
assert obj["status"]=="ok"
print("health ok")
PY

CREATE_PAYLOAD='{"merchantRef":"ORDER-001","payer":"0x1111111111111111111111111111111111111111","payee":"0x2222222222222222222222222222222222222222","token":"USDT","amount":"1000000","chainId":11155111,"policyId":"policy-demo","expiresAt":"2030-01-01T00:00:00Z"}'
CREATED="$(curl_json POST "${BASE_URL}${API_PREFIX}/payment-intents" "$CREATE_PAYLOAD")"
INTENT_ID="$(python3 - <<'PY' "$CREATED"
import json,sys
obj=json.loads(sys.argv[1])
print(obj["intentId"])
PY
)"

GET_INTENT="$(curl_json GET "${BASE_URL}${API_PREFIX}/payment-intents/${INTENT_ID}")"
python3 - <<'PY' "$GET_INTENT" "$INTENT_ID"
import json,sys
obj=json.loads(sys.argv[1])
assert obj["intentId"]==sys.argv[2]
assert obj["status"]=="created"
print("intent query ok")
PY

EVIDENCE="$(curl_json GET "${BASE_URL}${API_PREFIX}/evidence/${INTENT_ID}")"
EVIDENCE_DIGEST="$(python3 - <<'PY' "$EVIDENCE"
import json,sys
obj=json.loads(sys.argv[1])
assert obj["schemaVersion"]=="evidence-v1"
print(obj["digestSha256"])
PY
)"

VERIFY_PAYLOAD="{\"expectedDigestSha256\":\"${EVIDENCE_DIGEST}\",\"expectedSchemaVersion\":\"evidence-v1\"}"
VERIFIED="$(curl_json POST "${BASE_URL}${API_PREFIX}/evidence/${INTENT_ID}/verify" "$VERIFY_PAYLOAD")"
python3 - <<'PY' "$VERIFIED"
import json,sys
obj=json.loads(sys.argv[1])
assert obj["verified"] is True
assert obj["checks"]["digestMatch"] is True
assert obj["checks"]["schemaVersionMatch"] is True
print("evidence verify ok")
PY

ALERTS="$(curl_json GET "${BASE_URL}${API_PREFIX}/risk/alerts")"
python3 - <<'PY' "$ALERTS"
import json,sys
obj=json.loads(sys.argv[1])
assert isinstance(obj.get("alerts"), list)
print(f"alerts={len(obj['alerts'])}")
PY

echo "API smoke passed"
