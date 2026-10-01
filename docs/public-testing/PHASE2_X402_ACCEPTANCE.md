# Phase 2 x402 验收（公开摘要）

> 最近更新：2026-10-01  
> 操作文档：[`X402_INTEGRATION-zh.md`](../X402_INTEGRATION-zh.md)

## 自动化（公开 CI）

```bash
bash scripts/acceptance/phase2_x402_gate.sh
```

| 套件 | 预期 | 状态 |
|------|------|------|
| x402 单测 + 集成 | mock 402 → pay → receipt | pass（CI） |
| benchmark | `results/x402_benchmark_summary.json` | pass（CI） |

## 人工 / 测试网（待填）

| 场景 | 结果 |
|------|------|
| Sepolia USDC `sepolia` 后端 + 链上 tx | ✅ 2026-10-01（生产机实测，见下） |
| 出网护栏：私网/环回目标被拒 | ✅ 2026-10-01（生产配置拒绝 `http://127.0.0.1:9402/paid`） |
| OpenClaw `karma_x402_fetch` 实机 | ☐ 仍未跑（缺一个公网 x402 卖方） |

### 2026-10-01 真链实测（生产机 `47.82.74.68`）

`X402_PAYMENT_BACKEND=sepolia`、`X402_ALLOW_PRIVATE_HOSTS=false`，收款方是仓库里的示例
402 mock server（`payTo=0xdddd…`，只跑在容器环回上，测完即停）：

| 项 | 值 |
|---|---|
| 付款钱包 | `0x16B22fc82F4D0666d8B834e39409E006eB1Adb48`（x402 专用，与结算钱包分开；带 0.02 ETH gas / 50 mUSDC） |
| 链路 | 402 → 链上 `transfer` → 等回执 → 重试 → HTTP 200 |
| 交易哈希 | `0x73b99bae320e0a94ec0489ab133730aafb58b78ef88c02c8c4161522f754bcc0`（block 11821978） |
| 金额 | 1.000000 mUSDC：付款方 50.000000 → 49.000000，收款方 0.000000 → 1.000000 |
| 护栏 | 同一 URL 用**生产配置**的 client 调用被拒：`localhost targets disabled` |

说明两点，免得被误读：

- 收款方是环回上的 mock（我们没有公网 x402 卖方），所以付款那一步用的是
  `allow_private_hosts=True` 的测试 client；**生产配置本身**（`false`）在同一台机器上
  拒绝了同一个 URL。两条都跑了，不是二选一。
- 之前的 `X402_PAYMENT_BACKEND=env` 从没在生产跑通过：`KARMA_SIGNING_DEV_PRIVATE_KEY` /
  `TESTNET_PRIVATE_KEY` 都没设，`build_x402_client()` 一调用就 `ValueError`。所以
  「`tx_hash` 是 EIP-191 摘要而不是链上哈希」这件事,线上没有发生过 —— 现在换成
  `sepolia`，`tx_hash` 是真的链上交易哈希。

## 生产闸门

- `X402_ALLOW_PRIVATE_HOSTS=false` —— 机器判：`public-beta-security-gate.sh` 的 `A6`
- `X402_PAYMENT_BACKEND` 非 `mock` —— `A6` + `config/settings.py` 的发布环境校验
- `env` / `sepolia` 后端必须有 `X402_PRIVATE_KEY` —— 同上（生产构建期就拒绝启动）
