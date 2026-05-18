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
