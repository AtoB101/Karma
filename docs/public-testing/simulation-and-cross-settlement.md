# 公开模拟与交叉结算测试说明

> 最近更新：2026-05-13  
> 本文档描述 **公开可复现** 的模拟/压测思路与账本守恒验收口径；具体脚本与命令以仓库内 Runbook 为准。

---

## 1. 目标

- 在 **多账号、多路径交叉结算** 场景下，验证容量、预留、结算与冲销路径 **无系统性漏记或重复记账**。  
- 对外给出可审计的 **守恒指标**（例如全账汇总 **Delta=0**）及复现边界（环境、规模、随机种子）。

---

## 2. 环境与性能说明（公开结论对齐）

| 层级 | 说明 |
|------|------|
| **默认生产配置** | 应用默认 `database_url` 指向 **PostgreSQL**（`postgresql+asyncpg://…`），见 `config/settings.py`。生产级并发与连接池应在此类部署上验证。 |
| **CI / 集成测试** | `tests/conftest.py` 使用 **内存 SQLite**（`sqlite+aiosqlite:///:memory:`），用于快速、确定性回归；**不**代表生产吞吐上限。 |
| **瓶颈认知** | 若在 SQLite 上执行大规模交叉压测，数据库锁与单文件 I/O 往往成为 **主要瓶颈**；与协议逻辑是否守恒需区分看待——前者是引擎选型，后者是业务不变量。 |

---

## 3. 验收口径（示例：账本 Delta）

- **Delta=0**：在定义的聚合口径下（例如按身份/币种/账本科目汇总），全量流入与流出一致，无净漂移。  
- 具体科目定义、聚合 SQL 或脚本版本 **应在每次公开轮次中写明**（避免口头结论无法复核）。

---

## 4. 与仓库脚本的对应关系

| 能力 | 入口 |
|------|------|
| Trusted Agent Runtime 结构压测（Phase 4） | [`STRESS_TEST_RUNBOOK.md`](../STRESS_TEST_RUNBOOK.md)、`scripts/stress_trusted_agent_runtime.py` |
| API 层回归（含 Runtime E2E） | [`sdk-quickstart.md`](../sdk-quickstart.md) 中 pytest 说明；`make test-python` |
| 加固项与 E2E 报告对照 | [`testing-public-hardening.md`](../testing-public-hardening.md) |

若新增 **专用** 交叉结算压测脚本，请在本节增加一行链接，并在 [README 索引表](./README.md#4-公开结果索引模板) 登记轮次。

---

## 5. 后续更新（占位）

- [ ] 附上公开轮次的 **规模参数**（账号数、笔数、时长、种子）。  
- [ ] 附上 **Delta 定义** 与校验命令或脚本路径。  
- [ ] 对比 **SQLite 压测 vs PostgreSQL 压测** 的吞吐与延迟区间（仅公开聚合指标，不含内网拓扑）。
