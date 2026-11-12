# 测试网场地：喂币 + 完整成交闭环 + 孤儿绑定收尾（2026-10-14）

上一份记录（`2026-10-14-testnet-venue-escrow-bootstrap.md`）把 testnet 场地那台独立托管
合约发出来了，但场地里的演练身份是**空壳**：没有测试币、没有对托管合约的 ERC-20 授权、
没有链上承诺。所以「托管到底能不能真的把钱从买方钱包划到卖方钱包」这件事，在 testnet
上从来没被证明过。

这一轮把它跑通了。本文是**证据**，不是计划。

## 一、为什么之前的演练身份跑不动

四个数看一眼就明白：

| 东西 | 之前 | 需要 |
|------|------|------|
| 身份档案 `identity_profiles`（a2a-buyer / a2a-seller） | 不存在 | 有行 + `bound_wallet_address` |
| 钱包里的测试币 mUSDC | 无 | ≥ 承诺额 |
| 钱包对托管合约的 ERC-20 授权 | 0 | ≥ 承诺额（`commit()` 当场比） |
| 链上账单 `allowance_commits` | 0 行 | 买卖双方各一条 |

`claim_commit` 的判据是「这条账单的钱包必须属于这个身份」
（`wallet_lock.allowed_wallets()` = 身份钱包 ∪ `identity_profiles.bound_wallet_address`），
所以档案里没有绑定钱包时，连认领都会被拒。

## 二、新脚本：`scripts/seed_testnet_escrow_drill.py`

一次做完五步，幂等可重跑：

1. 给演练钱包发 gas（operator 出）；
2. mint 测试币（Sepolia 的 `mUSDC` 可 mint）；
3. 钱包 `approve(托管合约, 额度)`；
4. 钱包自己签 `commit(token, amount, operator)`，产出一条链上账单；
5. 台账把这条账单认到身份上（`claim_commit`，**金额从链上读**，客户端说了不算）+
   写 `identity_profiles.bound_wallet_address` + 对齐 `runtime_keys.wallet_address`。

私钥写在 `DRILL_KEYS_DIR`（默认 `karma_data/drill_keys`，0600），不进仓库。
`APP_ENV=production` 直接退出。

```bash
python3 scripts/seed_testnet_escrow_drill.py --dry-run
python3 scripts/seed_testnet_escrow_drill.py --amount 50 --stake 5
```

## 三、跑出来的结果（Sepolia 11155111）

合约 `0x2C9911F58CfDb5f097926c4aC104108f4f49743b`，token `mUSDC`
`0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF`（decimals 6），operator `0x1D147c9e…`。

| 身份 | 演练钱包 | 账单 | 承诺额 | commit tx | commit gasUsed |
|------|----------|------|--------|-----------|----------------|
| `a2a-buyer` | `0xD91acb5D…` | `1` | 50.0 | `0x947c87c0497b102cb4e7f191efc009ac6d74fc0c523c17711c2e09406afe677f` | 1,135,990 |
| `a2a-seller` | `0x9C479392…` | `2` | 5.0 | `0x5de91a3fa74088e2d902d2f3752db83a5e95f0c6bf78eda3f47bbac8eaaafe34` | 1,038,058 |

两条 `allowance_commits` 落地，卖方 capacity 被记 5（`escrow_capacity_mirror_reconciled`）。
买方原有 500 的内部额度不动（对账口径是「只补链上担保那一段」，不会把内部额度抹掉）。

### 3.1 踩到的两个坑（都写进脚本注释了）

**(1) 别拿 21000 硬编码一笔普通转账。** 这台测试网上「给一个全新地址发 1 wei」实测
`gasUsed = 204,600`（收据里读的，不是估的）。写死 21000 的结果是
`status 0 / gasUsed 恰好 21000` —— 一笔看起来正常的转账凭空 revert
（tx `0xfc032214…`）。修法：`send_value` 走 `estimate_gas`（带 1.5× 余量）。

**(2) 节点算 `eth_estimateGas` 时会用 `余额 / maxFeePerGas` 当搜索上限。**
钱包里只有 0.02 ETH、`maxFeePerGas = 30 gwei` → 上限 662,379。
而 `commit()` 实测要 1,135,990 gas —— 估算被截断，报
`gas required exceeds allowance (662379)`。修法：演练钱包充到 0.3 ETH（上限抬到千万级）。

这两条都不是「脚本写得糙」，是**这台链的 gas 事实**，所以留档。

## 四、完整成交闭环（走既有 API，不是自己拼链上调用）

买方 agent 那一条路径，逐笔都是真交易：

```
POST /v1/escrow/a2a-buyer/orders        （JWT actor = a2a-buyer）
  ├─ bind              tx 0x44888ee7793948373885fd8bc430e0981fb7a243bd3de2f0c1cd8cac28e6ed11
  └─ submitSettlement  tx 0xa2634ca5636df5e29282ab5f0871f5ce92e7a5fb774d1348cc6d3d6e5b105639
     pull_after = 1791942720（disputeWindow 60s）
        ↓ 等满保护期
POST /v1/escrow/a2a-buyer/orders/1/finalize
     finalizeSettlement tx 0xbe0cad448b103937dd43994335526d62f0992dfc502868464eede7ff440f65da
     paid_usdc = 10.0
```

金额与质押：订单 10.0 USDC，质押 `seller_stake.required_stake_usdc(10)` = 3.0（30%）。

### 4.1 钱真的动了（钱包 → 钱包，合约一分钱没持有）

| 钱包 | mUSDC 前 | mUSDC 后 | 对托管合约的授权 |
|------|----------|----------|------------------|
| 买方 `0xD91acb5D…` | 50 | **40** | 50 → 40 |
| 卖方 `0x9C479392…` | 5 | **15** | 5（未动） |

合约是 `checkNoCustody = true`：`finalizeSettlement` 那一刻从买方钱包 `transferFrom`
直划卖方。中间没有任何一刻钱停在 Karma 手里。

### 4.2 台账跟着链走

* `escrow_bindings`：`binding_id=1` → `state=settled`，三条 tx 哈希（bind / submit /
  finalize）齐；
* `allowance_commits`：账单 1 `spent_usdc=10`、`capacity_credited_usdc=40`；账单 2 未动；
* `capacity`：买方 `total_bill_credits=490 / available=480 / reserved=10`；
* `settlements`：`escrow_settlement.reconcile_task()` 之后
  `onchain_status=settled`、`onchain_binding_id=1`、`tx_hash=<finalize tx>`、
  `contract_address=0x2C9911F5…`。

### 4.3 一处必须说清楚的边界

走 `/v1/escrow/{id}/orders` 这条路（Console / agent 开单用的那条），**只驱动托管这条
独立面**：它写 `escrow_bindings`，不推业务状态机。所以这一单的
`settlements.status` 仍然是 `in_progress` —— 要让业务状态走到 `settled`，必须走
`escrow_settlement.submit_for_task` 那条路，而它要求「交付验证 VERIFIED + 至少一条成功
执行回执 + 资金链路可回溯」。那需要一条真的、带回执的交付，本轮没有造。
链上事实与台账这一点**是对齐的**，只是业务状态**故意没有跟着跳**。

## 五、孤儿绑定收尾（真实演练）

「孤儿」= 同一个 task 上有更新的绑定已经走完，而老的那条还在链上占着买方的授权额。
prod 上真实的 3 条（binding 92 / 161 / 171）就是这么来的。

testnet 上按同一个形状造了一遍：

| binding | 角色 | ledger 前 | 链上前 |
|---------|------|-----------|--------|
| 2 | 老（`bind_for_task`，未 submit） | `active` | `1`（Bound） |
| 3 | 新（`/orders` 路由，已 submit） | `finalizing` | `2`（Submitted） |

`bind_for_task` 发的 bind tx `0xfcdb8a41ee5fc7078e4de9bb740dd0493c376caa092eb9ac129b49e3773bb54c`；
新单 bind tx `0x1438d384…` + submit tx `0x51257dd9…`。

```bash
python3 scripts/escrow_orphan_bindings.py --task drill-orphan-t2          # dry-run：列出 1 条
python3 scripts/escrow_orphan_bindings.py --task drill-orphan-t2 --apply  # 真收
```

结果：链上 binding 2 `1 (Bound) → 5 (Cancelled)`，台账 `active → cancelled`，
binding 3 一动不动。**「按 binding 收尾、不误伤兄弟绑定」在真链上验证过了。**

> 造场景用的 `task_contracts` / `settlements` 两行是**演练夹具**（直接插在 testnet 场地库
> 里的，`/v1/settlement/create` 要求先有 task contract）。链上那两个 bind 和一个
> `cancelBinding` 都是真交易。

## 六、测试

```
pytest tests/unit/test_allowance_escrow.py tests/unit/test_escrow_settlement.py        tests/unit/test_self_dealing_ban.py tests/unit/test_escrow_orphan_binding.py
→ 109 passed in 28.12s
```

`scripts/seed_testnet_escrow_drill.py` 本地 `py_compile` + `ruff check` 干净。

## 七、还没做的（如实列）

* **prod 那 3 条真孤儿（92 / 161 / 171）仍在等 `--apply`**：需要 operator gas，
  且是动 prod，等负责人点头。开关 `ESCROW_ORPHAN_BINDING_CANCEL_ENABLED` 默认关。
* 业务状态机那条腿（`settlements.status → settled`）在 testnet 上仍未跑通，缺的是
  「带成功执行回执的交付」，不是托管本身。
* 本轮的场地数据（演练钱包 / 夹具行）留在 testnet，prod 一个字节没动。
