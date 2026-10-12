# 公开测试网 Docker 栈（PostgreSQL + Redis + API）

用于满足 Sentinel / Go-Live 清单 **P0-2**（勿用 SQLite 冒充公开测试网）。

## 启动

```bash
cd deploy
cp .env.testnet-stack.example .env
# 编辑 .env：APP_SECRET_KEY、AUTH_API_KEYS、可选 Sepolia 变量

docker compose -f docker-compose.testnet.yml up -d --build
cd .. && alembic upgrade head
curl -s http://127.0.0.1:8000/health
```

## 验收

```bash
bash scripts/acceptance/public_testnet_preflight.sh
# KARMA_TESTNET_ENV=deploy/.env bash scripts/acceptance/testnet_claw_manus_gate.sh
```

## Console 测试网横幅

在 Console 页面设置 `window.KARMA_TESTNET_BETA = true`（见 `apps/console/config.example.js`）或部署时在 HTML 中注入。

## 实测可用的走法（2026-10-12，1.6 GB 的发布机）

`docker-compose.testnet.yml` 是写给「这台机器能 build 镜像」的环境的。发布机上 **不能 build**
（build 会 OOM），所以实际这么起：

- 复用已有的 `karma-api:latest` 镜像（**不要** build），源码照 prod 那样 bind-mount 进去；
- 独立 compose project（`-p karma-testnet`）+ 独立容器名 / volume / state 目录，与 prod 完全不共享
  数据库、Redis、`mvp_data`；
- 端口错开：prod 占 `127.0.0.1:8000`，测试网栈挂 `127.0.0.1:18000`。

`.env` 上实测踩到的坑：

- `APP_ENV=production` 会**强制** `TRADE_LAUNCH_REQUIRE_EIP712=true`
  （`config/settings.py::_reject_default_secrets_in_production`），所以
  `APP_ENV=production` + `TRADE_LAUNCH_REQUIRE_EIP712=false` 是**起不来**的组合。要跑占位签名的
  smoke（路径 A）就老实用 `APP_ENV=development`；
- `APP_ENV=production` 还额外要求非默认 `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`、`X402_ENABLED=false`
  或 `X402_PRIVATE_KEY`、`AUTH_API_KEYS` 非空等 —— 少一样就起不来；
- 建表**不要** `alembic upgrade head`：app 自己在 lifespan 里 `Base.metadata.create_all()`
  （`db/session.py::init_db`）。先起 API 再 `alembic upgrade head` 会撞
  `relation "agents" already exists`（migration `0001_initial` 不是幂等的），正确做法是
  `docker compose exec api alembic stamp head`；
- 种子：`docker compose exec api python scripts/seed_phase1_dual_agents.py`（生成 `a2a-buyer` /
  `a2a-seller` 两把 bootstrap key）。
