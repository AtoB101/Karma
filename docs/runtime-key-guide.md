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

允许的权限名：`request_voucher`、`verify_voucher`、`submit_receipt`、`update_progress`、`request_settlement`、`sync_task_status`、`discover_agents`、`place_order`。

| 权限 | 能做什么 | 钱会不会动 |
| --- | --- | --- |
| `discover_agents` | 按需求发现可结算的 agent / 商家 | 不会（只读） |
| `place_order` | 在额度内自己发起一笔委托 | 只出凭证，验收通过才划转 |
| `request_voucher` | 替主人要一份付款凭证 | 凭证即责任，需验收 |
| `verify_voucher` | 核验对方凭证真实、已锁定 | 不会（只读） |
| `submit_receipt` / `update_progress` | 交付后写证据哈希 / 进度 | 不会 |
| `request_settlement` | 验证通过后请求划转 | 会（按结算状态机） |
| `sync_task_status` | 读本身份相关的任务 | 不会 |

## agent 先读边界再干活

```
GET /runtime/policy      # 我能自己拍板到什么程度
GET /runtime/capacity    # 我还有多少额度
```

`/runtime/policy` 只返回调用者自己那把 Runtime Key 对应的策略，不返回任何其他身份的数据。
其中 `per_order_auto_approve_usdc` 是「不问我就能下单」的上限，`per_order_hard_cap_usdc`
是硬上限（超过直接 403）。超过自动额度但没超硬上限时，`POST /runtime/place-order`
不会建单、不会扣额度，而是返回 `status=awaiting_owner_confirmation`，等主人在操作台确认。

## 发现与下单

```
POST /runtime/discover      # {requirement_text, amount?, limit?, client_nonce}
POST /runtime/place-order   # {requirement_text, amount, seller_identity_id?, client_nonce, auto_complete?}
```

`place-order` 的边界全部在服务端计算：Runtime Key 的单笔 / 每日上限、已保存的
automation-policy（`auto_enabled`、`responsibility_acknowledged`、`single_limit`）。
客户端传什么都不能放宽。

禁止的能力（Runtime Key **永远不能**执行）包括：提现、转 USDC、修改锁仓、提升额度、改钱包、改安全规则、删除账单、篡改已接受任务、绕过争议与结算状态机等——详见 `docs/security-boundary.md`。

## 吊销

`POST /runtime/revoke-key`，携带与创建时一致的钱包签名（消息格式见服务端 `services/runtime_wallet.py`）。

## 相关文档

- `docs/sdk-quickstart.md` — 安装与 30 分钟接入路径  
- `docs/agent-runtime-integration.md` — Agent 生命周期与 Runtime 对齐  
