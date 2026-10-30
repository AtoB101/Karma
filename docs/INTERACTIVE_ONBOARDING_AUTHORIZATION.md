# 交互式接入授权（Interactive Onboarding Authorization）

目标：当主人对 agent 说「接入 Karma」时，交互页面里一步步提示并取得授权，
直到授权成功。agent、交互页面、操作台共用同一份七步标准
`packages/evidence-schema/agent-onboarding-authorization-flow.v1.json`。

## 一、整体时序

```
主人 ──"接入 Karma"──▶ agent
agent ──POST /v1/onboarding-authorization/start──▶ Karma API ──▶ 返回 flow_id + 第 1 步 prompt
agent ──渲染 prompt──▶ 交互页面（KarmaOnboardingFlow.render）
主人 ──操作（签名/确认/输码）──▶ 交互页面
交互页面 ──KarmaOnboardingFlow.respond(action, value)──▶ agent
agent ──POST .../{flow_id}/respond──▶ Karma API ──▶ 返回第 2 步 prompt
…循环，直到 status=complete
```

每一步返回的 `prompt` 都是**可直接渲染**的对象；交互页面只按
`prompt_type` 画控件，不需要知道业务顺序。

## 二、七步授权（canonical）

| 序 | step_id | prompt_type | 主人操作 |
|---|---------|-------------|----------|
| 1 | owner_identity | wallet_sign | 钱包 SIWE 登录 |
| 2 | role_declaration | yes_no | 确认接入身份 |
| 3 | funding_bounds | ack | 勾选责任确认 + 确认边界 |
| 4 | runtime_key_mint | wallet_sign | 钱包签名铸运行时钥匙 |
| 5 | agent_pairing | matching_code | 输 8 位对照码 |
| 6 | binding_attestation | info | 点继续（平台签收） |
| 7 | runtime_spend | info | 点继续，完成接入 |

## 三、prompt 对象形状

```jsonc
{
  "status": "in_progress",
  "flow": { "flow_id": "obf_…", "step_index": 2, "status": "in_progress", "collected": {} },
  "prompt": {
    "flow_id": "obf_…",
    "step_id": "funding_bounds",
    "step_index": 3,
    "total_steps": 7,
    "prompt_type": "ack",             // yes_no | ack | wallet_sign | matching_code | info
    "title_zh": "设定资金边界",
    "body_zh": "主人设定单笔上限…",
    "protects_zh": "资金上限与权限…",
    "control": { "control_zh": "责任确认勾选 + 确认 / 拒绝", "actions": ["confirm", "reject"] },
    "actions": ["confirm", "reject"],
    "deep_link": null,
    "payload": {                       // 按 prompt_type 变化
      "defaults": { "single_limit": 100.0, "daily_limit": 500.0, "high_risk_mode": "above_single", "permissions": [ … ] }
    }
  }
}
```

`prompt_type → 控件` 的映射：

- `yes_no`：确认 / 拒绝按钮
- `ack`：责任确认勾选 + 确认 / 拒绝
- `wallet_sign`：`payload.sign_message` + 钱包签名按钮（personal_sign）
- `matching_code`：`payload.match_code` + 输入框
- `info`：信息卡 + 继续

## 四、API

前缀 `/v1/onboarding-authorization`（受保护路由，agent 用 bearer/api-key 调用）：

- `POST /start`  body `{identity_id, profile_id}` → 返回 flow + 第一步 prompt
- `GET /{flow_id}` → 当前步 prompt
- `POST /{flow_id}/respond`  body `{action, value}` → 推进并返回下一步
- `POST /{flow_id}/abort` → 中止流程

`action` 取值：`sign | confirm | reject | cancel | continue`。
`value` 按步骤：wallet_sign 传 `{address, signature}`；matching_code 传
`{code}`；role_declaration 可传 `{profile_id}`；其余 `{}`。

安全边界：本模块只收集「逐步同意 + 交接」，真正的 SIWE / 铸钥匙 / 配对
仍在 `auth` / `runtime_gateway` / `agent_pairing` 里各自再校验一次；
钱包签名不会被本模块当作资产操作的凭据。

## 五、交互页面接入

前端组件：`apps/console/scripts/cyber-onboarding-flow.js`，暴露
`KarmaOnboardingFlow`。两种用法：

```js
// 1) 由 agent 驱动整个流程（推荐）
var flow = KarmaOnboardingFlow.mount(document.getElementById('onboarding'), {
  api: {
    start: (body) => post('/v1/onboarding-authorization/start', body),
    respond: (flowId, action, value) =>
      post('/v1/onboarding-authorization/' + flowId + '/respond', { action, value }),
  },
  walletSign: function (payload, onSigned) {
    // 接入你的钱包适配器；拿到 address + signature 后调用 onSigned
    walletPersonalSign(payload.sign_message).then(onSigned);
  },
});
flow.start(identityId, 'merchant');

// 2) 已有 prompt 时单步渲染
KarmaOnboardingFlow.render(prompt, container, function (action, value) {
  flow.respond(action, value);
}, options);
```

## 五·五、真实钱包签名适配器

`wallet_sign` 步骤（owner_identity / runtime_key_mint）默认自动接入真实钱包：

- 前端组件 `cyber-onboarding-flow.js` 未注入 `options.walletSign` 时，
  自动回落到 `global.KarmaOnboardingWallet.sign`。
- `apps/console/scripts/cyber-onboarding-wallet.js` 暴露
  `KarmaOnboardingWallet.sign(payload, onSigned, onError)`，只调
  `eth_requestAccounts / eth_accounts / personal_sign`，从不接触私钥/助记词。
- provider 解析顺序：`KarmaWalletAuth.activeProvider()` → EIP-6963 发现 →
  `window.ethereum`（MetaMask）→ WalletConnect（需 `window.KARMA_WC_PROJECT_ID`）。

在操作台里，钱包适配器复用 `console-wallet-auth.js` 已连接的钱包；
在裸 agent 页面里，注入 MetaMask 或配 `KARMA_WC_PROJECT_ID` 即可独立工作。

## 六、官方 agent 接入模板（agent 开发者照着做）

1. 读标准：`GET /v1/standards/onboarding/authorization-flow` 拿七步定义。
2. 开流程：`POST /v1/onboarding-authorization/start {identity_id, profile_id}`。
3. 循环：
   - 把 `prompt` 渲染到交互页面（或调用 `KarmaOnboardingFlow.render`）。
   - 等主人动作，`POST /{flow_id}/respond {action, value}`。
   - 若返回 `status=in_progress`，继续渲染下一步；`complete` 则结束。
4. 交接（见 `complete` 响应里的 `next_steps`）：
   - 用 `collected` 里的边界写自动化策略；
   - 主人钱包签名铸运行时钥匙；
   - agent 公钥配对；
   - agent 读 `GET /runtime/policy` 确认自己的边界。

接入模板对应服务函数：`services/onboarding_authorization.py`（状态机）与
`services/agent_onboarding_template.py`（静态标准加载）。
