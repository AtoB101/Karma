# 自成交脏单：为什么卡死、怎么清、怎么绝后（2026-10-14）

承接 `security/audit/2026-10-13-stranded-auto-confirm-and-self-deal.md`（F3/F4 把
自成交**挡在接单那一刻**）与 `security/audit/2026-10-14-self-dealing-hard-ban.md`。
那一轮挡住了「新的自成交」，但**线上那条已经产生的脏单还卡在原地** —— 本文只解决这一条，
并给出一条**通用的出口**，让任何同类脏单都能收尾，而不是永远留在状态机里。

范围：测试网（VPS `47.82.74.68`，Sepolia `TESTNET_CHAIN_ID=11155111`）。**主网未动。**

---

## 1. 脏单是什么（线上实测，2026-10-14）

```
settlement_id      97f0dc0e-4748-41fe-8ad8-fe71e195b832
task_id            0d676417-0de2-4bdb-b286-ca4e2cc51fd1
status             in_progress
settlement_mode    escrow_allowance      funding_source internal
onchain_status     pending_bind          onchain_binding_id  (空)
escrow_amount      1                     tx_hash (空)
client_agent_id    kid_t23b_8d65f4e9e4a9      worker_agent_id agent-3610b5c97bb5
created_at         2026-10-13 01:36:01
escrow_bindings    该 task 一条都没有（0 条）
```

买卖双方解析到**同一个主身份、同一把钱包**：

```
买方账单 0x65eb…:12 → wallet 0x3295c96a2993c366b3db27b6ac81f85801d75f51
卖方账单 0x65eb…:4  → wallet 0x3295c96a2993c366b3db27b6ac81f85801d75f51
agent-3610b5c97bb5.owner_identity_id = kid_2b8b6dfca420c96a1409b8fd  ← 和买方同一个主人
```

**钱一分没动**：`KarmaAllowanceEscrow.bind` 只做 `reserved += amount`，从不转账；这一单
`pending_bind` 从未落过 binding，链上一条记录都没有，`allowance_commits` 里也没有为它
预留的行。所以它是一张**没进过链的空头结算单**，不是一笔钱。

## 2. 为什么它永远出不去（根因）

状态机的每一格出口（`CANCELLED` / `DISPUTED` / `SETTLED` / `REFUNDED`）在链上那一步之前都会先
`_fill_in_deferred_bind()`（`materialize_pending_bind`）——**这是对的**：真的会碰那条绑定的动作，
得先把延迟的绑定补成真绑定。但这条脏单补不出来：`bind_for_task` 里的自成交闸
（`assert_parties_not_self_dealing`）判它 `SameOwner()`，直接 409。

于是每一次尝试都是：`apply_settlement_transition` → 业务状态先落库 → `sync_chain_escrow_for_transition`
→ `_fill_in_deferred_bind` 抛 409 → `revert_chain_rejected_transition` 把业务状态退回去。
`settlement_transition_audits` 里能看到的正是这条：

```
in_progress -> disputed  允许   guard_stage=chain   「链上闸门拒绝了这一步（dispute opened）：业务状态已退回」
in_progress -> disputed  允许   guard_stage=chain   （第二次）
```

而自成交闸本身是**决定性的**（不是抖动）：`SameOwner()` 只看钱包地址，同一把钱包，
重试一万次还是同一堵墙。于是这张单**没有任何一格出口**，永久停在 `in_progress`。

> 这也解释了 autosettle 为什么长退避：`bind_due` 把 `SameOwner` 归到
> `_PERMANENT_BIND_ERRORS`，退避 3600s、同一原因只报一次——它在**正确地**避免每轮白烧 gas。

## 3. 口径（本文落地的三条）

1. **绝后**：自成交挡在接单那一刻——已有，不重复（PR #303 上线）。本文不动它。
2. **给出唯一的出口**：自成交的单**永远绑不上**，所以「取消」这条不需要 binding 的出口
   必须能走通 —— 跳过 `_fill_in_deferred_bind`，直接 `cancel_for_task`（它对本单返回
   `unbound`，一笔链上交易都不发）。
3. **放回去**：取消之后买方被占的额度由既有 `reconcile_capacity_mirror` 按链上事实对齐
   （本单从未占过额度，实际是 0 变更；逻辑上走同一条路，不额外发明）。

**为什么只开口 `CANCELLED`、不开 `SETTLED`/`REFUNDED`/`DISPUTED`**：后三条要么真的动钱
（settle 划款 / slash 罚没），要么要在链上立「谁都别想走」（dispute 需要真绑定）。
一张从未绑定的自成交单既没有钱可划、也没有绑定可 dispute —— 它们对这张单本来就**不成立**，
强行放行等于把「链上没落定，业务不许往前走」这条根本约束打穿。取消是唯一语义正确、
且不碰钱的出口。

## 4. 落地对应

| 件 | 内容 | 文件 |
|----|------|------|
| C1 | 自成交判定抽成**只判不抛**的 `detect_self_dealing()`；`assert_parties_not_self_dealing()` 改用它（行为、报文、留痕一字不改） | `services/chain/escrow_settlement.py` |
| C2 | `_sync_escrow_settlement` 的 `CANCELLED` 分支：先判自成交，命中就**跳过补绑**直接 `cancel_for_task` | `api/routes/settlement.py` |
| C3 | 收尾脚本：清单 + `--apply`，走**同一条审计过的状态机** `apply_settlement_transition`（`route_path=/ops/self-deal-terminate`，写 `settlement_transition_audits`） | `scripts/settlement_self_deal_terminate.py` |
| C4 | 单测：判定抽身不回归、取消出口放行、正常单不受影响、非自成交仍被挡 | `tests/unit/test_settlement_self_deal_recovery.py` |

## 5. 验证

* 本地：新增用例 + 相邻回归（见交付说明里的真实执行记录）。
* 线上：先在**测试网**跑 `--apply`，比对收尾前后的
  `settlements.status` / `settlement_transition_audits` / `capacity`，确认「钱没动、账对齐」。
* 主网：按用户口径**先测试网全部做完**再谈。

## 6. 明确不做

* 不新增「自动扫描并把自成交单自动取消」的定时任务（本文只给**显式人工**的出口；要不要自动化
  是另一个决定，需要单独的口径）。
* 不重写自成交闸、不动 `SameOwner` 的链上语义、不动既有任何一格状态的出口。
* 不碰那条脏单以外任何单子。
