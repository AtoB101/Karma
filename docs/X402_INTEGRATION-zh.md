# x402 机器支付集成（Phase 2）

> **基线：** `main` @ Phase 2 PR  
> **路线图：** [`KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md`](KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md) §5

## 目标

Agent 调用 **x402 兼容 HTTP API**（402 → 支付 → 重试），并将外部支付锚定到 Karma **ExecutionReceipt.external_payment** 与 settlement **funding_source**。

## 模块

| 路径 | 说明 |
|------|------|
| `sdk/x402/client.py` | 解析 `PAYMENT-REQUIRED`、预算校验、`pay_and_fetch` |
| `sdk/x402/middleware.py` | 示例卖方 402 中间件 |
| `sdk/x402/executors.py` | `MockX402PaymentExecutor`（CI/本地） |
| `services/x402_service.py` | `pay_and_fetch_with_audit` → receipt + funding_source |
| `POST /v1/x402/pay-and-fetch` | Runtime API |
| `karma_x402_fetch` | OpenClaw MCP |

## 配置

```env
X402_ENABLED=true
X402_PAYMENT_BACKEND=mock
X402_DEFAULT_MAX_BUDGET_USDC=10
X402_HARD_MAX_BUDGET_USDC=100
X402_ALLOW_PRIVATE_HOSTS=true   # 本地 mock；生产应 false
```

## 审计字段

**ExecutionReceipt.external_payment:**

```json
{
  "protocol": "x402",
  "tx_hash": "0x...",
  "amount_usdc": 1.0,
  "resource_url": "https://...",
  "payment_proof": "<PAYMENT-SIGNATURE b64>",
  "network": "base-sepolia",
  "asset": "USDC"
}
```

**Settlement.funding_source:** `internal` | `x402` | `hybrid`

## 验收

```bash
bash scripts/acceptance/phase2_x402_gate.sh
python3 examples/x402_agent_buy_api/mock_server.py   # 另开终端
```

示例：`examples/x402_agent_buy_api/README.md`

## 安全（KSA-X402）

见 [`public-testing/attack-testing-roadmap.md`](public-testing/attack-testing-roadmap.md) §3.4。

## 下一步

- 真实 Sepolia USDC + `SigningBackend` 支付执行器  
- 生产 `X402_ALLOW_PRIVATE_HOSTS=false`
