# Karma 公开仓库落地指南

面向 **外部贡献者**、**集成方** 与 **平台 SRE**。私有侧（Karma2、风控运行时、商业材料）见 [`PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md`](PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md)。

**公开真源：** [https://github.com/AtoB101/Karma](https://github.com/AtoB101/Karma)  
**许可：** AGPL-3.0-only（见根目录 `LICENSE`、`docs/LICENSING.md`）

---

## 1. 本仓库包含什么

| 区域 | 路径 | 说明 |
|------|------|------|
| 协议与合约 | `karma-core/contracts/` | 公开 NC 栈；不含 BillManager / LockPool 私有实现 |
| HTTP API | `api/`、`openapi/` | 公开契约；`/v1/verify` 转发至 **私有运行时** |
| Console / 网站 | `apps/console/`、`apps/website/` | 静态 UI + 公开 API 客户端 |
| OpenClaw / OpenManus | `packages/karma-openclaw/` 等 | MCP 与集成包 |
| 部署 | `deploy/`、`railway.toml`、`fly.toml` | 本地 Compose + PaaS 一键模板 |
| 跨仓同步工具 | `split-release/` | 生成 Karma2 同步包；**不**含私有引擎源码 |

边界说明：[`docs/security-boundary.md`](security-boundary.md)、[`VISIBILITY_MAP.md`](../VISIBILITY_MAP.md)。

---

## 2. 新人 15 分钟路径

```bash
git clone https://github.com/AtoB101/Karma.git
cd Karma
pip install -e ".[dev]"
cp .env.example .env
# 编辑 APP_SECRET_KEY、PRIVATE_RUNTIME_API_KEY 等
alembic upgrade head
uvicorn api.app:app --reload
```

- 更完整步骤：[`docs/GETTING_STARTED.md`](GETTING_STARTED.md)
- 合约：`forge build && forge test -q`
- 全量测试：`pytest tests/ -q` 或 `make test-python`
- 演示：`python examples/demo_captioning.py`

---

## 3. 生产 / 预发（PaaS）

| 步骤 | 文档 |
|------|------|
| Railway / Fly / Vercel 按钮与 env | [`deploy/one-click-deploy.md`](../deploy/one-click-deploy.md) |
| 示例 secrets | [`deploy/.env.paas.example`](../deploy/.env.paas.example) |
| 完整栈（Postgres、Redis、Worker、MinIO） | [`deploy/docker-compose.yml`](../deploy/docker-compose.yml) |
| 运维 SOP | [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) |

**生产 OpenClaw 授权链（`APP_ENV=production`）：** 须开启 `RUNTIME_REQUIRE_*` 与 Console 六步；技术说明见 [`OPENCLAW_P1_DUAL_AGENT.md`](OPENCLAW_P1_DUAL_AGENT.md)，运营一页纸见 [`OPENCLAW_OPERATOR_CHECKLIST-zh.md`](OPENCLAW_OPERATOR_CHECKLIST-zh.md)。

---

## 4. 公开 / 私有协作节奏

1. 协议与公开文档变更 → **本仓库** PR → 合并并记录 commit SHA / tag。  
2. 更新 **Karma2** 的 `CORE_VERSION.lock` + `deployment-manifest.json` → `verify-manifest` → 部署私有服务。  
3. 禁止将私有评分、外联名单、未披露审计附录提交到本仓库。

细则：[`PUBLIC_PRIVATE_OPERATIONS.md`](PUBLIC_PRIVATE_OPERATIONS.md)、[`split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md`](../split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md)。

---

## 5. 开源对外发布状态

逐项勾选见 [`OPEN_SOURCE_LAUNCH_CHECKLIST.md`](OPEN_SOURCE_LAUNCH_CHECKLIST.md)（随仓库演进更新）。

**已具备（合入主线后）：** `LICENSE`、`SECURITY.md`、`CONTRIBUTING.md`、CI（`forge-ci`、`python-tests`、`security-ci`）、`foundry.lock`、公开测试索引 [`public-testing/README.md`](public-testing/README.md)。

**仍建议补齐（非阻断克隆/部署）：** 正式发布 tag + `CHANGELOG` 条目、Railway Marketplace 模板 ID、Agent Guard 门户验收（`apps/agent-service-guard/ACCEPTANCE.md`）。

---

## 6. 文档索引（公开侧）

| 主题 | 文档 |
|------|------|
| API | [`API_REFERENCE.md`](API_REFERENCE.md) |
| Runtime Key | [`runtime-key-guide.md`](runtime-key-guide.md) |
| 测试网 | [`TESTNET_RUNBOOK.md`](TESTNET_RUNBOOK.md)、[`testnet-integration-checklist.md`](testnet-integration-checklist.md) |
| 公开 P0 验收 | [`PUBLIC_P0_ACCEPTANCE_RUNBOOK_CN.md`](PUBLIC_P0_ACCEPTANCE_RUNBOOK_CN.md) |
| 技术部 A（公开合约/CI） | [`TECH_TEAM_A_KARMA_PUBLIC_CHECKLIST.md`](TECH_TEAM_A_KARMA_PUBLIC_CHECKLIST.md) |
| 早期共建招募 | [`early-builders-recruitment-zh.md`](early-builders-recruitment-zh.md) |
| **私有仓执行** | [`PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md`](PRIVATE_REPO_EXECUTION_CHECKLIST-zh.md) |

---

*维护：公开侧文档随 `main` 更新；私有清单在 Karma2 内可放短指针链回本页。*
