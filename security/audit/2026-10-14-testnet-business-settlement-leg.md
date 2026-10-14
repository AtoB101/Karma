# 测试网：业务状态机那条腿走到 settled + 一条把「卖方收钱」打挂的真 bug（2026-10-14）

上一份记录 `2026-10-14-testnet-venue-escrow-drill.md` 的 §4.3 留了一句没做完的：

> 走 `/v1/escrow/{id}/orders` 这条路只驱动托管这条**独立面**，不推业务状态机。所以这一单的
> `settlements.status` 仍然是 `in_progress` —— 要让业务状态走到 `settled`，必须走
> `escrow_settlement.submit_for_task` 那条路，而它要求「交付验证 VERIFIED + 至少一条成功
> 执行回执 + 资金链路可回溯」。那需要一条真的、带回执的交付，本轮没有造。

这一轮把它补上了 —— 并且补的过程里撞出一条**线上真 bug**：一条脏回执会让
`POST /v1/settlement/{task}/buyer-accept` 直接 500，**卖方一分钱都收不到**。testnet 和
prod 各躺着一条这样的行。

本文是**证据**，不是计划。

## 一、结论先说

1. testnet 上那一单（task `eec1d64b…`）的 `settlements.status` **真的走到了 `settled`**：
   `delivered → settled` 由买方本人（`a2a-buyer` 的 key）点的放款，走的是既有的
   `POST /v1/settlement/{task}/buyer-accept`，不是直接改库、不是 Mock。
2. 第一次点下去是 **HTTP 500**。根因不在结算状态机，而在一条**读都读不出来**的执行回执：
   管道的 `kickoff_seller_execution` 一直把 `agent_steps` 的 **0 基下标**当成
   `ExecutionReceipt.step_index`（这个字段是 `Field(ge=1)`，**1 基**）。
3. 修法两处：写入侧改成 1 基（取「现有最大 + 1」）；再加迁移
   `0067_receipt_step_index_one_based` 把历史脏行归一。测试带**变异验证**。
4. 资金链路复核：`funds_trace` 无 issue、无 warning；链上余额与台账逐项对得上。

## 二、③ 到底缺什么

缺的不是托管，也**不是**回执本身 —— 这条 task 早有一条 `status=success` 的执行回执
（管道开单时写的）。缺的是**把业务状态机那条腿走完**：

```
POST /v1/settlement/{task}/submit        卖方交回执 → DELIVERED
POST /v1/settlement/{task}/buyer-accept  买方验收放款 → SETTLED
        └─ _sync_escrow_settlement → escrow_settlement.submit_for_task
               └─ assert_release_verified（钱这一步的闸）
```

鉴权口径（testnet `.env`）：`AUTH_ENFORCE_PROTECTED_ROUTES=true` +
`SETTLEMENT_REQUIRE_PARTY_ACTOR=true`，所以**必须**用当事方自己的凭据调用 ——
`X-Karma-Api-Key: karma_a2a-seller_*` 提交、`karma_a2a-buyer_*` 验收。明文在
`/opt/karma/testnet/phase1.local.env`（0600，不进仓库），其 `secret_sha256` 与
`karma_data/agent_api_keys.json` 逐字对上（已核对）。

### 2.1 交付（submit）：HTTP 200

```
POST /v1/settlement/eec1d64b-a036-404b-87ac-9e074e8bab5d/submit   (key = a2a-seller)
→ 200 {"status":"delivered","confirm_window_hours":72,
       "confirm_deadline_at":"2026-10-17T03:36:27.726850", ...}
```

`settlement_transition_audits` 落了一行：
`in_progress → delivered / allowed=t / guard_stage=store / actor=a2a-seller`。

P7 交付验证门、P4 主人确认门都**主动跳过**（这一单 `progress_rule_spec` 里没有
`scene_id`，也没有验证会话）—— 见 `_assert_p7_delivery_gate` 的
`no_scene_or_session` 分支。这不是绕过：门本身的判据就是「有没有场景」。
confirm 窗口 72h 写进了结算单，买方不表态也有出口。

### 2.2 验收（buyer-accept）：**第一次 500**

```
POST /v1/settlement/eec1d64b-a036-404b-87ac-9e074e8bab5d/buyer-accept  (key = a2a-buyer)
→ HTTP 500 Internal Server Error
```

容器日志里的真堆栈（节选）：

```
File "/app/api/routes/settlement.py", line 914, in buyer_accept_settlement
    await ensure_success_execution_receipt_before_seller_payout(
File "/app/services/settlement_receipt_release_guard.py", line 27, in ...
    receipts = await rstore.list_by_task(task_id)
File "/app/db/stores/receipt_store.py", line 95, in _from_row
    return ExecutionReceipt(
pydantic_core._pydantic_core.ValidationError: 1 validation error for ExecutionReceipt
step_index
  Input should be greater than or equal to 1 [input_value=0, input_type=int]
```

## 三、根因：0 基写进了 1 基的字段

| 位置 | 事实 |
|------|------|
| `core/schemas.py::ExecutionReceipt.step_index` | `Field(ge=1, description="Sequential step number (1-based)")` |
| `api/routes/receipts.py::submit_receipt` | 「这一单第一条必须是 1」，之后必须**连续** |
| `db/models/orm.py::ReceiptModel` | `UniqueConstraint("task_id", "step_index", name="uq_task_step")` |
| `services/trade_auto_execution.py::kickoff_seller_execution` | **写 `step_index=0`**（管线 `agent_steps` 的下标） |

`agent_steps` 用的是 0 基下标（`[{"index": 0, "action": "parse_requirement"}, …]`），
管道把这个下标直接塞进了回执的 `step_index`。于是库里多了一条**读不出来**的行：
`PostgresReceiptStore._from_row` 把它喂给 pydantic，当场 `ValidationError`。

后果不是「少一条回执」，而是**任何 `list_by_task` / `get_latest_by_task` 都炸成裸 500**。
放款路径上正好有两处要读这张表：

* `ensure_success_execution_receipt_before_seller_payout`（收付前的「至少一条成功回执」闸）；
* `escrow_settlement._assert_success_receipt`（钱这一步的同一道闸的镜像）。

也就是说：**这一条脏行会把卖方收钱那条路整条打挂。**

### 3.1 影响面（只读核对，两个环境各一遍）

| 环境 | `execution_receipts` 总行数 | `step_index < 1` | 受影响 task |
|------|------------------------------|------------------|-------------|
| testnet（`karma_testnet`） | 1 | 1 | `eec1d64b-a036-404b-87ac-9e074e8bab5d` |
| prod（`karma`） | 269 / 257 个 task | 1 | `0e5737ff-7bf8-4059-b92f-90903cb49b15` |

两条都是 `tool_name=trade_pipeline.parse_requirement`、`status=success`，两条都是**各自
那一单上唯一的一条回执**（所以归一时不会撞 `uq_task_step`）。prod 那条对应的单子
只要走到放款，就会 500。

## 四、修法

### 4.1 写入侧：1 基（根因）

`services/trade_auto_execution.py` 里改成取「这一单现有的最大 `step_index` + 1」，
没有就 1：

```python
latest_step = (
    await db.execute(
        select(ReceiptModel.step_index)
        .where(ReceiptModel.task_id == task_id)
        .order_by(ReceiptModel.step_index.desc())
        .limit(1)
    )
).scalar_one_or_none()
...
                step_index=int(latest_step or 0) + 1,
```

为什么不直接写死 `1`：卖家可能已经提交过真回执，写死会撞 `uq_task_step`，把接单路径
从「能跑」变成 500。取「最大 + 1」既守住 1 基，也不撞约束。

（顺带说明：修之前这条脏行存在时，收据路由自己也会 500 —— 它进来第一件事就是
`get_latest_by_task`。所以这不是「改了客户端预期」，而是把一个 500 换成一个有意义的下一步。）

### 4.2 历史数据：迁移 `0067_receipt_step_index_one_based`

`db/migrations/versions/0067_receipt_step_index_one_based.py`（`down_revision =
0066_escrow_binding_last_probed_at`）。逐行取「当前最大 + 1」，**不用一句 `SET = 1`** ——
同一单上已经有一条 1 号回执时会撞唯一约束。`downgrade` 有意为空：把回执降回 0 只会
重新造出「读不出来」的行。

### 4.3 回归测试

`tests/unit/test_receipt_step_index_one_based.py`（2 条）：

* `test_pipeline_kickoff_receipt_is_readable`：kickoff 写下的回执必须能被
  `PostgresReceiptStore` 读回来，且 `step_index == 1`；
* `test_pipeline_kickoff_does_not_collide_with_existing_receipt`：已有 1 号回执时，
  管线补的那条要落到 2，不撞 `uq_task_step`。

**变异验证**：把 `trade_auto_execution.py` 里的 `step_index` 改回 `0` 之后，这 2 条**恰好**
失败（其中一条正是产品里的那个 `ValidationError`）；改回来即绿。

```
pytest tests/unit/test_receipt_step_index_one_based.py        → 2 passed
pytest tests/unit/test_trade_pipeline_security.py tests/unit/test_escrow_settlement.py
       tests/unit/test_self_dealing_ban.py
       tests/unit/test_settlement_onchain_status_never_downgrades.py
       tests/integration/test_trade_order_pipeline_launch.py …  → 81 passed
```

## 五、testnet 实测：收尾那一单

testnet 现场跑的是**已部署的那份代码**（`/opt/karma/repo`），所以要先把那条脏行按
**迁移 0067 的同一套逻辑**归一，再重跑放款。归一是单事务 + 断言：

```
BEFORE:  96dc6fce-60c2-4576-a9e6-20438f7f9c00 | eec1d64b-… | step_index=0
DO $$ … 逐行 MAX(step_index)+1 … ; 断言「归一后 step_index<1 的行数 = 0」，否则 RAISE EXCEPTION
AFTER:   96dc6fce-60c2-4576-a9e6-20438f7f9c00 | eec1d64b-… | step_index=1 | success
remaining step_index<1 rows: 0
```

然后重跑放款：

```
POST /v1/settlement/eec1d64b-a036-404b-87ac-9e074e8bab5d/buyer-accept   (key = a2a-buyer)
→ HTTP 200
  "status":"settled"
  "released_amount":10.0   "refunded_amount":0.0
  "released_at":"2026-10-14T04:03:20.146226"
  "onchain_status":"settled"   "onchain_binding_id":1
  "escrow_amount":10.0  "currency":"USD"
  "arbitration_notes":"buyer accepted delivery — full settlement to seller;
                       p8_attestation=sat_5294a708762037063b53d0af"
```

### 5.1 状态机审计流水（全链可查）

| from | to | allowed | guard_stage | reason | actor | at |
|------|----|---------|-------------|--------|-------|----|
| draft | pending | t | store | trade pipeline: pending before lock | trade_pipeline_v2 | 2026-10-12 04:13:02 |
| pending | accepted | t | store | trade pipeline: worker locked | trade_pipeline_v2 | 2026-10-12 04:13:02 |
| accepted | in_progress | t | store | trade pipeline: execution kickoff | trade_pipeline_v2 | 2026-10-12 04:13:02 |
| in_progress | delivered | t | store | delivery submitted | a2a-seller | 2026-10-14 03:36:27 |
| delivered | settled | t | store | buyer accepted delivered work | a2a-buyer | 2026-10-14 04:03:20 |

每一步 `transition_allowed=t`、`guard_stage=store`，**没有一条 `guard_stage=chain` 的假失败**。

### 5.2 台账跟着走

* `settlements`：`status=settled`、`onchain_status=settled`、`released_amount=10`、
  `tx_hash=0xbe0cad448b…65da`（即 finalizeSettlement 那笔）、`contract_address=0x2C9911F5…`；
* `escrow_bindings#1`：`state=settled`；
* `capacity`：买方 `reserved_credits 10 → 0`、`released_credits 0 → 10`（钱从「冻着」变成
  「已放」）；卖方 `total_bill_credits=5 / available=5`。

## 六、资金链路对齐（用户口径：每一笔资金都要有源头）

动钱前后都跑一次 `services/chain/funds_trace.trace_task_funds`：

```
funds_trace ok: True
issues: []
warnings: []
describe: 资金来源：a2a-buyer 的账单 1（0xd91acb5d…）；受款方：a2a-seller 的账单 2
          （0x9c479392…）；链上绑定 #1；托管金额 10 USDC
```

链上余额（Sepolia 11155111，mUSDC `0x6AF606f5…`）：

| 钱包 | mUSDC | 对托管合约 `0x2C9911F5…` 的授权 |
|------|-------|--------------------------------|
| 买方 `0xD91acb5D…` | 36.0 | 36.0 |
| 卖方 `0x9C479392…` | 19.0 | 5.0 |

对得上：买方账单承诺 50 → 这一单花掉 10（+ 上一轮演练的 4）= `spent_usdc 14` /
`capacity_credited_usdc 36`；卖方那条链上账单 5 未动（`spent 0`），钱包里多出来的
10 正是这一单的货款。钱在 `finalizeSettlement` 那一刻从买方钱包**直划**卖方，
合约全程零持有。

## 七、还没做的（如实列）

* **prod 那条脏行（task `0e5737ff…`）要等这份迁移上线**才会被归一。合并部署后需要
  核对一次「prod `step_index<1` 的行数 = 0」。
* testnet 现场这次是**先归一数据、再跑放款**（现场代码还没有 §4.1 的写入侧修复）。
  写入侧修复的现场验证放在部署之后：重启 testnet api → 重新开一单 → 确认管道写下的
  回执 `step_index=1` 且读得出来。
* `escrow_settlement.assert_release_verified` 的钱闸这次**没有被走到**：这一单的
  `escrow_bindings#1` 在 `2026-10-14` 早先的托管演练里就已经 `settled`，`submit_for_task`
  按设计**提前返回**（「链上已经落定，别重复开窗」）。也就是说这一轮验证的是
  **业务状态机那条腿**；「业务状态机开链上窗」那条顺序正确的全链闭环还没在 testnet 上跑过
  （需要一条 binding 仍是 `active` 的新单）。
* 本轮只动 testnet；prod 的数据一个字节没动（除了这次要上的迁移）。
