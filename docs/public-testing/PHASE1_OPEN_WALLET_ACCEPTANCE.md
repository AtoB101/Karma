# Phase 1 Open Wallet 签名验收（公开摘要）

> 最近更新：2026-05-18  
> 实现 PR：[#86](https://github.com/AtoB101/Karma/pull/86)（合并后请将本行 SHA 更新为 `main` 合并 commit）  
> 路线图：[`KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md`](../KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md) Phase 1  
> 操作文档：[`OPEN_WALLET_SIGNING-zh.md`](../OPEN_WALLET_SIGNING-zh.md)

## 范围

| 项 | 说明 |
|----|------|
| EIP-712 | `TradeLaunchIntent` — preview / launch / 可选 `sign-with-backend`（仅 dev） |
| 策略 | automation-policy clamp + 当日 launch 累计 `daily_limit` + Runtime Key 日消耗镜像 |
| Voucher 统一 | `progress_rule_spec.trade_launch_attestation` + `voucher_buyer_commitment` 双路径 |
| 生产闸门 | `TRADE_LAUNCH_REQUIRE_EIP712=true`；`KARMA_SIGNING_BACKEND=client_only\|external` |

不在本阶段：链上 digest 绑定、x402、Console 强制去占位签名。

## 自动化验收（公开 CI）

```bash
bash scripts/run_public_acceptance_tests.sh -q
./scripts/production-prelaunch-gate.sh deploy/.env.paas.example  # 需按 example 填全

pytest tests/unit/test_trade_launch_eip712.py \
  tests/unit/test_voucher_buyer_commitment.py \
  tests/unit/test_trade_launch_security.py \
  tests/integration/test_trade_launch_eip712_launch.py -q
```

| 套件 | 预期 |
|------|------|
| 公开 acceptance gate | 298+ monorepo + 50 karma-public |
| Phase 1 专项 | 见上 `pytest` 全绿 |
| production-prelaunch-gate | Settings() 接受 production + trade EIP-712 闸门 |

## 建议私有/预发复测（归档时填写）

| 场景 | 环境 | 结果 | 备注 |
|------|------|------|------|
| signing-preview → 钱包签名 → launch | Sepolia + `TRADE_LAUNCH_REQUIRE_EIP712=true` | ☐ pass / fail | 记录 `order_id`、无占位 `buyer_signature` |
| 过期签名拒绝 | API | ☐ | `deadline_unix` 已过期 → 403 |
| 非绑定钱包签名 | API | ☐ | recover 地址 ≠ profile → 403 |
| 重复 `launch_nonce` / 幂等 | 同 `Idempotency-Key` | ☐ | 第二次应 `idempotent_replay` |
| 超 `daily_limit` | 多笔 launch 同日 | ☐ | 409 daily_limit |
| Redis + PostgreSQL 压测抽样 | 生产类拓扑 | ☐ | 可选；对比 #83 报告 |

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
```

## Karma2 锁步

合并后执行 `prepare-karma2-sync-package.sh --core-commit <merge-sha>`，更新 `CORE_VERSION.lock` 与 vendor 快照。
