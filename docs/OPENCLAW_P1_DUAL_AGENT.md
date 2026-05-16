# OpenClaw P0+P1 — 双端自动验证/交付 + 操作端手动授权

本页描述 **P1** 落地范围：两只 OpenClaw 在 **授权已由人在 Console 完成** 的前提下，自动跑 **进度查询、证据校验、执行收据构造、结算状态读取**；**不**通过 MCP 自动创建/接受 Voucher 或签发 Runtime Key。

## 原则

| 动作 | OpenClaw MCP | Karma Console（操作端） |
|------|:------------:|:----------------------:|
| 买方创建 Voucher / EIP-712 签名 | ❌ | ✅ 必须 |
| 卖方 verify + **accept** Voucher | ❌ | ✅ 必须 |
| 签发 / 吊销 Runtime Key | ❌ | ✅ 必须 |
| 首次 lock 额度（建议） | ⚠️ 有 `karma_lock_usdc` 仍建议 Console | ✅ 推荐 |
| 提交证据包、POST /v1/verify | ✅ handoff 校验通过后 | — |
| 列出进度 / 收据、读 settlement | ✅ | — |
| 买方 confirm progress | 默认 ❌（Console） | ✅ 默认 |

环境变量：

- `KARMA_RUNTIME_URL` — Karma API 根地址  
- `KARMA_API_KEY` — 对应身份的 `X-Karma-Api-Key`（卖方/买方各用各的进程）  
- `KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM` — 默认未设置；仅当买方已在 Console 点过确认且策略允许时设为 `true`

## 安装与启动 MCP

```bash
pip install -e ./packages/karma-openclaw
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=karma_<your-identity>_...
karma-openclaw-mcp
```

在 OpenClaw 中注册 **stdio** MCP 桥接上述命令。

## Handoff v1（协同信封）

双方完成 Console 授权后，由操作员导出或生成 `handoff.json`（示例见 `schemas/openclaw-handoff-v1.example.json`），字段：

- `task_id`、`voucher_id`、`buyer_identity_id`、`seller_identity_id`  
- `authorization.manual_console_steps_completed` — 已人工完成的步骤 id  
- `authorization.voucher_status` — 建议 `accepted`

Claw 在跑自动化前调用 MCP：

```text
karma_validate_handoff(handoff_json=<file contents>)
```

校验失败则停止，避免未授权自动化。

### 必须出现在 `manual_console_steps_completed` 的步骤

- `buyer_create_voucher`  
- `seller_accept_voucher`  
- `settlement_created`  

完整列表见 `karma_openclaw/handoff.py` 中的 `ALL_KNOWN_MANUAL_STEPS`。

## P0 MCP 工具（结算执行；仍需 handoff）

| 工具 | 作用 |
|------|------|
| `karma_verify_voucher` | POST verify（**不接受**） |
| `karma_settlement_pending` / `lock` / `start` / `submit` | 状态机推进 |
| `karma_settlement_buyer_accept` | 默认关闭，同 Console |
| `karma_submit_execution_receipt` | POST /v1/receipts |
| `karma_submit_progress` | POST /v1/progress |
| `karma_create_contract` / `create_settlement` | 默认关闭（`KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS`） |
| `karma_runtime_*` | 需 `KARMA_RUNTIME_KEY` |

示例目录：`examples/openclaw-dual-agent/`

环境变量补充：

- `KARMA_OPENCLAW_HANDOFF_PATH` — 默认 handoff 文件路径（可变工具省略 `handoff_json` 参数）  
- `KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS` — 允许 MCP 创建 contract/settlement（默认关）  
- `KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT` — 允许 MCP buyer-accept（默认关）

## P1 MCP 工具一览

| 工具 | 作用 |
|------|------|
| `karma_manual_auth_checklist` | 打印买方/卖方 Console 必做项 |
| `karma_validate_handoff` | 本地 + 可选 live voucher 状态检查 |
| `karma_submit_verification` | POST /v1/verify |
| `karma_list_progress_for_task` | GET progress 列表 |
| `karma_confirm_progress` | 默认关闭，Console 优先 |
| `karma_list_receipts_for_task` | GET 执行收据 |
| `karma_get_settlement` | GET 结算状态 |
| `karma_get_voucher` | 只读 voucher |
| `karma_new_client_nonce` | Runtime 防重放 nonce |
| `karma_build_execution_receipt_step` | 本地构造未签名收据 |
| `karma_build_mcp_receipt_extension` | mcp.* 扩展字段 |

v0.1 仍保留：`karma_get_capacity`、`karma_lock_usdc`、证据包读写。

**故意未提供：** `create_voucher`、`accept_voucher`、`verify_voucher`、`create-key` — 请用 Console。

## 推荐双 OpenClaw 流程

1. **人** — 甲 Console：lock → 创建 voucher；乙 Console：accept voucher；任一方 Console：contract + settlement。  
2. **人** — 填写 handoff.json，勾选 `manual_console_steps_completed`。  
3. **乙 Claw** — `karma_validate_handoff` → 执行工具链 → `karma_build_execution_receipt_step` → 通过 Runtime 或 API 提交收据（Runtime 需单独 sidecar，非本 MCP 包）。  
4. **甲/乙 Claw** — `karma_submit_verification`（bundle + contract JSON）。  
5. **人** — Console：`submit` delivery、`buyer-accept`（或卖方/买方 Runtime `request-settlement` sidecar）。  
6. 可选链上：仍用 `docs/TESTNET_RUNBOOK.md`，不由 OpenClaw 持私钥。

## Webhook（可选，后续）

已实现出站 webhook + 可选轮询，见 `docs/openclaw-handoff-webhook-v1.md`。MCP：`karma_poll_handoff_events`、`karma_automation_status`、`karma_runtime_check_voucher`。

## 相关文档

- `packages/karma-openclaw/README.md`  
- `docs/mcp-adapter-guide.md`  
- `docs/AGENT_INTEGRATION.md`  
- `examples/openclaw-adapter/README.md`
