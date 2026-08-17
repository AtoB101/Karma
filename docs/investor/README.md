# Karma 天使投资人资料包（公开产品图集）

> **打开顺序**：先读 [`00-一页纸介绍.md`](./00-一页纸介绍.md)，再按页翻完本目录即可完整路演。  
> **性质**：基于本仓库公开文档与代码整理的**产品 / 工程 / 验证**材料，不含估值、条款、客户名单等私密财务信息。融资条款请用 [`99-融资条款模板-私下填写.md`](./99-融资条款模板-私下填写.md) 在本地填写后单独发送。

---

## 路演打开顺序（约 15–20 分钟）

| 顺序 | 文件 | 投资人听什么 |
|------|------|--------------|
| 0 | [00-一页纸介绍.md](./00-一页纸介绍.md) | 30 秒：做什么、为何现在、做到哪 |
| 1 | [01-问题与方案.md](./01-问题与方案.md) | 痛点 → 方案 → 差异化 |
| 2 | [02-产品核心循环.md](./02-产品核心循环.md) | 锁仓→绑定→结算→放款（一图讲清） |
| 3 | [03-系统工程图.md](./03-系统工程图.md) | 前后端 / 合约 / 证据层架构 |
| 4 | [04-状态机与流程图.md](./04-状态机与流程图.md) | Bill / Binding / 争议状态图 |
| 5 | [05-已实现与未实现能力.md](./05-已实现与未实现能力.md) | 诚实的能力矩阵（合约·API·前端） |
| 6 | [06-验证与信任层.md](./06-验证与信任层.md) | Forge / Echidna / Certora / 对抗测试 |
| 7 | [07-生态集成与测试网.md](./07-生态集成与测试网.md) | OpenClaw / x402 / AP2 / Sepolia |
| 8 | [08-路线图与资金用途叙事.md](./08-路线图与资金用途叙事.md) | V1→V2 与天使轮该买什么进度 |
| 附录 | [99-融资条款模板-私下填写.md](./99-融资条款模板-私下填写.md) | **勿公开提交真实数字** |

---

## 图集索引（可直接插入 PPT）

| 图 | 文件 | 类型 |
|----|------|------|
| 结算主轨（视觉） | [`diagrams/karma-settlement-rail.png`](./diagrams/karma-settlement-rail.png) | PNG |
| 核心循环 | [`diagrams/01-core-loop.svg`](./diagrams/01-core-loop.svg) · PNG | 流程图 |
| 系统架构 | [`diagrams/02-architecture.svg`](./diagrams/02-architecture.svg) · PNG | 架构图 |
| Binding 状态机 | [`diagrams/03-binding-states.svg`](./diagrams/03-binding-states.svg) · PNG | 状态图 |
| Bill 状态机 | [`diagrams/04-bill-states.svg`](./diagrams/04-bill-states.svg) · PNG | 状态图 |
| 验证金字塔 | [`diagrams/05-verification.svg`](./diagrams/05-verification.svg) · PNG | 结构图 |
| 浏览器路演 | [`pitch.html`](./pitch.html) | 一页一页滚讲 |

源文件（可再导出）：`diagrams/*.mmd`

---

## 一句话定位（背诵版）

**Karma = AI Agent 之间做生意时的非托管双边托管 + 证据结算轨。**  
双方各锁 USDC → 铸 Bill Token → 绑定 → 交付可验证 → 结算放款。  
**Math settles, not humans.**

---

## 公开证据锚点（可让投资人点开）

| 证据 | 路径 |
|------|------|
| 产品 README | [`README.md`](../../README.md) |
| 聚焦路线图 | [`docs/FOCUS_ROADMAP.md`](../FOCUS_ROADMAP.md) |
| 结算流 | [`docs/SETTLEMENT_FLOW_PUBLIC.md`](../SETTLEMENT_FLOW_PUBLIC.md) |
| 争议流 | [`docs/DISPUTE_FLOW_PUBLIC.md`](../DISPUTE_FLOW_PUBLIC.md) |
| 安全基线 | [`SECURITY.md`](../../SECURITY.md) |
| Sepolia 部署 | [`deploy/sepolia_bilateral_deployment.json`](../../deploy/sepolia_bilateral_deployment.json) |
| Pilot E2E | [`docs/PILOT_E2E_PATH.md`](../PILOT_E2E_PATH.md) |
| 白皮书草稿 | [`docs/whitepaper.md`](../whitepaper.md) |

---

*整理日期：以仓库当前 `main` 能力为准。表述刻意保守：已上线 = 代码+测试+文档可证；规划中 = 明确标注。*
