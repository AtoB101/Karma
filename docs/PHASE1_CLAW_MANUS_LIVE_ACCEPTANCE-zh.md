# 阶段一 · OpenClaw / OpenManus 实测验收清单

在 **`main` 已合入 #78/#79** 且 `alembic upgrade head`（至 `0025`）后，用本清单在本地或测试网完成 **Claw + Manus** 接入实测。

## 0. 环境（共用）

```bash
export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export AUTH_ENFORCE_PROTECTED_ROUTES=false   # 本地实测可关；生产必须 true
export LEDGER_REQUIRE_PARTY_ACTOR=false      # 本地 pytest/脚本可关
export TRADE_LAUNCH_REQUIRE_EIP712=false     # 路径 A 本地兼容
# 配合 OPENCLAW_LOCAL_PHASE1_AUTO_RELAX=true 放宽 progress/receipt 签名校验（见 deploy/.env.local-openclaw.example）
# 完整模板：deploy/.env.local-openclaw.example
# 测试网：
# export SETTLEMENT_MODE=testnet
# export chain_anchor_hash=0x<64 hex>  # launch 时必填
```

启动 API：`uvicorn api.app:app --host 0.0.0.0 --port 8000`（或 deploy 栈）。

买方/卖方各准备：

- `identity_id`、API Key（`X-Karma-Api-Key`）
- `PUT /v1/identities/{id}/automation-policy`：`preauth_enabled`、`auto_enabled`、`auto_execute_pipeline=true`、`responsibility_acknowledged`
- 有效 **Runtime Key**
- 买方 `available_credits` 充足；卖方 `auto_accept_incoming` + 信任买方

自动化冒烟（不启动 MCP stdio）：

```bash
# 路径 A — 无 EIP-712（deploy/.env.local-openclaw.example）
python3 scripts/acceptance/phase1_claw_manus_smoke.py --buyer-id <buyer> --seller-id <seller>

# 路径 B — EIP-712 代签（deploy/.env.local-eip712.example）
python3 scripts/acceptance/phase1_eip712_launch_smoke.py --buyer-id <buyer> --seller-id <seller>
```

---

## A. OpenClaw（`karma-openclaw` MCP）

### 安装与测试

```bash
pip install -e "./packages/karma-openclaw[dev]"
pytest packages/karma-openclaw/tests -q
```

### MCP 启动

```bash
export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export KARMA_API_KEY=karma_<buyer-or-seller>_...
karma-openclaw-mcp
```

在 OpenClaw 注册 **stdio** MCP。

### 路径 1 — 全自动 trade launch（买方 API Key）

| 步骤 | MCP 工具 | 通过标准 |
|------|----------|----------|
| 1 | `karma_save_automation_policy`（买卖双方，或 Console 已保存） | 200，`preauth_enabled` 等 |
| 2 | `karma_launch_trade_order`（带唯一 `idempotency_key`） | `status=execution_started`，含 `task_id`、`order_id` |
| 3 | 重复步骤 2 相同 idempotency_key | `idempotent_replay: true`，同一 `order_id` |
| 4 | `karma_get_trade_order` | `pipeline_version=v2`，状态一致 |
| 5 | `karma_get_handoff_draft` + `karma_confirm_handoff`（买卖双方） | readiness 无 blocker |
| 6 | `karma_continue_after_trade_launch` | `ok: true`，含 `next_steps` |
| 7 | **卖方** `karma_submit_execution_receipt` / `karma_submit_progress` | handoff 校验通过后 2xx；本地 `TRADE_LAUNCH_REQUIRE_EIP712=false` 时 MCP 自动填充 `0xopenclaw_*` 占位签名 |
| 7b | （可选）pipeline 已写首条 progress | launch 后 `karma_list_progress_for_task` 已有 5% progress 则 A7 可标 pipeline-covered |

### 路径 2 — 付款码 + 传统/预授权（与 Console 一致）

| 步骤 | MCP 工具 | 通过标准 |
|------|----------|----------|
| 1 | `karma_build_payment_code_request` → `karma_create_payment_code` | `voucher_id`、`payment_code` |
| 2 | `karma_get_payment_code` | 载荷 hash 稳定 |
| 3a 预授权 | 卖方策略允许 | 自动 accept/reject + `karma_list_voucher_events` |
| 3b 传统 | `karma_accept_payment_code`（卖方 Key） | voucher `accepted` |
| 4 | handoff + P0 工具续跑 | 同 `docs/OPENCLAW_P1_DUAL_AGENT.md` |

### OpenClaw 签核

- [ ] MCP 工具列表含 Phase 1 表（见 `packages/karma-openclaw/README.md`）
- [ ] launch 幂等通过
- [ ] 卖方 receipt/progress 在 handoff 后成功

---

## B. OpenManus（BFF + 可选 Runtime）

### B1 — BFF 闭环（原有）

```bash
pip install -e ./packages/karma-openmanus
export KARMA_BFF_URL=http://127.0.0.1:8820
export BFF_INTEGRATION_SECRET=...
pytest tests/test_karma_bff_smoke.py -q
```

| 步骤 | 客户端方法 | 通过标准 |
|------|------------|----------|
| 1 | `KarmaBffClient.create_task` | `trace_id` 返回 |
| 2 | `submit_order_snapshot` → `request_buyer_lock_page` | 状态前进 |
| 3 | 链 webhook 或 dev simulate | `EXECUTE_ALLOWED` |
| 4 | `append_execution_receipt` | 收据写入 |

工具定义：`packages/openmanus-karma-tools/tools.json`

### B2 — Runtime 阶段一（新增 `KarmaRuntimeClient`）

```bash
export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export KARMA_API_KEY=karma_<buyer>_...
python3 -c "
import asyncio
from karma_openmanus import KarmaRuntimeClient
async def main():
    c = KarmaRuntimeClient.from_env()
    out = await c.launch_trade_order(
        buyer_identity_id='buyer-1',
        seller_identity_id='seller-1',
        requirement_text='caption 测试 15 USDC',
        idempotency_key='manus-live-001',
        task_type='api.caption',
    )
    print(out)
asyncio.run(main())
"
```

| 步骤 | 方法 | 通过标准 |
|------|------|----------|
| 1 | `launch_trade_order` | `execution_started` |
| 2 | `get_trade_order` | 与 launch 一致 |
| 3 | `get_automation_readiness` | `ready_for_task_automation` 按策略 |
| 4 | `get_handoff_draft` | 可导出 handoff 字段 |

Runtime 工具清单：`packages/karma-openmanus/karma_openmanus/data/runtime_tools.json`

### OpenManus 签核

- [ ] BFF smoke 绿
- [ ] `KarmaRuntimeClient.launch_trade_order` 实测成功
- [ ] 编排器仅在 `EXECUTE_ALLOWED`（BFF）或 `execution_started`（Runtime）后跑重任务

---

## C. Console 交叉验证

- [ ] `apps/console/pages/trade/` 发起全流程带 `Idempotency-Key`
- [ ] 与 MCP launch 返回的 `task_id` 可在 `GET /v1/settlement/{task_id}` 查到

---

## D. 合入与发布

| 项 | 状态 |
|----|------|
| main 含 #78 阶段一 + #79 安全 | 已合入 |
| 本 SDK PR | `cursor/sdk-openclaw-openmanus-integration-3ed7` |
| 迁移 | `0025` |

---

## 参考

- `docs/CONSOLE_PHASE1_TRADITIONAL_PREAUTH-zh.md`
- `docs/TESTNET_PHASE1_TRADE_ACCEPTANCE-zh.md`
- `docs/OPENCLAW_OPERATOR_CHECKLIST-zh.md`
- `examples/phase1-live-test/README.md`
