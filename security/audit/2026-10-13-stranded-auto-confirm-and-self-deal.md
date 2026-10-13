# 安全审计 —— 25 张卡死的「自动放款」单 + 自成交绑定（2026-10-13，第二轮）

Range: 测试网（`https://karma-network.ai` / VPS `47.82.74.68`，Sepolia `TESTNET_CHAIN_ID=11155111`）。
**主网未动**。承接 `security/audit/2026-10-13-auto-brake-self-hardening.md` §4 里
「19 张卡住的单子（现在 25 张）没有修 —— 那是另一个问题」这一条。

**结论先行**：那 25 张单卡住的根因**不是** Sepolia RPC、不是 operator 没 gas、也不是
escrow binding 状态 —— 是**这一单一条成功执行回执都没有**，而自动放款的代码把业务状态
先推到 `settled` 再动链，被放款门禁挡下后退回 `auto_confirmed`；这个状态**没有任何自动流程
会再推进它**，于是买方的授权额被永久占住。修了三件事，另加两处加固。

## 1. 现象与真实数据（线上原始证据）

```
 select status, onchain_status, count(*), sum(escrow_amount) from settlements group by 1,2;
   auto_confirmed | bound | 25 | 2.5      -- 全部 0.1 USDC / 2026-09-30 14:24–14:55 建
   in_progress    | bound | 61 | 12.8
```

25 张单对应的 `escrow_bindings`（binding_id 108–137，全部 `state='active'`）：

```
 binding_id | state  | amount_usdc | stake_usdc | bind_tx_hash | submit_tx_hash
 108        | active | 0.1         | 0.03       | 0xfb0a3b96…  | (null)
 …（25 张同样：bind 成功、submit 从未成功）
```

`settlement_transition_audits` 里它们只被尝试过**两次**（不是每轮重试）：

```
 2026-10-03 14:00 | delivered → auto_confirmed | t | store | 6
 2026-10-03 14:00 | auto_confirmed → settled   | t | store | 6
 2026-10-03 14:00 | auto_confirmed → settled   | f | chain | 6
 2026-10-13 02:00 | delivered → auto_confirmed | t | store | 19
 2026-10-13 02:00 | auto_confirmed → settled   | t | store | 19
 2026-10-13 02:00 | auto_confirmed → settled   | f | chain | 19   ← 就是这批把自动刹车点着了
```

## 2. 根因（代码级）

失败链（`api/routes/settlement.py`）：

1. `_auto_confirm_release` 先 `DELIVERED → AUTO_CONFIRMED`（落库），再 `AUTO_CONFIRMED → SETTLED`
   （`_apply_transition` **先 commit 落库、再动链**，2026-10-01 死锁修复留下的顺序）；
2. 动链那一步是 `submit_for_task` → `assert_release_verified(mode=PAY)`：
   * 状态是 `settled` ✓、交付验证 ✓；
   * `_assert_success_receipt` ✗ —— `services/settlement_receipt_release_guard.py` 要求
     **至少一条 `ToolStatus.SUCCESS` 执行回执**（`settlement_requires_success_execution_receipt_for_seller_release` 默认 True）。
     这 25 张单 0 条成功回执 → 409；
3. `_revert_chain_rejected_transition` 把状态从 `settled` 退回 `AUTO_CONFIRMED`，并记一条
   `guard_stage='chain'` 的审计 —— 但这是**前置条件**没过，不是链上腿失败；
4. **恢复缺口**：`auto_confirm_expired_settlements` 只扫 `store.list_by_status(DELIVERED)`；
   `escrow_autosettle.stranded_bindings` 只挑结算单状态 ∈
   `("settled","refunded","cancelled","failed","expired")`。`auto_confirmed` **两边都不在**，
   于是这张单再也不会被任何自动流程推进 —— 链上那笔预留（买方账单的 0.1 USDC reserved）
   谁也解不开。

**钱在哪**：`KarmaAllowanceEscrow.bind` 只做 `reserved += amount`，**不转账**；钱只在
`finalizeSettlement` 里 `transferFrom` 走。这 25 张 `submitSettlement` 一次都没成功，所以
**钱一步没动，全在买方自己的钱包里**，只是账单上的可用额度被占住（0.1 × 25 = 2.5 USDC）。

## 3. 修复（本轮）

| # | 改什么 | 文件 |
|---|---|---|
| F1 | 新增 `assert_release_preflight`：把「交付验证 + 成功执行回执」这两条**与状态无关**的前置条件提到推状态机**之前**。自动放款的路上，**没有回执的单子连 `AUTO_CONFIRMED` 都不进** —— 进得去、出不来。同时那条拒绝不再冒充链上腿失败 | `services/chain/escrow_settlement.py`、`api/routes/settlement.py` |
| F2 | 收尾缺口：`stranded_bindings` 开始认**退回来的** `auto_confirmed`（要放满 `STRANDED_AUTO_CONFIRM_GRACE_SECONDS=600s` —— 它可能只是自动放款路上的一瞬间），`reap_stranded` 对它走 `cancelBinding`（解预留、钱一步没动） | `services/chain/escrow_autosettle.py` |
| F3 | 自成交闸：`bind_for_task` 在发交易**之前**判「买卖双方解析到同一个钱包主身份」，判不过就 409 说清原因 —— 合约里那是 `SameOwner()`，一次都不会成 | `services/chain/escrow_settlement.py` |
| F4 | `bind_due` 对永久性错误（自成交）改成长退避（1h）＋**同一原因只报一次**：过去每 ~2 分钟刷一条 `escrow_autosettle_bind_failed` | `services/chain/escrow_autosettle.py` |
| F5 | 链上腿失败告警文案不再声称「retries continue」：实际是**业务状态已退回、钱没动**，重试与否取决于是哪一类失败 | `services/security_monitoring.py` |

`_REAP_CANCEL_SETTLEMENT_STATES = ("cancelled", "failed", "expired", "auto_confirmed")`
—— 只加 `auto_confirmed`，`refunded → slash` / `settled → submit` 两条**真动钱**的路没动
（这一条是既有回归测试 `test_business_final_but_chain_still_reserved_is_reaped` 抓出来的：
第一版把它写成 `_DECIDED_SETTLEMENT_STATES + (...)`，把 `refunded`/`settled` 也引到了
取消分支上，测试当场红）。

## 4. 验证

* **单测**：`tests/unit` 全量 **1920 passed / 20 skipped**（skip 的是需要 bash 的用例，本机
  没有 bash；CI 在 ubuntu 上跑）。新增：
  * `test_escrow_settlement.py::test_release_preflight_blocks_a_payout_with_no_receipt`
  * `test_escrow_settlement.py::test_release_preflight_is_a_noop_without_escrow`
  * `test_escrow_settlement.py::test_self_dealing_is_refused_before_any_chain_call`
  * `test_escrow_stranded_reap.py::test_a_reverted_auto_confirm_stops_holding_the_buyers_allowance`
  * `test_escrow_stranded_reap.py::test_a_fresh_auto_confirm_is_left_alone`
  * `test_escrow_autosettle.py::test_a_self_dealing_bind_backs_off_hard_and_says_it_once`
  * `tests/integration/test_auto_confirm_reaper.py::test_holds_without_a_success_receipt_and_never_strands`
* **集成**：`tests/integration` 全量（见 PR CI 记录）。
* **线上**：修复部署后由 autosettle 的 `reap_stranded` 自动解开这 25 条绑定（每轮
  `ESCROW_AUTOSETTLE_BATCH` 条），验证口径见 §5。

## 5. 线上收尾与验证口径

部署后（push main → `deploy-vps.yml`）：

```
# 1) 25 条绑定应该逐条变成 cancelled（不是 settled / slashed —— 钱没动过）
 select state, count(*) from escrow_bindings where binding_id ~ '^[0-9]+$' and binding_id::int between 108 and 140 group by 1;
# 2) 每条一条 escrow_stranded_reaped，settlement_status=auto_confirmed
 docker logs karma-api | grep escrow_stranded_reaped
# 3) 买方账单的 reserved 回落
# 4) 告警口径：settlement_transition_chain_gate_spike 不再增长（不会再有新的假链上腿失败）
```

## 6. 本轮**没有**做的

* **没碰主网**；没改 `can_transition`、没改托管合约、没改任何金额计算。
* **没决定**「没有成功执行回执的自动放款单最终该怎么结」这个**产品口径**：本轮只做到
  「不让它变成死账、也不让它冒充链上腿失败」。25 张单的处置是**解预留**（钱回买方可用额度），
  不是放款、也不是罚没。要不要给它一条「超期自动转争议 / 自动退款」的路，需要产品拍板。
* 性能（autosettle 每 20s 一跳、单跳 5–11s，余量很薄）仍未动，留作独立任务。
* 容器日志 `json-file 10MB×3` 保留太小（~2h），证据窗口仍偏窄。