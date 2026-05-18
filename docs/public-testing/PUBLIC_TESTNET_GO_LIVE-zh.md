# 公开测试网（Sepolia）上线签字页

> **审计基线（Sentinel）：** Karma `main` @ `02eb650` · Karma2 `main` @ `e706031`  
> **审计日期：** 2026-05-18  
> **结论：** **支持受控公开测试网试点**（非无门槛主网生产）

---

## 1. 执行摘要

| 维度 | 状态 | 说明 |
|------|------|------|
| 代码 / 协议 | ✅ 就绪 | Phase 1–3 + x402 + 全链路审计门已合入 `main` |
| 生产闸门 | ✅ 就绪 | `APP_ENV=production` 下 14+ 项强制，缺一项拒绝启动 |
| 攻击回归 | ✅ 就绪 | KSA / KSA2 / KSA-TL / KSA-X402 / KSA-AP2 |
| 历史压力/测试网 | ✅ 参考 | 2026-05-17：0 CRITICAL/HIGH；Sepolia 7/7 |
| 运维前置 | 🔴 待补 | RPC、合约、钱包、Redis、PostgreSQL、密钥、on-call |
| 集成实测 | 🟡 待补 | OpenClaw MCP、EIP-712 真实钱包、`testnet_claw_manus_gate.sh` |

**对外表述建议：** 「Sepolia 公开测试网（邀请制/文档化限制）」— 勿称「与主网生产等价的全自动商用」。

---

## 2. 自动化验收（上线前必跑）

### 2.1 离链全链路（无需 RPC）

```bash
pip install -e ".[dev]"
bash scripts/acceptance/full_chain_audit_gate.sh
python3 scripts/acceptance/reverse_rule_audit.py
```

| 步骤 | 内容 |
|------|------|
| 1 | 反向规则静态审计 |
| 2–4 | Phase 1 Open Wallet / Phase 2 x402 / Phase 3 AP2 |
| 5 | KSA 攻击回归（含 KSA-AP2） |
| 6 | `run_public_acceptance_tests.sh`（monorepo + OpenClaw/OpenManus + karma-public） |
| 7 | `production-prelaunch-gate.sh` |

详见 [`FULL_CHAIN_AUDIT_ACCEPTANCE-zh.md`](FULL_CHAIN_AUDIT_ACCEPTANCE-zh.md)。

### 2.2 测试网 + OpenClaw / Manus（需运行中 API）

推荐 Docker 栈（PostgreSQL + Redis）：[`deploy/TESTNET_STACK-zh.md`](../deploy/TESTNET_STACK-zh.md)

```bash
cd deploy && cp .env.testnet-stack.example .env && docker compose -f docker-compose.testnet.yml up -d --build
cd .. && alembic upgrade head
```

或本地 uvicorn：

```bash
cp deploy/.env.testnet-claw-manus.example .env.testnet.local
set -a && source .env.testnet.local && set +a
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

```bash
bash scripts/acceptance/public_testnet_preflight.sh
bash scripts/acceptance/testnet_claw_manus_gate.sh
```

---

## 3. 生产闸门清单（`APP_ENV=production`）

部署公开测试网 API 时 **必须全部为 true/安全值**（与 Sentinel 报告一致）：

| 变量 | 要求 |
|------|------|
| `AUTH_ENFORCE_PROTECTED_ROUTES` | `true` |
| `AUTH_ALLOW_DEV_KEY_FALLBACK` | `false` |
| `RATE_LIMIT_REDIS_FAIL_CLOSED` | `true` |
| `RUNTIME_REQUIRE_SAVED_AUTOMATION_POLICY` | `true` |
| `RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS` | `true` |
| `RUNTIME_REQUIRE_HANDOFF_ATTESTATION` | `true` |
| `RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING` | `true` |
| `RUNTIME_DAILY_SPEND_PERSIST` | `true` |
| `RECEIPT_REQUIRE_SIGNATURE` | `true` |
| `LEDGER_REQUIRE_PARTY_ACTOR` | `true` |
| `SETTLEMENT_REQUIRE_PARTY_ACTOR` | `true` |
| `OPENCLAW_RELAX_DELIVERY_SIGNATURES` | `false` / 未设置 |
| `OPENCLAW_LOCAL_PHASE1_AUTO_RELAX` | `false` |
| `TRADE_LAUNCH_REQUIRE_EIP712` | `true` |
| `KARMA_SIGNING_BACKEND` | `client_only` |
| `X402_PAYMENT_BACKEND` | `sepolia`（非 `mock`） |

校验：`APP_ENV=production bash scripts/production-prelaunch-gate.sh`

**禁止** 将 `deploy/.env.local-openclaw.example` 原样用于公开测试网。

---

## 4. 运维前置条件（Go 前全部 ☐→☑）

| # | 条件 | 负责人 | ☐ |
|---|------|--------|---|
| 1 | Sepolia `TESTNET_RPC_URL` + `NONCUSTODIAL_AGENT_PAYMENT_ADDRESS` + ERC20 | 链上 | |
| 2 | 有余额的 buyer/seller 测试钱包（或 KMS） | 链上 | |
| 3 | 每笔 testnet launch 的 `CHAIN_ANCHOR_HASH`（64 hex） | 集成 | |
| 4 | **Redis** 可用（生产限流 fail-closed） | SRE | |
| 5 | **PostgreSQL** 替代 SQLite | SRE | |
| 6 | `APP_SECRET_KEY`、`AUTH_API_KEYS` 强密钥 | 安全 | |
| 7 | `SECURITY_ONCALL_PRIMARY` / `BACKUP` | 安全 | |
| 8 | `deployment-manifest.json` + `verify-manifest.sh` 与链上一致 | 发布 | |
| 9 | Karma2 `CORE_VERSION.lock` == 公开 commit（若跑私有 verify） | 私仓 | |
| 10 | OpenClaw MCP 注册 + 路径 A/B 至少一条人工签字 | 运营 | |
| 11 | OpenManus / `phase1_claw_manus_smoke.py` 成功 | 集成 | |
| 12 | （可选）`RUN_TESTNET_ONCHAIN=true` 链上 hybrid 冒烟 | 链上 | |

---

## 5. Sentinel 审计矩阵（存档）

| 测试层 | 通过/总数 | 通过率 |
|--------|-----------|--------|
| 全量单元 + 集成 | **309/309**（`main` @ `f60d8cf`+） | 100% |
| EIP-712 专项 | 11/11 | 100% |
| 生产/安全专项 | 66/66 | 100% |
| E2E / P0 | 14/14 | 100% |
| KSA 攻击回归 | 11/11 | 100% |
| Phase 2 x402 | 10/10 | 100% |
| Phase 3 AP2 | 9/9 | 100% |

Sentinel 原「2 项非阻塞失败」已在 `f60d8cf` / #94 修复，并由 `tests/unit/test_sentinel_nonblocking_regressions.py` 锁定（见 [`OPTIMIZATION_BACKLOG_POST_AUDIT-zh.md`](OPTIMIZATION_BACKLOG_POST_AUDIT-zh.md)）。

---

## 6. 攻击面与合约（公开引用）

- 攻击矩阵：[`attack-testing-roadmap.md`](attack-testing-roadmap.md)  
- 压力摘要：[`STRESS_ATTACK_ACCEPTANCE_2026-05-17.md`](STRESS_ATTACK_ACCEPTANCE_2026-05-17.md)  
- 测试网预授权：[`TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md`](TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md)  
- 链上 hybrid：[`TESTNET_RUNBOOK.md`](../TESTNET_RUNBOOK.md)  
- Forge 不变量：`active + reserved == locked`（128k calls, 0 revert — 部署地址须与 manifest 一致）

---

## 7. Go / No-Go 签字

| 角色 | 离链全链路门 | 测试网 smoke | 生产闸门配置 | 日期 | 签名 |
|------|-------------|-------------|-------------|------|------|
| 工程 | ☐ | ☐ | ☐ | | |
| 安全 | ☐ | ☐ | ☐ | | |
| 链上 | ☐ | ☐ | — | | |
| 运营 (OpenClaw) | — | ☐ | — | | |
| 产品 (YMZ) | ☐ | ☐ | ☐ | | |

**Go 条件：** 上表全部 ☑ + 对外公告已写明范围与限制。  
**No-Go：** 仍用 SQLite/无 Redis 冒充生产、或开启 OpenClaw relax / 关闭鉴权。

---

## 8. 相关文档

- [`FULL_CHAIN_AUDIT_ACCEPTANCE-zh.md`](FULL_CHAIN_AUDIT_ACCEPTANCE-zh.md)  
- [`PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md`](../PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md)  
- [`PRODUCTION_PRELAUNCH_CHECKLIST-zh.md`](../PRODUCTION_PRELAUNCH_CHECKLIST-zh.md)  
- Karma2 私仓缺口：同步包内 `docs/PHASE1-3_PRIVATE_GAP_CHECKLIST-zh.md`
