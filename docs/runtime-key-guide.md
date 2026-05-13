# Runtime Key 指南

Runtime Key（`KRM_RT_…`）是 **Agent 工作通行证**，用于调用公开的 **Runtime Gateway**（`/runtime/*`）。它不是钱包私钥，不能提现、不能转走 USDC、不能修改锁仓额度。

## 用户只在官方 Console 授权钱包

1. 在 Console「设置 → AI Agent 自动授权中心」配置自动授权策略与额度（演示页将策略保存在浏览器 `localStorage`；生产环境应接入账户级持久化）。
2. 使用钱包对固定文本做 **EIP-191 personal_sign**，调用 `POST /runtime/create-key`。
3. 服务器返回的 `runtime_key` **只显示一次**；关闭后无法再次查看明文，只能吊销后重新生成。

## Agent 只拿 Runtime Key

- SDK：`from karma import KarmaRuntime` 或 `from sdk.runtime_client import KarmaRuntime`。
- 环境变量：`KARMA_RUNTIME_URL`、`KARMA_RUNTIME_KEY`、可选 `KARMA_EXPECTED_CHAIN_ID`、`KARMA_APP_SECRET`（用于校验响应 HMAC）。

## 权限子集

允许的权限名：`request_voucher`、`submit_receipt`、`update_progress`、`request_settlement`、`sync_task_status`。

禁止的能力（Runtime Key **永远不能**执行）包括：提现、转 USDC、修改锁仓、提升额度、改钱包、改安全规则、删除账单、篡改已接受任务、绕过争议与结算状态机等——详见 `docs/security-boundary.md`。

## 吊销

`POST /runtime/revoke-key`，携带与创建时一致的钱包签名（消息格式见服务端 `services/runtime_wallet.py`）。

## 相关文档

- `docs/sdk-quickstart.md` — 安装与 30 分钟接入路径  
- `docs/agent-runtime-integration.md` — Agent 生命周期与 Runtime 对齐  
