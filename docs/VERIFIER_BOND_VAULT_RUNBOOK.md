# 验证者质押金库（KarmaVerifierBond / G12）运维手册

这份手册只讲一件事：**怎么部署、核对、并使用链上质押金库，让「节点作恶」有经济代价**。
测试网先跑稳，主网另说 —— 主网未动。

- 合约：`karma-core/contracts/core/KarmaVerifierBond.sol`
- 部署脚本（forge，有主网守卫）：`karma-core/contracts/script/DeployKarmaVerifierBond.s.sol`
- ops 执行手：`scripts/ops/verifier_bond_vault.py`（部署 / 状态 / 罚没 / 分池，支持 `--dry-run`）
- 链下台账与状态机：`services/bond_slash.py`；只读 / 构造调用：`services/chain/verifier_bond_vault.py`
- 入场闸门：`services/verifier_bond.py`

## 1. 安全不变量（先读这段）

1. **后端全程不持有、不索取、不传输任何私钥。** 后端只做两件事：把状态读出来、把一笔治理动作
   编码成 calldata 交给治理账户去签。签名脚本读的是**环境变量**里的密钥，永不打印、永不落盘。
2. **没有链上 tx 不许写 `settled`。** 台账状态机是 `pending → submitted → settled | failed`；
   `VERIFIER_BOND_VAULT_ADDRESS` 为空时罚没一律停在 `pending`（见 `services/bond_slash.py`）。
   金库配好了、治理账户签了、拿到 tx hash，才允许回写 `settled`。
3. **入账 / 出账主体分离。** 判负那一刻的事（停用 + 记台账 + 扣声誉）当场做；钱怎么动是另一件事，
   可以延后，但延后不等于假装完成。
4. **生产 `admin` / `slasher` 必须是多签合约。** admin 能改 `minBond` / 分账比例 / 起奖线，
   slasher 能划走任何节点的保证金 —— 单个 EOA 私钥泄露 = 整个验证网络的经济安全归零。
   部署脚本 `_isTestnet(chainId)` 之外一律要求 `admin.code.length > 0 && slasher.code.length > 0`，
   是 EOA 就 revert。**本手册里的 EOA 用法仅限测试网。**
5. **罚没是治理动作**，不该由热钱包执行。测试网用部署者 EOA 演练；主网走多签 —— 本 CLI 不是主网治理通道。
6. **`solvencyGap() == 0` 是账目自证。** 每一次出账/分池后它都必须为 0：链上代币余额 ≥ 应付未付总额。
   不为 0 就是账目对不上，立刻停下来查。

## 2. 需要的环境变量

写在 `/opt/karma/.env`（应用读），或由 ops 侧注入给 CLI：

| 变量 | 用途 |
|---|---|
| `VERIFIER_BOND_VAULT_ADDRESS` | 金库地址。后端靠它决定「罚没能不能出账」 |
| `TESTNET_RPC_URL`（或 `VERIFIER_BOND_RPC_URL`） | RPC 端点 |
| `VERIFIER_BOND_OPS_PRIVATE_KEY` | **仅签名时**读取的治理私钥；不存在任何兜底取密钥的路径（fail-closed） |

CLI 也支持 `--rpc` / `--vault` / `--key-env` 覆盖，优先于环境变量。
`--artifact` 指向 forge 产出的 `KarmaVerifierBond.json`（含 `abi` + `bytecode`）。

## 3. 部署（测试网）

```bash
# 1. 先干跑，看清要发什么（不广播、不碰链）
python scripts/ops/verifier_bond_vault.py deploy --dry-run \
    --artifact out/KarmaVerifierBond.json \
    --token "$ERC20_TOKEN_ADDRESS" \
    --min-bond 5 --cooldown-hours 72 --min-pool-payout 1

# 2. 真部署（admin = slasher = 签名者；非测试网会被合约/脚本守卫挡下）
python scripts/ops/verifier_bond_vault.py deploy \
    --artifact out/KarmaVerifierBond.json \
    --token "$ERC20_TOKEN_ADDRESS" \
    --min-bond 5 --cooldown-hours 72 --min-pool-payout 1
```

部署会依次发三笔：`constructor` → `setStakeConfig(minBond, cooldown, minPoolPayout)` → `setSlasher`。
**创建 gas 需求约 9.2M**（`via_ir` 编译很贵），默认上限给到 12M；低于它会在
`contract creation code storage out of gas` revert。

拿到地址后写进 `/opt/karma/.env`：

```
VERIFIER_BOND_VAULT_ADDRESS=0x…
```

改完 `.env` 要**重建** app 容器才会生效（`docker compose` 只在启动时读 env file）：

```bash
cd /opt/karma/repo
docker compose --env-file /opt/karma/.env -f deploy/docker-compose.yml \
    up -d --no-build --remove-orphans --force-recreate app
```

## 4. 核对状态（只读）

```bash
python scripts/ops/verifier_bond_vault.py status --address 0xNode
```

输出 JSON：`admin` / `slasher` / `token` / `minBond` / `unbondCooldown` / `minPoolPayout` /
`victimShareBps` / `totalBonded` / `slashPool` / `solvencyGap`，以及每个 `--address` 的
`bondAmount` / `isActive` / `isRegistered`。

后端侧确认（需要鉴权，`X-Karma-Api-Key: karma_<agent_id>_<secret>`）：

```bash
curl -s -H "X-Karma-Api-Key: $KEY" http://127.0.0.1:8000/v1/verifiers/slashes
# → {"slashes":[...],"total":N,"pool_total":…,"vault_configured":true}
```

`vault_configured=false` 说明后端还没认到金库 —— 罚没会停在 `pending`，**这不是成功**。

## 5. 罚没与分池（治理动作）

```bash
# 先干跑：比对 calldata 与链下台账口径（同一份 ABI、同一个小数位、同一套理由哈希）
python scripts/ops/verifier_bond_vault.py slash --dry-run \
    --verifier 0xNode --amount 6 --victim 0xVictim --reason "challenge 42 upheld"

# 再真发
python scripts/ops/verifier_bond_vault.py slash \
    --verifier 0xNode --amount 6 --victim 0xVictim --reason "challenge 42 upheld"

# 池子攒到 minPoolPayout 后分给优秀节点
python scripts/ops/verifier_bond_vault.py distribute --winners 0xA,0xB --amount 1
```

`--victim` 缺省时受害方那一份（80%）并入罚没池 —— 与链下台账「没有可指认的受害方就不凭空指一个
收款人」完全一致。罚没后节点保证金低于 `minBond`，链上当场 `active=false`；冷却期内**仍可被罚没**。

拿到 tx hash 后再回写台账（把 `pending` 推进到 `submitted → settled`）。**顺序不能反。**

## 6. 首次真实出账（2026-10-11，Ethereum Sepolia）

回归账目自证的样板（`stake(10) → slash(6) → distributePool(1)`）：

| 步骤 | tx | 结果 |
|---|---|---|
| `stake(10 mUSDC)` | `0xa1c9a41c…` | `totalBonded=10`，节点 `active=true` |
| `slash(6, victim)` | `0x3cbcb6f6…` | 受害者 +4.8（80%）、`slashPool=1.2`（20%）、保证金 10→4 低于 `minBond` → `active=false` |
| `distributePool([b,victim_b], 1)` | `0xb4c3a042…` | 两名节点各 +0.5、`slashPool` 1.2→0.2 |

每一步 `solvencyGap()==0`。用本 CLI 对同样入参编出的 calldata 与上述两笔链上 `input` **逐字节一致**。

## 7. 主网升级清单（未做）

1. 部署金库，`ADMIN_ADDRESS` / `VERIFIER_BOND_SLASHER` 都指向多签（Safe / 时间锁）；
   非测试网是 EOA 会直接 revert。
2. 多签自己发 `setStakeConfig` 与 `setSlasher`（部署者不是 admin 时脚本会打印
   `ACTION REQUIRED`，不假装配好了）。
3. 治理账户（= 多签）签名出账；`VERIFIER_BOND_OPS_PRIVATE_KEY` 这条 EOA 通路**不要带到主网**。
4. 明确罚没池分配策略：**谁算「优秀节点」、什么时机分** —— 这是链下治理规则，测试网跑稳后再定，
   在此之前不要假装它已经自动化。
5. 结算回滚仍未做：仲裁被推翻只罚庭，接口如实返回 `settlement_reversal="not_performed"`。