# 自动结算 tick 的链上读成本 + 台账自愈分频（2026-10-14）

承接上一轮（`2026-10-13-auth-failure-noise-and-self-heal.md`）之后要做的性能那一项。
本轮只做一件事：**把自动结算 tick 里最贵的一段链上读从「每 15 秒一轮」摊薄到更慢的节拍**。
不动状态机、不动资金路径、不动阈值。

## 1. 结论先说

自动结算（`services/chain/escrow_autosettle.run_forever`）一轮 tick 实测 **5.7~9.1 秒**，其中
**约 90% 花在链上读**；而主 tick 的间隔只设了 15 秒。结果就是循环被自己的活儿拖慢：相邻两轮
的间隔实测 **21 秒**，不是 15 秒。

最贵的一段是**台账自愈** `reconcile_all_capacity_mirrors`（2.9~6.4s）。它每一轮都对**每个持有
活承诺的身份**读一次链上 ERC-20 授权额（`backing_report` 里那次同步 `eth_call`）。这一步是
**兜底**，不是主路径 —— 正常交易在请求路径上已经各自对过一次账 —— 所以它可以从每 15 秒
一轮改成更慢的节拍。这就是本轮的改动。

## 2. 实测证据

线上 `karma-api`（库 `karma`）的 `escrow_autosettle_tick_slow` 日志（这条 warning 在任一步
≥1.0s 时才打）：

```
steps=[('bind_due', 0.002), ('settle_due', 0.002), ('breach_due', 0.001),
       ('reconcile_from_chain', 1.476), ('auto_confirm_expired_settlements', 0.002),
       ('reap_stranded', 1.269), ('align_disputed_settlements', 0.001),
       ('voucher_reaper.expire_due', 0.001), ('voucher_reaper.restore_leaked', 0.003),
       ('reconcile_capacity_mirrors', 6.356), ('commit', 0.001)]
total_s=9.114
```

四条相邻样本的 `total_s` 是 `9.114 / 6.539 / 5.704 / 5.778`，时间戳 `16:35:26 / 16:35:47 /
16:36:08 / 16:36:29` —— **间隔 21 秒**（15s 节拍 + ~6s 干活）。

链上读这三个地方，其它步骤全部 ≈ 0.01s、可以忽略：

| 步骤 | 每轮耗时 | 为什么贵 |
|------|---------|---------|
| `reconcile_capacity_mirrors` | 2.9~6.4s | 每个活身份一次 `eth_call` 读 ERC-20 授权额；线上 7 个身份 |
| `reconcile_from_chain` | ~1.5s | `_onchain_state()` 每行一次 `eth_call`；批量 5 行 |
| `reap_stranded` | ~1.3s | 3 条 stranded 绑定，每行一次状态读 |

数据面（同时点实测）：

```
allowance_commits       : 7 个身份（36 open / 3 revoked）
escrow_bindings         : active 65 / settled 211 / cancelled 50 / slashed 45 / disputed 4
```

## 3. 根因

台账自愈的设计口径是「每轮把所有身份的链上授权额重读一遍」。它是一个 **O(身份数)** 的链调用，
却挂在 **15 秒**的主 tick 上。身份数一多，循环就永远追不上自己的间隔：

```
每轮成本 ≈ 身份数 × 0.5~1s
身份数 = 100  →  每轮 50~100s  >>  15s 间隔
```

而它**只是兜底**（代码里也是这么写的）：

* 用户锁仓 / 撤仓：`api/routes/escrow.py` 在请求里直接调 `reconcile_capacity_mirror`；
* 结算放款：`_record_final()` 里对买卖双方各调一次 `sync_commits`。

也就是说，链上真变了的时候，账**在请求路径上**就已经对上了；这一遍循环只是兜「进程重启 /
RPC 抖动 / 人工改库 / 别人推进了链上状态」这类没人在线的场景。这类场景不需要 15 秒级的
及时性。

## 4. 改动

| 文件 | 改动 |
|------|------|
| `config/settings.py` | 新增 `escrow_autosettle_mirror_interval_seconds: int = 60`（`<= 0` 退回旧行为：每轮都跑） |
| `services/chain/escrow_autosettle.py` | 新增纯函数 `_capacity_mirror_due()`；`run_forever` 里只有到点才跑自愈那一步 |

**没有碰**：链上调用的顺序与内容、结算状态机、资金路径、任何阈值、其它步骤的节拍（便宜的
步骤照常每 15 秒跑）。

安全口径说明（这一段是这次改动的「为什么可以慢」）：

* 自愈慢下来只会让「账上先于链上」的窗口变长（最多 60s），**不会**让任何一笔钱动或不动的
  判断改变 —— 判断依据始终是链上事实，读链那一步一次都没省；
* 即便账上的可用额度一时偏大，链上授权额才是硬约束，超额的下单在 `backfill/bind` 那一步
  会被链拒掉，不会划走一分钱；
* 反过来「链上还有钱、账上显示 0 可用」这种卡用户的情况，仍然由请求路径即时纠正。

## 5. 测试

新增 `tests/unit/test_escrow_autosettle_mirror_cadence.py`（7 例）：

* 纯函数边界：首轮必跑 / 未到点跳过 / 到点跑 / `<=0` 回旧行为；
* 默认节拍必须慢于主 tick（直接从 `Settings.model_fields` 读默认值，不受环境变量影响）；
* 接线（AST）：`reconcile_all_capacity_mirrors` 必须挂在 `_capacity_mirror_due` 的 `if` 里，
  不许在 `while` 循环里裸跑。

回归：`test_escrow_autosettle / test_autosettle_short_transactions / test_escrow_stranded_reap /
test_escrow_breach_slash / test_escrow_dispute_freeze_release / test_capacity_mirror_conservation /
test_allowance_backing / test_allowance_escrow` 共 **132 例全绿**；`tests/unit` 全量见 PR。

## 6. 这一轮**没有**做（都在资金路径上，先出方案等拍板）

1. **`reconcile_from_chain` 的窗口饥饿**：它 `order_by(created_at).limit(5)`，而线上有 **65 条
   `active` 绑定** —— 于是它每一轮探的都是**最老的那 5 条**（`#5/#29/#30/#31/#32`，全是 09-30
   之前的试单），第 6 条往后**从来没有被这个兜底探过**。这跟 `stranded_bindings` 那个
   「窗口被老行占死」是同一个坑（那个已经修过，见该函数 docstring 里 2026-10-01 的记录），
   但这一处没修。修法（加轮转 / 按 `updated_at` 取最久没探的）动的是资金状态机的对齐逻辑，
   要先给方案。
2. **陈旧数据清理**：65 条 `active`（多为 2026-09-30 / 10-01 的 `in_progress/bound` 试单）、
   3 条 stranded（`#92/#161/#171`，结算已 `settled`、绑定还 `active`）、以及 1 条自成交脏单。
   清掉之后上面的两段链上读会直接少一大截 —— 但清库要拍板，不在这一轮。
3. **自成交脏单**：settlement `97f0dc0e-…`（task `0d676417-…`，1 USDC）买卖双方是**同一把钱包**
   `0x3295c96a2993c366b3db27b6ac81f85801d75f51`，合约 `SameOwner()` 直接拒，永远 bind 不上。
   上一轮的 F4 长退避已经生效：最近 4000 行日志里只有 **1 条** `escrow_autosettle_bind_failed`
   （`permanent=True retry_in_seconds=3600`），不再是每 ~2 分钟白烧一笔 operator gas。
   作废还是换独立钱包，等拍板。
