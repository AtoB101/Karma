# OpenClaw 授权与自动化 — 运营检查清单（一页纸）

面向 **Console 操作员** 与 **上线验收**。完整技术说明见 `docs/OPENCLAW_P1_DUAL_AGENT.md`；代码合入后执行迁移 `alembic upgrade head`（`0020`–`0022`）。

---

## 上线前（平台 / SRE，一次性）

| 检查项 | 要求 |
|--------|------|
| 合并 PR | [PR #75](https://github.com/AtoB101/Karma/pull/75)（或等价授权链分支）已合 `main` |
| 数据库迁移 | `alembic upgrade head` |
| `APP_ENV` | `production` |
| Runtime 闸门（全部为 `true`） | `RUNTIME_REQUIRE_SAVED_AUTOMATION_POLICY`、`RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS`、`RUNTIME_REQUIRE_HANDOFF_ATTESTATION`、`RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING`、`RUNTIME_DAILY_SPEND_PERSIST` |
| API 鉴权 | `AUTH_ENFORCE_PROTECTED_ROUTES=true`，`AUTH_API_KEYS` 已配置 |
| OpenClaw 进程（买方/卖方各一份） | `KARMA_OPENCLAW_REQUIRE_SERVER_ATTESTATION=true` |

参考：`deploy/.env.paas.example`、`deploy/one-click-deploy.md`。

---

## 每个任务：Console 六步（人工授权 → 才允许 AI）

在 **Settings** 页按顺序完成；**不可跳步**。

| 步 | 操作 | 通过标准 |
|:--:|------|----------|
| 1 | 填写单次/每日 USDC 额度、勾选 Runtime 权限、**勾选责任边界确认** | 权限范围最小化（默认勿勾 `request_voucher`） |
| 2 | **保存服务端策略** | 页上显示「策略：已保存」 |
| 3 | 钱包签名 **铸造 Runtime Key** | 成功；额度/权限不超过步骤 1；钱包将绑定 identity |
| 4 | 在 Payments/Receiving 等页 **人工** 完成 Voucher 创建、卖方 **Accept**、Settlement 创建/锁定 | 账本状态与业务一致 |
| 5 | ① **检查自动化就绪**（`for_handoff_confirm`） | 返回 `ready_for_handoff_confirm: true`，无未解决 `blockers` |
| 6 | ② **登记服务端存证** → ③ **导出 handoff.json** | 显示「存证：已登记」；再将 handoff 交给对应 OpenClaw |

**禁止由 AI 代做：** Voucher 创建/接受、Runtime Key 签发、责任边界未确认即开启自动执行。

---

## 每个参与方：API 快速验收（可选 curl）

将 `BASE`、`KEY`、`IDENTITY`、`TASK` 替换为实际值。

```bash
# 4 — 登记存证前就绪（不含存证项）
curl -s -H "X-Karma-Api-Key: $KEY" \
  "$BASE/v1/openclaw/automation-readiness?task_id=$TASK&karma_identity_id=$IDENTITY&role=buyer&for_handoff_confirm=true"

# 5 — 登记存证
curl -s -X POST -H "X-Karma-Api-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"task_id\":\"$TASK\",\"karma_identity_id\":\"$IDENTITY\",\"role\":\"buyer\"}" \
  "$BASE/v1/openclaw/handoff-confirm"

# 存证是否生效
curl -s -H "X-Karma-Api-Key: $KEY" \
  "$BASE/v1/openclaw/handoff-attestation?task_id=$TASK&karma_identity_id=$IDENTITY"

# 6 — 全量就绪（含存证，开启 RUNTIME_REQUIRE_HANDOFF_ATTESTATION 时）
curl -s -H "X-Karma-Api-Key: $KEY" \
  "$BASE/v1/openclaw/automation-readiness?task_id=$TASK&karma_identity_id=$IDENTITY&role=buyer"
```

期望：最后一次 `automation-readiness` 中 `ready_for_task_automation: true`。

---

## 买方 / 卖方 OpenClaw 进程

| 变量 | 买方 | 卖方 |
|------|------|------|
| `KARMA_RUNTIME_URL` | API 地址 | 同左 |
| `KARMA_API_KEY` | 买方 API Key | 卖方 API Key |
| `KARMA_ID` | 买方 identity | 卖方 identity |
| `KARMA_RUNTIME_KEY` | 买方铸 Key 结果 | 卖方铸 Key 结果 |
| `KARMA_OPENCLAW_HANDOFF_PATH` | 导出 handoff 路径 | 同左 |
| `KARMA_OPENCLAW_REQUIRE_SERVER_ATTESTATION` | `true` | `true` |

启动 MCP 后建议先调用：`karma_check_automation_readiness` → `karma_validate_handoff`。

**默认保持关闭（除非 Console 已人工确认）：**  
`KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS`、`KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT`、`KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM`。

---

## 常见失败与处理

| 现象 | 原因 | 处理 |
|------|------|------|
| 不能铸 Runtime Key | 未保存策略 / 与策略额度权限不一致 | 回到步骤 1–2 |
| `wallet does not match` | 换钱包签 Key | 使用已绑定钱包或联系管理员解绑 |
| 就绪检查有 blockers | Voucher 未 accept、无 Settlement、无 Key 等 | 完成步骤 4 人工项 |
| 不能登记存证 | `ready_for_handoff_confirm` 为 false | 先解决 blockers |
| Runtime 403 `automation_not_ready` | 未存证或未就绪 | 完成步骤 5–6 |
| MCP `handoff_not_attested` | 未 `handoff-confirm` | Console 步骤 6② |
| 超过每日额度 | 当日 Runtime 累计超限 | 调策略或次日重试 |

---

## 签字确认（上线/试点）

| 角色 | 姓名 | 日期 | 签名 |
|------|------|------|------|
| 产品/运营 | | | |
| 工程 | | | |
| 安全复核 | | | |

---

*文档版本：与 PR #75 授权链一致；如有 env 名变更以 `config/settings.py` 为准。*
