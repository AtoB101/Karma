# 共建网络计分规格 v1
# Identity × Contribution × Incentive

> 目标：把「垂直开发者 + 行业专业人士」的共创贡献，变成可写入计分系统的**身份绑定、贡献权重、长期收益**规则。  
> 不是招人文案；这是计分 / 奖励池更新规格。  
> 对齐现状：`ScoringEngine` · P8 `settlement_reputation` · karma-economy `ContributionNFT` · `DeveloperRewardPool`(40%) · `VerifierNodePool`(20%)

---

## 0. 一页公式（先背这个）

```text
IdentityBound  = 钱包 + 角色凭证(SBT/ContributionNFT) + 赛道绑定
Contribution = Σ (事件类型权重 × 质量系数 × 赛道乘数 × 衰减)
Score        = clamp(0..10000, f(SettlementRep, Contribution, StakeTier))
EpochShare   = PoolUSDC × (α·GMV份额 + β·Contribution份额)
长期绑定     = Soulbound NFT weight 不可转让 + 赛道分成按 epoch 计提
```

现有经济池已定（不可改费率叙事）：

| 国库分账 | 比例 | 计分侧对应角色 |
|----------|------|----------------|
| DeveloperRewardPool | **40%** | 垂直开发者 / 适配器共创者 |
| StakerRewardPool | 30% | 质押者（非本规格主焦点） |
| VerifierNodePool | **20%** | 验证者 / 行业核验贡献 |
| AutoBuyBurn | 10% | 通缩 |

`DeveloperRewardPool` 现成拆分：**GMV 70% + ContributionNFT weight 30%**（`GMV_WEIGHT_BPS=7000`, `NFT_WEIGHT_BPS=3000`）。  
本规格要补的是：**哪些贡献可 mint NFT weight、如何计分、如何和 ScoringEngine/P8 打通。**

---

## 1. 身份层 Identity（必须先绑定才能计分）

### 1.1 角色枚举（扩展 ScoringEngine.PartyType）

| Role ID | 角色 | 证明 | 计分账户 |
|---------|------|------|----------|
| `SUPPLIER` | 卖方 Agent / 商家 | 既有 | ScoringEngine |
| `BUYER` | 买方 | 既有 | ScoringEngine |
| `VERIFIER` | 验证 / 仲裁节点 | 既有 + stake | ScoringEngine + VerifierNodePool |
| `BUILDER` | 垂直开发者 | 注册 + 贡献 NFT | **新增** ContributorScore |
| `EXPERT` | 行业专业人士 | 注册 + 赛道认证 | **新增** ContributorScore |
| `SCENE_OWNER` | 赛道标准维护组 | 多签 / 委员会 | ContributorScore（治理权重） |

> 一个人可兼多角色；**收益按角色分账户计提**，避免「开发者分」和「验证分」混池。

### 1.2 身份绑定最小字段

```json
{
  "wallet": "0x...",
  "roles": ["BUILDER", "EXPERT"],
  "tracks": ["api_commerce", "local_delivery"],
  "identity_sbt": "tokenId?",
  "contribution_weight": 0,
  "registered_at": "ISO-8601",
  "status": "active|suspended"
}
```

规则：
- 无 `wallet` 绑定 → **不计贡献、不可领 epoch**
- `tracks` 为空 → 只能拿通用贡献，赛道乘数 = 1.0 封顶且无赛道分成
- Soulbound：`ContributionNFT` 已禁止转让 → 长期身份绑定已具备合约底座

---

## 2. 贡献层 Contribution（计分事件目录）

### 2.1 事件类型与基础权重 `W_base`（建议初值，可配置）

| code | 事件 | 谁产生 | W_base | 证据要求 |
|------|------|--------|--------|----------|
| `ADAPTER_SHIP` | 垂直适配器合并/上线 | BUILDER | 500 | repo PR + 通过验收用例 |
| `SCENE_SPEC` | 赛道验收/证据标准被采纳 | EXPERT | 800 | 标准文档 hash + SCENE_OWNER 批准 |
| `VERIFY_RULE` | 可执行验证规则上线 | EXPERT+BUILDER | 600 | schema + 测试向量 |
| `TEMPLATE_LIVE` | 场景模板产生真实 settle | BUILDER | 300 + 量 | ≥1 笔 Sepolia/主网 SETTLED |
| `SETTLE_OK` | 作为供需方成功结算 | SUPPLIER/BUYER | 既有 SETTLE_WEIGHT | Bilateral settle |
| `ATTEST_OK` | 正确 attestation | VERIFIER | 既有 | Gateway + Registry |
| `DISPUTE_HELP` | 专业意见被采纳解决争议 | EXPERT | 400 | 案例 id + 裁决引用 |
| `AUDIT_PASS` | 外部审计协助/漏洞负责任披露 | BUILDER/EXPERT | 1000 | 报告 hash（无利用） |
| `NEGATIVE_*` | 作假标准 / 刷量 / 恶意争议 | 任意 | 见惩罚 | slash 流程 |

### 2.2 质量系数 `Q`（0.25–1.50）

| 条件 | Q |
|------|---|
| 仅提交未采纳 | 0.25 |
| 采纳但无线上 settle | 0.70 |
| 采纳且测试网跑通 | 1.00 |
| 主网/受控生产有真实 GMV | 1.25 |
| 成为该赛道默认标准 ≥30 天 | 1.50 |

### 2.3 赛道乘数 `T`（专业度溢价）

| 赛道风险档（对齐 P8 scene） | T |
|------------------------------|---|
| `daily_commerce` / `digital` | 1.0 |
| `b2b` / `professional` | 1.2 |
| `high_risk`（金融/医疗等） | 1.5（且必须 OWNER_CONFIRM，禁止瞎自动） |

### 2.4 单事件贡献分

```text
C_event = W_base × Q × T
```

写入：
1. **链下贡献账本**（先落地，便于调参）  
2. 达阈值后由 minter 调用 `ContributionNFT.mint(to, weight, uri)`  
   - `weight` 建议用整数：`weight = round(C_event)`  
   - `uri` → 贡献证明 JSON（事件 code、track、artifact hash、评审人）

### 2.5 窗口与衰减

```text
C_active(addr) = Σ C_event × decay(age)
decay(age) = 1.0                    if age ≤ 90d
           = 0.5                    if 90d < age ≤ 365d
           = 0.2                    if age > 365d
```

负向事件**不衰减**（或慢衰减），与 ScoringEngine「负向难消」一致。

---

## 3. 综合分 Score（写入计分系统）

### 3.1 三分量

| 分量 | 来源 | 区间 |
|------|------|------|
| `R_settle` | ScoringEngine / P8 场景信誉 | 0–10000 |
| `R_contrib` | 贡献活跃分归一化 | 0–10000 |
| `R_stake` | MultiTierStake tier 映射（可选） | 0–10000 |

### 3.2 角色加权合成（建议）

**BUILDER**

```text
Score_builder = 0.25·R_settle + 0.60·R_contrib + 0.15·R_stake
```

**EXPERT**

```text
Score_expert  = 0.20·R_settle + 0.70·R_contrib + 0.10·R_stake
```

**VERIFIER**（与现网一致，略调）

```text
Score_verifier = 0.55·accuracy + 0.25·volume_norm + 0.20·stake_tier
```
→ 同步到 `VerifierNodePool.accuracyScore`

**SUPPLIER / BUYER**  
保持既有 ScoringEngine + P8，不把「写标准」权重塞进交易信誉（防刷）。

### 3.3 归一化 `R_contrib`

```text
R_contrib = min(10000, 10000 * log1p(C_active) / log1p(C_ref))
C_ref 初值建议 = 5000（可配置；约等于若干次高质量 SCENE_SPEC）
```

---

## 4. 激励层 Incentive（收益怎么发）

### 4.1 冷启动（revenueMode=false）

- **不计 USDC 手续费**，但仍记 GMV / 贡献分 / NFT weight  
- 激励形态：
  1. 贡献分排行与赛道徽章  
  2. 测试网额度 / 优先接入位  
  3. 预登记 epoch 份额（`pending_share`），等 `revenueMode=true` 后按权重补发或从生态预算发放

### 4.2 开启收费后（对齐已有池）

**开发者 / 共创者（40% DeveloperRewardPool）**

```text
claim_i = EpochUSDC × (
    0.70 × GMV_i / Σ GMV
  + 0.30 × NFTWeight_i / Σ NFTWeight
)
```

其中：
- `GMV_i`：该 BUILDER 的适配器/模板所服务的结算 GMV（需 `developer` 字段进 FeeBridge / 归因表）  
- `NFTWeight_i`：`ContributionNFT.totalWeightOf(i)`（已被身份绑定）

**行业专家**：不强制走 GMV；主要通过 **NFT weight（标准/规则类贡献）** 拿 30% 腿；可另设 `EXPERT_BOOST`：赛道标准被引用次数计入额外 weight。

**验证者（20% VerifierNodePool）**

```text
按 accuracyScore × 合规 stake 分配（合约已具备骨架）
```

### 4.3 反作弊（必须写进计分更新）

| 行为 | 处理 |
|------|------|
| 刷 settle / 自成交 | 归因 GMV 不计；C_event×0；可 slash |
| 抄袭标准改皮 | SCENE_OWNER 驳回；重复提交降 Q |
| 假验证 | Verifier slash + PENALTY_WEIGHT |
| 买水军评审 | 多签门槛；利益冲突披露 |
| Sybil 多钱包 | 身份合并策略；领奖需主身份 |

---

## 5. 对现有系统的「落库更新清单」

### 5.1 链下计分服务（优先，2 周可落地）

新增模块建议：`services/cocreation_score.py` + 表 `contributor_profiles` / `contribution_events` / `contribution_epochs`

| API（建议） | 作用 |
|-------------|------|
| `POST /v1/cocreation/register` | 绑定 wallet + roles + tracks |
| `POST /v1/cocreation/events` | 申报贡献（待审） |
| `POST /v1/cocreation/events/{id}/accept` | SCENE_OWNER/多签采纳 → 记账 |
| `GET /v1/cocreation/score/{wallet}` | 返回 Score 三分量 |
| `POST /v1/cocreation/epoch/preview` | 预览分成 |
| `POST /v1/cocreation/nft/mint-request` | 达阈值申请 mint weight |

与 P8：赛道标准采纳后，更新 `settlement-reputation` scene profile 的字段/确认策略。  
与 discovery：`compute_trust_bonus` 可增加 `+ k * R_contrib_norm`（仅 BUILDER 目录）。

### 5.2 ScoringEngine（链上，第二阶段）

1. 扩展 `PartyType`：`BUILDER`, `EXPERT`（或并行 `ContributorRegistry` 避免破坏旧 ABI）  
2. `recordContribution(party, weight, trackId)` onlySettler/or ContributionOracle  
3. settle 后继续 `recordSettlement`（补齐 Bilateral 接线缺口）  
4. `_computeComposite` 按 §3.2 真正计算，替换 stub

### 5.3 karma-economy（已有则接线）

1. 贡献采纳 → `ContributionNFT.mint`  
2. FeeBridge `developer` 地址 = 适配器归因 BUILDER  
3. `DeveloperRewardPool.registerDeveloper`  
4. `VerifierNodePool.setAccuracy` ← 来自 ScoringEngine/链下准确率  
5. 保持 `revenueMode` 默认 false，直到有真实 GMV

---

## 6. 赛道共创工作流（细节打磨怎么进分）

```text
行业专家 提出验收/证据/争议细则
        ↓
垂直开发者 落成 Adapter + 验证规则 + 模板
        ↓
SCENE_OWNER 评审采纳（记 SCENE_SPEC / VERIFY_RULE / ADAPTER_SHIP）
        ↓
测试网跑通真实 settle（记 TEMPLATE_LIVE）
        ↓
P8 scene 配置更新（行业差异结算）
        ↓
贡献分 → NFT weight →（有收入后）epoch 分成
```

这保证：**技术分 ≠ 行业分**；两边都要，才能把细枝末节变成可验证标准。

---

## 7. 配置初值表（给你直接贴进计分配置）

```yaml
cocreation:
  roles: [BUILDER, EXPERT, SCENE_OWNER, VERIFIER, SUPPLIER, BUYER]
  weights:
    ADAPTER_SHIP: 500
    SCENE_SPEC: 800
    VERIFY_RULE: 600
    TEMPLATE_LIVE: 300
    DISPUTE_HELP: 400
    AUDIT_PASS: 1000
  quality:
    submitted: 0.25
    accepted: 0.70
    testnet_live: 1.00
    prod_gmv: 1.25
    default_30d: 1.50
  track_multiplier:
    daily_commerce: 1.0
    digital: 1.0
    b2b: 1.2
    professional: 1.2
    high_risk: 1.5
  score_mix:
    BUILDER: { settle: 0.25, contrib: 0.60, stake: 0.15 }
    EXPERT:  { settle: 0.20, contrib: 0.70, stake: 0.10 }
  economy:
    developer_pool_pct: 40
    gmv_leg_bps: 7000
    nft_leg_bps: 3000
    revenue_mode_default: false
  mint_threshold_weight: 200   # 累计 C_event 达此值可申请 mint
  decay:
    hot_days: 90
    warm_days: 365
    hot: 1.0
    warm: 0.5
    cold: 0.2
```

---

## 8. 验收标准（计分系统更新是否合格）

1. 同一钱包双角色，贡献与结算分账户可查  
2. 未绑定身份的事件进不了 NFT / epoch  
3. 采纳标准但不跑 settle，Q 不超过 0.70  
4. high_risk 赛道不能靠自动确认刷 TEMPLATE_LIVE  
5. revenueMode=false 时仍能累计 weight 与 pending_share  
6. Developer 分成预览：`0.7 GMV + 0.3 NFT` 与合约常量一致  
7. 负向事件可下调 Score 且不影响「别人的」赛道标准

---

## 9. 与主页叙事的对齐（实现层）

主页说的「舞台 + 身份与长期收益绑定」在本规格中的落点：

| 叙事 | 机制 |
|------|------|
| 结算舞台 | Bilateral + P8 场景标准 |
| 垂直开发者 | BUILDER + Adapter/Template 贡献 |
| 专业人士 | EXPERT + SCENE_SPEC / VERIFY_RULE |
| 身份绑定 | wallet + Soulbound ContributionNFT |
| 长期收益 | NFT weight × epoch + GMV 归因分成 |
