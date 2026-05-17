# 测试网 · 预授权 Agent 自动执行验收（公开摘要）

> 最近更新：2026-05-17  
> 公开基线：`ee68f62d3c3f2f0cda3ee1b3d3b6c375c9997b9a`（`main`，含 #78/#79/#80）  
> 完整工件（若存在）：私仓 / CI 内 `reports/testnet-pre-auth-2026-05-17.md`（不纳入公开 git）

## 结论

| 指标 | 结果 |
|------|------|
| 总测试 | 353 |
| 通过 | 352 |
| 通过率 | **99.7%** |
| CRITICAL/HIGH 漏洞 | **0** |
| Sepolia 链上 | **7/7** |

**判定：测试网预授权 + 全自动流水线验收通过**（生产前另见 [PRODUCTION_PRELAUNCH_CHECKLIST-zh.md](../PRODUCTION_PRELAUNCH_CHECKLIST-zh.md)）。

## 分层结果

| 层 | 通过 | 说明 |
|----|------|------|
| Python API / 集成 / 运行时 | 260/261 | 见「唯一失败项」 |
| Foundry 合约 | 85/85 | 含不变量 fuzz 256 runs × 128k calls，0 revert |
| Sepolia on-chain | 7/7 | 与 manifest / RPC 配置一致时 |

## 预授权全链路（已验证）

```
AutomationPolicy → ReadinessGate → HandoffAttestation → RuntimeKey → VoucherVerify
                                                       ↓
TradeOrderLaunch → Decompose → AutoAccept → Settlement → ExecutionKickoff
```

| 闸门 | 预期 | 实测 |
|------|------|------|
| 无策略 | 403 | ✅ |
| 无 handoff 证明 | 403 | ✅ |
| 精度不匹配 | 自动拒绝 | ✅ |
| 未信任对手方 | 阻止 | ✅ |
| 重复 launch | 幂等 | ✅ |

## 合约（公开 NC 栈）

- 结算流程测试 49 + 引擎/认证/断路器 35  
- 不变量：`active + reserved == locked`，128k calls 无违规  

## 配置注意

| 项 | 测试网 | 生产建议 |
|----|--------|----------|
| `RECEIPT_REQUIRE_SIGNATURE` | 曾关闭以跑部分用例 | **必须 true**（`APP_ENV=production` 强制） |
| `SETTLEMENT_MODE` | testnet/hybrid | 按部署 |
| `chain_anchor_hash` | launch 必填（testnet/hybrid） | 同左 |

## 唯一失败项（261 套件中的 1 条）

在启用 `RECEIPT_REQUIRE_SIGNATURE=false` 的测试配置下可能出现；**生产环境不得关闭**。公开仓 `APP_ENV=production` 启动校验已拒绝 `receipt_require_signature=false`（PR #82）。

## 复现（公开仓）

```bash
alembic upgrade head
pytest tests/integration/test_phase1_payment_code_flow.py \
  tests/integration/test_trade_order_pipeline_launch.py \
  tests/integration/test_automation_authorization_chain.py -q
```

测试网脚本：`scripts/testnet/trade_preauth_pipeline_acceptance.py` — 见 [TESTNET_PHASE1_TRADE_ACCEPTANCE-zh.md](../TESTNET_PHASE1_TRADE_ACCEPTANCE-zh.md)。

## 相关文档

- [PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md](../PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md)  
- [OPENCLAW_OPERATOR_CHECKLIST-zh.md](../OPENCLAW_OPERATOR_CHECKLIST-zh.md)  
- [STRESS_ATTACK_ACCEPTANCE_2026-05-17.md](./STRESS_ATTACK_ACCEPTANCE_2026-05-17.md)
