# 公开仓库测试加固说明（对照 E2E 报告）

以下条目澄清**公开仓库**已具备的能力，并记录本次加固：

## 报告中的误判（公开仓库已存在）

| 报告声称 | 实际情况 |
|----------|----------|
| Runtime Key 全生命周期 0 代码 | 已实现：`/runtime/create-key`、`list-keys`、`revoke-key`、`permissions` 等，见 `api/routes/runtime_gateway.py` |
| Voucher 无专用端点 | 已有 `POST /v1/vouchers` 及 accept/verify；Runtime 侧有 `POST /runtime/request-voucher` |
| Dispute API 不存在 | 已有 `POST /v1/settlement/{task_id}/dispute` 等 |
| Console 无 UI | `apps/console/pages/settings/index.html` 含 Runtime Key 与自动授权中心 |

## 不在公开仓库实现（按架构边界）

- **Private Risk Engine** 的评分与规则细节：留在私有仓库；公开 API 只暴露核验结果与公开 Schema。

## 本次代码层加固

1. **合约托管金额**：`POST /v1/contracts` 校验 `escrow_min_amount` / `escrow_max_amount`；若买方在账本上有 `Capacity` 行，则 **`escrow_amount` 不得超过 `available_credits`**。
2. **`POST /v1/verify` 认证**：与 `AUTH_ENFORCE_PROTECTED_ROUTES` 对齐；未强制时允许匿名标签，避免本地 E2E 无密钥即 401。
3. **结算 lock 线性（可选）**：`settlement_lock_requires_pending` 为 true 时禁止 DRAFT 直跳 lock。
4. **`GET /v1/info`**：返回 `verify_auth`、`runtime_gateway_prefix`、`settlement_guards` 元数据，便于自动化探测。
5. **`karma` 包导出**：`from karma import KarmaClient, KarmaRuntime` 便于安装后从任意目录导入。

详细认证说明见 **`docs/API_AUTH.md`**。
