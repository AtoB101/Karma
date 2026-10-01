# x402 机器支付集成（Phase 2）

> **基线：** `main` @ Phase 2 PR  
> **路线图：** [`INTEGRATIONS.md`](INTEGRATIONS.md) · [`FOCUS_ROADMAP.md`](FOCUS_ROADMAP.md)

## 目标

Agent 调用 **x402 兼容 HTTP API**（402 → 支付 → 重试），并将外部支付锚定到 Karma **ExecutionReceipt.external_payment** 与 settlement **funding_source**。

## 模块

| 路径 | 说明 |
|------|------|
| `sdk/x402/client.py` | 解析 `PAYMENT-REQUIRED`、预算校验、`pay_and_fetch` |
| `sdk/x402/middleware.py` | 示例卖方 402 中间件 |
| `sdk/x402/executors.py` | `MockX402PaymentExecutor`（CI/本地） |
| `sdk/x402/chain_executor.py` | `EnvSigningX402PaymentExecutor`（EIP-191 签名证明）、`SepoliaErc20X402PaymentExecutor`（真实 USDC transfer） |
| `services/x402_service.py` | `pay_and_fetch_with_audit` → receipt + funding_source |
| `POST /v1/x402/pay-and-fetch` | Runtime API |
| `karma_x402_fetch` | OpenClaw MCP |

## 配置

```env
X402_ENABLED=true
X402_PAYMENT_BACKEND=mock   # mock | env | sepolia
X402_DEFAULT_MAX_BUDGET_USDC=10
X402_HARD_MAX_BUDGET_USDC=100
X402_ALLOW_PRIVATE_HOSTS=false  # 代码默认 true（本地 mock 图方便）；生产必须 false，闸门 A6 判
X402_PRIVATE_KEY=0x...          # env / sepolia 后端的专用热钱包（一把 service agent 一把 key）
TESTNET_RPC_URL=...             # sepolia 后端
ERC20_TOKEN_ADDRESS=0x...       # sepolia USDC
```

私钥的解析顺序是 `X402_PRIVATE_KEY` → `KARMA_SIGNING_DEV_PRIVATE_KEY` →
`TESTNET_PRIVATE_KEY`（后两个是 dev/CI 的便利）。`SETTLEMENT_OPERATOR_PRIVATE_KEY`
**故意不在链上**：托管结算走 `allowance_escrow._broadcast_tx`，那里的 nonce 由进程内缓存
分配（`_SEND_LOCK` + `_LAST_NONCE`），而 x402 的 `chain_executor` 是各自读
`get_transaction_count` —— 两个发送方共用一个钱包会拿到同一个 nonce，后签的那笔会把前一笔
顶掉，最坏情况是托管结算被静默替换。**每个 service agent 一把独立 key**，这条对 x402 同理。

## 出网安全（KSA-X402-005 / SSRF）

`/v1/x402/pay-and-fetch` 的目标 URL 是调用方（agent）给的，所以它是一个「调用方指定目标」
的出网口：

- `X402_ALLOW_PRIVATE_HOSTS=false`（生产强制）时，`sdk/x402/url_safety.py` 拒绝
  `localhost` / 环回 / 私网 / 链路本地 / 保留 / 组播地址的字面 IP；
- 裸域名**先解析再判**：域名指向 `127.0.0.1` 或云元数据 `169.254.169.254` 一律拒绝，
  解析不出来也拒绝（原来只查字面 IP，裸域名直接放行，等于没拦）；
- 解析放在 `asyncio.to_thread` 里做，不堵事件循环。

**残留缺口要说清楚**：这里解析一次，httpx 连的时候会再解析一次，中间换了答案（DNS
rebinding）这次检查拦不住。要彻底关掉这个口子得把连接钉在验过的 IP 上，本轮没做。

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

## 后端模式

| `X402_PAYMENT_BACKEND` | 行为 |
|------------------------|------|
| `mock` | 占位 tx + 签名（CI，**生产禁止**） |
| `env` | EIP-191 签名 `PAYMENT-SIGNATURE`；`tx_hash` 是 **digest，不是链上哈希**（生产禁用） |
| `sepolia` | 真实 ERC-20 `transfer`，等回执再返回；`tx_hash` 是**真的链上交易哈希** |

> 只有 `sepolia` 的 `tx_hash` 是链上哈希。`env` 那份是 EIP-191 摘要，字段名一样但语义不同 —— 生产用 `sepolia`（`config/settings.py` 的生产校验里 `mock` 直接拒绝，`env`/`sepolia` 必须有 key）。

## 下一步

- EIP-3009 `transferWithAuthorization`（完整 x402 链上路径，现在是 `transfer`）
- 把 DNS 解析结果钉到连接上，堵住 rebinding（见上文「残留缺口」）
