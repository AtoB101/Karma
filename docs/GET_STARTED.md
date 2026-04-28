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

If wallet cannot connect:
- Use `http://` URL (not `file://`)
- Check MetaMask unlocked and network matches deployed chain

If Health Check is blocked:
- Verify token balance
- Verify allowance to `NON_CUSTODIAL_ADDRESS`
- Verify addresses and chain

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

该命令会自动：
- 做环境与变量自检
- 执行部署
- 启动前端服务（8790 端口）
- 输出前端访问地址

### 第三步：打开前端

```text
http://127.0.0.1:8790/examples/v01-metamask-settlement.html
```

页面操作顺序：
1. Load config
2. Connect Wallet
3. Run Health Check
4. Batch control（可选）
