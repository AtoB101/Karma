# Karma Commands Cheat Sheet (CN/EN)

This page is a quick command index for daily development and support.

## Fast Start

```bash
cp .env.example .env
make quickstart
```

## Command Index

### 1) Developer onboarding

- `make quickstart`  
  CN: 从 `.env` 启动全流程（自检 + 部署 + 前端）。  
  EN: Full startup from `.env` (preflight + deploy + frontend).

- `make quickstart-skip-deploy`  
  CN: 跳过部署，仅启动前端（仍读取 `.env`）。  
  EN: Skip deploy, start frontend only (reads `.env`).

- `make preflight`  
  CN: 做环境与变量检查（读取 `.env`）。  
  EN: Run environment checks with `.env`.

### 2) Diagnostics and support

- `make doctor`  
  CN: 生成文本诊断：`results/doctor-report.txt`。  
  EN: Generate text diagnostics report.

- `make doctor-json`  
  CN: 生成机器可读诊断：`results/doctor-report.json`。  
  EN: Generate machine-readable diagnostics JSON.

- `make support-bundle`  
  CN: 一键打包排障 zip（doctor 文本+JSON+关键日志+proof SOP 执行单+proof-index 指纹索引+manifest digest）。  
  EN: Build one-click support zip bundle (doctor reports + key logs + proof SOP checklist + proof-index manifest + manifest digest).

- `make verify-proof-index`  
  CN: 校验 `results/` 下最新 support-bundle 的 `manifestDigest`（输出 pass/fail 与失败原因）。  
  EN: Verify manifest digest for latest support-bundle in `results/` (pass/fail with reason).

- `make verify-proof-index-batch`  
  CN: 批量校验目录下所有 support-bundle 的 `manifestDigest`，支持失败阈值、时间范围、最小样本量与最近通过时效门槛。  
  EN: Batch-verify support-bundle manifest digests with fail-threshold, time-window, minimum-sample, and recent-pass policies.

- `make validate-evidence-schema`  
  CN: 校验最新 diagnosis JSON 的证据结构版本与关键字段兼容性。  
  EN: Validate schema-version compatibility and required fields in latest diagnosis JSON.

- `make ci-proof-gates`  
  CN: 运行 M4.1 的证据/索引门禁（schema 兼容 + proof-index 批量策略）。  
  EN: Run M4.1 proof gates (schema compatibility + batch proof-index policies).
- `make ci-proof-gate`  
  CN: `make ci-proof-gates` 的兼容别名（便于旧脚本调用）。  
  EN: Compatibility alias of `make ci-proof-gates` for legacy automation.

- `make proof-patrol`  
  CN: 按巡检策略（strict/balanced/lenient）执行 proof-index 巡检并输出告警 JSON。  
  EN: Run profile-based proof patrol and emit alert-friendly JSON.

- `make agent-safety-guardian`  
  CN: 运行全链路 Agent 安全管家（自检 + 证据兼容 + proof 巡检 + 风险分级登记）。  
  EN: Run end-to-end Agent safety guardian (self-check + evidence compatibility + proof patrol + risk registry).
- `make guardian`  
  CN: `make agent-safety-guardian` 的兼容别名（便于旧脚本调用）。  
  EN: Compatibility alias of `make agent-safety-guardian` for legacy automation.

- `make rule-gap-adversarial-sim`  
  CN: 运行规则漏洞对抗模拟，生成“利用规则”攻击场景与风险评分报告。  
  EN: Run rule-gap adversarial simulation and export exploit-oriented risk report.

- `make commercialization-gate`  
  CN: 运行商用准入门禁（MUST/SHOULD/CAN 分层），输出 `commercial-ready` / `pilot-ready` / `not-ready` 结论。  
  EN: Run commercialization readiness gate (MUST/SHOULD/CAN layers) and output `commercial-ready` / `pilot-ready` / `not-ready`.

- `make validate-output-contracts`  
  CN: 校验关键 JSON 输出是否包含统一契约字段（`schemaVersion/generatedAt/source/traceId`）。  
  EN: Validate required unified output contract fields (`schemaVersion/generatedAt/source/traceId`) in core JSON artifacts.

- `make slither-gate`  
  CN: 运行 Slither 静态分析门禁（未安装 Slither 会给出安装提示并返回非零）。  
  EN: Run Slither static-analysis gate (returns non-zero with installation guidance if Slither is missing).

- `make system-status`  
  CN: 聚合商用门禁、巡检、安全管家、契约校验状态，生成系统健康视图。  
  EN: Aggregate commercialization/patrol/guardian/contract status into a system health snapshot.

- `make ops-summary`  
  CN: 一条命令生成运维摘要（自动刷新关键产物，输出总体健康、告警级别与 runbook 建议）。  
  EN: One-command operational summary (refreshes core artifacts and prints health, alert level, and runbook actions).

- `make ops-alert`  
  CN: 导出告警工件 JSON（用于对接 IM/告警平台），输出 severity/priority/channel 与 nextActions。  
  EN: Export alert artifact JSON for ChatOps/on-call integrations with severity/priority/channel and nextActions.

- `make release-readiness`  
  CN: 发版前总门禁（一条命令串行执行：commercialization/proof-gates/patrol/guardian/contracts/system-status/ops-alert，任一失败即阻断）。  
  EN: Pre-release master gate (single command runs commercialization/proof-gates/patrol/guardian/contracts/system-status/ops-alert; any failure blocks release).

- `Security CI workflow` (`.github/workflows/security-ci.yml`)  
  CN: PR 自动执行 `forge test + slither-gate + release-readiness` 三段阻断，任一失败即阻断合并。  
  EN: PR auto-runs `forge test + slither-gate + release-readiness`; any failure blocks merge.

### 3) Local CI checks

- `make ci-local`  
  CN: 本地 CI 门禁（本地 preflight + forge build + 核心测试），不要求 `.env`。  
  EN: Local CI gate (local preflight + forge build + focused tests), no `.env` required.

- `make ci-local-env`  
  CN: 与上面相同，但会加载 `.env` 做环境校验。  
  EN: Same as above, but loads `.env` for env validation.

### 4) O1 grouped command entrypoints (new)

- `make ops-doctor`  
  CN: 生成诊断文本报告（分层入口，等价 `make doctor`）。  
  EN: Generate diagnostics text report (grouped entry, alias of `make doctor`).

- `make ops-bundle`  
  CN: 生成支持包（分层入口，等价 `make support-bundle`）。  
  EN: Build support bundle (grouped entry, alias of `make support-bundle`).

- `make ops-commercial-gate`  
  CN: 运行商用准入门禁（分层入口，等价 `make commercialization-gate`）。  
  EN: Run commercial readiness gate (grouped entry, alias of `make commercialization-gate`).

- `make ops-summary`  
  CN: 运行运维摘要（分层入口，一次输出系统健康概览）。  
  EN: Run ops summary (grouped entry for one-shot system health overview).

- `make ops-alert`  
  CN: 导出标准运维告警工件（分层入口，便于后续告警通道接入）。  
  EN: Export standardized ops alert artifact (grouped entry for alert channel integrations).

- `make safety-gates`  
  CN: 运行证据/索引门禁（分层入口，等价 `make ci-proof-gates`）。  
  EN: Run proof/evidence gates (grouped entry, alias of `make ci-proof-gates`).

- `make safety-patrol`  
  CN: 运行巡检策略（分层入口，等价 `make proof-patrol`）。  
  EN: Run patrol profile (grouped entry, alias of `make proof-patrol`).

- `make safety-guardian`  
  CN: 运行安全管家（分层入口，等价 `make agent-safety-guardian`）。  
  EN: Run safety guardian (grouped entry, alias of `make agent-safety-guardian`).

- `make safety-adversarial-sim`  
  CN: 运行规则漏洞对抗模拟（分层入口，等价 `make rule-gap-adversarial-sim`）。  
  EN: Run rule-gap adversarial simulation (grouped entry, alias of `make rule-gap-adversarial-sim`).

- `make api-serve`  
  CN: 启动 API 服务（分层入口，等价 `make api-run`）。  
  EN: Start API service (grouped entry, alias of `make api-run`).

- `make api-check`  
  CN: 运行 API 冒烟测试（分层入口，等价 `make api-smoke`）。  
  EN: Run API smoke tests (grouped entry, alias of `make api-smoke`).

### 5) Proof verification (frontend SOP)

- `python3 -m http.server 8790`  
  CN: 启动前端控制台，用于离线验链/验签流程。  
  EN: Start frontend console for offline chain/signature verification flow.

- Open `http://127.0.0.1:8790/examples/v01-metamask-settlement.html`  
  CN: 在导出面板依次执行：
  1) Verify from JSON file  
  2) Export stable proof  
  3) (可选) Sign stable proof  
  4) Verify proof signature  
  EN: In export panel run:
  1) Verify from JSON file  
  2) Export stable proof  
  3) (optional) Sign stable proof  
  4) Verify proof signature

- SOP 文档 / SOP doc: `docs/PROOF_VERIFICATION_SOP.md`

- `make proof-sop-checklist`  
  CN: 生成可归档 SOP 执行记录模板（Markdown）。  
  EN: Generate archivable SOP execution record template (Markdown).

## Direct Script Usage

- `./scripts/dev-up.sh --from-env`
- `./scripts/preflight.sh --from-env`
- `./scripts/preflight.sh --mode local`
- `./scripts/doctor.sh --port 8790`
- `./scripts/doctor.sh --format json --output results/doctor-report.json`
- `./scripts/support-bundle.sh --port 8790`
- `./scripts/support-bundle.sh --port 8790 --operator "alice@ops" --reviewer "bob@audit" --ticket "INC-2026-0428-01"`
- `./scripts/verify-proof-index.sh --path results/support-bundle-<timestamp>.zip`
- `./scripts/verify-proof-index-batch.sh --dir results --glob "support-bundle-*.zip" --format json --output results/proof-index-batch.json`
- `./scripts/verify-proof-index-batch.sh --dir results --glob "support-bundle-*.zip" --format csv --output results/proof-index-batch.csv`
- `./scripts/verify-proof-index-batch.sh --dir results --glob "support-bundle-*.zip" --strict --max-fail 0`
- `./scripts/verify-proof-index-batch.sh --dir results --since "2026-04-28T12:00:00Z" --until "2026-04-28T13:00:00Z"`
- `./scripts/verify-proof-index-batch.sh --dir results --min-total 3 --require-recent-pass 24`
- 批量 JSON 报告新增聚合字段 / Batch JSON report includes aggregates:
  - `latestPassAt`
  - `reasonSummary`
- 批量 JSON 报告新增策略字段 / Batch JSON report includes policy fields:
  - `minTotal`
  - `requireRecentPassHours`
  - `recentPassThreshold`
  - `policy`
  - `ok`
- `./scripts/ci-local.sh`
- `./scripts/ci-local.sh --from-env`
- `./scripts/ci-proof-gates.sh`
- `./scripts/ci-proof-gates.sh --format json`
- `./scripts/proof-sop-checklist.sh --operator <name> --reviewer <name> --ticket <id>`
- `./scripts/validate-evidence-schema.sh --path results/karma-v01-diagnosis-<timestamp>.json`
- `./scripts/proof-patrol.sh --profile strict --dir results --batch-output results/proof-patrol-batch-strict.json --alert-output results/proof-patrol-alert-strict.json`
- `./scripts/proof-patrol.sh --profile balanced --since "2026-04-28T00:00:00Z" --until "2026-04-28T23:59:59Z"`
- `./scripts/agent-safety-guardian.sh --profile strict --output results/agent-safety-guardian-strict.json --register results/agent-risk-register.json`
- `./scripts/agent-safety-guardian.sh --profile balanced --trend-window-hours 24 --escalate-repeat-threshold 2`
- `./scripts/agent-safety-guardian.sh --profile balanced --auto-apply-recommendation --auto-confirm-runs 2 --auto-state results/agent-safety-autotune-state.json`
- `./scripts/agent-safety-guardian.sh --profile balanced --alert-threshold medium --alarm-output results/agent-safety-alarm-latest.json --fail-on-alarm`
- `./scripts/rule-gap-adversarial-sim.sh --output results/rule-gap-adversarial-latest.json`
- `./scripts/commercialization-gate.sh --format text`
- `./scripts/commercialization-gate.sh --format json --output results/commercialization-gate-latest.json`
- `./scripts/validate-output-contracts.sh --format text`
- `./scripts/validate-output-contracts.sh --format json`
- `./scripts/slither-gate.sh --format text`
- `./scripts/slither-gate.sh --format json --output results/slither-gate-latest.json`
- `./scripts/system-status.sh --format text`
- `./scripts/system-status.sh --format json --output results/system-status-latest.json`
- `./scripts/ops-summary.sh`
- `./scripts/ops-alert.sh --input results/system-status-latest.json --output results/ops-alert-latest.json --format text`
- `./scripts/ops-alert.sh --input results/system-status-latest.json --output results/ops-alert-latest.json --format json`
- `./scripts/release-readiness.sh`
- `./scripts/system-status.sh --format json | jq '.summary'`
- `./scripts/api_server.py --host 127.0.0.1 --port 8811 --token dev-token`
- `./scripts/api-smoke.sh --host 127.0.0.1 --port 8811 --token dev-token`

## Frontend URL

After startup, open:

`http://127.0.0.1:8790/examples/v01-metamask-settlement.html`

If stale page appears, hard refresh:
- Windows/Linux: `Ctrl+F5`
- macOS: `Cmd+Shift+R`
