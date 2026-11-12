# 孤儿绑定收尾（按 binding，不按 task）——方案

用户口径不变：**每一笔资金都要有源头；结算前都要回溯整个流程的资金状态是否对齐。**
这是「对齐」里的最后一类残留：**同一 task 有多条绑定**时，收尾动作只认最新那条，
老的那条永远解不开。

## 1. 问题（线上实测，2026-10-14）

`escrow_bindings` 里有 3 条**孤儿绑定**：`92` / `161` / `171`（各 0.1 USDC），
所在 task 各自还有一条更晚的兄弟绑定，而**兄弟那条已经 `settled`**：

| task | 孤儿绑定 | 兄弟绑定 |
|------|---------|---------|
| `3327dbc2-88ef-4192-bf7a-9897af14c947` | `92` active / 0.1 / 14:08:13 | `94` settled / 0.1 / 0x24aa9d176d74 |
| `06797bd4-4f28-4a38-a9f3-4cb49e535a93` | `161` active / 0.1 / 15:53:01 | `166` settled / 0.1 / 0x076c16e83b33 |
| `4538ae75-5dd0-4943-b53c-55bf73ba9dd7` | `171` active / 0.1 / 16:09:25 | `173` settled / 0.1 / 0xb31b8a24cabd |

现象：`escrow_stranded_reap_noop` **每轮 tick 打 3 条**（6 分钟 60 条），
`acted_on=94/166/173` 而 `binding_id=92/161/171`。

**没有烧 gas**：全程只有 noop warning，没有任何 `finalize/cancel/submit` 交易、
没有 `escrow_stranded_reap_failed`。但那条孤儿绑定在链上仍占着**买方的授权额**，
永远解不开 —— 用户链上有钱、可用额度少一截。

## 2. 根因

`reap_stranded` 拿到的是**具体某一条**绑定（`stranded_bindings()` 逐行挑），
但它落地的动作是 **task 作用域**的：

* `cancel_for_task` / `submit_for_task` / `slash_for_task` 内部都是
  `_find_binding(db, task_id=…)` → `order_by(created_at.desc()).first()`，**只会挑最新那条**。
* 于是一个 task 有多条绑定时，动作落到兄弟绑定上，这一条**一个字节都没动**。

代码里已经有防「撒谎指标」的闸（`acted_on != row.binding_id` → `escrow_stranded_reap_noop`），
2026-10-01 就记过这 3 条 —— 它拦住了假成功，但孤儿本身没被解。

## 3. 方案：给「按 binding 收尾」补一条路

新增 `escrow_settlement.cancel_binding_row(db, *, row, reason=None)`：
**只对传进来的这一条**绑定做「取消」——链上 `allowance_escrow.cancel_binding(binding_id, contract_address)`
本来就支持指定 binding（`open_and_submit_order` 的注释里就叫它「那个以前得手工放的孤儿」）。

链上闸与 `cancel_for_task` 完全同口径（钱一旦有受款人就不许撤）：

| 检查 | 行为 |
|------|------|
| 台账 state ∈ `settled/cancelled/slashed` | 幂等返回，不动 |
| 台账 state ∈ `finalizing/breaching/disputed`（责任状态） | **拒**（409）——窗口已开、钱有主 |
| 台账 state != `active` | 返回现状，不动 |
| `adopt_chain_finalizing`（链上已开窗） | **拒**（409），并把台账拉到链上 |
| 链上已终局（3/4/5） | **对齐台账**（`row.state = mapped`），不撤 |
| 链上状态读不出来 或 认不出来（非 1/6） | **拒**（409），不动钱也不动台账 |
| 链上 `ACTIVE(1)` / `DISPUTED(6)` | 发 `cancelBinding(binding_id)` → `row.state = cancelled` |

**与 task 作用域的关键差别（必须的）**：
取消孤儿绑定**绝不回写 `settlements`**。`_reflect` / `reflect_final` 写的是
「这个 task 的链上事实」那一格，兄弟绑定已经把它写成 `settled`；被孤儿这次
`cancelled` 覆盖掉，操作台就会从「已结算」翻成「已取消」。所以孤儿这一路**只**：

1. `row.state = cancelled`、`row.updated_at`；
2. 释放**这一条**占的子身份额度 `_release_quota(db, row, refunded=True)`
   （`release_profile_credits` 自带 clamp：永远不会放出比 `in_progress` 更多的额度）；
3. `escrow.sync_commits(db, buyer_identity_id)` —— 链上放开的额度让镜像跟上；
4. 记一条 `escrow_orphan_binding_cancelled`（info）。

`settlements`、`voucher` 的 task 级结论一律不动（voucher 的释放是幂等的，
但 settled 的单子本来就不该再走取消那一套）。

## 4. 什么时候才允许自动收孤儿（严格子集）

`reap_stranded` 里插入的位置：先 `_reconcile_from_chain`（链上已终局 → 对齐）、
再 `adopt_chain_finalizing`（链上开窗 → 认了），**然后**才轮到孤儿收尾。允许的条件：

* 绑定台账 `state == active`，且链上 `ACTIVE`；
* 该 task 的结算单 `status` 属于**钱已经有结论**的那几个：
  * `cancelled` / `failed` / `expired` → 没有任何钱要动 → 可收；
  * `settled` → **且** `onchain_status ∈ {settled, slashed, cancelled}`（放款/退款真的落定了）
    → 可收；
* 其余（`in_progress` / `delivered` / `disputed` / `refunded` / `auto_confirmed` /
  `settled` 但链上还没落定）→ **一律不收**，留给正常状态机推进。

理由：只有「这个 task 的钱已经走完了（或根本不用走）」时，另一条绑定的锁定才
100% 是一份不会再被用到的占位。任何「钱还要动」的时刻去撤，都可能把还在等
受款人的额度抽走。

## 5. 开关与灰度

* 新增设置 `escrow_orphan_binding_cancel_enabled: bool = False`（**默认关**）。
* 打开后 `reap_stranded` 才启用第 4 节的自动收尾；失败进 `_backed_off` 退避，
  不会每轮重撞。
* 另给一个只读/可执行的清单脚本 `scripts/escrow_orphan_bindings.py`
  （默认 dry-run 打印清单；`--apply` 才真动），用于**先出清单**与 testnet 演练。

## 6. 落地顺序

1. 本方案（本文）；
2. 代码 + 单测（含：responsibility 拒、链上开窗拒、链上已终局→对齐、不清楚的链上状态拒、
   `settled` 但链上未落定**不**收、`settled` 且已落定**收**、幂等、退避）；
3. CI → 合并 → 部署；
4. **testnet**：种子复现孤儿（一条 task 两条绑定，老 active、新 settled）→ 打开开关
   → 看孤儿被收（state → cancelled、额度回可用、链上 `cancelBinding` 有回执）；
5. 清单给用户确认后，再在 prod 打开开关处置 `92/161/171`。

## 7. 不做

* 不改 `settlements` 的结论、不动 voucher 生命周期、不动阈值；
* 不改 `submit_for_task` / `slash_for_task` 的既有语义（它们仍按 task 找最新绑定 ——
  正常路径本来就是「一个 task 一条活跃绑定」）；
* 不碰主网。

## 8. 本 PR 落地了什么（与方案的对应）

| 方案里的东西 | 落在哪 |
|--------------|--------|
| 按 binding 收尾 | `services/chain/escrow_settlement.py::cancel_binding_row` |
| 「我手上这条是不是孤儿」 | `services/chain/escrow_settlement.py::newest_binding_for_task` |
| 够格自动收的判据（纯函数） | `services/chain/escrow_autosettle.py::_orphan_cancel_allowed` |
| 挂进收尾那一遍 | `services/chain/escrow_autosettle.py::reap_stranded`（在 `_reconcile_from_chain` / `adopt_chain_finalizing` **之后**） |
| 总开关（默认关） | `config/settings.py::escrow_orphan_binding_cancel_enabled` |
| 先出清单 / 人工收 | `scripts/escrow_orphan_bindings.py`（默认 dry-run，`--apply` 才动） |

两处刻意的取舍（都不是随手写的）：

1. **不用 `adopt_chain_finalizing` 去看链上有没有开窗**。它会 `_reflect`，把这一条的
   链上事实写进 `settlements` —— 而那一格已经被兄弟绑定写成 `settled`。所以
   `cancel_binding_row` 自己读一次 `chain_snapshot`：链上 `FINALIZING(2)` 就只**拒**
   （409），台账和结算单一个字节都不改。
2. **不动档案额度**（`profile_capacity`）。正常取消/结算那一环的档案额度释放是按
   **task** 走的（`_release_profile_credits_if_bound`），孤儿再放一次会凭空多出可用额度。
   孤儿这一路只做链上 `cancelBinding` + `row.state = cancelled` + `escrow.sync_commits(buyer)`
   —— 额度以**链为准**，镜像跟着走。

**测试**：`tests/unit/test_escrow_orphan_binding.py`（8 例：链上开窗拒 / 台账责任态拒 /
已终局幂等 / 链上终局→对齐 / 认不出的链上态拒 / 主路径按自己的 id 收 / RPC 读不到照发 /
链上拒→409，且每一例都钉住 `settlements.onchain_status` 没被动过）
+ `tests/unit/test_escrow_stranded_reap.py`（5 例：判据表 + 孤儿被按 binding 收 +
  钱还要动时不收 + 默认关 + 最新那条仍走老路）。相邻 12 个文件 **197 passed**。
