# 全量压力 & 攻击测试验收（公开摘要）

> 最近更新：2026-05-17  
> 公开基线：`ee68f62d3c3f2f0cda3ee1b3d3b6c375c9997b9a`  
> 完整工件（若存在）：`reports/stress-attack-test-2026-05-17.md`（私仓 / CI，不纳入公开 git）

## 总览

| 指标 | 结果 |
|------|------|
| 总测试量 | **3,143** |
| CRITICAL/HIGH 漏洞 | **0** |
| MEDIUM 待修复（轮次初） | **3**（见下「公开仓修复」） |
| 综合评估 | **安全态势良好** |

## 分层覆盖

| 层 | 数量 | 结果 |
|----|------|------|
| Pytest 单元/集成/E2E | 261 | 260 通过 (99.6%) |
| Foundry 合约 | 85 | 85 (100%) |
| 攻击模拟（12 类 / 30 种） | 30 | **27 拦截** / 3 MEDIUM |
| 压力（500 并发） | 2,760 req | 1,854 ok / 906 err |
| Sepolia on-chain | 7 | 7 (100%) |

## 攻击防御矩阵（27/30 = 90%）

| 级别 | 结果 |
|------|------|
| CRITICAL（5/5） | ✅ 超大金额、Nonce 重放、状态机绕过、双重结算、并发竞态 |
| HIGH（8/8） | ✅ ID 伪造、提现密钥、步骤重复、进度回退、并发收据、非参与方争议、自交易、未授权 Admin |
| INJECTION（8/8） | ✅ SQL、XSS、模板、路径遍历、超大字段 |

## MEDIUM 项与公开仓对策

| # | 发现 | 公开仓状态（2026-05-17 分支） |
|---|------|------------------------------|
| 1 | 批量 Agent 注册无速率限制（500/500） | **已加固**：`POST /v1/agents` 使用 `register_agent` 限流键；Redis 不可用时仅该键启用进程内滑动窗口兜底（`api/middleware/rate_limit.py`）；`POST /v1/auth/token` 仍用 `register` 键；生产须 `RATE_LIMIT_REDIS_FAIL_CLOSED=true` + Redis |
| 2 | 乱序时间戳未严格校验 | **已加固**：`POST /v1/receipts` 拒绝 `started_at` 早于同任务上一笔收据（`api/routes/receipts.py`）；进度见 `api/routes/progress.py` |
| 3 | 环形结算 A→B→C→A | **已有 KSA2-034**：`assert_lock_does_not_close_payment_cycle`；补充三角环集成测 `tests/integration/test_triangle_settlement_cycle.py`。压测须 `settlement_block_buyer_worker_payment_cycle=true`（默认 true） |

复测建议：在 **Redis 可用** 且 **PostgreSQL** 环境下重跑攻击/压力套件；SQLite 单 worker 下 Agent 列表读 94/500 为已知瓶颈，非安全漏洞。

## 合约不变量（最高等级）

```
active + reserved == locked
Runs: 256 | Calls: 128,000 | Reverts: 0
```

## 压力测试摘要（500 并发）

| 场景 | 结果 | 备注 |
|------|------|------|
| Health | 500/500 | ~75 req/s |
| Agent 注册（写） | 500/500 | ~56 req/s；修复后无 Redis 时受进程内限额约束 |
| Rapid Burst | 500/500 | ~152 req/s |
| Agent 列表（读） | 94/500 | SQLite 读瓶颈；生产 PostgreSQL 预期 5–10× |

## 复现（公开仓）

```bash
# 单元 + 集成（含环、时序、攻击回归）
pytest tests/unit/test_level2_attack_mitigations.py \
  tests/unit/test_security_attack_mitigations.py \
  tests/integration/test_triangle_settlement_cycle.py \
  tests/unit/test_receipt_chronology.py -q

forge test -vv

# 结构压测（本地确定性，非 HTTP）
python3 scripts/stress_trusted_agent_runtime.py --agents 100 --seed 42
```

## 相关文档

- [attack-testing-roadmap.md](./attack-testing-roadmap.md)  
- [TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md](./TESTNET_PREAUTH_ACCEPTANCE_2026-05-17.md)  
- [STRESS_TEST_RUNBOOK.md](../STRESS_TEST_RUNBOOK.md)  
- [PRODUCTION_PRELAUNCH_CHECKLIST-zh.md](../PRODUCTION_PRELAUNCH_CHECKLIST-zh.md)
