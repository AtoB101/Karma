# 资金溯源与对齐（2026-10-14）

用户口径：**每一笔资金都要有源头；结算前都要回溯整个流程的资金状态是否对齐 ——
这是保障资金安全的核心。**

本轮把它做成一个可复用的检查器 `services/chain/funds_trace.py`，挂在**动钱之前**
的两个位置。不读链、不改状态机分支、不改任何阈值。

## 1. 结论先说

* 新增 `trace_task_funds()`：把一笔钱的链路整条读出来 ——
  **结算单 → 链上绑定 → 买方/卖方账单 → 双方钱包 → 托管合约 → 金额 → 链上状态**，
  每一环都验证「它指着的是不是同一笔钱」。
* **拒绝**（409，链上一笔都不发）只用在「钱会划错地方 / 根本划不动」上；
  金额漂移（部分结算合法）之类只记 warning —— 拦错了比不拦更伤用户。
* 挂点：

| 位置 | 行为 | 为什么在这儿 |
|------|------|-------------|
| `assert_release_verified`（PAY / SLASH） | **拒** | 开结算窗 / 罚没之前，有人等着，报得出人话 |
| `assert_release_preflight` | **拒** | 推状态机**之前**先查，避免「状态推上去又退回来」留下假拒绝 |
| `escrow_autosettle.settle_due` | **只观察**（warning + 安全事件） | 窗口已开、钱迟早会动：这里负责每一轮都留痕，不负责拦人 |

## 2. 为什么只读台账、不读链

请求路径上多一次 `eth_call` 就是几十个用户的等待时间（2026-10-14 实测：一轮
autosettle tick 90% 花在链上读，见 `2026-10-14-autosettle-tick-cost-and-mirror-cadence.md`）。

链上事实由**动钱那一刻**的闸来对，而且本来就在那儿：

* `escrow_autosettle.settle_due` 在发 `finalizeSettlement` 之前先 `_onchain_state`；
* `submit_for_task` 先 `adopt_chain_finalizing`（链上已开窗就别再发一次）。

溯源闸补的是**台账这一侧**：钱从哪个身份、哪张账单、哪台合约来，是不是同一个人的钱。
两边各管一段，合起来才是「整条链路对得上」。

## 3. 判什么（对不上就拒）

| # | 环节 | 对不上的含义 |
|---|------|-------------|
| 1 | 有没有结算记录 | 资金没有源头 |
| 2 | 有没有链上绑定台账 | 钱从哪来、要划给谁都没记录 |
| 3 | 结算单 ↔ 绑定的链上指认（`onchain_binding_id` / 两张账单 id） | 两边指的不是同一条绑定 |
| 4 | 绑定的账单能不能在**当事人**名下找到 | 受款方对不上 —— 钱可能划给别人 |
| 5 | 双方钱包是不是同一把 | 链上 `SameOwner()` 必定 revert（与自成交硬禁同一口径） |
| 6 | 绑定在不在**当前**托管合约上 | 旧合约上链上划不动，开窗也划不走 |
| 7 | 绑定金额 > 托管金额 | 划的比托管的还多 |
| 8 | 链上已落定（`settled`/`slashed`）而 `onchain_status` 没跟上 | 钱动了账没动 |

只记 warning（不拦）：绑定金额 < 托管金额（部分结算/关窗后重绑）、状态机审计流水缺失、
结算单与绑定的合约字段字面不一致、账单上没有可用钱包。

**口径分清楚**：`settlements.status` 是**账上的验证结论**（该不该结），
`settlements.onchain_status` / `escrow_bindings.state` 才是**链上事实**。
「`status=settled` 而 binding 还 `active`」是**正常**的（窗口刚开、钱还没划）；
只有「链上钱已经划走、账上却没跟上」才算对不上。

## 4. 留痕

* 通过：`escrow_funds_trace_ok`（info），带上「资金来源 / 受款方 / 链上绑定 / 金额」一句话；
* 对不上：`escrow_funds_trace_mismatch`（warning）+ 安全事件
  `SecurityMonitoringEventType.FUNDS_TRACE_MISMATCH`（`stage` = `pay` / `slashed` / `preflight` /
  `autosettle_finalize`）；
* tick 里的观察者任何异常都吞掉：**观察者不许把整轮结算拖垮**。

## 5. 测试

`tests/unit/test_escrow_settlement.py` 新增 12 例：

* 健康单子：整条链路走通，`buyer/seller` 身份、账单 id、钱包、链上 id、金额全对得上；
* 没有绑定台账 → 拒（且不 throw 到链上：`calls["submit"] == []`）；
* 同一把钱包（绑定台账是既成事实）→ 拒；
* 绑定指的账单不在当事人名下 → 拒；
* 链上已 `settled` 而账上还 `finalizing` → 拒；
* 旧合约上的绑定 → 拒；
* 绑定金额 > 托管金额 → 拒；
* 绑定金额 < 托管金额 → 只 warning，放行；
* 对不上会留下一条 `FUNDS_TRACE_MISMATCH`；
* 链路对不上时**取消仍然放行**（取消是出路，不能被溯源闸挡住）；
* 结算 tick 的观察者：对不上 → 安全事件，且**不发交易、不写库**；健康单子 → 不吵。

相关回归：`test_escrow_autosettle.py` / `test_autosettle_short_transactions.py` /
`test_escrow_autosettle_mirror_cadence.py` / `test_self_dealing_ban.py` 全绿。

## 6. 这一步之后，剩下的

* **存量的 65 条 `active` + 3 条 stranded**：先出逐条清单给用户确认，再 testnet → prod 处置。
* **自成交脏单** `97f0dc0e-…` 的清退（走 `cancel_for_task`）。
* `reconcile_from_chain` 的窗口饥饿（A 项）。

**未碰主网；未改阈值；未改资金路径的判定顺序。**