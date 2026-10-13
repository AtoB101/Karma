# 自成交硬禁（2026-10-14）

用户拍板：**绝对禁止自刷单**。本轮把「买方和卖方是同一个人」从「事后扣分」升级成
**接单那一刻就 409、一笔链上交易都不发**，并把判定收敛成一份实现（四条口径）。

## 1. 结论先说

* 线上那条自成交单（结算 `97f0dc0e-4748-41fe-8ad8-fe71e195b832`）的成因已定位：
  **接单走的是延迟绑定** `bind_for_task_deferred`，那条路上原先**没有**自成交闸 ——
  单子被「接受」、买方额度被占住，之后 autosettle 每个退避周期拿一笔 operator gas
  去撞链上的 `SameOwner()`。
* 本轮：判定（`assert_parties_not_self_dealing`）在**两个** bind 入口都调，
  MiniApp 结算链路再各加一道，状态机 `mark_settled` 加最内层。
* 脏数据不该产生，比事后收拾便宜得多 —— 这条从现在起**不产生**。

## 2. 链上/链下的形状

链上 `openOrder` 对 `buyerBill.owner == sellerBill.owner` 直接 revert `SameOwner()`。
合约只比**钱包地址**，而且要到 `bind` 那一笔才 revert；`SameOwner` 不问身份 id、
也不问「两个子身份背后是不是同一个人」。

线上那条单：

| 事实 | 值 |
|------|-----|
| settlement | `97f0dc0e-4748-41fe-8ad8-fe71e195b832`（1 USDC） |
| task | `0d676417-0de2-4bdb-b286-ca4e2cc51fd1` |
| 状态 | `in_progress` / `onchain_status=pending_bind` |
| 买方 | `kid_t23b_8d65f4e9e4a9` |
| 卖方 | `agent-3610b5c97bb5`（owner `kid_2b8b6dfca420c96a1409b8fd`） |
| 两边账单钱包 | `0x3295c96a2993c366b3db27b6ac81f85801d75f51`（**同一把**） |
| 链上 | `SameOwner()` revert，`escrow_bindings` **无行**，钱一步没动 |

F4 长退避已生效：最近 4000 行日志里只有 **1** 条 `escrow_autosettle_bind_failed`
（`permanent=True retry_in_seconds=3600`）—— 退避是对的，但**它本来就不该被接受**。

## 3. 根因

`bind_for_task`（同步路径）本来有两道内联闸：同主身份、比账单钱包
（`_assert_distinct_bill_wallets`）。接单实际走的是 `bind_for_task_deferred`
（`api/routes/settlement.py:1384`，只落 `pending_bind` 标记，链上回执由 autosettle 补），
**那条路上两道都没有**。于是：

```
接单 →  无自成交检查  →  写 pending_bind（占住买方额度）
     → autosettle 补绑 → 链上 SameOwner() revert → 长退避，反复烧 operator gas
```

只比身份 id 也不够：脏单里买方是 `kid_…`、卖方是 `agent-…`，**两个 id**，
可比的钱包是同一把。

## 4. 改动

判定收敛成一份实现，四条口径任一命中就 409 + 留痕 + 一笔链上交易都不发：

1. **同一个 id** —— 自己买自己的单；
2. **同一个主身份** —— 同一个人开出来的两个子身份（链上看钱包看不出来，去
   `services.identity_gateway.store.resolve_main_identity` 回溯，agent 走
   `owner_identity_id`）；
3. **同一把钱包** —— 合约 `bind` 真正比的那个（链上账单 `allowance_commits.wallet_address`）；
4. **库里认领过的钱包** —— `identity_profiles` / `identity_role_profiles.bound_wallet_address`。

任一来源读不到都只跳过、不拦单：判自成交的代价不能是「读不到库就谁也别做单」。

改动落点：

| 文件 | 改了什么 |
|------|---------|
| `services/chain/escrow_settlement.py` | 新增 `assert_parties_not_self_dealing`（4 口径）+ `_norm_wallet` / `_party_owner` / `_party_main` / `_party_wallets`；删掉旧的 `_assert_distinct_bill_wallets`；`bind_for_task` 两道内联闸改为调两次共享函数（挑账单**前**一次、挑账单**后**带账单再一次）；`bind_for_task_deferred` **在接单那一刻**调一次 |
| `api/routes/telegram_miniapp_commerce.py` | 新增 `_refuse_self_dealing(order)`，插在 `/risk/assess`、`/verification/runs`、`/settlement/finalize` 三处 —— 原来只把 `self_deal` 记进 `public_proof`，结算照样放行，和链上直接打架 |
| `services/miniapp_commerce/orders.py` | `mark_settled` 纵深防御：买卖钱包相同（两者都非空时）→ `ValueError`，结算状态不落 |
| `services/security_monitoring.py` | 新增事件类型 `SELF_DEAL_REFUSED = "self_deal_refused"` |
| `scripts/attack_simulation.py` | 11.1 自成交用例从 HIGH/VULNERABLE 升为 **CRITICAL 且要求必须 BLOCKED** |

### 为什么判在「接单那一刻」

判在接单那一刻，脏数据（`pending_bind` + 占住的额度）**根本不会落库**；判在 autosettle
里只是「事后打扫」，额度已经被占了、还要烧一笔 gas 才知道链上不收。

## 5. 纵深防御（三层）与分工

* **契约层**：`api/routes/contracts.py` 的 assign 一直拦 `worker_agent_id == client_agent_id`。
* **资金层**：`assert_parties_not_self_dealing`（本轮，4 口径，两个 bind 入口）。
* **状态机层**：MiniApp `_refuse_self_dealing` + `mark_settled`。

与 `services/wash_trade.py` 的分工：那边管「信誉分不发 / GMV 不记」，这里管
「单子根本不成立」。两条都要有 —— 只扣分不拦单，链上那笔照样白烧。

## 6. 测试

新增 `tests/unit/test_self_dealing_ban.py`（6 例）：

* 口径 1：同一个 id → 409；
* 口径 2：同一个主身份（主身份 + 子身份）→ 409；
* 口径 3：**延迟绑定** `bind_for_task_deferred` 同一把钱包 → 409，且
  **结算单一个字都没写**（`settlement_mode != escrow_allowance`、
  `onchain_status is None`）、**没有 binding 行**、**留了一条
  `SELF_DEAL_REFUSED` 安全事件**；
* 两个不同的人 + 两把不同钱包 → 放行（`pending_bind`）；
* `mark_settled` 同钱包 → `ValueError`，状态停在 `VERIFIED`；
* MiniApp `_refuse_self_dealing` → HTTP 409。

相邻回归：`test_escrow_settlement.py` + `test_telegram_miniapp_mvp.py` +
`test_wash_trade.py` + `test_self_dealing_ban.py` → **68 passed**；
`test_adversarial_whole_project.py` + `test_adversarial_p1_p8.py` +
`test_escrow_breach_slash.py` → **72 passed**。

## 7. 还没做（等拍板 / 下一步）

* 线上那条脏单 `97f0dc0e-…` 的**清退**：走 `escrow_settlement.cancel_for_task`
  把买方额度放回去（先在 testnet 演练，再 prod）。存量处置属资金状态机动作，
  单独立项，不在本轮代码范围内。
* 65 条陈旧 `active` 绑定 + 3 条 stranded 的逐条清单与处置（A 项）。

**未碰主网；未改阈值；未改资金路径的判定顺序。**