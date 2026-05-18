# 公开测试网审计后 — 优化与加固 backlog

> 对照 Sentinel 报告（2026-05-18）与 `main` @ `e3f8c7e`+。  
> **P0** = 公开测试网前应完成；**P1** = 试点期间；**P2** = Phase 4+。

---

## 已在本仓库落地

| 项 | 说明 |
|----|------|
| 全链路门 + 反向审计 | `full_chain_audit_gate.sh`、`reverse_rule_audit.py` |
| Sentinel 2 项失败 | `test_sentinel_nonblocking_regressions.py` + UTC helpers |
| 测试网 Claw/Manus | `testnet_claw_manus_gate.sh`、`deploy/.env.testnet-claw-manus.example` |
| **P0-1 CI 全链路门** | `.github/workflows/python-tests.yml` |
| **P0-2 PG+Redis 栈** | `deploy/docker-compose.testnet.yml`、`deploy/TESTNET_STACK-zh.md` |
| **P0-3 relax 误配** | `public_testnet_preflight.sh` |
| **P0-4 manifest 抽样** | `verify_testnet_manifest_sample.sh`（可选 cast） |
| **P0-5 Console 横幅** | `testnet-banner.js` + `KARMA_TESTNET_BETA` |
| **P1-6 Webhook 重试** | `openclaw_webhook_max_retries` + 指数退避 |
| **P1-7 Intent 过期** | Admin API + Celery beat + `scripts/maintenance/expire_payment_intents.py` |
| **P1-2 pytest markers** | `pyproject.toml` `integration` / `unit` |
| KSA-AP2、x402 生产闸门等 | 见 CHANGELOG |

---

## P0 — 仍需运维 / 私仓

| # | 优化 | 状态 |
|---|------|------|
| P0-4 | Sepolia 凭证 + 链上地址真值 | 🔴 运维 |
| P0-6 | Karma2 AP2 风控 `/v1/verify` 扩展 | 🔴 私仓 |
| P1-8 | `public-beta-security-gate.sh` + on-call env | 🟡 部署时 |

---

## P1 — 试点期间（未自动化）

| # | 优化 |
|---|------|
| P1-3 | OpenClaw MCP 实机签字 |
| P1-4 | x402 Sepolia provider 一笔摘要 |
| P1-1 | 逐步清理测试里残留 `datetime.utcnow()`（非安全路径） |

---

## P2 — Phase 4–5

policy-as-code、Mandate 链、CLI 统一验收、benchmark、租户 API Key。

---

*维护：公开仓随 `main` 更新；私仓见 Karma2 同步包 `PHASE1-3_PRIVATE_GAP_CHECKLIST-zh.md`。*
