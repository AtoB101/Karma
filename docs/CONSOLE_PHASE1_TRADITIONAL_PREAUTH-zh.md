# 阶段一 · 操作台传统模式 + 预授权（公开仓库）

## 产品行为

1. **主界面**：[`apps/console/pages/trade/index.html`](../apps/console/pages/trade/index.html) — 传统付款码 / 卖方验码接单或拒绝。  
2. **底部**：「一键开启预授权」→ 展开买卖双方预授权设置（责任边界 ID、任务精密度区间、信任对手方、金额上限等）。  
3. **预授权付款码**：`payment_mode=preauth` 时，创建后服务端按卖方策略 **自动 accept 或 reject**，并写入 `voucher_events` + webhook（`voucher.rejected` / `voucher.accepted`）。

## API（公开）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/payment-codes` | 创建时效付款码 + Voucher |
| GET | `/v1/payment-codes/{voucher_id}` | 读取 `payment_code_v1` 载荷 |
| POST | `/v1/payment-codes/{id}/accept` | 传统卖方手动接单 |
| POST | `/v1/payment-codes/{id}/reject` | 卖方拒绝 + 买方事件回执 |
| PUT | `/v1/identities/{id}/automation-policy` | 含 `preauth_enabled`、`auto_accept_incoming` 等扩展字段 |
| GET | `/v1/vouchers/{id}/events?identity_id=` | 事件时间线 |
| POST | `/v1/capacity/{id}/release` | 有责任账单币时 **409** 拒绝释锁 |

## 迁移

`alembic upgrade head` — revision `0023_phase1_preauth_payment_code`。

## 阶段二（未在本阶段）

账单币迁移至子身份、链上哈希锚定、定向可见性审计 — 见 `docs/PHASE2_BILLCOIN_MIGRATION-zh.md`（占位）与私有仓清单。
