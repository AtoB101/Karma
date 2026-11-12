# 台账自愈的窗口饥饿（2026-10-14）

`escrow_autosettle.reconcile_from_chain` 是状态机对齐的**兜底那一遍**：链上早已落定
（别人推了 `finalizeSettlement`、或者我们没等到回执），就把台账补上，让卡在半路的
绑定走到终局、把买方的授权额放回去。

它每一轮只取 `escrow_autosettle_batch`（默认 5）条。取数原本是
`order_by(created_at).limit(5)` —— **最老的那 5 条被反复问，第 6 条起永远轮不到。**

## 1. 为什么这是资金安全问题（不是「慢」）

这不是性能问题，是**覆盖不到**：

* 线上实测（2026-10-14，`karma-api`）：`escrow_bindings` 共 375 行，其中
  `active` **65** 条、`settled` 211、`cancelled` 50、`slashed` 45、`disputed` 4。
* 每轮 tick 只问 `created_at` 最老的 5 条；其余 60 条**一次都没被问过**。
* 后果：链上早就 `CANCELLED` / `SETTLED` 的绑定会永远停在 `active`，
  它占着的子身份额度（`reserved`）永远不会释放 —— 用户看着链上还有钱，
  可用额度却是 0，一单也开不出来。用户口径里「每一条都要对齐」在这里被打破了。

## 2. 修法（只改取数，不改判定）

| 改动 | 位置 | 说明 |
|------|------|------|
| 新增列 `last_probed_at` | `db/models/orm.py` `EscrowBindingModel` | 「上一次来问过链」的时刻。NULL = 还没问过 |
| 新增索引 | 同上 `__table_args__` | `(state, last_probed_at)` —— 取数就是 `state IN (...) AND (last_probed_at IS NULL OR < cutoff) ORDER BY last_probed_at NULLS FIRST, created_at` |
| 新增设置 | `config/settings.py` | `escrow_reconcile_probe_interval_seconds = 300`（`<= 0` 退回旧行为） |
| 取数改成「最久没问过的先问」 | `services/chain/escrow_autosettle.py` | 见下 |
| 迁移 | `db/migrations/versions/0066_escrow_binding_last_probed_at.py` | `ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`，`down_revision = 0065` |

新的取数（`reconcile_from_chain`）：

1. 加了 `_reconcile_probe_cutoff()`（纯函数）：`now - interval`；`interval <= 0` → `None`
   （不限，旧行为）。
2. `where(last_probed_at IS NULL OR last_probed_at < cutoff)`：刚问过的不重复问。
3. `order_by(last_probed_at ASC NULLS FIRST, created_at)`：从没问过的排最前，
   其次是最久没问过的。
4. **先盖时间戳再干活**：`row.last_probed_at = probed_at` 在调用链之前就写，
   并且 `await db.flush()` —— 哪怕某一条问链抛异常（RPC 抖动），它这一轮也让位给下一条，
   否则一条坏绑定会永远占着窗口里的一格。

于是每一轮 tick 的工作量**有上界**（最多 `batch` 次链上读），而全体绑定在一轮一轮里
被**逐个覆盖**：65 条 / 每轮 5 条 ≈ 13 轮（约 195 秒）全部盖过一遍，之后按 300 秒的
间隔滚动复查。稳态下每 15 秒 tick 平均只问 `65 × 15 / 300 ≈ 3.3` 条。

**判定分支一字未改**：链上落定才改台账（`_CHAIN_DONE`），「链上读不到」仍然
`return False`（不改台账、不写库）。这一遍依旧只做对账，不动一分钱。

## 3. 测试

`tests/unit/test_escrow_autosettle.py` 新增 5 例：

* `_reconcile_probe_cutoff` 是纯函数：`300` → `now-300`；`0` / 负数 → `None`；
* **窗口饥饿**：7 条绑定、每轮取 5 —— 两轮下来 7 条**全部**问到，
  且第二轮只问上一轮没问过的那 2 条（刚问过的让位）；
* 刚问过的（`last_probed_at` 在间隔内）让位给没问过的；
* 问链抛异常**也要盖章**（坏绑定不许一直占窗口）；
* `interval <= 0` 也不许饿死：每轮 `batch=1`，三轮回下来把三条都盖到。

回归（相邻 7 个文件）：`test_escrow_autosettle.py` / `test_escrow_settlement.py` /
`test_autosettle_short_transactions.py` / `test_escrow_autosettle_mirror_cadence.py` /
`test_escrow_stranded_reap.py` / `test_escrow_binding_id_collision.py` /
`test_escrow_breach_slash.py` —— **124 passed**。

## 4. 部署注意

`db/session.py::_migrate_missing_columns` 只补**列**、不建**索引**。滚到 VPS 时
必须真的跑过 alembic（部署流程 `deploy/karma` 的 `cmd_migrate` 会跑），
上线后要确认 `0066` 已执行、`ix_escrow_bindings_state_probed` 存在、且
`last_probed_at` 开始被逐轮盖上。

## 5. 这一步之后，剩下的

* 存量的 65 条 `active` 逐条处置（先出清单给用户确认，testnet → prod）。
* 自成交脏单 `97f0dc0e-…` 的清退。
* 离站备份落点 / 主网（用户已定：测试网做到商业级再谈主网）。

**未碰主网；未改阈值；未改资金路径的判定顺序。**
