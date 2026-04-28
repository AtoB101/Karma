# TrustChain Commands Cheat Sheet (CN/EN)

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

### 3) Local CI checks

- `make ci-local`  
  CN: 本地 CI 门禁（本地 preflight + forge build + 核心测试），不要求 `.env`。  
  EN: Local CI gate (local preflight + forge build + focused tests), no `.env` required.

- `make ci-local-env`  
  CN: 与上面相同，但会加载 `.env` 做环境校验。  
  EN: Same as above, but loads `.env` for env validation.

### 4) Proof verification (frontend SOP)

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
- `./scripts/proof-sop-checklist.sh --operator <name> --reviewer <name> --ticket <id>`

## Frontend URL

After startup, open:

`http://127.0.0.1:8790/examples/v01-metamask-settlement.html`

If stale page appears, hard refresh:
- Windows/Linux: `Ctrl+F5`
- macOS: `Cmd+Shift+R`
