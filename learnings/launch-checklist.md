# Karma 上线执行方案

> 基于《去中心化项目成功对比与成功方案 V1.0》整理
> 日期：2026-05-06

---

## 一、上线前（预计 30-60 天）

### 🔴 P0 — 阻塞项（不做完不能上线）

#### 1. 合约安全
- [ ] 第三方智能合约审计（非自己人）
  - [ ] Access Control 矩阵审查（OWASP #1 漏洞，2024 年 $953M 损失）
  - [ ] EIP-712 签名安全专项：domain separator / nonce / deadline / signature malleability
  - [ ] 重入攻击检查（Checks-Effects-Interactions 模式）
  - [ ] 外部调用返回值检查
  - [ ] 整数溢出检查（Sol 0.8+ 内置安全）
- [ ] CircuitBreaker 测试：pause/unpause 权限正确、紧急冻结可用
- [ ] 部署脚本审核（Deploy.s.sol 未暂存修改需 commit）
- [ ] 用 OpenZeppelin 合约库，不手写安全原语

#### 2. 合约最小版（7 个核心函数）
```
lock()          — 买家锁仓 USDC/USDT
createBill()    — 创建账单
submitEvidence()— 提交执行证据（EIP-712 签名）
settle()        — 正常结算释放
dispute()       — 发起争议
release()       — 仲裁后释放
refund()        — 仲裁后退款
```

#### 3. EvidenceBundle V1 标准
- [ ] 字段固定：
  - caller / provider / serviceType / price / timestamp
  - inputHash / outputHash / executionResult / failureReason
  - buyerSignature / sellerSignature / evidenceHash
  - settlementStatus / disputeStatus
- [ ] EIP-712 typed data 定义
- [ ] 证据哈希上链（不存原文，存 hash）

#### 4. 风险参数标准
- [ ] 买家锁仓比例
- [ ] 卖家违约保证金
- [ ] 单笔订单金额上限
- [ ] 单日结算上限
- [ ] 新 Agent 冷启动额度
- [ ] 争议率阈值
- [ ] 失败率阈值
- [ ] 自动放款延迟
- [ ] 证据不完整 → 不得自动结算

---

### 🟡 P1 — 上线必需（核心产品闭环）

#### 5. 官网第一屏
- [ ] 标题：The Trust Layer for Agent Payments
- [ ] 副标题：Non-custodial escrow, signed execution evidence, and dispute-safe settlement
- [ ] 三个按钮：I sell agent services / I buy agent services / I am a developer
- [ ] 一句话定位：Karma 用非托管锁仓、签名执行证据和争议感知结算，保护 Agent 服务交易

#### 6. 控制台 MVP
- [ ] **卖家收款区**：创建服务 → 设置价格 → 接入 API → 查看订单/待结算/争议 → Trust Badge
- [ ] **买家付款区**：连接钱包 → 锁定预算 → 查看账单/调用记录 → 发起争议
- [ ] 钱包连接（RainbowKit / WalletConnect）

#### 7. 开发者 SDK
- [ ] JS SDK：`buyer.lock()` / `seller.registerService()` / `karma.createBill()` / `karma.signEvidence()` / `karma.settle()` / `karma.dispute()`
- [ ] REST API
- [ ] x402 middleware 雏形
- [ ] 示例 Agent 服务（至少 2 个：一个正常结算、一个失败退款）

#### 8. 文档
- [ ] 快速开始（3 分钟看懂怎么接入）
- [ ] 合约说明
- [ ] 安全说明（非托管说明）
- [ ] EIP-712 集成指南
- [ ] FAQ

---

### 🟢 P2 — 上线前最好做完

#### 9. 公开数据面板
- [ ] 累计订单数 / 累计结算金额 / 争议数
- [ ] 成功结算率 / 退款金额 / 平均结算时间 / 接入 Agent 数量
- [ ] 聚合展示，不暴露用户隐私

#### 10. 仓库分工
- [ ] **公开仓库**：合约接口 / SDK / 数据标准 / 示例 Demo / 文档 / 测试
- [ ] **私有仓库**：评分算法 / 反作弊规则 / 争议权重 / 黑名单策略 / 行为检测模型

#### 11. 测试
- [ ] 单元测试 + 集成测试覆盖率 > 90%
- [ ] EIP-712 签名测试
- [ ] 失败结算测试
- [ ] 争议冻结测试
- [ ] 模拟 100 笔交易 + 5 笔争议

#### 12. 14 天冲刺任务
| 天 | 任务 |
|----|------|
| 1 | 确定一句话定位 |
| 2 | 改官网第一屏 |
| 3 | 整理公开仓库 README |
| 4 | 整理私有仓库规则 |
| 5 | 完成 EvidenceBundle V1 |
| 6 | 完成卖家收款区 UI |
| 7 | 完成买家付款区 UI |
| 8 | 第一个示例 Agent（简单 API 按次收费） |
| 9 | 第二个示例 Agent（数据查询，失败可退款） |
| 10 | x402 middleware 雏形 |
| 11 | 公开数据面板 |
| 12 | 找 10 人跑小额测试（每人 3-5 单） |
| 13 | 故意制造 5 个争议案例 |
| 14 | 第一篇开局文章 |

---

## 二、上线后（按阶段）

### 第 1 阶段：0-30 天 — 证明「能用」

**目标：可演示、可测试、可小额真实结算闭环**

- [ ] 上线官网 + 控制台 + 合约最小版 + SDK
- [ ] 10 个卖家服务 / 20 个买家钱包 / 100 笔交易
- [ ] 至少 5 笔模拟争议，所有证据可导出
- [ ] 结算成功率 > 95%
- [ ] 无资金丢失、无错误释放

---

### 第 2 阶段：30-90 天 — 证明「有人愿意用」

**目标：真实小额使用**

#### 产品
- [ ] x402 middleware 完整体
- [ ] Trust Badge：Protected by Karma / Non-custodial settlement / Evidence-backed execution
- [ ] 真实资金小额主网（单笔 1-20 USDC，日上限 100 USDC，新卖家 50 USDC）

#### 运营
- [ ] 找第一批真实场景：API 调用、数据查询、自动研究、自动监控、MCP 工具服务
- [ ] 先找小卖家：没品牌的小 API 服务商、个人开发者、x402 Provider
- [ ] 推出 Karma Buyer Protection（买家保护 → 倒逼卖家接入）
- [ ] 公开 Live Settlement Dashboard

#### 内容
- [ ] 输出 6 篇英文 + 5 篇中文标准文档型文章
- [ ] 做 10 个样板 Agent/API Demo（全部用 Karma 结算）

#### 指标
- [ ] 1000 笔真实小额订单
- [ ] 50 个接入 Agent/API 服务
- [ ] 累计结算 $5K-$20K USDC
- [ ] 争议率 < 5%
- [ ] ≥3 个外部开发者主动接入
- [ ] 10 个真实成功案例

---

### 第 3 阶段：90-180 天 — 证明「有商业价值」

#### 产品
- [ ] 卖家信任页（公开：订单数/结算率/响应时间/争议率/Trust Score）
- [ ] 买家保护机制（失败自动退款 / 证据缺失冻结 / 超时退款 / 恶意降权）

#### 商业化
- [ ] 收费模型上线：成功结算 0.3%-0.8% / 争议处理固定费 / 高级 Badge 订阅
- [ ] 合作目标：x402 生态 / AI API 市场 / Agent 工具市场 / 数据服务商

#### 指标
- [ ] 10000 笔订单
- [ ] 100+ 服务商
- [ ] 累计结算 $100K+ USDC
- [ ] 月收入开始出现
- [ ] 有卖家公开说「接入 Karma 后转化率提升」

---

### 第 4 阶段：180-365 天 — 成为细分标准

#### 产品
- [ ] 多链支持：Base → Ethereum → Arbitrum → Polygon
- [ ] 多稳定币：USDC → USDT → DAI
- [ ] 仲裁网络雏形（核心团队 + 外部专家 + 合作方）
- [ ] 风险服务 API：checkBuyerRisk() / checkSellerRisk() / recommendLockAmount()

#### 治理
- [ ] 逐步开放规则（有真实数据后再做，不要早期 DAO 化）

#### 指标
- [ ] 10 万笔订单
- [ ] $1M+ 累计结算
- [ ] 1000+ 服务接入
- [ ] Karma Trust Score 被外部展示
- [ ] 至少一个生态把 Karma 当成推荐结算方式

---

## 三、不发币承诺

> ⚠️ 以下条件**全部满足**后再设计代币：

- [ ] 10 万+ 笔订单
- [ ] $1M+ 累计保护交易额
- [ ] 1000+ Agent/API 服务接入
- [ ] 真实争议数据库
- [ ] 外部生态依赖 Karma Trust Score
- [ ] 可证明的协议收入
- [ ] 真实需求：激励仲裁员/节点/开发者/风控服务商

---

## 四、绝对不能踩的坑

| # | 坑 | 为什么 |
|---|-----|--------|
| 1 | 做得太大 | 先打穿 Agent/API 按次调用结算，不做大而全 |
| 2 | 只讲技术不讲利益 | 用户不关心 EIP-712，关心会不会被骗、能不能收到钱 |
| 3 | 完全去中心化幻想 | 早期你必须负责：定规则、处理争议、验证证据、修产品 |
| 4 | 公开核心运行规则 | 公开字段，不公开权重（防刷分、防伪造、防抄袭） |
| 5 | 没有真实案例 | Web3 用户不信 PPT，必须尽快有真实交易截图和链上记录 |
| 6 | 急着发币 | 缺的不是代币，是真实交易、真实争议、真实数据 |

---

## 五、一句话行动纲领

**上线前：把 7 个合约函数 + EvidenceBundle V1 + 一个可演示闭环做完**

**上线后：先找 10 个小卖家跑真实交易，用买家保护倒逼供给侧**

**永远：安全 > 增长，真实 > 宣传，克制 > 扩张**
