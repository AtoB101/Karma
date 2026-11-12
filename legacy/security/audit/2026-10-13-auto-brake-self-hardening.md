# 安全审计 —— 自动刹车自我加固（清不掉）的根因与修复（2026-10-13）

Range: 测试网（`https://karma-network.ai` / VPS `47.82.74.68`，Sepolia `TESTNET_CHAIN_ID=11155111`）。**主网未动**。

**结论先行**：`runtime_safety_mode` 的自动刹车确实会**自我加固、清不掉**，而且现在就在线上
发作（`enabled=t`，`triggered_at=02:53:24`，`updated_at=03:40:02` —— 有人清过，又被自动拉回去了）。
根因**不是**「刹车制造的拒绝」，而是两件事叠在一起：

1. **口径错**：19 张卡在 `auto_confirmed` 的结算单（链上 `bound`、`finalizeSettlement` 一直失败）
   被 autosettle 每轮各拒一次，`guard_stage=chain`。「链上腿失败」被算进了**同一个**拒绝率；
2. **没有迟滞**：告警窗口是往后看的（运维轮询器默认 `window_minutes=60`），人工清闸后那批
   **旧**拒绝还留在窗口里，下一轮轮询拿同一批证据又把闸拉回去。

两处都修了，并且用**线上真实事件流**回放过（见 §3）。没有任何资金状态机逻辑被放宽，
失败方向仍然偏安全那一侧。

## 1. 触发与现象（线上原始证据）

线上 `settlement_transition_audits`（`karma-postgres` / 库 `karma`）：

```
 select guard_stage, transition_allowed, count(*) ... where created_at > now() - interval '48 hours';

 guard_stage | transition_allowed | count
-------------+--------------------+-------
 store       | t                  |    69
 chain       | f                  |    21
```

`chain` 那 21 条里 19 条落在**同一秒**（`02:43:12.2xx`），`route_path=/internal/auto-confirm`、
`actor_id=system:auto-confirm`、`from_status=auto_confirmed → to_status=settled`，
**19 个不同的 `task_id`** —— 即 autosettle 一轮扫过 19 张卡住的单子，每单失败一次。

```
 select date_trunc('minute',created_at) m, count(*) n, count(distinct task_id) tasks ...;

          m          | n  | tasks
---------------------+----+-------
 2026-10-13 02:43:00 | 19 |    19
```

刹车行：

```
 select enabled, triggered_by, triggered_at, updated_at from runtime_safety_mode;
 enabled |  triggered_by |        triggered_at        |        updated_at
 t       | security-ops | 2026-10-13 02:53:24.939744 | 2026-10-13 03:40:02.320999
```

`reason` = `auto brake: settlement transition denied rate critical alert`。`triggered_at` 停在
02:53（第一次自动拉闸），`updated_at` 03:40 —— **最后一次状态变化是 03:40 的自动复燃**。

## 2. 根因

* 指标定义（`services/security_monitoring.py`）：`denied_rate = denied / total`，
  `denied` = 所有 `transition_allowed=false` 的审计事件 —— 不区分成因。
* 告警（`SETTLEMENT_TRANSITION_DENIED_RATE`，CRITICAL）→ `api/routes/security.py`
  的 `should_auto_brake` → `set_runtime_safety_mode_persisted(enabled=True)`。
* 闸落下之后，`assert_runtime_operation_allowed("new_settlement")` 把 autosettle 挡在 503，
  于是**不再产生新拒绝** —— 但**旧事件还在窗口里**。
* 运维轮询器（`scripts/ops/security_alert_poller.py`）默认 `window_minutes=60`：
  02:53 那批事件在 03:40 仍在窗口内 → 同一批证据再次判 CRITICAL → 自动复燃。
  人工清闸之后能撑住的时间，等于「距离下一轮轮询」。

`can_transition` 这条**真**状态机闸门本身没有任何问题：48 小时窗口里
`guard_stage in (route, pipeline)` 的拒绝是 **0**。被误算的 21 条全是链上腿失败。

## 3. 修复与验证

修法（两个都在这一轮）:

| # | 改什么 | 文件 |
|---|---|---|
| F1 | 拒绝按 `denial_class` 分类：`state_machine`(route/pipeline) / `chain_gate`(chain) / `store_conflict`(store)。`settlement_transition_denied_count`、`_rate` **只数 state_machine**；分母 = 放行的迁移数 + 状态机拒绝数 | `services/settlement_transitions.py`、`api/routes/settlement.py`、`services/security_monitoring.py` |
| F2 | 链上腿失败另立 **HIGH** 告警 `settlement_transition_chain_gate_spike`，按**结算单**去重（同单重试 N 次 = 1 条），**不接自动刹车** | `core/schemas.py`、`services/security_monitoring.py` |
| F3 | 迟滞：新增 `runtime_safety_mode.manual_override_at`（migration `0065`）。人工放闸盖章；自动刹车只认**比它更晚发生**的状态机拒绝 | `services/runtime_safety.py`、`api/routes/security.py`、`db/models/orm.py`、`db/migrations/versions/0065_runtime_safety_manual_override.py` |

**为什么链上腿失败不接自动刹车**：刹车拦不住链上腿失败本身，却会把 autosettle 的放款重试
**和**人工恢复一起掐死 —— 越刹越出不来。而这条链路本来就是 fail-closed：账上状态已退回、
钱一分没动，只是「没结算成功」。它该做的是**报出来给人查**，不是把全站资金闸拉下。

**线上事件流回放**（把 `karma-api` 容器里的真实 journal `/app/mvp_data/security_events.jsonl`
按新老两套口径各算一遍）：

```
journal lines            : 6886
audit events total       : 130

=== window last 60m ===
  audits            : 79
  OLD  denied/rate  : 19/79 = 24.05%   -> CRITICAL at >=20% & total>=10: True
  NEW  denied(sm)   : 0
  NEW  guard_evals  : 60
  NEW  denied/rate  : 0/60 = 0.00%   -> CRITICAL: False
  NEW  chain_gate   : 19 retries over 19 distinct settlement(s)
  denial_class hist : {'chain_gate': 19}
```

即：**同一批线上事件**，旧口径判 CRITICAL（正是 02:53 的那一跳），新口径不再触发自动刹车，
而那 19 条并没有被藏起来 —— 它们变成一条按单去重的链上腿失败告警。

**migration 在真实 Postgres 上验过**（沙箱库 `karma_testnet`）：`ADD COLUMN IF NOT EXISTS`
连跑两次，第二次 `NOTICE ... already exists, skipping`；列类型
`timestamp without time zone / nullable` 与 ORM 一致；`DROP COLUMN IF EXISTS` 干净回滚。

**回归测试**：`tests/unit/test_security_ops.py`（口径分离 / 按单去重 / 迟滞 / 老事件兼容）、
`tests/unit/test_runtime_safety_persistence.py`（时间戳活过重启、自动刹车不覆盖它、
建表+加列与 ORM 一一对应）。

## 4. 本轮**没有**做的

* 没碰主网，没碰任何资金路径的业务逻辑；`can_transition`、托管合约、结算金额计算全部未改。
* **19 张卡住的单子（现在 25 张）没有修** —— 那是另一个问题（`finalizeSettlement` 为什么
  一直失败：sepolia RPC / escrow binding 状态 / operator allowance 待查）。本轮只保证
  「它不再冒充状态机攻击、也不再把刹车锁死」。这条留作下一步，已进 §11.2 的问题清单。
* 审批链的 `approver_id` 自报问题（见 `docs/SECURITY_THRESHOLD_POLICY.md` 的已知薄弱点）
  仍未动。
