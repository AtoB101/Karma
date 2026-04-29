# TrustChain Quick Start (CN/EN)

This guide is the fastest path for first-time developers.

## 1) Copy environment template

```bash
cp .env.example .env
```

Edit `.env` and fill required variables:
- `ETH_RPC_URL`
- `DEPLOYER_PRIVATE_KEY`
- `ADMIN_ADDRESS`

Recommended:
- `TOKEN_ADDRESS`
- `PAYEE_ADDRESS`

## 2) One-command preflight + deploy + frontend

```bash
./scripts/dev-up.sh --from-env
```

or with Make:

```bash
make quickstart
```

What it does:
1. Runs environment checks (`forge`, `cast`, `python3`, required env).
2. Deploys non-custodial core with `scripts/deploy-v01-eth.sh`.
3. Starts local static frontend on `127.0.0.1:8790`.
4. Prints exact UI URL.

## 3) Open frontend

Open:

```text
http://127.0.0.1:8790/examples/v01-metamask-settlement.html
```

Use this order:
1. Load config
2. Connect Wallet
3. Run Health Check
4. Batch controls (optional)

## 4) Quick troubleshooting

If page looks stale:
- Hard refresh (`Ctrl+F5` or `Cmd+Shift+R`)
- Add timestamp query:
  `...?ts=<epoch>`

If setup still fails, generate diagnostics for support:

```bash
make doctor
```

This writes `results/doctor-report.txt`.

For one-step bundle packaging (text + JSON + key artifacts):

```bash
make support-bundle
```

This writes a zip file in `results/` (e.g. `support-bundle-YYYYmmdd-HHMMSS.zip`).

For local CI-style checks (build + focused tests):

```bash
make ci-local
```

If you also want environment validation via `.env`:

```bash
make ci-local-env
```

If wallet cannot connect:
- Use `http://` URL (not `file://`)
- Check MetaMask unlocked and network matches deployed chain

If Health Check is blocked:
- Verify token balance
- Verify allowance to `NON_CUSTODIAL_ADDRESS`
- Verify addresses and chain
- Run `make doctor` for text diagnostics
- Run `make doctor-json` for machine-readable diagnostics
- Run `make support-bundle` for one-file handoff
- Run `make ci-local` for local CI checks before opening a PR
- Run `make ci-local-env` if you also want `.env` preflight checks

## 5) 中文快速说明

### 第一步：配置环境变量
1. `cp .env.example .env`
2. 编辑 `.env`，至少填：
   - `ETH_RPC_URL`
   - `DEPLOYER_PRIVATE_KEY`
   - `ADMIN_ADDRESS`
3. 建议同时填 `TOKEN_ADDRESS` 和 `PAYEE_ADDRESS`

### 第二步：一键启动

```bash
./scripts/dev-up.sh --from-env
```

或者使用 Make：

```bash
make quickstart
```

该命令会自动：
- 做环境与变量自检
- 执行部署
- 启动前端服务（8790 端口）
- 输出前端访问地址
 - 如需排障：执行 `make doctor` 或 `make doctor-json`

如果仍然启动失败，执行：

```bash
make doctor
```

会生成 `results/doctor-report.txt`，可以直接发给支持同学排查。

如果你希望把诊断和关键产物打成一个压缩包，执行：

```bash
make support-bundle
```

会在 `results/` 下生成 `support-bundle-时间戳.zip`，可直接发送给支持同学。

如果你希望在本地跑一套“提交前检查”（构建 + 核心测试），执行：

```bash
make ci-local
```

如果你还希望同时做 `.env` 环境自检，执行：

```bash
make ci-local-env
```

### 第三步：打开前端

```text
http://127.0.0.1:8790/examples/v01-metamask-settlement.html
```

页面操作顺序：
1. Load config
2. Connect Wallet
3. Run Health Check
4. Batch control（可选）

---

Full command cheatsheet / 完整命令速查：
- `docs/COMMANDS.md`
- M1 acceptance checklist / M1 验收清单：
- `docs/M1_ACCEPTANCE_CHECKLIST.md`
