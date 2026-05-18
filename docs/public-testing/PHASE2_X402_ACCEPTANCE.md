# Phase 2 x402 验收（公开摘要）

> 最近更新：2026-05-18  
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
| 真实 x402 provider + Sepolia USDC | ☐ |
| OpenClaw `karma_x402_fetch` 实机 | ☐ |

## 生产闸门

- `X402_ALLOW_PRIVATE_HOSTS=false`
- `X402_PAYMENT_BACKEND` 非 `mock`（待实现 chain 执行器）
