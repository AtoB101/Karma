# Phase 1 Open Wallet 签名验收（公开摘要）

> 最近更新：2026-05-18  
> 基线：`main` @ [`81d20b0`](https://github.com/AtoB101/Karma/commit/81d20b0)（#86–#88）  
> 路线图：[`KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md`](../KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md) Phase 1  
> 操作文档：[`OPEN_WALLET_SIGNING-zh.md`](../OPEN_WALLET_SIGNING-zh.md) · OpenClaw：[`PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md`](../PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md)

## 范围

| 项 | 说明 |
|----|------|
| EIP-712 | `TradeLaunchIntent` — preview / launch / 可选 `sign-with-backend`（仅 dev） |
| 策略 | automation-policy clamp + 当日 launch 累计 `daily_limit` + Runtime Key 日消耗镜像 |
| Voucher 统一 | `progress_rule_spec.trade_launch_attestation` + `voucher_buyer_commitment` 双路径 |
| 生产闸门 | `TRADE_LAUNCH_REQUIRE_EIP712=true`；`KARMA_SIGNING_BACKEND=client_only\|external` |
| OpenClaw 本地 | `OPENCLAW_LOCAL_PHASE1_AUTO_RELAX` + `deploy/.env.local-openclaw.example`（#88） |

不在本阶段：链上 digest 绑定、x402、Console 强制去占位签名。

## 自动化验收（公开 CI）

```bash
bash scripts/acceptance/phase1_open_wallet_gate.sh
bash scripts/run_public_acceptance_tests.sh -q
./scripts/production-prelaunch-gate.sh deploy/.env.paas.example  # 需按 example 填全
```

| 套件 | 预期 | 公开仓状态（@ `81d20b0`） |
|------|------|---------------------------|
| `phase1_open_wallet_gate.sh` | Phase 1 pytest + OpenClaw relax + 生产 Settings | pass |
| 公开 acceptance gate | 309 monorepo + 50 karma-public | pass |
| production-prelaunch-gate | production + trade EIP-712 闸门 | pass |

## 本地冒烟脚本（需已 seed 买卖双方 policy/capacity）

| 路径 | 命令 | env 模板 |
|------|------|----------|
| A — 无 EIP-712 | `python3 scripts/acceptance/phase1_claw_manus_smoke.py` | `deploy/.env.local-openclaw.example` |
| B — EIP-712 代签 | `python3 scripts/acceptance/phase1_eip712_launch_smoke.py` | `deploy/.env.local-eip712.example` |

## OpenClaw 本地实测（路径 A）

| 场景 | 环境 | 结果 | 备注 |
|------|------|------|------|
| 全自动 launch + 幂等 + handoff | `.env.local-openclaw.example` | pass（2026-05-18 审计报告） | 基线 `6ab1ccf`；#88 修复 A9 后复测建议 @ `81d20b0` |
| 卖方 MCP receipt/progress | `OPENCLAW_LOCAL_PHASE1_AUTO_RELAX=true` | pass（#88） | 或 pipeline 首条 progress 已覆盖 |

## 建议预发 / Sepolia 复测（归档时填写）

| 场景 | 环境 | 结果 | 备注 |
|------|------|------|------|
| signing-preview → 钱包签名 → launch | Sepolia + `TRADE_LAUNCH_REQUIRE_EIP712=true` | ☐ | 路径 C；无占位 `buyer_signature` |
| 路径 B 代签 smoke | 预发 + `phase1_eip712_launch_smoke.py` | ☐ | `KARMA_SIGNING_BACKEND=env` |
| 过期签名拒绝 | API | ☐ | `deadline_unix` 已过期 → 403 |
| 非绑定钱包签名 | API | ☐ | recover ≠ profile → 403 |
| 重复 `launch_nonce` / 幂等 | 同 `Idempotency-Key` | ☐ | `idempotent_replay` |
| 超 `daily_limit` | 多笔 launch 同日 | ☐ | 409 |
| Redis + PostgreSQL 压测 | 生产拓扑 | ☐ | 可选 |

## 攻击矩阵（公开仓已覆盖）

见 [attack-testing-roadmap.md](./attack-testing-roadmap.md) §3.3（KSA-TL-*）。

## 生产配置核对

```env
TRADE_LAUNCH_REQUIRE_EIP712=true
KARMA_SIGNING_BACKEND=client_only
TRADE_LAUNCH_RECORD_RUNTIME_DAILY_SPEND=true
RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING=true
RATE_LIMIT_REDIS_FAIL_CLOSED=true
RECEIPT_REQUIRE_SIGNATURE=true
OPENCLAW_LOCAL_PHASE1_AUTO_RELAX=false
```

## Karma2 锁步

```bash
./split-release/prepare-karma2-sync-package.sh --core-commit 81d20b0
```

在私仓 Karma2 更新 `CORE_VERSION.lock`、vendor 快照与生产 env。

## Phase 1 公开仓落地判定

| 层级 | 状态 |
|------|------|
| 代码 + CI + gate | ✅ `81d20b0` |
| OpenClaw 本地 A/D + A9 | ✅ #88 |
| EIP-712 B 脚本 + 单测 | ✅ 可本地跑；预发签字 ☐ |
| Sepolia 钱包 C | ☐ 人工 |
| Karma2 锁步 | ☐ 私仓 |
