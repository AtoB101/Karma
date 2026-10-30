# Agent 接入授权流程 V1

每个 agent 接入 Karma 都必须按本流程逐步取得主人授权。这是 agent 与操作台共用的**唯一事实来源**（机器可读标准见
`packages/evidence-schema/agent-onboarding-authorization-flow.v1.json`），避免接入向导、SDK、MCP 各写一套流程走偏。

## 为什么需要它

之前的接入流程只在「铸钥匙」这一个点要主人签名，其余步骤的授权边界散落在各个模块里，没有一份可以给 agent 和
操作台同时读的步骤清单。结果是：agent 不知道下一步要提示主人点什么，操作台也不知道该在什么时机弹什么控件。
本流程把「谁授权、用什么方式授权、给用户看什么、这一步在保护什么」固定下来。

## 读取方式

```http
GET /v1/standards/onboarding/authorization-flow
```

`/v1/info` 的 `agent_onboarding_template.authorization_flow` 也指向它。

## 七步流程

| # | step_id | 授权方式 | 谁授权 | 在保护什么 |
|---|---------|----------|--------|------------|
| 1 | `owner_identity` | SIWE 钱包签名 | 主人 | 之后所有授权动作的会话根 |
| 2 | `role_declaration` | 确认弹窗（Yes/No） | 主人 | 目录里能力/边界的可问责性 |
| 3 | `funding_bounds` | 责任确认（勾选） | 主人 | 单笔/日上限与权限；打开自动化的前置 |
| 4 | `runtime_key_mint` | 钱包 personal_sign | 主人 | 钥匙权限不得超出已保存策略 |
| 5 | `agent_pairing` | 8 位对照码 + Ed25519 签名 | 主人 + agent | 钥匙不被冒领 |
| 6 | `binding_attestation` | 平台签收（自动） | 平台 | agent 可自证「绑的确实是我」 |
| 7 | `runtime_spend` | 逐笔确认弹窗（持续） | 主人 | 每一笔资金去向 |

## 授权类型枚举

`authorization_type` 是稳定的枚举值，前端按它渲染对应控件：

- `siwe_signature` —— 钱包登录签名按钮
- `yes_no` —— 确认/拒绝弹窗
- `responsibility_ack` —— 责任确认勾选
- `wallet_signature` —— 一次性钱包签名按钮
- `matching_code` —— 公钥指纹核对 + 8 位对照码输入框
- `platform_attestation` —— 无控件，平台自动签收
- `none` —— 无人类授权步骤

## 第 7 步的逐笔授权规则

第 7 步不是一次性步骤，而是接入之后持续生效。由主人的 `high_risk_mode` 决定：

- `above_single`（默认）：额度内 agent 自主下单；超过单笔上限才弹主人确认。
- `always`：每一笔都弹主人确认。
- `off`：额度内全自动。

无论哪种模式，以下动作**永远不自动**，必须主人确认：取消、退款、改价、换商家、锁定关键字段。

## 与现有实现的关系

- 第 1 步 = `console-wallet-auth.js` 的 SIWE 登录。
- 第 2–4 步 = 操作台「接入一个 Agent」一条龙向导（`cyber-authorize.js`）顺序落库
  `automation-policy` → `allocations` → `runtime/create-key`。
- 第 5–6 步 = `agent-pairing` 配对码 + `runtime/bind-key` 的 `binding_scope` 平台签收。
- 第 7 步 = `intent_fulfillment.py` 的 `effective_policy_auto` + 确认会话（`confirmation_sessions`）。

## Related

- `docs/AGENT_ONE_CLICK_CONNECT_V1.md` — 一键接入
- `docs/AGENT_ONBOARDING_TEMPLATE_V1.md` — 行业模板目录
- `docs/HUMAN_CONFIRMATION_POLICY_V1.md` — 成交场景的确认策略
- `docs/AGENT_P1_ONBOARDING_V1.md` — P1 就绪 / 防伪