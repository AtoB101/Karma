# 测试网场地托管合约 bootstrap（2026-10-14）

G10 那批工作里留了一条尾巴：**testnet 场地缺 `ALLOWANCE_ESCROW_ADDRESS`**，于是
`escrow_enabled() == False`，testnet 上任何「真的碰链」的动作都跑不起来（只能空转）。
本文把它补上，并把选择理由记清楚。

## 为什么不是直接指到 prod 那台

prod 的托管合约 `0x65eb82058F4ea707B1a0aFb2A5872eb95076b6F2` 也在 Sepolia。
但 testnet 场地存在的意义是**隔离**（`/opt/karma/testnet` 独立容器 + 独立库
`karma_testnet`），演练要能随便造、随便删，不能往 prod 那台合约上堆绑定。
所以给 testnet 场地**单独发一台**。

## 发了什么

| 项 | 值 |
|----|----|
| 合约 | `KarmaAllowanceEscrow`（`karma-core/contracts/core/KarmaAllowanceEscrow.sol`，v5） |
| 地址 | `0x2C9911F58CfDb5f097926c4aC104108f4f49743b` |
| 网络 | Sepolia `11155111` |
| deploy tx | `0bcc871e…` |
| setTokenAllowed tx | `3cf3d27c…` |
| admin / disputeResolver | `0x1D147c9eefd9D1d4C4725700a05EDc6ca13975Cc`（operator） |
| disputeWindowSeconds / settleDelaySeconds | `60` / `0`（与 prod 同参数） |
| token | USDC `0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF`（`tokenAllowed = true`） |
| bindingVersion | `5` |

`checkNoCustody(USDC) == true` —— 合约一分钱都不持有，和其它环境是同一条不托管原则。

记录文件：`deploy/sepolia_allowance_escrow_testnet_venue.json`。

## 场地配置（`/opt/karma/testnet/.env`，不进仓库）

```
ALLOWANCE_ESCROW_ADDRESS=0x2C9911F58CfDb5f097926c4aC104108f4f49743b
ALLOWANCE_ESCROW_DISPUTE_WINDOW=60
SETTLEMENT_OPERATOR_PRIVATE_KEY=<同 TESTNET_PRIVATE_KEY>
```

改完 `docker compose up -d --force-recreate api` 重载（env_file 只在创建时读）。
`.env` 改动前已备份为 `.env.bak-allowance-<epoch>`。

## 验证（线上实读）

```
escrow_enabled       True
can_server_settle    True
missing              []
contract             0x2C9911F58CfDb5f097926c4aC104108f4f49743b
chain_id             11155111
bindingVersion       5
admin/disputeResolver 0x1D147c9eefd9D1d4C4725700a05EDc6ca13975Cc
disputeWindowSeconds 60   settleDelaySeconds 0
tokenAllowed(USDC)   True
checkNoCustody       True
```

prod 一侧复读：`escrow_enabled True / can_server_settle True / contract 0x65eb…` —— **未动**。

## 与代码的关系

**未改任何代码、未改任何 ABI、未动 prod 配置。** 这一步只是把 testnet 场地缺的那条
配置补上，让 testnet 从此能跑「真的碰链」的演练（bind / settle / slash / cancelBinding）。

## 还差什么（说清楚，不粉饰）

* testnet 的身份钱包还没有 Sepolia 测试 USDC，也还没做对这台新合约的 ERC20 授权 ——
  要跑完整「下单 → 锁额 → 凭证 → 结算」的演练，得先给演练身份备测试币与授权。
* 孤儿绑定收尾（`escrow_orphan_binding_cancel_enabled`）在 testnet 上目前**没有**孤儿样本，
  要演练得先造一条（建议在演练脚本里一起做）。
