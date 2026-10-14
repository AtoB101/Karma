# ④ 仲裁回滚（settlement reversal）落地方案

> 状态：**方案**；**④-A1（执行拆两段 + `execute_after`）已落地**（2026-10-14）。
> 合约与业务状态机的转移表**未改**（没有加任何新边）。
> 代码基线：`045259f5`（testnet 业务状态机那条腿已走到 `settled`）。
> 本文所有判断都带代码位置；拿不到证据的地方明说不确定。

---

## 一、一句话结论

**「把钱倒回来」这件事，链上没有原语，也不该有。** 正确的做法是把资金安全的边界提前：
裁决执行后先过一个**上诉窗口**，窗口内钱一步不动，推翻零成本；窗口外才谈「补偿 + 追偿」。
这样既不改托管合约，也不给状态机加「反向转账」这种危险边。

---

## 二、现状（代码证据）

### 2.1 裁决执行今天会立刻动钱

`api/routes/arbitration.py:861` 的 `POST /cases/{case_id}/execute`：

| 判决 | 业务目标态 | 链上动作 |
|---|---|---|
| `seller_wins` | `SETTLED` | `submit_for_task` → `submitSettlement`，开**放款窗** |
| `buyer_wins` | `REFUNDED` | `slash_for_task` → `submitBreach`，开**罚没窗** |
| `partial` | `SETTLED` | 同上（按比例金额） |

代码位置：`api/routes/arbitration.py:904-945`、`api/routes/settlement.py:1445-1456`。
开窗本身**一分钱不动**（`services/chain/allowance_escrow.py:1854-1857`：
真正划款的是 `finalizeSettlement` / `finalizeBreach` 那两笔），但方向在开窗那一刻就写死了；
窗口到点（`allowance_escrow_dispute_window`，默认 120s）由 `services/chain/escrow_autosettle.py`
执行 `finalizeSettlement` / `finalizeBreach`，钱才真的走。

### 2.2 推翻今天只罚庭，不回滚

`api/routes/arbitration.py:724` 的 `POST /cases/{case_id}/overturn`：
把在庭仲裁员按「立案费 × `ARBITRATION_SLASH_MULTIPLE`」落进 `bond_slashes` 台账
（`services/bond_slash.py`），并把 `IdentityRoleProfile.stake_amount` 当场下调
（押金走则岗停）。接口**如实**返回 `settlement_reversal="not_performed"`
（`arbitration.py:745 / 835 / 857`），不假装已经退了。

这条缺口在三份文档里都被记着：`docs/VERIFIER_BOND_VAULT_RUNBOOK.md:136`、
`security/audit/2026-10-08-boundary-and-permission-gap-audit.md:322`、
`security/audit/2026-10-14-prod-orphan-cancel-onchain-status-flip.md:154`。

### 2.3 为什么不能「链上倒钱」——三条硬约束

1. **托管合约没有反向入口。** `services/chain/allowance_escrow.py:149-321` 的 ABI 全集里，
   终局函数只有 `finalizeSettlement` / `finalizeBreach` / `cancelBinding` / `markDisputed`。
   链上事件 `Settled` / `StakeSlashed` 一旦落定，钱在卖方/买方钱包里，合约管不着了。
2. **争议冻结只能在开窗前打。** `services/chain/escrow_settlement.py:1694-1715`：
   `markDisputed` 只认链上 `ACTIVE`（state 1）；窗口已开（`FINALIZING`）之后不回退。
   所以「先放款、再冻结」不可能。
3. **业务状态机里 `SETTLED` / `REFUNDED` 是终局。** `core/settlement/engine.py:70-72`：
   这两个态的唯一边是 `FROZEN`。给它们加一条回退边，等于让终局可以反悔 ——
   全系统对账、凭证、信誉都要重算。

> 结论：**不是没时间做，是不该那样做。** 回滚要靠「提前拦截」和「赔付」，
> 不是靠给状态机开口子。

### 2.4 存量（testnet，2026-10-14 只读核对）

| 表 | 行数 / 状态 |
|---|---|
| `arbitration_cases` | **0** |
| `arbitration_pool_members` | **0** |
| `bond_slashes` | **0** |
| `settlement_reversals` | 表**不存在** |
| `escrow_bindings` | 2 行，全是 `settled`（来自 ③ 那两单闭环） |

也就是说：**今天 testnet 上没有任何一个仲裁案件，也没有任何一个被推翻的裁决。**
④ 是从零起步，不存在「历史脏数据要先收拾」的问题 —— 这对落地是有利的。

---

## 三、按链上态分流：三档，各走各的

设被推翻案件对应的结算单绑在链上的那条 binding，链上态取自 `getBinding().state`
（`services/chain/allowance_escrow.py:325` 的 `BINDING_STATE`）：

| 档 | 链上态 | 钱动了吗 | 能否原地回滚 | 做法 |
|---|---|---|---|---|
| **A** | `active`(1) / `disputed`(6) | 没动 | **能，零成本** | 不执行原判决，重开案件重判；买方授权原路放回（`cancel_for_task`） |
| **B** | `finalizing`(2) / `breaching`(2，方向=罚没) | 没动，但已有受款人 | **不能改方向** | 等窗口走完（钱按原方向走），再走 ④-B 补偿 |
| **C** | `settled`(3) / `slashed`(4) | **动了** | 不能 | ④-B：补偿 + 追偿 |

关键洞察：**A 档今天就能做到零成本回滚 —— 前提是别那么早执行。**
所以 ④ 的第一刀应该砍在「执行时机」，而不是「倒钱」。

---

## 四、④-A：上诉窗口（推荐先做，测试网可落地）

### 4.1 做什么

把 `execute` 拆成两段：

1. **判决落地（立刻返回，不动链）**：写 `case.decided_outcome`、`case.status = decided`，
   并记 `case.execute_after = now + ARBITRATION_APPEAL_WINDOW`。
2. **放款（窗口到点才做）**：由后台 tick（复用 `services/chain/escrow_autosettle.py`
   的循环，新增 `arbitration_execute_due` 分支）扫 `decided` 且
   `execute_after <= now` 的案件，调用现有 `_sync_escrow_settlement` 走钱。

窗口内：收到上诉 → `case.status` 改判或置回 `voting`，**链上一步没走，无需回滚**；
窗口内没上诉 → 走钱，`case.status = executed`。

### 4.2 为什么这样是安全的

- 链上行为**不变**：还是 `submitSettlement` / `submitBreach` 开窗，只是开窗时间从
  「点执行那一刻」推迟到「上诉窗口到点」。
- 窗口期内钱的位置很清楚：链上 binding 停在 `active` / `disputed`
  （`_RESPONSIBILITY_STATES`，`escrow_settlement.py:99`），reservation 挂着但
  **没有任何受款人**；双方都不能自己撤（`_CANCEL_BLOCKED_DETAIL`，`escrow_settlement.py:102`）。
- 状态机不加新边：`DISPUTED → ARBITRATED` 之后停在 `ARBITRATED`，
  到点才 `ARBITRATED → SETTLED / REFUNDED`（`engine.py:69`）。

### 4.3 代价与取舍（要拍板的）

- 卖方拿到钱的时间 = 上诉窗口 + 原有结算窗（120s）。窗口多长是产品决策：
  测试网建议先 `ARBITRATION_APPEAL_WINDOW=300`（5 分钟），主网再按风控口径定。
- 需要一条**常驻 tick**。testnet 目前**没有**常驻 autosettle 进程（③ 的已知缺口），
  所以 ④-A 落地时必须把 tick 一起带上，否则「窗口到点自动放款」会变成人工催。

---

## 五、④-B：窗口外推翻（钱已动）—— 补偿 + 追偿

链上无原语，所以只能**赔**，不能**倒**。资金按优先级：

1. **被推翻那一庭的质押**（链上 `KarmaVerifierBond`）→
   `slash(verifier, amount, victim=受损方钱包)`，合约按 `victimShareBps`（默认 80/20）
   分账，**受损方直接收到 80%**。证据：`karma-core/contracts/core/KarmaVerifierBond.sol:267`、
   `docs/VERIFIER_BOND_VAULT_RUNBOOK.md:118-125` 有真机 tx 样板。
2. **不足部分** → 落一条**回滚欠款台账**（新表 `settlement_reversals`），
   记「欠受损方 X」，由罚没池后续积累支付；**不写 `settled`，不假装已退**。
   与 `services/bond_slash.py:162` 同一条硬规矩：没有 tx 就没有 settled。

### 5.1 前置依赖：仲裁员质押今天没进金库

`/overturn` 落的 `bond_slashes` 行 **`wallet_address=None`**（`arbitration.py:804`），
而链上 `slash()` 必须知道被罚的是哪个地址。也就是说：仲裁员的质押目前只在账上
（`IdentityRoleProfile.stake_amount` + `CapacityModel.total_locked_usdc`，见
`services/governance_stake.py:69-106`），**没有进金库**，所以这条链上赔付通路今天发不出交易 ——
`bond_slash.slash_instructions()` 会返回 `verifier=null`（`services/bond_slash.py:227`）。

要打通 ④-B，必须先把仲裁员质押真上链：`stake()` → 记 `wallet_address` →
推翻时 `slash(..., victim=受损方)`。这是一条独立的、可单独验收的子任务
（文档见 `docs/VERIFIER_BOND_VAULT_RUNBOOK.md`），建议排在 ④-A 之后。

### 5.2 现网实测：金库地址压根没接上后端（2026-10-14 只读核对）

在 testnet 容器里只读核对的结果：

```
testnet-api 环境变量：ALLOWANCE_ESCROW_ADDRESS      = 0x2C9911F5...49743b  (有)
                      VERIFIER_BOND_VAULT_ADDRESS   = (unset)
```

按 `docs/VERIFIER_BOND_VAULT_RUNBOOK.md:93` 的口径，`vault_configured=false`
意味着**罚没一律停在 `pending`** —— 这不是成功。所以 ④-B1 的第一个动作不是写代码，
是把金库地址接进 testnet 后端配置（金库本身 2026-10-11 已在 Sepolia 真出过账，
见 runbook §6 的三笔 tx），然后现场核对 `vault_configured=true`。

---

## 六、资金闭环要求（每一笔钱都要有源头）

回滚的每一笔出账，都必须能**回溯到源头**，复用现有两件工具：

- `services/chain/funds_trace.py`：动钱前回溯整条链路是否对齐；
- `bond_slash` 的 `(subject, source)` 唯一键 + `slash_instructions()`。

新增 `settlement_reversals` 表至少要有：`case_id`、`task_id`、`binding_id`、
`victim_identity_id`、`victim_wallet`、`owed_amount`、`paid_amount`、
`funding_source`（`bench_bond` / `slash_pool` / `platform_debt`）、
`status`（`pending` / `submitted` / `settled` / `failed`）、`tx_hash`、`attempts`。

**幂等键**：`(case_id, victim_identity_id)` —— 同一案件对同一受害方只赔一次。

---

## 七、安全门（不许绕过）

1. 任何 `settled` 必须带 tx hash（沿用 `bond_slash.settle_slash` 的规矩）。
2. 回滚**不改** `SETTLED` / `REFUNDED` 这两个终局态的语义；只新增独立的补偿记录，
   操作台另开一块展示。
3. 每一笔出账前跑 `funds_trace`；出现 issue 就拒绝出账（默认拒绝）。
4. 上诉窗口内的案件，链上不许有受款人 —— 落地时加断言：
   `getBinding().state` 必须 ∈ `{active, disputed}`，否则拒绝进入窗口逻辑（宁可报错）。
5. 绝对禁止自成交：赔付前复用 `detect_self_dealing`（`escrow_settlement.py:907`）判一次，
   自成交单不入赔付通道。
6. 不引入 Mock：测试网测试必须用真 mUSDC 与真 tx，记录 hash。

---

## 八、落地顺序（测试网优先）

| 阶段 | 内容 | 依赖 | 可否独立验收 |
|---|---|---|---|
| ④-A1 | 执行拆两段 + `execute_after` 字段 + 迁移 | 无 | **已落地**（见 8.1） |
| ④-A2 | 后台 tick（`arbitration_execute_due`）+ 常驻进程 | ④-A1 | 是 |
| ④-A3 | 上诉入口（窗口内改判，零链上动作） | ④-A1 | 是 |
| ④-B1 | 金库地址接上后端 + 仲裁员质押真上链（`stake` + 记 wallet） | 金库已部署（testnet 已有） | 是 |
| ④-B2 | `settlement_reversals` 台账 + `/overturn` 接上赔付 | ④-B1 | 是 |
| ④-B3 | 罚没池补足欠款 + 操作台展示 | ④-B2 | 是 |

每阶段独立 PR、独立 CI、独立测试网实测，不合并做。

### 8.1 ④-A1 已落地（2026-10-14）

* 开关：`ARBITRATION_APPEAL_WINDOW_SECONDS`（默认 **0 = 关闭**，行为与历史逐字一致）。
* 列：`arbitration_cases.execute_after`（迁移 `0068_arbitration_execute_after`；老行全 NULL
  = 没有窗口，正好是关闭态的语义）。
* `POST /v1/arbitration/cases/{id}/execute`：窗口开着时**只**记 `execute_after` + 一条
  `case_execute_scheduled` 事件，**链上一笔不发**；重复调用不会把到期时刻往后推。
* `POST /v1/arbitration/cases/{id}/execute-due`：窗口到点后落钱；没到点一律 409
  （时间闸在服务端判，谁调都一样）。两个入口共用同一条落钱路径，口径只有一处。
* 闸门跟着拆：两个入口都挂 `require_arbitration_operator`（没登录 401 / 不在白名单 403）。
* 测试：`tests/unit/test_arbitration_appeal_window.py`（7 条）。变异验证 —— 把窗口分支
  关掉 4 条红、把时间闸拆掉 1 条红。

**注意：光有 ④-A1 时窗口还没有入口。** `/overturn` 仍要求案件已 `executed`，所以窗口
内目前**没有**「上诉 / 改判」这个动作 —— 窗口只是把放款推迟并记下到期时刻。要让
「推翻零成本」真正可用，必须接 ④-A3（窗口内的上诉入口）。

---

## 九、未做 / 依赖 / 不确定项（如实）

- **主网零改动**：本方案未在主网做任何变更。
- **testnet 无常驻 autosettle/tick 进程**：④-A2 必须一并解决，否则窗口到点靠人工推。
- **仲裁员质押未上链**（见 5.1）：④-B 的链上赔付通路今天发不出交易。
- **`partial` 判决的回滚**：本方案按「补偿欠款」处理，未设计按比例的部分回滚细则，
  需要产品确认（未定）。
- **上诉窗口时长**：待产品/风控拍板，本文只给测试网建议值。
- `KarmaVerifierBond` 的 `slasher` / `minBond` / `token` 三项链上配置本次**没有核对**，
  落地 ④-B1 前仍需现场只读确认（本次只确认了「后端没配金库地址」这一条）。

---

## 十、建议的下一步

**④-A3（窗口内的上诉入口）**：让当事人/运维在窗口内把一个 `decided` 且未到期的案件打回去
重判（清掉 `execute_after`、案件回到 `voting`）—— 链上一笔没发，所以这是**零回滚成本**
的那条路，也是 ④-A1 的兑现动作：没有它，窗口是空转的。之后才是 ④-A2（tick）与
④-B（窗口外补偿）。