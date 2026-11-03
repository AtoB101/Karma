# 消费授权审批流 · 端到端自证（APPROVAL E2E）

> 状态：脚本 + 官方审批页 + 后端接口三方契约一致，`tests/unit/test_grant_approval.py`
> 11 个用例全绿。本文档说明如何对任意部署跑一遍**真实主人授权握手**。

## 1. 这条流程在验证什么

agent 想拿一笔有额度上限的花钱授权，不能自己批。真正的握手是：

1. agent 调用 `POST /v1/spending-grants/approval-request` 发起申请，拿到
   `challenge_id`、`confirmation_code`（只出现这一次）、`approval_uri`。
2. 主人在**官方域**打开 `approval_uri`，看到 agent 名称 / 公钥指纹 / 币种 / 总额 /
   单笔上限 / 有效期 / 用途，并输入 agent 在对话里展示的那串核对码（双向核对）。
3. 主人连接钱包，对服务端返回的 canonical 文本 `personal_sign`（EIP-191）。
4. 服务端**同时**验码（SHA-256 摘要比对）+ 验签（recover 出的地址必须等于钱包）+
   反查钱包绑定的身份，三者都过才落 `grant`。

缺一不可：`challenge_id` 防猜、`confirmation_code` 证明双方在同一场对话、钱包签名
证明主人批准了**这些条款**。

## 2. 前置条件

- 服务已启动（默认 `http://127.0.0.1:8000`）。
- 有一个可用的 agent 引导 key（`karma_<agent_id>_<secret>`），用于走 `approval-request`
  这条需要 agent 身份的路。
- 主人钱包必须已绑定到一个身份档案（`IdentityProfileModel.bound_wallet_address`）。
  批准那一步会用 `resolve_identity_id_by_wallet` 反查身份，查不到直接 403：
  `wallet is not bound to a Karma identity`。

钱包绑定的两条现实路径：

- 操作台里走「连接钱包 / 绑定钱包」；或
- 首次铸造 runtime key 时，`runtime_auto_bind_wallet_on_create_key` 会把签名钱包自动
  写进该身份档案（`POST /runtime/create-key`，钱包对 canonical 消息签名）。

自查：确认目标钱包能通过
`services.identity_wallet_binding.resolve_identity_id_by_wallet` 反查到身份即可。

## 3. 运行

PowerShell：

```powershell
cd C:\Users\Administrator\AppData\Local\Temp\karma-main-20261020-100553
$env:KARMA_BASE_URL="http://127.0.0.1:8000"
$env:AGENT_API_KEY="karma_<agent_id>_<secret>"
$env:OWNER_PRIVATE_KEY="0x<主人钱包私钥>"
$env:AGENT_NAME="OpenClaw Purchase Assistant"
python scripts\verify_approval_e2e.py
```

可选环境变量：

- `TOTAL_LIMIT`（默认 100）、`PER_TX_LIMIT`（默认 10）：批多少、单笔多少。
- `OUTPUT_DIR`（默认 `outputs`）：结果 JSON 落盘目录。

## 4. 脚本逐段断言

| 步骤 | 断言 |
| --- | --- |
| approval-request | 200，且返回 `challenge_id` 与 `confirmation_code` |
| public-view | 200，`status=pending`，额度与申请一致，**且不泄漏 `confirmation_code`** |
| sign-message | 200，文本含 `Karma Spending Grant` 与钱包地址 |
| approve | 200，签名（EIP-191）+ 核对码通过，返回 `status=active` 的 grant |
| post-approve-view | 公开展示翻转为 `status=approved` |

任何一步失败，脚本以非零码退出，并把完整记录写到
`outputs/approval-e2e-<UTC 时间戳>.json`。

## 5. 与官方页面的对应关系

`apps/console/pages/grant-approval/index.html` + `scripts/cyber-grant-approval.js` 调的是同一组
接口，字段与脚本一致：`GET .../approval/{challenge_id}`、`GET .../sign-message?wallet_address=`、
`POST .../approve`（body 为 `confirmation_code` + `wallet_address` + `wallet_signature`）。

页面只调 `eth_requestAccounts` / `eth_accounts` / `personal_sign`，不索要私钥或助记词；
签名文本由服务端 `_grant_terms_unlocked` 重建，前端不自己拼额度，防止展示与签名内容不一致。
