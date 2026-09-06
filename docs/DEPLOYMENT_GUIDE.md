# Karma 部署说明书（生产环境）

> 适用版本：`feat/console-profile-binding-ui`（一卡多身份 P1–P3 已落地）
> 目标：把 Karma 部署到服务器，跑通「官网/操作台 → API → 链上结算」。

---

## 1. 架构概览

| 组件 | 作用 | 技术 |
|---|---|---|
| Karma API | 核心业务（身份/档案/凭证/结算/回执/容量） | FastAPI + SQLAlchemy async |
| Celery worker | 异步上链（lock/bind/settle/finalize） | Celery + Redis |
| Celery beat | 定时任务（finalize/reconcile/sweep） | Celery |
| Redis | 任务队列 broker/result + 限流 | Redis |
| PostgreSQL | 业务数据库 | SQLAlchemy async + Alembic |
| MinIO | 对象存储（evidence / receipts bundle） | MinIO / S3 |
| 链上合约 | KarmaBilateral（托管 + 1:1 bill 锚定） | Solidity / Foundry |
| Console（操作台） | 用户操作界面 | 静态 HTML/JS（`apps/console`） |

---

## 2. 环境要求

- **Python 3.11+**（建议 3.11/3.12）
- **Node.js 18+**（仅 console 本地预览需要）
- **Foundry**（`forge`，用于编译/部署合约）
- **Redis** 7.x
- **PostgreSQL** 14+
- **MinIO**（或任意 S3 兼容对象存储）
- 可选：**nginx / Caddy** 做反向代理 + TLS

---

## 3. 安装依赖

```bash
cd /opt/karma
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"                    # 核心 + 测试依赖
# 如需 BFF：
pip install -r requirements-bff.txt
```

编译合约（如需重新部署链上合约）：

```bash
forge build          # 产物在 out/KarmaBilateral.sol/KarmaBilateral.json
forge test           # 合约单测
```

---

## 4. 配置 `.env`

复制 `.env.example` 为 `.env`，按生产要求填。**关键配置**：

```ini
# ── 基础 ──
APP_ENV=production
APP_SECRET_KEY=<强随机密钥>
APP_HOST=0.0.0.0
APP_PORT=8000

# ── 认证（生产必填，见第 8 节校验）──
AUTH_ENFORCE_PROTECTED_ROUTES=true
AUTH_API_KEYS=agent-1:<强密钥>,agent-2:<强密钥>
AUTH_ALLOW_DEV_KEY_FALLBACK=false
ADMIN_ACTOR_IDS=<管理员 identity_id 列表>
ARBITRATOR_ACTOR_IDS=<仲裁员 identity_id 列表>

# ── 数据库 / Redis / MinIO ──
DATABASE_URL=postgresql+asyncpg://karma:<密码>@localhost:5432/karma_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/3
CELERY_RESULT_BACKEND=redis://localhost:6379/4
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=<非默认>
MINIO_SECRET_KEY=<非默认>

# ── CORS ──
CORS_ALLOW_ORIGINS=https://你的控制台域名

# ── 结算模式：offchain | testnet | hybrid ──
SETTLEMENT_MODE=testnet

# ── 链上 ──
TESTNET_RPC_URL=<Sepolia/主网 RPC>
TESTNET_CHAIN_ID=11155111
KARMA_BILATERAL_ADDRESS=<部署后的 KarmaBilateral 地址>
ERC20_TOKEN_ADDRESS=<USDC 地址>
SETTLEMENT_TOKEN_DECIMALS=6
# 生产必须 false：后端热钱包不得充当托管付款方
CHAIN_ALLOW_HOT_WALLET_PAYER=false
# 付款方签名后端：生产只允许 client_only 或 external
KARMA_SIGNING_BACKEND=client_only
# 生产建议启用 EIP-712 凭证/交易签名
VOUCHER_REQUIRE_EIP712=true
TRADE_LAUNCH_REQUIRE_EIP712=true
X402_PAYMENT_BACKEND=live   # 生产不允许 mock

# ── Runtime Key（生产必填）──
RUNTIME_REQUIRE_SAVED_AUTOMATION_POLICY=true
RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS=true
RUNTIME_REQUIRE_HANDOFF_ATTESTATION=true
RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING=true
RUNTIME_DAILY_SPEND_PERSIST=true

# ── 回执 / 账本安全 ──
RECEIPT_REQUIRE_SIGNATURE=true
LEDGER_REQUIRE_PARTY_ACTOR=true
SETTLEMENT_REQUIRE_PARTY_ACTOR=true
RATE_LIMIT_REDIS_FAIL_CLOSED=true

# ── 签名密钥（Ed25519，回执签名）──
ED25519_PRIVATE_KEY_PATH=./keys/agent_private.pem
ED25519_PUBLIC_KEY_PATH=./keys/agent_public.pem
```

> 生产校验：`config/settings.py` 内置 `_reject_default_secrets_in_production`，`APP_ENV=production` 时上述安全项缺失/为默认值会直接拒绝启动。请务必逐项核对。

---

## 5. 数据库迁移

```bash
source .venv/bin/activate
alembic upgrade head
```

> 迁移文件在 `db/migrations/versions/`（001–0037）。生产必须用 Alembic（不是 `create_all`）。

---

## 6. 部署链上合约（KarmaBilateral）

1. 编译：`forge build`（产物 `out/KarmaBilateral.sol/KarmaBilateral.json`）。
2. 部署（以 seller/管理员钱包部署）：
   ```bash
   forge create karma-core/src/KarmaBilateral.sol:KarmaBilateral \
     --rpc-url $TESTNET_RPC_URL \
     --private-key $ADMIN_KEY \
     --constructor-args <admin_address>
   ```
3. 部署后初始化（管理员）：
   - `setTokenAllowed(USDC, true)`
   - `setDisputeWindow(0)` / `setOptimisticDisputeWindow(0)`（如需快速结算；生产按业务设值）
4. 把部署地址写入 `.env` 的 `KARMA_BILATERAL_ADDRESS`。

参考脚本：`scripts/e2e_bilateral_sepolia.py`（真链 E2E）、`scripts/testnet_full_bilateral.py`（全量链上测试）。

---

## 7. 启动服务

建议用 **systemd**（或 Docker/进程管理器）托管：

```bash
# 1) API
uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers 4
# 或使用 entry point：karma-api

# 2) Celery worker（上链任务）
celery -A worker.tasks worker --loglevel=INFO --pool=solo
# 或：karma-worker

# 3) Celery beat（定时 finalize/reconcile/sweep）
celery -A worker.tasks beat --loglevel=INFO
```

---

## 8. 前端（操作台）部署

操作台是纯静态站点（`apps/console/`），核心页 = `pages/cyber/index.html`。

**nginx 示例**（把 `/console/` 映射到静态目录）：

```nginx
server {
    listen 443 ssl;
    server_name console.example.com;

    location /console/ {
        alias /opt/karma/apps/console/;
        index index.html;
        try_files $uri $uri/ =404;
    }
    # 反向代理 API
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

本地预览：`python3 -m http.server 8787`（在 `apps/console/` 下），打开 `http://127.0.0.1:8787/pages/cyber/index.html`。

---

## 9. 生产安全检查清单（上线前必过）

- [ ] `APP_ENV=production`
- [ ] `APP_SECRET_KEY` 强随机，非默认值
- [ ] `AUTH_ENFORCE_PROTECTED_ROUTES=true`
- [ ] `AUTH_API_KEYS` 至少一个 agent key
- [ ] `AUTH_ALLOW_DEV_KEY_FALLBACK=false`
- [ ] `RATE_LIMIT_REDIS_FAIL_CLOSED=true`
- [ ] `RUNTIME_REQUIRE_*` 全部 true
- [ ] `ARBITRATOR_ACTOR_IDS` 非空
- [ ] `CHAIN_ALLOW_HOT_WALLET_PAYER=false`（后端热钱包不碰资金）
- [ ] `KARMA_SIGNING_BACKEND=client_only|external`
- [ ] `RECEIPT_REQUIRE_SIGNATURE / LEDGER_REQUIRE_PARTY_ACTOR / SETTLEMENT_REQUIRE_PARTY_ACTOR` = true
- [ ] `X402_PAYMENT_BACKEND != mock`
- [ ] `TRADE_LAUNCH_REQUIRE_EIP712 / VOUCHER_REQUIRE_EIP712` = true
- [ ] MinIO 凭证非默认
- [ ] `CORS_ALLOW_ORIGINS` 白名单，不用 `*`
- [ ] Alembic 迁移已跑（`alembic upgrade head`）

---

## 10. 部署后验证

```bash
# 健康检查
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/info

# 身份档案接口
curl http://127.0.0.1:8000/v1/identity/role-profiles

# 跑测试
pytest tests/ -q
```

真链验证（testnet）：参考 `scripts/e2e_bilateral_sepolia.py`，确认 lock → bind → settle → finalize 后 escrow 归零、卖方到账。
