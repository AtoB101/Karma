#!/usr/bin/env bash
set -euo pipefail

# Generate CN integration report from scenario artifacts.
#
# Optional env vars:
# - OPENCLAW_RESULT_PATH   default: latest results/integration-openclaw-run-*.json
# - HERMES_RESULT_PATH     default: latest results/integration-hermes-run-*.json
# - REPORT_OUTPUT_PATH     default: docs/INTEGRATION_RESULTS_REPORT_CN.generated.txt
# - REPORT_OWNER           default: unknown

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"

latest_file() {
  local pattern="$1"
  local latest
  latest="$(ls -1t ${pattern} 2>/dev/null | head -n 1 || true)"
  echo "$latest"
}

OPENCLAW_RESULT_PATH="${OPENCLAW_RESULT_PATH:-$(latest_file "${RESULTS_DIR}/integration-openclaw-run-"*.json)}"
HERMES_RESULT_PATH="${HERMES_RESULT_PATH:-$(latest_file "${RESULTS_DIR}/integration-hermes-run-"*.json)}"
REPORT_OUTPUT_PATH="${REPORT_OUTPUT_PATH:-${ROOT_DIR}/docs/INTEGRATION_RESULTS_REPORT_CN.generated.txt}"
REPORT_OWNER="${REPORT_OWNER:-unknown}"

if [[ -z "${OPENCLAW_RESULT_PATH}" || -z "${HERMES_RESULT_PATH}" ]]; then
  echo "Missing scenario artifacts."
  echo "Need both:"
  echo "- results/integration-openclaw-run-*.json"
  echo "- results/integration-hermes-run-*.json"
  exit 1
fi

python3 - "$OPENCLAW_RESULT_PATH" "$HERMES_RESULT_PATH" "$REPORT_OUTPUT_PATH" "$REPORT_OWNER" <<'PY'
import json
import os
import sys
from datetime import datetime

openclaw_path, hermes_path, out_path, owner = sys.argv[1:]

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def run_id_from_path(path):
    base = os.path.basename(path)
    # integration-openclaw-run-001.json -> 001
    parts = base.replace(".json", "").split("-")
    return parts[-1] if parts else "unknown"

def pass_fail(data):
    return "PASS" if str(data.get("status", "")).lower() == "passed" else "FAIL"

def chk(data, key):
    return data.get("checkpoints", {}).get(key, "N/A")

openclaw = read_json(openclaw_path)
hermes = read_json(hermes_path)

failure_count = 0
if pass_fail(openclaw) != "PASS":
    failure_count += 1
if pass_fail(hermes) != "PASS":
    failure_count += 1

nc205_yes = (
    pass_fail(openclaw) == "PASS"
    and pass_fail(hermes) == "PASS"
    and bool(chk(openclaw, "buyerConsistent"))
    and bool(chk(openclaw, "sellerConsistent"))
    and bool(chk(hermes, "buyerConsistent"))
    and bool(chk(hermes, "sellerConsistent"))
)

content = f"""Karma 场景接入结果报告（OpenClaw + Hermes）

版本：v0.1
日期：{datetime.utcnow().strftime("%Y-%m-%d")}
执行人：{owner}

==================================================
1) 环境信息
==================================================
- Chain: {openclaw.get("chainId", "N/A")}
- RPC: (masked)
- NON_CUSTODIAL_ADDRESS: {openclaw.get("nonCustodialAddress", "N/A")}
- TOKEN_ADDRESS: {openclaw.get("tokenAddress", "N/A")}
- BUYER_ADDRESS: {openclaw.get("buyer", "N/A")}
- SELLER_ADDRESS: {openclaw.get("seller", "N/A")}

==================================================
2) OpenClaw 结果
==================================================
- 脚本：scripts/integration-openclaw-run.sh
- RUN_ID: {run_id_from_path(openclaw_path)}
- 产物：{os.path.relpath(openclaw_path, os.path.dirname(out_path))}
- 结论：{pass_fail(openclaw)}

关键字段：
- status: {openclaw.get("status", "N/A")}
- checkpoints.finalBillStatus: {chk(openclaw, "finalBillStatus")}
- checkpoints.finalBatchStatus: {chk(openclaw, "finalBatchStatus")}
- checkpoints.buyerConsistent: {chk(openclaw, "buyerConsistent")}
- checkpoints.sellerConsistent: {chk(openclaw, "sellerConsistent")}
- checkpoints.batchModeEnabled: {chk(openclaw, "batchModeEnabled")}
- checkpoints.batchCircuitBreakerPaused: {chk(openclaw, "batchCircuitBreakerPaused")}

==================================================
3) Hermes 结果
==================================================
- 脚本：scripts/integration-hermes-run.sh
- RUN_ID: {run_id_from_path(hermes_path)}
- 产物：{os.path.relpath(hermes_path, os.path.dirname(out_path))}
- 结论：{pass_fail(hermes)}

关键字段：
- status: {hermes.get("status", "N/A")}
- checkpoints.finalBillStatus: {chk(hermes, "finalBillStatus")}
- checkpoints.finalBatchStatus: {chk(hermes, "finalBatchStatus")}
- checkpoints.buyerConsistent: {chk(hermes, "buyerConsistent")}
- checkpoints.sellerConsistent: {chk(hermes, "sellerConsistent")}
- checkpoints.batchModeEnabled: {chk(hermes, "batchModeEnabled")}
- checkpoints.batchCircuitBreakerPaused: {chk(hermes, "batchCircuitBreakerPaused")}

==================================================
4) 问题与分类
==================================================
- 总失败数：{failure_count}
- 主要失败类型 Top3：
  1) 待补充（基于 diagnostics / tx logs）
  2) 待补充
  3) 待补充
- 已修复项：见近期提交与执行文档
- 待修复项：聚焦 NC-102 / NC-105 收尾

==================================================
5) 最终结论（是否进入下一阶段）
==================================================
- 是否达到 NC-205 验收：{"YES" if nc205_yes else "NO"}
- 依据：
  1) OpenClaw 可复现 run artifact
  2) Hermes 可复现 run artifact
  3) 失败原因可分类可追溯
- 下一步动作：
  - 若为 YES：进入对外案例发布与复测扩样
  - 若为 NO：先修复失败项后重跑两条场景
"""

os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Report generated: {out_path}")
PY

echo "Done."
echo "OpenClaw input: ${OPENCLAW_RESULT_PATH}"
echo "Hermes input  : ${HERMES_RESULT_PATH}"
echo "Output report : ${REPORT_OUTPUT_PATH}"
