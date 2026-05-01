# Karma Security Summary (CN/EN)

This one-page summary is intended for investors, partners, exchanges, and technical reviewers.

---

## 中文摘要（可直接外发）

**Karma 当前已完成 5 层安全验证，覆盖从功能测试到形式化证明的完整链条。**

| 层级 | 工具 | 类型 | 结果 |
|---|---|---|---|
| 1 | Forge Unit Test | 单元测试 | 55/55 通过 |
| 2 | Forge Invariant | 不变量 Fuzz | 256 轮，0 revert |
| 3 | Slither | 静态分析 | 22 条提示，无资金损失级漏洞 |
| 4 | Echidna | 攻击型 Fuzz | 100,000 轮，0 violation |
| 5 | Certora | 形式化验证 | 6/6 规则全部通过 |

### Certora 已证明性质（核心）

1. `confirmWorksOnPending`：Confirm 仅在 Pending 状态可生效  
2. `cancelWorksOnPending`：Cancel 仅在 Pending 状态可生效  
3. `finalStateNoTransition`：终态不可回退  
4. `splitResolvedMath`：分账/结算数学一致性成立  
5. `unlockPreservesReserved`：Unlock 不破坏 Reserved 约束  
6. `lockFundsIncreasesLocked`：Lock 行为正确增加 Locked

### 对外沟通建议（一句话）

Karma 已对资金路径和状态机关键性质建立“测试 + Fuzz + 静态分析 + 形式化证明”的分层证据链，并在当前基线上实现 Certora 6/6 数学证明通过。

### 风险边界声明（建议保留）

形式化验证证明的是“已定义性质成立”，不等于“系统零漏洞”。Karma 通过多工具交叉验证降低未覆盖风险。

---

## English Summary (External-Ready)

**Karma has completed a five-layer security validation stack, covering the path from functional testing to formal verification.**

| Layer | Tool | Type | Result |
|---|---|---|---|
| 1 | Forge Unit Tests | Functional tests | 55/55 passed |
| 2 | Forge Invariant | Invariant fuzzing | 256 runs, 0 revert |
| 3 | Slither | Static analysis | 22 findings, no fund-loss class issue |
| 4 | Echidna | Adversarial fuzzing | 100,000 runs, 0 violation |
| 5 | Certora | Formal verification | 6/6 rules verified |

### Certora Properties Verified

1. `confirmWorksOnPending`: confirm applies only on `Pending` state  
2. `cancelWorksOnPending`: cancel applies only on `Pending` state  
3. `finalStateNoTransition`: terminal states cannot transition back  
4. `splitResolvedMath`: settlement split math remains correct  
5. `unlockPreservesReserved`: unlock does not violate reserved accounting  
6. `lockFundsIncreasesLocked`: lock operation correctly increases locked value

### One-Line External Narrative

Karma enforces settlement and state-machine safety with a layered assurance model (tests + fuzzing + static analysis + formal proofs), including Certora 6/6 verified critical properties.

### Scope Boundary Statement

Formal verification proves specified properties, not the total absence of all bugs. Residual risk is reduced through cross-layer validation and continuous pipeline checks.

