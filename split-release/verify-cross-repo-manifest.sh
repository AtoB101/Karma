#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_PATH="${1:-$ROOT_DIR/split-release/deployment-manifest.json}"

err() { echo "ERR  $*"; }
ok() { echo "OK   $*"; }

if [[ ! -f "$MANIFEST_PATH" ]]; then
  err "manifest file not found: $MANIFEST_PATH"
  err "copy split-release/templates/deployment-manifest.example.json to split-release/deployment-manifest.json and fill values"
  exit 1
fi

python3 - "$MANIFEST_PATH" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
data = json.loads(manifest_path.read_text())

required_root = [
    "manifestVersion",
    "environment",
    "core",
    "engine",
    "validation",
    "rollbackPlan",
]
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

core_commit = require(data, "core.commitSha")
engine_commit = require(data, "engine.commitSha")
core_tag = require(data, "core.versionTag")
engine_tag = require(data, "engine.versionTag")
compatible_core_tag = require(data, "engine.compatibleCoreTag")
settlement = require(data, "core.contracts.SettlementEngine")
payment = require(data, "core.contracts.NonCustodialAgentPayment")

hex40 = re.compile(r"^0x[a-fA-F0-9]{40}$")
sha_like = re.compile(r"^[a-fA-F0-9]{7,40}$")

if not sha_like.match(core_commit):
    raise SystemExit("core.commit must look like a git sha")
if not sha_like.match(engine_commit):
    raise SystemExit("engine.commit must look like a git sha")
if not hex40.match(settlement):
    raise SystemExit("core.contracts.SettlementEngine must be address format 0x + 40 hex chars")
if not hex40.match(payment):
    raise SystemExit("core.contracts.NonCustodialAgentPayment must be address format 0x + 40 hex chars")
if compatible_core_tag != core_tag:
    raise SystemExit("engine.compatibleCoreTag must match core.versionTag")
if not core_tag.startswith("core-v"):
    raise SystemExit("core.versionTag should start with core-v")
if not engine_tag.startswith("engine-v"):
    raise SystemExit("engine.versionTag should start with engine-v")

print("OK manifest schema and critical values validated")
PY

ok "cross-repo deployment manifest is valid: $MANIFEST_PATH"
