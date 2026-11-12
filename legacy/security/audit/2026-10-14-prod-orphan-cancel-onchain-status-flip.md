# 2026-10-14 清场批次：testnet 演练残渣 + prod 三条孤儿绑定

执行人：YMZAI <haozi8868@qq.com>
范围：① testnet 场地（`karma_testnet`）演练残渣；② prod 部署（`karma`）三条孤儿绑定。
原则：**先只读核对完再动手**；每一处删除/改动都带主键、带删前后计数、带链上交易哈希。

---

## 一、核对（只读，全部表）

扫描方式：对 `public` schema 下每张表的每个 text/uuid/json 列做
`ILIKE '%drill%' OR ILIKE '%a2a-%'`，再逐表 dump 命中行。

结论：**testnet 场地库本身就是一个纯演练场地** —— 20 张有数据的表，全部行都属于本次
演练（`a2a-buyer` / `a2a-seller`）或 Phase1 seed。除下面第四条列出的 4 行之外，
没有任何一行是「无主的残渣」。

命中清单（`drill` 关键字）：

| 表 | 列 | 行数 |
| --- | --- | --- |
| `escrow_bindings` | `task_id` | 2 |
| `identity_profiles` | `display_id` | 2 |
| `settlements` | `settlement_id` / `task_id` | 1 / 1 |
| `task_contracts` | `task_id` / `title` / `description` / `contract_hash` | 1 / 1 / 1 / 1 |

## 二、链上事实（改之前）

合约 `0x2C9911F58CfDb5f097926c4aC104108f4f49743b`（Sepolia, chain 11155111）：

* `binding 1` state=3（SETTLED）、`binding 2` state=5（CANCELLED）、
  `binding 3` state=**2（FINALIZING）** ← 还占着买方 4 mUSDC + 卖方 1.2 mUSDC 的预留。
* `bill 1`（买方）amount 50 / reserved 4 / spent 10；`bill 2`（卖方）amount 5 / reserved 1.2。

`FINALIZING` 的唯一出口只有 `finalizeSettlement`（`cancelBinding` 只认 ACTIVE，
`markDisputed` 也只认 ACTIVE）—— 合约层面没有「退回去」这条路。

## 三、清理动作

### 3.1 testnet：先把链上那笔悬着的收尾

```
finalize_settlement(binding_id=3)
  -> tx 0x68fe2e3ff926361412ff678de75dfa257e325893b4cb7eb16073545c20dc4b07
  -> binding 3: 2（FINALIZING）-> 3（SETTLED），closedAt 落定
  -> bill 1 reserved 4 -> 0、spent 10 -> 14；bill 2 reserved 1.2 -> 0
  -> 买方钱包 40 -> 36、卖方钱包 15 -> 19（两边都是演练自己的钱包）
```

### 3.2 testnet：删演练夹具（一个事务，带计数断言）

删除前先跑 FK 检查：引用 `task_contracts` 的 6 张表（`execution_receipts` /
`progress_receipts` / `evidence_bundles` / `settlements` / `arbitration_cases` /
`verification_results`）对 `drill-orphan-t2` **全部为 0 行**；`trade_orders` /
`vouchers` / `voucher_events` / `settlement_transition_audits` / `responsibility_edges`
同样 0 命中。

事务内先断言 `escrow_bindings=2 / settlements=1 / task_contracts=1`，不符即
`RAISE EXCEPTION` 回滚，然后删：

| 表 | 主键 | 结果 |
| --- | --- | --- |
| `escrow_bindings` | `2`, `3`（task `drill-orphan-t2`） | DELETE 2 |
| `settlements` | `drill-orphan-s1` | DELETE 1 |
| `task_contracts` | `drill-orphan-t2` | DELETE 1 |

删后复扫：`drill` 关键字只剩 `identity_profiles.display_id`
（`KARMA-DRILL-A2A-BUYE` / `KARMA-DRILL-A2A-SELL`），那两行是场地的种子身份，
**保留**。

### 3.3 testnet：台账镜像回链上真值

`escrow.sync_commits` + `escrow.reconcile_capacity_mirror`：

* `allowance_commits 1`（买方）50 / spent 14 / reserved 0 / credited 36
* `allowance_commits 2`（卖方）5 / spent 0 / reserved 0 / credited 5
* `capacity` buyer 486 / available 476 / reserved 10（基线 500 − 已结算 10 − 本次收尾 4）

### 3.4 prod：三条孤儿绑定

清单（dry-run 与 apply 两次一致）：

| binding | task | 金额 | 结算 status/onchain | 最新绑定 |
| --- | --- | --- | --- | --- |
| 92 | 3327dbc2-88ef-4192-bf7a-9897af14c947 | 0.1 | settled / settled | 94 |
| 161 | 06797bd4-4f28-4a38-a9f3-4cb49e535a93 | 0.1 | settled / settled | 166 |
| 171 | 4538ae75-5dd0-4943-b53c-55bf73ba9dd7 | 0.1 | settled / settled | 173 |

链上确认三条都是 state=1（ACTIVE），且都在**当前** prod 合约
`0x65eb82058F4ea707B1a0aFb2A5872eb95076b6F2` 上（prod escrow 也是 Sepolia）。

`python3 /app/scripts/escrow_orphan_bindings.py --apply`：

```
92  -> cancelled    161 -> cancelled    171 -> cancelled     成功 3 / 失败 0
链上 92 / 161 / 171 全部 state 5（CANCELLED）
operator gas 1.595821088570969798 -> 1.595820550335816866 ETH（约 5.4e-7 ETH）
再跑 dry-run：(空)
```

## 四、这一轮抓到的真问题：孤儿收尾把「已结算」翻成「已取消」

**现象**：prod `settlements` 里出现一行 `status='settled'` 但
`onchain_status='cancelled'` —— `fb155a19-af06-4363-954b-7f13471bbdf6`
（task `4538ae75`，`updated_at=2026-10-14 03:11:06`）。收工前是 `settled`。

**机制**：按 binding 收尾 171 的同一时刻，正好有一轮 `reap_stranded` 在跑
（日志 `escrow_autosettle_tick_slow reap_stranded=9.823s total_s=10.908`，紧接着
`escrow_stranded_reconciled_from_chain binding_id=171`）。那条路：
`_reconcile_from_chain` → `_record_final(state=cancelled)` → `reflect_final` →
`_reflect(onchain_status='cancelled')`，而 `_reflect` 是**按 task_id** 找结算单的
—— 一个 task 的结算单是两条绑定共用的，于是孤儿这条的「链上被撤」把兄弟绑定写好的
「已结算」盖掉了。同一行的 `tx_hash` 还指着真正划钱的
`0xb31b8a24cabd56dd3c7de53638e83ce34b04bab254230e53f8cd876ce1be1171`
（= binding 173 的 `finalize_tx_hash`），`onchain_binding_id` 也被改指到了孤儿 171。

对照：92 / 161 没被留下这个痕迹，是因为它们各自的那一轮对账随后又被
「以最新绑定为准」的对账纠回了 `settled` —— 换句话说，这行的正确值本来会自我修复，
只是 171 这行没等到。

**数据修复**（带断言、单行）：

```sql
UPDATE settlements SET onchain_status='settled', onchain_binding_id='173', updated_at=now()
 WHERE settlement_id='fb155a19-af06-4363-954b-7f13471bbdf6';
```

修复前断言 `status='settled'` 且当前值恰为 `cancelled|171`，否则回滚。
修完全库 `status='settled' AND onchain_status='cancelled'` 计数 = 0。

**代码修复**：`services/chain/escrow_settlement.py::_reflect` 加一道「只升不降」闸 ——
结算单的 `onchain_status` 已经是 `settled` / `slashed`（= `_TERMINAL_MONEY_STATUS`）时，
任何不同的新值一律拒写并打 `escrow_settlement_refused_onchain_downgrade` warning；
`onchain_binding_id` / `tx_hash` / `contract_address` 那些字段这一轮也一并不写（闸放在
所有写字段之前）。绑定行自己的收尾（`escrow_bindings.state`）不受影响，照旧往前走。

## 五、测试

新增 `tests/unit/test_settlement_onchain_status_never_downgrades.py`（4 条）+ 
`tests/unit/test_escrow_stranded_reap.py::test_a_cancelled_orphan_never_downgrades_a_settled_settlement`（1 条）。

变异验证：把闸的门条件改成 `if False and ...` 后重跑，恰好这 3 条断言失败、
「向前推进」（finalizing → settled）与「同一终值重复回写」两条照常通过 —— 说明测试
真的钉在这次的 bug 上，而不是顺手绿。

回归面：11 个 escrow 相关单测文件 **192 passed**。

## 六、仍未落地（如实）

* prod 4 代合约里的历史绑定（`0x32b3a608…` / `0x3fe45f40…` / `0x6D752dCA…`）
  仍有 `active` 残留的老数据，本轮只收当前合约上的孤儿。
* `settlements` 里还有 2 行 `status='cancelled'` / `onchain_status='settled'`
  的历史脏行（与本轮无关，未动）。
* 仲裁被推翻只罚庭、货款不回滚（`settlement_reversal="not_performed"`），仍未做。
* 业务状态机那条腿（`settlements.status → settled`）在 testnet 仍未走通：
  需要「交付验证 VERIFIED + 至少一条成功执行回执」。
