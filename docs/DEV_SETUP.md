# Karma 本地开发环境（统一）

> 目标：新开发者 clone 仓库后，一条命令就能把本地栈跑起来，不再被构建垃圾/环境差异坑。

---

## 1. 一键启动

```bash
make dev          # 或 ./scripts/dev.sh up
```

它会自动完成：

1. 检查依赖（python3、redis-server）
2. 创建 `.venv` 虚拟环境（如不存在）
3. `pip install -e ".[dev]"` 安装依赖
4. 启动 Redis（6379）
5. 启动 Celery worker
6. 启动 API（`uvicorn api.app:app`，`127.0.0.1:8000`）
7. 启动操作台（静态服务，`127.0.0.1:8787`）

启动后：

| 服务 | 地址 |
|---|---|
| API | http://127.0.0.1:8000（`/health` 健康检查） |
| 操作台 | http://127.0.0.1:8787/pages/cyber/index.html |
| 文档 | http://127.0.0.1:8000/docs |

停止 / 重置：

```bash
make down            # 或 ./scripts/dev.sh down
./scripts/dev.sh reset   # 停止 + 删除 .venv，回到干净状态
```

---

## 2. 前置依赖（一次性）

- **Python 3.11+**
- **Redis**（Windows 用 [tporadowski/redis](https://github.com/tporadowski/redis/releases)；`redis-server --port 6379`）
- （可选）**Foundry**（`forge`）—— 只在改合约时需要
- （可选）**Node.js** —— 只在本地预览静态页需要

---

## 3. 本地 vs 生产（重要区别）

| | 本地开发 | 生产 |
|---|---|---|
| 数据库 | SQLite（`.env` 里 `DATABASE_URL=sqlite+aiosqlite:///./karma_dev.db`） | PostgreSQL |
| 建表方式 | API 启动时 `init_db()` 自动 `create_all` | `alembic upgrade head` |
| 结算模式 | `offchain` 或 `testnet` | `offchain`/`testnet`/`hybrid` |
| 认证 | 可关闭（`AUTH_ENFORCE_PROTECTED_ROUTES=false`） | 必须开启 + 全部安全项 |

> **本地开发不要跑 `alembic upgrade head`**（迁移文件是 PostgreSQL 定向的，SQLite 上会报错）。SQLite 的表由 API 自动建。

---

## 4. 已清理的构建垃圾（已加入 `.gitignore`）

以下目录/文件现在会被 git 忽略，不会再出现在 `git status` 里误导开发者：

- `.venv/`、`.venv-*/`、`venv/` —— 虚拟环境
- `*.log`、`*.log.err` —— 运行日志
- `out/`、`cache/`、`broadcast/` —— Foundry 构建产物
- `__pycache__/`、`*.pyc`、`.pytest_cache/`、`*.egg-info/` —— Python 缓存/构建
- `node_modules/`、`dist/`、`*.whl` —— Node/打包产物
- `*.db`、`*.db-*` —— 本地测试数据库
- `*.pem`、`*.key`、`**/.env*`（除 example） —— 密钥与本地配置

---

## 5. 首次启动检查清单

- [ ] `.env` 存在（脚本会自动从 `.env.example` 复制；本地建议用 SQLite）
- [ ] `make dev` 一条命令跑通
- [ ] `curl http://127.0.0.1:8000/health` 返回 `{"status":"ok"}`
- [ ] 打开操作台 `http://127.0.0.1:8787/pages/cyber/index.html` 能加载

---

## 6. 相关文档

- 生产部署：`docs/DEPLOYMENT_GUIDE.md`
- 使用说明：`docs/USAGE_GUIDE.md`
- 一键部署（Railway/Fly/Vercel）：`deploy/one-click-deploy.md`
