# Karma2 私有仓库执行清单（一页纸）

面向 **Karma2（或等价私有仓）** 的建仓、锁步发布、运行时与商业运维。公开协议真源始终为 [AtoB101/Karma](https://github.com/AtoB101/Karma)；本清单 **不得** 将私有逻辑回灌到公开仓。

配套公开文档：[`PUBLIC_REPO_LANDING-zh.md`](PUBLIC_REPO_LANDING-zh.md)、[`PUBLIC_PRIVATE_OPERATIONS.md`](PUBLIC_PRIVATE_OPERATIONS.md)。

---

## A. 一次性建仓（私有仓空库 → 可开发）

| # | 动作 | 通过标准 |
|---|------|----------|
| A1 | 创建 **Private** 仓库（例：`AtoB101/Karma2`），最小 Owner 集合 | 仅安全/运维/核心工程可写 |
| A2 | 在 **公开仓** 根目录执行同步包生成 | `./split-release/prepare-karma2-sync-package.sh --out-dir results/karma2-sync-package` |
| A3 | 可选：生成迁移引导包 | `./scripts/private-repo-sync.sh --private-repo-url https://github.com/AtoB101/Karma2.git` |
| A4 | 将 `split-release/templates/karma2/` 复制到私有仓 `ops/release/`（见模板 README） | 存在 `CORE_VERSION.lock`、`deployment-manifest.json`、`ENV_SYNC`、`verify-manifest.sh` |
| A4b | 从同步包复制 Phase 1–3 私仓补齐清单 | `docs/PHASE1-3_PRIVATE_GAP_CHECKLIST-zh.md`（由 `prepare-karma2-sync-package.sh` 生成） |
| A5 | 启用 CI workflow **Lockstep Sync Check**（模板内） | PR 上 lock 与 manifest 不一致则失败 |
| A6 | 配置 Secrets（**仅** CI/部署密钥库，不进 git） | RPC（带鉴权）、`TESTNET_*_PRIVATE_KEY`、KMS、WalletConnect 生产 ID、内部 DB |
| A7 | 私有 README 使用 [`docs/README_PRIVATE.md`](README_PRIVATE.md) 文案 | 明确风控/评分为私有边界 |

**禁止：** 在公开仓提交 investor deck、tokenomics 参数表、外联 CRM 导出、未披露审计附录。

---

## B. 每次公开基线升级（锁步发布）

在 **Karma `main`（或约定发布分支）** 合并并打 tag 之后，在 **Karma2** 同一发布窗口完成：

| # | 动作 | 命令 / 产物 |
|---|------|-------------|
| B1 | 记录公开 commit / tag | 例：`core-v1.x.y` @ `abc1234` |
| B2 | 更新 `CORE_VERSION.lock` | `core.commit` 与公开 SHA **完全一致** |
| B3 | 刷新 `vendor/karma-public-sync/`（同步包内只读快照） | 来自 `prepare-karma2-sync-package.sh` 输出 |
| B4 | 更新 `deployment-manifest.json` | `chain_id`、合约地址、ABI 哈希（若使用）、`engine` 版本 |
| B5 | 校验 | 私有仓根目录 `./verify-manifest.sh`；公开仓可选 `./split-release/verify-cross-repo-manifest.sh` |
| B6 | 私有集成测试 | BillManager / LockPool / 风控路径对锁定地址跑通 |
| B7 | Go/No-Go | 公开 CI 绿 + 私有 CI 绿 + manifest 校验 + 负责人签字 |

**紧急：** 仅配置/路由热修可只在 Karma2 改；**ABI 或地址变更** 必须同步 B2–B5。

---

## C. 私有运行时与风控（部署项）

| # | 组件 | 说明 |
|---|------|------|
| C1 | Private Risk Runtime | 评分、反作弊、争议权重；**不**出现在公开 SDK |
| C2 | 与公开 API 对接 | `POST /v1/verify` 等由公开 API 转发；`PRIVATE_RUNTIME_API_KEY` 仅部署环境 |
| C3 | 网络隔离 | 生产建议 localhost / 内网；见 [`DEPLOYMENT.md`](DEPLOYMENT.md) §6 |
| C4 | Celery / 异步任务 | 公开 PaaS 模板不含 Worker；私有栈自行部署 |
| C5 | 对象存储 | MinIO 或 S3 兼容；敏感证据 URI 访问控制由集成方负责 |

---

## D. 合约与 BillManager（仅 Karma2）

| # | 项 | 责任 |
|---|-----|------|
| D1 | `BillManager` / `LockPoolManager` | 源码与测试 **仅在私有仓** |
| D2 | `CircuitBreaker` 阈值强制执行 | 在 `createBill`（或等价入口）调用公开部署的 `CircuitBreaker` |
| D3 | Admin → Gnosis Safe | 新部署时 immutable 角色写入 Safe；公开侧配合写入 manifest |
| D4 | `nonReentrant` / 分页等 P0 | 按 [`fix-checklist-2026-05-06.md`](fix-checklist-2026-05-06.md) 私有段执行 |

公开侧 NC 栈验收：[`TECH_TEAM_A_KARMA_PUBLIC_CHECKLIST.md`](TECH_TEAM_A_KARMA_PUBLIC_CHECKLIST.md)。

---

## E. 生产环境变量（私有服务 + 联动公开 API）

| 类别 | 示例（名称以各仓 `settings` / manifest 为准） |
|------|-----------------------------------------------|
| 链 | `TESTNET_RPC_URL`、`TESTNET_CHAIN_ID`、引擎/代币地址（来自 manifest） |
| 签名 | `TESTNET_BUYER_PRIVATE_KEY`、`TESTNET_SELLER_PRIVATE_KEY`（或 KMS 代理） |
| 公开 API 回调 | 公开部署的 `KARMA_*` base URL、`AUTH_API_KEYS` 映射各租户 |
| OpenClaw（若启用） | 买方/卖方进程各一套 `KARMA_RUNTIME_KEY`；`KARMA_OPENCLAW_REQUIRE_SERVER_ATTESTATION=true` |

公开 Console 六步与 PaaS Runtime 闸门：[`OPENCLAW_OPERATOR_CHECKLIST-zh.md`](OPENCLAW_OPERATOR_CHECKLIST-zh.md)、[`deploy/.env.paas.example`](../deploy/.env.paas.example)。

---

## F. 商业 / 外联 / 合规（私有仓目录建议）

| 路径（建议） | 内容 |
|--------------|------|
| `outreach/` | 合作方、活动记录（勿进公开仓） |
| `commercial/` | 报价、合同模板、客户集成 Runbook |
| `ops/incident/` | 未公开 IR  playbook、战时沟通模板 |
| `investor/` | 融资材料、tokenomics 工作表 |

同步脚本 `scripts/private-repo-sync.sh` 生成的 `results/private-repo-sync/` 仅本地使用，**不提交** 到任一 git 远程。

---

## G. 发布前 60 秒核对（每次上生产）

- [ ] `CORE_VERSION.lock` == 本次要跑的公开 commit  
- [ ] `deployment-manifest.json` 地址与链 ID 与链上 `cast call` 抽样一致  
- [ ] `verify-manifest.sh` 通过  
- [ ] 无 secrets 进 PR diff  
- [ ] 公开 API `APP_ENV=production` 时 Runtime 闸门已全部 `true`（若本环境托管公开 API）  
- [ ] 私有风控健康检查 / 冒烟（verify + 一笔测试任务）通过  
- [ ] 回滚 manifest 已归档（上一版 JSON 可一键指回）

---

## H. 回滚

1. 取出上一版 **已知良好** `deployment-manifest.json`。  
2. 将引擎服务回滚到 manifest 中的 `engine.commit`。  
3. 若合约地址变更，配置指回上一组地址（或保持链上不变仅回滚链下）。  
4. 重跑冒烟；内部记录 incident 说明（不进公开仓未修复细节）。

详见 [`split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md`](../split-release/CROSS_REPO_DEPLOYMENT_PLAYBOOK.md) § Rollback。

---

## I. 签字（试点 / 主网上线）

| 角色 | 姓名 | 日期 | 签名 |
|------|------|------|------|
| 私有仓 Owner | | | |
| 链上/合约 | | | |
| 风控/安全 | | | |
| 运营（OpenClaw/Console） | | | |

---

*版本：与公开 `main` 锁步流程一致；env 名变更以各仓 `config/settings.py` 与 `deployment-manifest.json` schema 为准。*
