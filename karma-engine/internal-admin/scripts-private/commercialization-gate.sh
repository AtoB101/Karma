#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/lib/common.sh"
OUTPUT_PATH="${ROOT_DIR}/results/commercialization-gate-latest.json"
FORMAT="text"
WORKSPACE_ROOT="$(cd "${ROOT_DIR}/../.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/commercialization-gate.sh [--output <path>] [--format <text|json>]

Description:
  Evaluate commercial-readiness baseline with MUST/SHOULD/CAN layers.
EOF
}

usage_if_requested "${1:-}" usage

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -lt 2 ]] && { echo "Error: --output requires a value"; exit 1; }
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --format)
      [[ $# -lt 2 ]] && { echo "Error: --format requires a value"; exit 1; }
      FORMAT="$2"
      if [[ "$FORMAT" != "text" && "$FORMAT" != "json" ]]; then
        echo "Error: --format must be text or json"
        exit 1
      fi
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

if [[ "$OUTPUT_PATH" != /* ]]; then
  OUTPUT_PATH="${ROOT_DIR}/${OUTPUT_PATH}"
fi
mkdir -p "$(dirname "$OUTPUT_PATH")"

python3 - "$ROOT_DIR" "$OUTPUT_PATH" "$FORMAT" <<'PY'
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

root = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
fmt = sys.argv[3]

def exists(rel):
    return (root / rel).exists()

def check_script_exec(rel):
    p = root / rel
    return p.exists() and p.is_file()

def run_ci_proof_gate():
    script = root / "scripts" / "ci-proof-gates.sh"
    if not script.exists():
        return False, "missing script"
    proc = subprocess.run(
        [str(script), "--format", "json"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode == 0, proc.stdout.strip()[-1000:]

must_checks = []
should_checks = []
can_checks = []

def add_check(bucket, name, ok, detail):
    bucket.append({"name": name, "ok": bool(ok), "detail": detail})

ci_ok, ci_detail = run_ci_proof_gate()
add_check(must_checks, "ci-proof-gates pass", ci_ok, ci_detail)
add_check(must_checks, "guardian script present", check_script_exec("scripts/agent-safety-guardian.sh"), "scripts/agent-safety-guardian.sh")
add_check(must_checks, "patrol script present", check_script_exec("scripts/proof-patrol.sh"), "scripts/proof-patrol.sh")
add_check(must_checks, "openapi contract present", (root.parent.parent / "openapi" / "karma-v1.yaml").exists(), f"{root.parent.parent}/openapi/karma-v1.yaml")
add_check(must_checks, "api server present", check_script_exec("scripts/api_server.py"), "scripts/api_server.py")
add_check(must_checks, "api smoke present", check_script_exec("scripts/api-smoke.sh"), "scripts/api-smoke.sh")

add_check(should_checks, "api roadmap doc present", (root.parent.parent / "docs" / "API_ROADMAP_V01.md").exists(), f"{root.parent.parent}/docs/API_ROADMAP_V01.md")
add_check(should_checks, "rule-gap model doc present", (root.parent.parent / "docs" / "RULE_GAP_RISK_MODEL_V01.md").exists(), f"{root.parent.parent}/docs/RULE_GAP_RISK_MODEL_V01.md")
add_check(should_checks, "proof SOP doc present", (root / "docs-private" / "PROOF_VERIFICATION_SOP.md").exists(), f"{root}/docs-private/PROOF_VERIFICATION_SOP.md")

add_check(can_checks, "support-bundle script present", check_script_exec("scripts/support-bundle.sh"), "scripts/support-bundle.sh")
add_check(can_checks, "proof index verifier present", check_script_exec("scripts/verify-proof-index.sh"), "scripts/verify-proof-index.sh")
add_check(can_checks, "proof batch verifier present", check_script_exec("scripts/verify-proof-index-batch.sh"), "scripts/verify-proof-index-batch.sh")
add_check(can_checks, "governance doc present", (root / "docs-private" / "community" / "GOVERNANCE_V01.md").exists(), f"{root}/docs-private/community/GOVERNANCE_V01.md")

must_ok = all(x["ok"] for x in must_checks)
should_warning_count = sum(1 for x in should_checks if not x["ok"])
can_missing_count = sum(1 for x in can_checks if not x["ok"])

if must_ok and should_warning_count == 0:
    overall = "commercial-ready"
elif must_ok:
    overall = "pilot-ready"
else:
    overall = "not-ready"

action_plan = []
if not must_ok:
    action_plan.append("Close all MUST failures before commercial release.")
if should_warning_count > 0:
    action_plan.append("Address SHOULD warnings to harden operational maturity.")
if can_missing_count > 0:
    action_plan.append("Prioritize CAN optimizations based on integration demand.")
if not action_plan:
    action_plan.append("Maintain current baseline and monitor regression via CI gate.")

generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
report = {
    "version": "commercialization-gate-v1",
    "schemaVersion": "karma.commercial.gate.v1",
    "generatedAt": generated_at,
    "source": "script:commercialization-gate.sh",
    "traceId": f"commercial-gate-{generated_at}",
    "overallStatus": overall,
    "must": {
        "ok": must_ok,
        "total": len(must_checks),
        "failCount": sum(1 for x in must_checks if not x["ok"]),
        "checks": must_checks,
    },
    "should": {
        "warningCount": should_warning_count,
        "total": len(should_checks),
        "checks": should_checks,
    },
    "can": {
        "missingCount": can_missing_count,
        "total": len(can_checks),
        "checks": can_checks,
    },
    "actionPlan": action_plan,
}

output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

if fmt == "json":
    print(json.dumps(report, indent=2))
else:
    print(f"status: {report['overallStatus']}")
    print(f"must.ok: {report['must']['ok']} (fail={report['must']['failCount']}/{report['must']['total']})")
    print(f"should.warnings: {report['should']['warningCount']}/{report['should']['total']}")
    print(f"can.missing: {report['can']['missingCount']}/{report['can']['total']}")
    print(f"output: {output_path}")
PY
