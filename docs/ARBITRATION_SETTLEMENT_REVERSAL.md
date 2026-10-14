# ④ 仲裁回滚（settlement reversal）落地方案

> 状态：**④-A1 / ④-A2 / ④-A3 已落地**（2026-10-14）；**④-B1 已落地并在测试网真链实测**（2026-10-15，见 §5.6 与 `VERIFIER_BOND_VAULT_RUNBOOK.md`）；
> **④-B2 为方案、待批**（§十一）。
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
| ④-A2 | 后台 tick（`arbitration_execute_due`）+ 常驻进程 | ④-A1 | **已落地**（见 8.3） |
| ④-A3 | 上诉入口（窗口内改判，零链上动作） | ④-A1 | **已落地**（见 8.2） |
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

**④-A3 补上了这个入口**（见 8.2）：窗口内可以把裁决打回去重审，链上一笔不发。
`/overturn`（窗口**外**的推翻）仍要求案件已 `executed`，那条路属于 ④-B —— 钱已经动了，
只能赔、不能倒。两者不是一回事，别把窗口内上诉当成 `/overturn` 的替代品。

### 8.2 ④-A3 已落地（2026-10-14）

* 开关：沿用 ④-A1 的 `ARBITRATION_APPEAL_WINDOW_SECONDS`（窗口关着时这个入口一律 409，
  等于不存在）；限次：`ARBITRATION_MAX_APPEALS`（默认 **3**，<= 0 = 不限）。
* `POST /v1/arbitration/cases/{id}/appeal`：把 `decided` 且**未到期**的案件打回 `voting`，
  清 `decided_outcome` / `final_partial_percent` / `execute_after`，`vote_round += 1`，
  落一条 `case_appeal_opened` 事件。**链上一笔不发、结算一步不动** —— 这就是「推翻零成本」。
* 谁来提：当事人（立案人 / 结算买卖双方）本人，或 `ARBITRATOR_ACTOR_IDS ∪ ADMIN_ACTOR_IDS`
  白名单运维岗代提；两条路都过 `require_identity_binding`。
* 票按**轮次**计（迁移 `0069_arbitration_appeal_rounds`）：`arbitration_votes.vote_round`，
  唯一键从 `(case_id, arbitrator_identity_id)` 换成
  `(case_id, vote_round, arbitrator_identity_id)`。老行一律 `vote_round = 0`，所以升级前后
  对老案件的计票口径逐字一致。**只把状态改回 `voting` 而不分轮 = 没打回**：重审里随便
  再来一票就会把旧结论重新投出来 —— 这是这条路上最容易写错的地方（有用例专门钉它）。
* 链上门禁（§七.4 落地）：`services/chain/escrow_settlement.assert_no_payee_yet()` ——
  `getBinding().state` 必须 ∈ `{active(1), disputed(6)}`；已经 `finalizing` / 落定的一律 409，
  读不到链上状态也 409（默认拒绝）。托管没启用时是空操作。
* 打回之后原来的 `/execute-due` 自然失效（案件已不在 `decided`，409）。
* 测试：`tests/unit/test_arbitration_appeal_reopen.py`（9 条）。变异验证 —— 把计票里的
  轮次过滤拆掉，`test_previous_round_votes_cannot_decide_the_new_round` 变红。

### 8.3 ④-A2 已落地（2026-10-14）

* **不新造调度器**：复用已经存在的那一个常驻循环 —— API 进程 lifespan 里的
  `services/chain/escrow_autosettle.run_forever()`（`api/app.py:150`，`ESCROW_AUTOSETTLE_ENABLED`
  控制；prod 已开，testnet 实测时临时打开）。窗口到点的仲裁裁决作为这一轮 tick 里的
  一个新步骤 `execute_due_arbitration_cases`（`api/routes/arbitration.py`），**不另起进程、
  不引 celery / APScheduler**（仓库里本来就没有这两样）。
* **口径只有一处**：tick 与人工 `POST /cases/{id}/execute-due` 调的是同一个
  `_settle_from_decision`，没有第二条落钱路径。审计链靠 `route_path` 区分
  （`…/execute-due (autosettle tick)` vs `…/execute-due`）。
* **只挑到点的**：`status='decided'` + `execute_after` 非空 + `execute_after <= now()`。
  窗口关着（默认）时案件从不留 `execute_after`，这一步是空操作 —— prod 行为逐字不变。
* **不双放款**（这条路上最贵的错误）：落钱前对案件行 `SELECT … FOR UPDATE SKIP LOCKED`，
  人工 `/execute-due` 也改成同一把 `FOR UPDATE`；谁先拿到锁谁放款，另一个 re-check 后
  必然看到 `executed` 从而 409。拿到锁后状态/时间闸再判一次（锁等到的可能是别人已落完的单）。
* **一条坏不拖住别的**：每条案件各自提交，失败 `rollback` + 按 `RETRY_BACKOFF_SECONDS`
  退避（复用 autosettle 的 `_failed_at`），链上门禁 / 结算行缺失一律当失败 —— 整条回滚，
  案件留在 `decided`，绝不出现「账上已结算、链上一分没动」。
* 测试：`tests/unit/test_arbitration_autosettle_due.py`（9 条）。变异验证 —— 拆掉失败分支的
  `rollback` → `test_one_bad_case_does_not_block_the_next` 变红；同时拆掉 SQL 时间过滤与
  re-check → `test_tick_skips_a_case_whose_window_is_still_open` 变红。
* **单测跑在 SQLite 上**（方言不渲染 `FOR UPDATE`），所以用例钉的是**顺序**与 **re-check
  逻辑**；那把真正的行锁由 Postgres 在 testnet 上实测。

---

## 九、未做 / 依赖 / 不确定项（如实）

- **主网零改动**：本方案未在主网做任何变更。
- **testnet 现在没有开 `ESCROW_AUTOSETTLE_ENABLED`**（默认 false）—— ④-A2 的代码已在，
  但测试网这条循环默认不跑；prod 是开的（窗口默认 0，这一步在 prod 是空操作）。
  测试网要到点自动放款，需显式打开该开关。
- **仲裁员质押未上链**（见 5.1）：④-B 的链上赔付通路今天发不出交易。
- **`partial` 判决的回滚**：本方案按「补偿欠款」处理，未设计按比例的部分回滚细则，
  需要产品确认（未定）。
- **上诉窗口时长**：待产品/风控拍板，本文只给测试网建议值。
- `KarmaVerifierBond` 的 `slasher` / `minBond` / `token` 三项链上配置本次**没有核对**，
  落地 ④-B1 前仍需现场只读确认（本次只确认了「后端没配金库地址」这一条）。

---

## 十、建议的下一步

④-A 三步（`execute_after` / 窗口内上诉 / 到点常驻 tick）都已落地，主网仍是「窗口关」的
历史行为。接下来是 ④-B：④-B1 把 `VERIFIER_BOND_VAULT_ADDRESS` 接进后端
（现在是 unset，罚没一律停在 `pending`），④-B2 建 `settlement_reversals` 台账并把
`/overturn` 接上赔付，④-B3 罚没池补欠款 + 操作台展示。

**④-B1 已于 2026-10-15 落地并真链实测**（`build_transaction` 带 `from`、`HexBytes` 归一，两处只有真链才暴露的 bug 都已修；见 `VERIFIER_BOND_VAULT_RUNBOOK.md` §5.6）。**④-B2 的具体落地方案见 §十一（待批）。**

## 十一、④-B2 落地方案：`settlement_reversals` 台账 + `/overturn` 接上赔付（2026-10-15）

> 状态：**方案，待批**。④-B1 已落地并已在测试网真链实测（见 §5.6）。
> 本节所有判断都对着**当前 main**（`11b639f`）与**测试网真库**核过，附证据。

### 11.1 一句话

回滚**不改终局状态机、不发新链上原语**：新增一张「欠谁多少、这笔钱由哪个来源出」的台账
`settlement_reversals`，`/overturn` 当场按**推定**（不采信调用方口述）把它写出来；
出账仍守 ④-B1 那条硬规矩 —— **没有链上 tx 就没有 `settled`，`paid_amount` 一个子儿都不会动**。

### 11.2 这次核到的具体事实（不是推测）

测试网真库只读核对，`case 970925f2-ece0-40d0-b63f-2232baf4c3ec`：

| 事实 | 值 |
|---|---|
| `arbitration_cases` | `status=executed`、`decided_outcome=buyer_wins`、`task_id=task-arb-a1-171639`、`settlement_id=3d827927…` |
| `escrow_bindings`（按 `task_id` 关联） | `binding_id=8`、`state=slashed`、`amount_usdc=3`、`stake_usdc=0.9`、`contract_address=0x2C9911F5…` |
| `settlements` | `client=a2a-buyer`、`worker=a2a-seller`、`escrow_amount=3`、`released=0`、`refunded=3`、`onchain_binding_id=8` |
| 双方钱包（`identity_profiles.bound_wallet_address`） | buyer `0xD91acb5D…`、seller `0x9C479392…` |

**结论**：钱确实动了（`slashed`）= 档 C，受害方与金额都能从库里**推**出来 —— 这是一条
现成的、可真机演练的 fixture。

同时核到的两处**现状缺口**：

1. `/overturn` 的赔付对象今天是**调用方传进来的参数**（`body.victim_wallet_address` /
   `victim_identity_id`，`api/routes/arbitration.py:785-786`，直接透传给 `record_slash`）。
   → 「赔给谁」不能由调用方随口给，必须按案件推定。
2. 迁移基线是 `db/migrations/versions/0069_arbitration_appeal_rounds.py` → 本阶段是 `0070`。

### 11.3 数据模型（迁移 `0070_settlement_reversals`）

| 列 | 说明 |
|---|---|
| `reversal_id` | 主键（uuid） |
| `case_id` / `task_id` / `binding_id` | 回溯链：案件 → 任务 → 链上那条绑定 |
| `victim_identity_id` / `victim_wallet` | **推定**出来的受害方；推不出钱包就 `NULL`（不编） |
| `owed_amount` | 必须还给受害方的金额（源头见 11.4 第 4 步） |
| `paid_amount` | **已真实到账**的金额，只在对应链上 tx 被核过之后才增加 |
| `funding_source` | `bench_bond` / `slash_pool` / `platform_debt`（当前这台账打算从哪出） |
| `status` | `pending` / `submitted` / `settled` / `failed`（与 `bond_slash` 同名同义） |
| `tx_hash` / `attempts` / `last_error` / `settled_at` | 与 `bond_slash.BondSlash` 逐字对齐 |

**幂等键**：`UniqueConstraint(case_id, victim_identity_id)` —— 同一案件对同一受害方只可能有一条账。
`funding_source` 是**动态**的（先 `bench_bond`，不够再 `platform_debt`），所以它不进唯一键。

### 11.4 `/overturn` 接上赔付（7 步，每一步失败都默认拒绝）

1. **前置**（已有）：案件必须 `executed` 且有 `decided_outcome`。
2. **找绑定**：按 `task_id` 取最新 `escrow_bindings`。**没有绑定** → 不动钱、不建台账，
   `settlement_reversal="no_binding"`（如实：这一单没有链上结算，谈不上回滚）。
3. **问链**（`escrow_settlement.chain_snapshot`）分档（沿用 §三 的表）：
   * 档 A `active(1)/disputed(6)`：钱没动 → **不建赔付台账**，返回 `"not_moved"`，
     提示走 `/appeal`（零成本回滚那条路）；
   * 档 B `finalizing(2)`：钱在窗口里还没走 → 建台账、`status=pending`，注记「等落定再算实付」；
   * 档 C `settled(3)/slashed(4)`：钱动了 → 建台账并进入赔付通道。
   * **链上读不到** → 409，一条账都不写（fail-closed，`chain_snapshot` 返回 `None` 时也一样）。
4. **推定受害方与欠款额**（**不采信调用方参数**）：
   * `seller_wins` → 货款已付给卖方 → `victim = 买方`，`owed = binding.amount_usdc`；
   * `buyer_wins` → 货款没付、卖方质押被划 → `victim = 卖方`，`owed = binding.amount_usdc`
     （**要不要再加回被误划的质押：见 11.7 第 2 条，待拍板**）；
   * `partial` → **本阶段一律 409「partial 回滚细则未定」**，不猜一个比例出来；
   * 受害方钱包：`binding.buyer_identity_id / seller_identity_id` →
     `identity_profiles.bound_wallet_address`；取不到 → `victim_wallet=NULL`、台账照记、
     `status=pending`（赔付通路发不出 tx，如实停住，不编地址）；
   * 调用方传的 `victim_wallet_address` / `victim_identity_id` **只在与推定一致时**被接受，
     不一致（或推定成功却传了别人）→ **409**。这条是防「把赔款指给别人」。
5. **`assert_funds_traceable(task_id, stage="settlement_reversal")`**（`services/chain/funds_trace.py:317`）：
   资金来源链路对不上 → 409，且**一条账都不写**。
6. **自成交**：`escrow_settlement.detect_self_dealing`（`:937`）命中 → 不进赔付通道
   （与托管同一份判据，不另写一套）。
7. **幂等**：find-or-create，沿用 `bond_slash.record_slash`（`services/bond_slash.py:84`）的写法；
   重复 `/overturn` 不会重复计债。

### 11.5 出账：钱从哪来，什么时候才算「已赔」

优先级（沿用 §五）：

1. **被推翻那一庭的质押**：这条通路 ④-B1 **已经打通**（`bond_slashes` → 治理账户真发链上
   `slash(verifier, victim, …)` → `/slashes/{id}/status` 回链核 calldata → `settled`）。
   B2 要补的只有一件事：`victim_wallet_address` 从「调用方传」改成「按 11.4 推定」，
   这样金库按 `victimShareBps` 分出来的 80% 才真的落在受损方钱包上。
2. **不足部分** → `settlement_reversals` 台账记「欠」。
   `paid_amount` 的增加条件（**两条都要满足，缺一不可**）：
   * 该案 `bond_slashes` 行**已 `settled`**；
   * 那条 tx **回链核过**（复用 ④-B1 的 `verify_slash_tx`，核对被罚钱包 / 受害方 / 金额）。
   只 settled 没核 tx 的、或者核出来受害方不是同一个钱包的 —— 一律不加。
3. **池子补欠款**（`funding_source='slash_pool'` 的出账）**不在本阶段**：
   金库现有原语只有 `slash()`（罚）与 `distributePool()`（按人头奖励成员），
   **没有「把池子钱转给某个受害方」这条**。要新增它就是新增链上原语 —— 那必须单独方案 + 单独审计，
   归 ④-B3。

**本阶段不发任何新交易**：B2 只写账与推定，链上动作全部沿用 ④-B1 已实测的那条路。

### 11.6 接口与操作台

* `/overturn` 响应：`settlement_reversal` 从单一字面量改成明确枚举 ——
  `recorded`（建了台账）/ `not_moved`（档 A）/ `no_binding`（没有链上结算）/
  `not_performed`（本阶段仍不做的那些，如实保留），并新增 `settlement_reversal_detail`
  （`reversal_id` / `victim_identity_id` / `victim_wallet` / `owed_amount` / `funding_source` / `status`）。
* **这会改现有契约**：`tests/unit/test_arbitrator_overturn_slash.py:92` 现在钉的是
  `== "not_performed"`。本阶段**显式改这条测试**并在 PR 里写明（不是顺手改）。
* 新增只读 `GET /v1/arbitration/reversals`（`require_admin_actor`）：列出欠款台账 +
  每条的资金来源与实付。操作台展示归 ④-B3（一次改太多容易漏）。

### 11.7 要你拍板的（我不替你定）

1. **`partial` 判决的回滚细则**：按比例谁欠谁多少 —— 未定，B2 一律 409（不猜）。
2. **`buyer_wins` 被推翻时，被误划走的那笔卖方质押算不算进欠款**：
   两个口径差一笔钱（本例是 0.9 USDC），而且那笔钱现在在**买方**钱包里、追不回来。
   净额口径（只欠 `escrow_amount`）/ 总额口径（`escrow_amount + 被误划质押`，其中一部分算
   对买方的债权）—— 这是产品与法务口径，不是技术选择。
3. **`platform_debt` 最终由谁出账、什么时限**：不定这个，欠款可能永远挂在 `pending`。
4. **上诉窗口时长**（④-A 遗留）：测试网先 300s 是否合适。

### 11.8 测试与验收（按老规矩：本地 → 变异 → CI → 合并 → 部署 → 真链演练）

* 新增 `tests/unit/test_settlement_reversals.py`，至少钉住：
  * 幂等：同一案件重复 `/overturn` 只出一条账；
  * 档 A 不建台账、档 C 建台账、档 B `pending`；链上读不到 → 409 且零写入；
  * 受害方按 `decided_outcome` **两个方向**各推一次，推出来的钱包与库里绑的一致；
  * 调用方传一个**别人**的钱包 → 409（这条要单独钉，它防的是最贵的错误）；
  * `funds_trace` 不过 → 409 且零写入；自成交 → 不建赔付；
  * `partial` → 409；
  * `paid_amount` 在没有 tx 时**纹丝不动**；`settled` 不带 tx 一律拒绝。
* 变异验证：逐条拆（409 改放行、幂等键去掉、`funds_trace` 调用挪走、`paid_amount` 无条件增加），
  要求每条都被抓；文件按字节还原。
* **真链演练**（testnet，用 11.2 那条现成 fixture）：
  1. 传**错的** victim → 409；
  2. 正确调用 → 台账出现 `owed=3`、`victim=a2a-seller`、`victim_wallet=0x9C479392…`；
  3. `bond_slashes` 真出账（治理钥 `slash`）→ `settled` → `paid_amount` 增加；链上核 calldata；
  4. 用完复原（drill 档案删净、开关撤掉），台账保留。
* 主网：本轮**零改动**（与 ④ 前几段一致）。

### 11.9 本阶段**不做**的（写在这儿，免得被当成已做）

* 不给业务状态机加回退边：`SETTLED` / `REFUNDED` 仍是**终局**（§2.3）；
* 不动托管合约、不发明「链上倒钱」原语；
* 池子补欠款 + 操作台展示（④-B3）；
* `partial` 的比例细则（等 11.7 拍板）。

---
