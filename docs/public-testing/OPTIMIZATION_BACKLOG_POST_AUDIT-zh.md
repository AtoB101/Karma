# 公开测试网审计后 — 优化与加固 backlog

> 对照 Sentinel 报告（2026-05-18）与 `main` @ `02eb650`。  
> **P0** = 公开测试网前应完成；**P1** = 试点期间；**P2** = Phase 4+。

---

## 已在本仓库落地（2026-05-18 跟进）

| 项 | 说明 |
|----|------|
| 全链路门 | `full_chain_audit_gate.sh` + `reverse_rule_audit.py` |
| 测试网包装 | `testnet_claw_manus_gate.sh` + `deploy/.env.testnet-claw-manus.example` |
| 生产 x402 闸门 | `X402_PAYMENT_BACKEND=sepolia` 写入 prelaunch / phase1 gate |
| KSA-AP2 回归 | `tests/unit/test_ap2_security.py` |
| 测试确定性 | `test_submit_receipt_rejects_missing_signature` 显式关闭 OpenClaw relax + `trade_launch_require_eip712` |
| 时区 | `future_deadline_unix()` / `utc_naive_datetime()` 测试辅助；voucher attestation 回归 |
| Sentinel 专项 | `tests/unit/test_sentinel_nonblocking_regressions.py`（含 relax-on 对照测） |
| 运维预检 | `scripts/acceptance/public_testnet_preflight.sh` |
| 上线签字页 | 本文档姊妹篇 [`PUBLIC_TESTNET_GO_LIVE-zh.md`](PUBLIC_TESTNET_GO_LIVE-zh.md) |

---

## P0 — 公开测试网前应完成

| # | 优化 | 理由 | 建议动作 |
|---|------|------|----------|
| P0-1 | **CI 挂全链路门** | 避免仅跑 pytest 漏掉 phase 门 / 反向审计 | `.github/workflows/python-tests.yml` 增加 `full_chain_audit_gate.sh` 步骤 |
| P0-2 | **部署栈 Redis + PG** | SQLite 并发与限流语义不等于生产 | `deploy/` 提供 `docker-compose.testnet.yml` 或文档化 Helm 清单 |
| P0-3 | **禁止 relax 误配** | 测试网若误开 `OPENCLAW_LOCAL_PHASE1_AUTO_RELAX` 会削弱签名 | preflight 脚本检测并 fail |
| P0-4 | **Sepolia 凭证与 manifest** | 链上地址漂移导致 100% 假通过 | `verify-manifest.sh` + `cast call` 抽样入 Runbook |
| P0-5 | **对外范围声明** | 避免用户以为已上主网 | 网站/Console 横幅「Testnet Beta」+ 链接本签字页 |
| P0-6 | **Karma2 verify 扩展** | AP2 风险分仅在私仓 | 私仓 sprint：P3-1/P3-2（见 PHASE1-3 私仓清单） |

---

## P1 — 试点期间建议

| # | 优化 | 理由 |
|---|------|------|
| P1-1 | **统一 UTC 测试** | 消除 `datetime.utcnow()` 在测试中的歧义（GMT+7 CI） |
| P1-2 | **集成测试分层** | `pytest -m "not integration"` 快路径 + 全量夜间 |
| P1-3 | **OpenClaw 自动化 MCP 冒烟** | 当前以人工 MCP 为主；可加 headless 工具调用回归（非 stdio 全模拟） |
| P1-4 | **x402 真实 provider 签字** | Phase 2 文档中仍为 ☐；补一笔 Sepolia x402 摘要进 `PHASE2_X402_ACCEPTANCE.md` |
| P1-5 | **Rate limit 多实例** | 进程内滑动窗口仅单 worker；生产必须 Redis |
| P1-6 | **Webhook 投递可靠性** | OpenClaw `settlement.settled` 等需重试/死信（若运营依赖） |
| P1-7 | **PaymentIntent 过期清扫** | `expire_stale_intents` 需 cron/scheduler 调用 |
| P1-8 | **安全事件 on-call 门** | `public-beta-security-gate.sh` 需 `SECURITY_ONCALL_*` |

---

## P2 — 架构演进（Phase 4–5）

| # | 优化 |
|---|------|
| P2-1 | policy-as-code 引擎（路线图 Phase 4） |
| P2-2 | 多代理 Mandate 链 + 环检测扩展 |
| P2-3 | `karma` CLI 包装全部 acceptance 脚本 |
| P2-4 | 公开 benchmark 发布（BENCHMARK_AGENT_COMMERCE） |
| P2-5 | 租户级 API Key / 分域限流 |

---

## 针对 Sentinel「2 项失败」的说明

| 测试 | Sentinel 根因 | 加固 |
|------|---------------|------|
| `test_submit_receipt_rejects_missing_signature` | dev + OpenClaw relax 时 `validate_*` 不要求签名 | 测试内 `monkeypatch` 关闭 relax（已加固） |
| `test_trade_launch_attestation_*` | `datetime.utcnow().timestamp()` 时区 | 改为 `timezone.utc`（已加固） |

在 **`APP_ENV=production`** 下，生产路径**不**接受无签名 receipt（除非显式 relax，且 production 禁止 relax）。

---

## 度量（建议每次发布更新）

| 指标 | 目标 |
|------|------|
| `full_chain_audit_gate.sh` | exit 0 |
| `run_public_acceptance_tests.sh` | 0 failures |
| 反向规则审计 | 0 failures |
| Sepolia 预授权 runbook | 7/7 或文档化例外 |
| OpenClaw 路径 | ≥1 人工签字 / 发布 |

---

*维护：公开仓随 `main` 更新；私仓风控项在 Karma2 `PHASE1-3_PRIVATE_GAP_CHECKLIST-zh.md` 跟踪。*
