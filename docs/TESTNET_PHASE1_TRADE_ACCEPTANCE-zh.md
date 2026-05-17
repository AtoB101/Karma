# 测试网 · 阶段一预授权交易流水线验收标准

本文档定义 **公开仓库** 在 `SETTLEMENT_MODE=testnet` 或 `hybrid` 下，对 Console 预授权 + 全自动交易流水线（`/v1/trade/orders/launch`）的验收项。私有风控权重与仲裁启发式不在此列。

## 前置条件

| 项 | 要求 |
|----|------|
| 数据库迁移 | `alembic upgrade head` 至 **`0025_trade_pipeline_security`** |
| 结算模式 | `SETTLEMENT_MODE=testnet` 或 `hybrid` |
| RPC / 合约 | `TESTNET_RPC_URL`、`TESTNET_CHAIN_ID`、`KARMA_*_ADDRESS`、`ERC20_TOKEN_ADDRESS` 已配置 |
| 钱包 | 买方/卖方测试私钥与余额（见 `docs/TESTNET_RUNBOOK.md`） |
| 双方策略 | `preauth_enabled`、`auto_enabled`、`auto_execute_pipeline=true`、`responsibility_acknowledged` |
| Runtime Key | 双方各一枚 **active**、未过期 Runtime Key |
| 卖方预授权 | `auto_accept_incoming=true`，买方在 `trusted_counterparty_ids` 内（或策略允许） |
| 买方容量 | `available_credits` ≥ 订单 `bill_credit_amount` |

## A) 安全与幂等（服务端）

- [ ] `POST /v1/trade/orders/launch` 携带 `Idempotency-Key`（8–256 字符）；重复请求返回 **相同** `order_id` 与 `idempotent_replay: true`
- [ ] 相同 Idempotency-Key 但买方/卖方/需求指纹不同 → **409**
- [ ] `buyer_identity_id === seller_identity_id` → **400**
- [ ] `SETTLEMENT_MODE=testnet|hybrid` 时无 `chain_anchor_hash` → **400**；格式须为 `0x` + 64 位十六进制
- [ ] 金额超出 `escrow_min_amount` / `escrow_max_amount` 或任一方 `single_limit` → **400**
- [ ] 结算状态迁移经审计表 `settlement_transition_audits`（`route_path` 含 `/internal/trade_pipeline/v2`）
- [ ] 锁定前执行 `assert_lock_does_not_close_payment_cycle`（KSA2-034）
- [ ] 有责任账单币占用时 `POST /v1/capacity/{id}/release` → **409**

## B) 流水线状态机（离链）

按 `GET /v1/trade/orders/{order_id}` 验证 `status` 顺序（成功路径）：

`decomposed` → `contract_created` → `voucher_created` → `accepted` → `settlement_created` → `settlement_locked` → `handoff_confirmed` → `execution_started`

- [ ] `pipeline_version` 为 `v2`
- [ ] 关联 `vouchers.task_id` 与 `trade_orders.task_id` 一致
- [ ] 结算任务最终为 `IN_PROGRESS`（执行 kickoff 后）
- [ ] `voucher_events` 含 `voucher.created`；成功时含 `trade.execution_started`

## C) 测试网链上（可选 `--send`）

使用脚本：

```bash
export SETTLEMENT_MODE=testnet
# … TESTNET_* 与双方 Runtime / 策略已在 Console 或 API 配好 …
python3 scripts/testnet/trade_preauth_pipeline_acceptance.py \
  --base-url http://127.0.0.1:8000 \
  --buyer-id <buyer_karma_id> \
  --seller-id <seller_karma_id> \
  --idempotency-key testnet-trade-$(date +%s) \
  --chain-anchor-hash 0x$(openssl rand -hex 32) \
  --output-dir results/trade-acceptance
```

- [ ] Launch 返回 `201`，`status=execution_started`
- [ ] 输出 JSON 含 `order_id`、`task_id`、`payment_code`、`trace_id`
- [ ] （`--send`）链上 createBill / lock 与 `chain_anchor_hash` 可追溯（见 `operational_log.jsonl`）
- [ ] 重复相同 `--idempotency-key` 不产生第二笔订单

## D) 生产闸门对齐（说明）

| 环境变量 | 测试网建议 | 生产建议 |
|----------|------------|----------|
| `RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS` | 可先 `false` 做 E2E，再 `true` 验阻断 | `true` |
| `RUNTIME_REQUIRE_HANDOFF_ATTESTATION` | 流水线会写入 handoff；可与 readiness 联测 | `true` |
| `AUTH_ENFORCE_PROTECTED_ROUTES` | 按部署一致 | `true` |
| `Idempotency-Key` | 强烈建议 | **必填**（`APP_ENV=production`） |

## E) 自动化测试（CI / 本地）

```bash
pytest tests/unit/test_trade_pipeline_security.py \
  tests/integration/test_trade_order_pipeline_launch.py \
  tests/integration/test_trade_pipeline_idempotency.py -q
```

## 签核

| 角色 | 姓名 | 日期 | 通过 |
|------|------|------|------|
| API / 流水线 | | | |
| 测试网运维 | | | |
| Console 产品 | | | |
