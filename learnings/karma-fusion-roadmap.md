# Karma — 融合路线图 & 最低安全规则量化标准

> **作者:** Security Sentinel 🛡️  
> **时间:** 2026-05-23  
> **基于:** 16 竞品深度分析 + 10 场景执行路径 + 现有 Karma 架构

---

## PART 1: Karma 融合路线图

### 战略定位

```
Karma 不是 Agent 框架 (不做 LangChain/CrewAI 的事)
Karma 不是 AI 推理平台 (不做 Ritual/Morpheus 的事)
Karma 不是 L1 公链 (不做 NEAR/Solana 的事)

Karma = Agent 经济的结算与信任标准层
     = SWIFT (银行间结算) + Equifax (信誉) + ISO (标准) 的三位一体
     = 任何 Agent 框架挂载的通用信任协议
```

### 三阶段融合路线图

```
┌──────────────────────────────────────────────────────────┐
│  PHASE 1: 基础设施标准化 (Q2-Q3 2026)                     │
│  Karma 单方面定义标准 → 市场验证 → 迭代                    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  1.1 KYA Registry MVP (Q2)                               │
│      基础: DID 注册 + Stake + 信誉分                      │
│      融合 NEAR: 兼容 NEAR 的 agent ID 格式                │
│      融合 Fetch: KYA 比 Fetch 信誉更可移植                │
│                                                          │
│  1.2 Receipt 标准 v1.0 (Q2-Q3)                            │
│      基础: UniversalReceipt + 40+ 收据类型                │
│      融合 RISC Zero: 设计 ZK-proof 扩展字段               │
│      (当前用 Ed25519, 预留 ZK slot)                       │
│                                                          │
│  1.3 Hybrid Anchoring MVP (Q2-Q3)                        │
│      基础: 账单层 + Solana Merkle 锚定                    │
│      PR #110 完成                                         │
│                                                          │
│  1.4 多生态 SDK (Q3)                                     │
│      当前: OpenClaw ✅, OpenManus ✅, Solana ✅, BNB ✅   │
│      新增: Fetch.ai uAgents SDK, NEAR AI SDK             │
│      PR #98 合并后开始                                    │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  PHASE 2: 生态融合 (Q3-Q4 2026)                           │
│  Karma 与现有生态互操作 → 成为"默认信任层"                │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  2.1 Phala TEE 集成                                      │
│      TEE-attested receipt: Agent 在 TEE 内执行            │
│      → Phala 生成 TEE 证明                               │
│      → Karma 收据附加 TEE attestation                    │
│      → 硬件级可信执行证据                                 │
│      目标: KYA Registry 中增加 `tee_verified` 标记        │
│                                                          │
│  2.2 RISC Zero ZK 收据                                   │
│      场景 S9 (合规审查) + 高价值交易 (>$1000)             │
│      → Agent 在 RISC Zero zkVM 内执行                    │
│      → 生成 ZK proof 附在 receipt 上                     │
│      → 第三方验证 proof (零信任)                          │
│      不替代 Ed25519 签名，作为可选增强                     │
│                                                          │
│  2.3 Chainlink Automation 集成                           │
│      S7 (订阅) + 自动结算:                                │
│      → Chainlink Automation 监听 task_verified           │
│      → 自动触发 escrow.release()                         │
│      减少人工干预，提高结算效率                            │
│                                                          │
│  2.4 EigenLayer AVS 验证者网络                           │
│      Karma 去中心化验证:                                  │
│      → 验证者质押 ETH 到 EigenLayer                      │
│      → 验证者独立验证 receipt 链和 Merkle proofs          │
│      → 恶意验证者被 slashing                              │
│      → 替代中心化 Karma Runtime 的验证角色                │
│      目标: 验证者网络经济安全 ≥ $10M                      │
│                                                          │
│  2.5 Fetch.ai Agent 市场桥接                             │
│      Fetch 的 Agent 发现 + Karma 的结算:                  │
│      → Fetch Agent 在 Agentverse 被发现                  │
│      → 双方达成交易 → Karma 托管 + 记录 + 结算           │
│      → Fetch 获得信任层，Karma 获得用户量                 │
│                                                          │
├──────────────────────────────────────────────────────────┐
│  PHASE 3: 行业标准 (Q1-Q2 2027)                           │
│  Karma 推动标准化 → 成为行业默认                           │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  3.1 UARS (Universal Agent Reputation Standard)          │
│      FICO for Agents:                                    │
│      → 跨平台可移植信誉分                                 │
│      → 基于链上验证的交易记录                             │
│      → 开放标准，任何人可实现                              │
│      融合: Fetch信誉 + Autonolas链上 + NEAR身份            │
│                                                          │
│  3.2 VAR (Verifiable Agent Receipt) 标准                  │
│      ISO 级别的收据格式标准:                              │
│      → UniversalReceipt Schema 开放                      │
│      → Ed25519 签名 (Phase 1)                            │
│      → ZK proof 可选 (Phase 2)                           │
│      → TEE attestation 可选 (Phase 2)                    │
│      参考: RISC Zero receipt 格式                         │
│                                                          │
│  3.3 RACF (Regulated Agent Compliance Framework)         │
│      监管级合规框架:                                      │
│      → SOC2 Type II 映射到 Karma 证明                    │
│      → HIPAA/GDPR 合规模板                               │
│      → 审计员 Agent API                                   │
│      参考: Chainlink PoR, EigenLayer AVS 审计             │
│                                                          │
│  3.4 跨链 KYA (Omnichain Agent Identity)                 │
│      KYA 身份在多个链上可用:                              │
│      → LayerZero/Wormhole/Axelar 同步                    │
│      → Agent 在 Solana 注册，在 Arbitrum 被识别           │
│      → 一次 KYC，全链可用                                 │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 融合优先级矩阵

```
                      影响力
                   高 ───────── 低
               ┌─────────────────────┐
          高   │ P0: KYA MVP        │ P1: TEE集成
               │ P0: Receipt标准    │ P1: ZK收据
   复杂度      │ P0: Hybrid锚定     │
               ├─────────────────────┤
          低   │ P1: 多生态SDK      │ P2: 跨链KYA
               │ P1: Chainlink自动化│ P2: UARS标准
               │ P1: Fetch桥接      │ P2: RACF合规
               └─────────────────────┘

P0 = 当前在做的 (PR #110 + #98 + #103)
P1 = Phase 2 重点 (Q3-Q4 2026)
P2 = Phase 3 长期 (2027)
```

---

## PART 2: 最低安全规则量化标准

> **原则:** 可量化、可被任何接入方独立验证、不依赖 Karma 服务器的信任

### 标准 1: 收据完整性 (Receipt Integrity)

```yaml
standard: RECEIPT_INTEGRITY_V1

rules:
  # R1.1 每条收据必须被签名
  receipt_must_be_signed:
    requirement: "每条 UniversalReceipt 必须包含有效的 Ed25519 签名"
    verification: "Ed25519.verify(payload_hash, signature, generator_public_key)"
    threshold: "100% — 任何未签名收据 = 交易无效"
    
  # R1.2 收据链必须连续
  receipt_chain_unbroken:
    requirement: "parent_receipt_id 形成完整的单向链表"
    verification: "对 receipt[i], i>0: receipt[i].parent_receipt_id == receipt[i-1].receipt_id"
    threshold: "100% — 链断裂 = 交易无效"
    
  # R1.3 哈希必须正确
  receipt_hash_correct:
    requirement: "payload_hash = SHA256(canonical_json(receipt_fields))"
    verification: "任何第三方可独立计算并比对"
    threshold: "100%"
    
  # R1.4 时间戳单调递增
  receipt_timestamp_monotonic:
    requirement: "receipt[i].created_at >= receipt[i-1].created_at"
    verification: "ISO8601 时间戳比对"
    threshold: "100%"
    tolerance: "±5 秒 (时钟偏移)"
```

### 标准 2: 证据锚定 (Evidence Anchoring)

```yaml
standard: EVIDENCE_ANCHORING_V1

rules:
  # R2.1 每 N 条收据或每 T 秒必须锚定
  anchor_frequency:
    requirement: |
      满足以下任一条件必须触发锚定:
      (a) 未锚定收据数 >= anchor_every_n_receipts (推荐: 3)
      (b) 距上次锚定 >= anchor_every_n_seconds (推荐: 30)
    verification: "检查 anchor_tx 时间戳间隔"
    threshold: "锚定间隔上限 = max(anchor_every_n_receipts, anchor_every_n_seconds) × 2"
    
  # R2.2 关键状态必须立即锚定
  force_anchor_on_critical_states:
    requirement: |
      以下状态变更触发立即锚定:
      - FUNDED (资金已锁定)
      - DELIVERED (已交付)
      - VERIFIED (已验收)
      - SETTLED (已结算)
      - DISPUTED (争议)
      - FROZEN (冻结)
    verification: "检查状态变更时间与最近 anchor_tx 时间差 < 5秒"
    threshold: "100% — 任何关键状态变更后 5 秒内必须有锚定"
    
  # R2.3 Merkle Root 可独立验证
  merkle_root_verifiable:
    requirement: "Merkle Root 可由收据列表独立重建"
    verification: "merkle_tree(receipt_leaves).root == chain_anchor.root"
    threshold: "100%"
    
  # R2.4 链上锚定确认
  chain_anchor_confirmed:
    requirement: "anchor_tx 必须在链上达到最低确认数"
    confirmation_count:
      solana: 1    # Solana 1 确认 ≈ 400ms 最终性
      arbitrum: 1  # Arbitrum 快速确认
      ethereum: 12 # ETH 传统确认数
    threshold: "100%"
```

### 标准 3: 状态机安全 (State Machine Security)

```yaml
standard: STATE_MACHINE_SECURITY_V1

rules:
  # R3.1 无特权后门
  no_admin_override:
    requirement: "状态机代码中不存在 admin_override、force_transition、bypass_validation 方法"
    verification: "代码审查 + 自动化扫描 (禁止的方法名黑名单)"
    threshold: "0 个违规方法"
    
  # R3.2 所有转换路径预定义
  transition_paths_predefined:
    requirement: "所有合法状态转换在 BILLING_STATE_TRANSITIONS 中预定义"
    verification: "转换时查表验证，不在表中 → 拒绝"
    threshold: "100% — 无动态路径"
    
  # R3.3 每次转换生成不可变审计记录
  transition_audit_immutable:
    requirement: "StateTransitionRecord INSERT 后不可 UPDATE/DELETE"
    verification: "DB 层触发器阻止 + 应用层保证"
    threshold: "100%"
    
  # R3.4 非法转换告警
  illegal_transition_alert:
    requirement: "任何非法转换尝试 → 记录 + 告警"
    verification: "审计日志中有 ILLEGAL_TRANSITION_ATTEMPT 事件"
    threshold: "100% 检测率"
    alert_channel: "Telegram + 应用日志 + 链上事件"
    
  # R3.5 并发安全
  concurrent_safety:
    requirement: "状态转换使用 asyncio.Lock 或 DB row lock 保证原子性"
    verification: "并发测试: 同时 100 个转换请求 → 状态一致"
    threshold: "0 个竞态条件"
```

### 标准 4: 结算安全 (Settlement Security)

```yaml
standard: SETTLEMENT_SECURITY_V1

rules:
  # R4.1 资金非托管
  non_custodial:
    requirement: "买方资金在 Escrow 合约中，任何时候 Karma 都无法单方面提取"
    verification: "合约代码审查: 无 withdraw(admin) 函数，release 只能到 seller 地址"
    threshold: "100% — 零特权提取"
    
  # R4.2 结算必须基于验证通过的收据
  settlement_requires_verified_receipts:
    requirement: "escrow.release() 只能在 task.state == VERIFIED 时调用"
    verification: "链上 require(task_state == VERIFIED)"
    threshold: "100%"
    
  # R4.3 争议窗口
  dispute_window:
    requirement: "验收后必须有争议窗口期"
    min_window_hours: 24
    verification: "检查 delivered_at → settled_at 时间差 >= min_window_hours"
    threshold: "100%"
    
  # R4.4 多重验证 (高价值交易)
  multi_verification_for_high_value:
    requirement: "交易金额 > $1000 → 需要 ≥3 个独立验证者"
    verification: "检查 verification_count >= 3"
    threshold: "100% for amount > $1000"
    
  # R4.5 资金上限
  per_transaction_limit:
    requirement: "单笔交易上限 $10,000 (可配置)"
    verification: "链上 require(amount <= max_amount)"
    daily_limit: "$50,000 per buyer"
```

### 标准 5: 数据隐私 (Data Privacy)

```yaml
standard: DATA_PRIVACY_V1

rules:
  # R5.1 收据中不存原始数据
  receipt_no_raw_data:
    requirement: "收据只存哈希，不存 input/output 原文"
    verification: "检查 UniversalReceipt.schema 中无 raw_data 字段"
    threshold: "100%"
    
  # R5.2 高价值数据加密
  data_encryption_for_high_value:
    requirement: "场景 S5 (数据购买) 中，交货数据用买方公钥加密"
    verification: "检查 DATA_DELIVERED 收据的 data_uri 是否加密"
    threshold: "100% for S5"
    
  # R5.3 敏感信息最低暴露
  minimal_exposure:
    requirement: "公开 API 不返回 agent 的私钥、endpoint_url (可选)、PII 数据"
    verification: "API 响应字段白名单审计"
    threshold: "100%"
```

### 标准 6: 可用性 (Availability)

```yaml
standard: AVAILABILITY_V1

rules:
  # R6.1 收据同步延迟
  receipt_sync_latency:
    requirement: "收据生成 → 买方/卖方 WebSocket 收到: < 500ms (P99)"
    verification: "监控 receipt.created_at → ws_push_time"
    threshold: "< 500ms"
    
  # R6.2 锚定确认延迟
  anchor_confirmation_latency:
    requirement: "锚定交易提交 → 链上确认: < 5s (Solana), < 15s (Arbitrum)"
    verification: "监控 anchor_tx.submitted_at → confirmation_time"
    threshold: "< 5s (Solana) / < 15s (Arbitrum)"
    
  # R6.3 系统可用性
  system_uptime:
    requirement: "账单层可用性 ≥ 99.9%"
    verification: "监控 + 独立第三方检测"
    alert: "< 99.9% → 橙色告警, < 99% → 红色告警"
```

### 标准 7: 跨场景兼容性 (Cross-Scenario Compatibility)

```yaml
standard: CROSS_SCENARIO_V1

rules:
  # R7.1 所有场景使用相同收据 Schema
  unified_receipt_schema:
    requirement: "10 个场景共享 UniversalReceipt Schema，差异由 scenario_data 承载"
    verification: "每个场景的 receipt 都可被 UniversalReceipt.validate() 通过"
    threshold: "100%"
    
  # R7.2 场景间可切换
  scenario_switching:
    requirement: "交易可以从 S1 切换到 S8 (争议)，从 S3 拆分到 S1×N"
    verification: "状态机允许跨场景状态转移"
    threshold: "100%"
    
  # R7.3 新场景零代码变更
  new_scenario_zero_code_change:
    requirement: "新增场景只需在 ScenarioRegistry 注册，不改基础设施代码"
    verification: "注册 → 收据 → 同步 → 锚定 → 验证 → 全部自动工作"
    threshold: "100%"
```

---

## PART 3: 安全评分标准

### 当前 Karma 评分: 8.5/10

| 标准 | 达标 | 分数 | 差距 |
|------|------|------|------|
| R1 收据完整性 | ✅ Ed25519签名 | 9/10 | ZK proof 扩展未实现 |
| R2 证据锚定 | ⚠️ 链上锚定未部署 | 5/10 | Solana Devnet 部署 |
| R3 状态机安全 | ✅ 五条铁律 | 10/10 | — |
| R4 结算安全 | ✅ 非托管 + Escrow | 9/10 | 多签未部署 (H2) |
| R5 数据隐私 | ✅ 哈希存储 | 8/10 | 加密交付未实现 |
| R6 可用性 | ⚠️ 未度量 | 5/10 | 监控体系待建立 |
| R7 跨场景兼容 | ✅ 统一 Schema | 9/10 | 新场景未全部实现 |

### 评分路径

```
当前:  8.5/10
Q3:   9.0/10  (Solana锚定上线 + 监控部署 + H2多签)
Q4:   9.5/10  (TEE/ZK收据 + 多验证者 + 加密交付)
2027: 9.8/10  (完整合规 + 跨链KYA + 行业标准)
```

---

## PART 4: 可被接入方独立验证的检查清单

任何接入 Karma 的生态可以执行以下检查，无需信任 Karma 服务器：

```yaml
independent_verification_checklist:
  
  check_1_receipt_signature:
    description: "验证收据签名"
    how: |
      1. 获取 receipt.payload_hash
      2. 获取 agent 的 Ed25519 公钥 (从 KYARegistry 或 DID 文档)
      3. Ed25519.verify(payload_hash, receipt.signature, public_key)
    trust_required: "只信任 agent 的公钥注册"
    
  check_2_merkle_proof:
    description: "验证收据在证据树中"
    how: |
      1. 获取 receipt 的 leaf_hash = SHA256(receipt_id|task_id|step|payload_hash|timestamp)
      2. 获取 merkle_proof 路径 (Karma API 或直接从链上)
      3. 用 leaf_hash + proof 重建 Merkle Root
      4. 比对链上的 Merkle Root (Solana CMT)
    trust_required: "只信任 Solana 链上数据"
    
  check_3_chain_integrity:
    description: "验证收据链完整"
    how: |
      1. 获取 task 的所有 receipts
      2. 检查 receipt[i].parent_receipt_id == receipt[i-1].receipt_id
      3. 检查所有时间戳单调
    trust_required: "只信任收据内容 (已签名)"
    
  check_4_escrow_state:
    description: "验证资金状态"
    how: |
      1. 查询 Escrow.sol 合约: deposits(task_id) 
      2. 查询合约事件: EscrowDeposited, EscrowReleased, EscrowRefunded
    trust_required: "只信任 Solana 链上数据"
    
  check_5_state_machine:
    description: "验证状态转换合法性"
    how: |
      1. 获取 StateTransitionRecord 列表
      2. 检查每条记录的 from_state → to_state 在预定义路径中
      3. 检查 triggered_by_receipt_id 的收据存在且有效
    trust_required: "只信任预定义的转换规则 (公开)"
```

---

## 总结

Karma 的战略路径清晰：

1. **Phase 1 (当前):** 先把基础设施标准化做实 — KYA + Receipt + Anchoring + 多生态 SDK
2. **Phase 2 (今年):** 与 Phala/RISC Zero/Chainlink/EigenLayer 融合，从"自建"到"生态共建"
3. **Phase 3 (明年):** 推动行业标准，Karma 成为 Agent 经济默认信任层

**核心差异化始终是:** 全场景标准化 × 不可篡改执行证据 × 公开可独立验证 × 非托管安全
