# 测试网公开验收说明

> 最近更新：2026-05-13  
> 本文档约定：**测试网相关验收步骤与对外可公开的结果** 均在本 `docs/public-testing/` 目录体系内维护或索引。

---

## 1. 权威操作文档（不重复抄写）

以下文档为当前仓库内的 **测试网执行权威来源**，本文件只做索引与「对外承诺」边界说明：

| 文档 | 用途 |
|------|------|
| [`TESTNET_RUNBOOK.md`](../TESTNET_RUNBOOK.md) | 最小链上路径、环境变量、脚本入口 |
| [`TESTNET_EXECUTION_CHECKLIST.md`](../TESTNET_EXECUTION_CHECKLIST.md) | 执行前检查项 |
| [`testnet-integration-checklist.md`](../testnet-integration-checklist.md) | 集成验收清单 |
| [`TESTNET_RUNBOOK.md`](../TESTNET_RUNBOOK.md) 同目录相关脚本 | `scripts/testnet_*.py` 等（以 Runbook 为准） |

---

## 2. 对外公开内容（允许写进本目录的）

- 网络名称与 **chain_id**  
- 已部署合约地址（引擎 / NonCustodial / Token 等）  
- **公开** 交易哈希、区块高度、事件摘要  
- 验收结论：通过 / 有条件通过 / 阻塞项（不含内网 IP、密钥、内部账号口令）

---

## 3. 不得在本目录出现的内容

- 任何私钥、助记词、`.env` 全文  
- 带凭证的 RPC URL（内网或带 API Key 的完整 URL）  
- 未披露的漏洞利用链（遵循负责任披露）

---

## 4. 公开结果索引（测试网轮次）

| 轮次代号 | 日期 | 网络 | 结论摘要 | 详细说明 / 工件 |
|----------|------|------|----------|-----------------|
| （待填） | — | 例：Sepolia | — | 链接至本节下方子段落或外部审计友好的摘要 MD |

每次公开测试网轮次结束后：

1. 在本表新增一行；  
2. 若有需要，在 `README.md` 的 [总索引表](./README.md#4-公开结果索引模板) 同步一行；  
3. 在 [`migrations/`](../migrations/) 或发布说明中已有 breaking 时，按仓库规范更新迁移影响说明。

---

## 5. 与「模拟压测」文档的分工

- **模拟 / 压测 / 账本 Delta**：见 [simulation-and-cross-settlement.md](./simulation-and-cross-settlement.md)（可完全脱链）。  
- **测试网**：本文档 + 上述 Runbook（涉及真实链上状态与配置）。
