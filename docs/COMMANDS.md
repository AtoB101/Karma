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
  CN: 一键打包排障 zip（doctor 文本+JSON+关键日志）。  
  EN: Build one-click support zip bundle.

### 3) Local CI checks

- `make ci-local`  
  CN: 本地 CI 门禁（本地 preflight + forge build + 核心测试），不要求 `.env`。  
  EN: Local CI gate (local preflight + forge build + focused tests), no `.env` required.

- `make ci-local-env`  
  CN: 与上面相同，但会加载 `.env` 做环境校验。  
  EN: Same as above, but loads `.env` for env validation.

- `make security-baseline-guard`
  CN: 公开仓库敏感内容门禁扫描（文件名 + 内容规则）。
  EN: Public repo sensitive-content guard (filename + content rules).

- `make private-repo-sync`
  CN: 将敏感核心内容同步到私有子仓库（默认 `../karma-internal`）。
  EN: Sync sensitive assets to private sub-repository (default `../karma-internal`).

## Direct Script Usage

- `./scripts/dev-up.sh --from-env`
- `./scripts/preflight.sh --from-env`
- `./scripts/preflight.sh --mode local`
- `./scripts/doctor.sh --port 8790`
- `./scripts/doctor.sh --format json --output results/doctor-report.json`
- `./scripts/support-bundle.sh --port 8790`
- `./scripts/ci-local.sh`
- `./scripts/ci-local.sh --from-env`
- `./scripts/security-baseline-guard.sh`
- `./scripts/private-repo-sync.sh ../karma-internal`

## Frontend URL

After startup, open:

`http://127.0.0.1:8790/examples/v01-metamask-settlement.html`

If stale page appears, hard refresh:
- Windows/Linux: `Ctrl+F5`
- macOS: `Cmd+Shift+R`
