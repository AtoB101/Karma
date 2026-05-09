#!/usr/bin/env bash
set -euo pipefail

MANIFEST_PATH=""
LOCK_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      MANIFEST_PATH="$2"
      shift 2
      ;;
    --lock)
      LOCK_PATH="$2"
      shift 2
      ;;
    *)
      echo "ERR  unknown argument: $1" >&2
      echo "Usage: ./verify-manifest.sh --manifest <deployment-manifest.json> --lock <CORE_VERSION.lock>"
      exit 1
      ;;
  esac
done

if [[ -z "$MANIFEST_PATH" || -z "$LOCK_PATH" ]]; then
  echo "ERR  --manifest and --lock are required" >&2
  echo "Usage: ./verify-manifest.sh --manifest <deployment-manifest.json> --lock <CORE_VERSION.lock>"
  exit 1
fi

python3 - "$MANIFEST_PATH" "$LOCK_PATH" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
lock_path = Path(sys.argv[2])

if not manifest_path.exists():
    raise SystemExit(f"manifest not found: {manifest_path}")
if not lock_path.exists():
    raise SystemExit(f"lock file not found: {lock_path}")

data = json.loads(manifest_path.read_text())

required_root = ["manifestVersion", "environment", "releaseTag", "core", "engine", "deployment", "validation", "rollback"]
for key in required_root:
    if key not in data:
        raise SystemExit(f"missing root key: {key}")

def require(obj, path):
    cur = obj
    for part in path.split("."):
        if part not in cur:
            raise SystemExit(f"missing key: {path}")
        cur = cur[part]
    if cur in ("", None):
        raise SystemExit(f"empty value: {path}")
    return cur

core_tag = require(data, "core.versionTag")
core_commit = require(data, "core.commit")
engine_commit = require(data, "engine.commit")
chain_id = str(require(data, "deployment.chainId"))
settlement = require(data, "deployment.contracts.settlementEngine")
payment = require(data, "deployment.contracts.nonCustodialAgentPayment")

sha_like = re.compile(r"^[a-fA-F0-9]{7,40}$")
hex40 = re.compile(r"^0x[a-fA-F0-9]{40}$")

if not sha_like.match(core_commit):
    raise SystemExit("core.commit must look like git sha")
if not sha_like.match(engine_commit):
    raise SystemExit("engine.commit must look like git sha")
if chain_id not in {"1", "11155111"}:
    raise SystemExit("deployment.chainId must be 1 or 11155111")
if not hex40.match(settlement):
    raise SystemExit("deployment.contracts.settlementEngine must be 0x + 40 hex chars")
if not hex40.match(payment):
    raise SystemExit("deployment.contracts.nonCustodialAgentPayment must be 0x + 40 hex chars")

lock_map = {}
for raw in lock_path.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    lock_map[k.strip()] = v.strip()

lock_tag = lock_map.get("CORE_TAG")
lock_commit = lock_map.get("CORE_COMMIT")
if not lock_tag or not lock_commit:
    raise SystemExit("CORE_TAG and CORE_COMMIT must exist in lock file")
if lock_tag != core_tag:
    raise SystemExit(f"core tag mismatch: lock={lock_tag} manifest={core_tag}")
if lock_commit != core_commit:
    raise SystemExit(f"core commit mismatch: lock={lock_commit} manifest={core_commit}")

print("OK manifest + lock alignment validated")
PY

echo "OK   verify-manifest passed"
