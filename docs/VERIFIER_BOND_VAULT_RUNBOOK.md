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
| `VERIFIER_REQUIRE_VAULT_BOND` | （④-B1）节点质押必须真的在金库里：出证前回链上核对 `bondAmount >= stake` |
| `ARBITRATION_REQUIRE_VAULT_BOND` | （④-B1）仲裁员质押同样要求：入池与投票都回链上核对；钱包取该身份在 Console 绑定的那个 |

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

回写入口（④-B1）：

```bash
curl -sS -X POST "$KARMA_API/v1/verifiers/slashes/<slash_id>/status" \
  -H "X-Karma-Api-Key: $ADMIN_API_KEY" -H 'Content-Type: application/json' \
  -d '{"status":"settled","tx_hash":"0x..."}'
```

`settled` 这一档不只要求带 tx hash，还会**回链上核验**：该 tx 已上链、没 revert、
收款方是当前配的金库、调用的是 `slash(address,address,uint256,bytes32)`。核不过就 409，
台账继续停 `pending` —— 一个手拄的 hash 不能把台账变成「已出账」。这个入口需要
**平台管理员**（`ADMIN_ACTOR_IDS`）凭证，仲裁员白名单不够。

## 5.5 质押真上链（④-B1，2026-10-15）

此前「质押即准入」只看账面锁仓额度（`capacity.total_locked_usdc`），而链上
`slash(address verifier, ...)` 只能划**金库里那笔 `Bond`**。两者不是一回事的后果是：
判负当场生效、钱却划不动 —— 「他们不敢作恶」只剩一句口头承诺。同时 `/overturn` 此前
记的是 `wallet_address=None`，「罚谁」在链上无从指认。

现在三件事各归各位：

1. **质押人自己把钱进金库**（后端不碰私钥）：

   ```bash
   # 质押人自己的钥匙（--key-env），approve + stake 两步，已有足够 allowance 时跳过 approve
   python scripts/ops/verifier_bond_vault.py stake --amount 150 --key-env A2A_SELLER_KEY
   ```

   读回里必须能看到 `bond_amount_wei` / `bond_isRegistered=true`。

2. **闸门**（`VERIFIER_REQUIRE_VAULT_BOND` / `ARBITRATION_REQUIRE_VAULT_BOND`）：打开后
   出证 / 入池 / 投票都回链上核对 `bondAmount >= 质押额`；RPC 读不到一律
   **fail-closed**（读不到不当成 0）。钱包取该身份在 Console 绑定的那个：
   入池前先绑钱包，否则 409（`no_wallet`）。

3. **指认**：`/v1/arbitration/cases/{id}/overturn` 现在记的是该仲裁员绑定的钱包，
   于是 `bond_slash.slash_instructions()` 才产得出一条**能真发**的链上说明。
   没绑钱包时不编一个：台账照记、状态停在 `pending`（宁可发不出 tx，也不乱指认）。

**不变的东西**：后端仍不签名、不新增落钱路径；`settled` 仍然必须带 tx hash；
主网零改动。`stake()` 进金库属于**质押人自己的钱**，所以不走后端热钱包。

## 5.6 测试网端到端演练（④-B1，2026-10-15，Ethereum Sepolia）

这一节是「质押 → 准入 → 出账 → 台账回写」四段在**真链 + 真库**上跑通的记录。
金库 `0x8eBCF8668a6B54872A4e747d82dB152095B21027`，mUSDC
`0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF`，`minBond = 5`。

| 段 | 动作 | 链上/库里结果 |
|---|---|---|
| 1 | 质押人自己 `approve` + `stake(10)` | tx `0x63a40914479cfa0f196874186381e9f2c9aaf5fee80cfb33168bdc23239f6af1`，block 11915327；`totalBonded 4 → 14`，该钱包 `bondAmount=10`、`isRegistered=true`、`isActive=true` |
| 2 | 闸门（`VERIFIER_REQUIRE_VAULT_BOND=true`） | 绑了这个钱包的身份 PASS（`active`）；换成 150 的质押额 → `below_bond` 拒；没绑钱包的身份 → 409 `no_wallet` |
| 3 | 治理钥真 `slash(1 mUSDC)` | tx `0x4a1e20d0d8802d1015464446050a8d561584b521a869d56297d8950e2283892e`，block 11915330；`totalBonded 14 → 13`、`slashPool 0.2 → 0.4`、被罚钱包保证金 10 → 9 |
| 4 | `/overturn` → 3 条 `bond_slashes` | 有绑定钱包的那条带上钱包；没绑的两条 `wallet_address` 为空（不编） |
| 5 | `settled` 回写 | 假 tx hash → **409**；没钱包的台账行 → **409**；真 tx → **200**，台账落 `settled` + `tx_hash` |

全程 `solvencyGap() == 0`；链上那两笔的 `input` 与
`services.chain.verifier_bond_vault` 编出来的 calldata **逐字节一致**。
演练结束后已复原：drill 档案删净、三个开关从 `.env` 与容器里撤掉、健康检查 200；
**罚没台账保留**（那是真实发生的事）。

### 5.6.1 这轮真链抓出的两个 bug（都已修，且都不可能在假链上发现）

1. **`build_transaction` 不带 `from`**（#319）：web3 会拿零地址做 gas 估算，凡是按
   `msg.sender` 判权限的函数（`approve` / `stake` / `setSlasher` / `setStakeConfig`）
   在估算这一步就 revert，真交易根本发不出去 —— 链上表现是
   `execution reverted, data 0x`，而同一份 calldata 带 `from` 的 `eth_call` 是好的。
   现在全文件只有一个建交易入口 `_build(fn, signer)`，永远带 `from`；有一条源码守卫
   测试盯着「只允许这一个调用点」。
2. **`verify_slash_tx_sync` 直接 `str(tx["input"])`**（#320）：真节点回的是
   `HexBytes`（`bytes` 子类），`str()` 出来是 `b"...\xa5'\xf1..."` 的样子，选择器
   比对永远为假 —— **一笔真的链上 slash 被判成「不是 slash 调用」**，台账只能停在
   `pending`。现在 calldata 一律走 `wallet_lock._hexstr`（bytes / HexBytes / 带不带
   `0x` 的裸 hex 都归一）。

教训写在这：**假链全绿不等于真链能跑**。上面两处都是 mock 与真节点的**形状差异**
（`from` 缺省、`HexBytes` vs `str`），单测里用 dict 和 0x 字符串喂料是照不出来的 ——
所以本节这种「真链 + 真库」演练必须在新链路进生产前跑一遍。

### 5.6.2 这轮**没有**解决的（别当成已做）

- 罚没池分配（④-B3）：谁算「优秀节点」、什么时机分，仍是链下治理规则。
- 结算回滚（④-B2）：`settlement_reversals` 未做；仲裁被推翻只罚庭。
- 链上 `slash()` 会把金额**按保证金封顶**（`take = min(amount, bond)`），保证金不足时
  实际划走的少于台账数 —— 这是「按链上事件对账」的事，本轮没做，台账这时只会停在
  `pending`（不会假报 settled）。
- 测试网金库的 `admin` / `slasher` 那个 EOA 自己押了 4 mUSDC，但低于 `minBond=5`，所以
  `isActive=false`。生产环境的在岗节点不一定押够了，**prod 本轮不开这两个开关**。
- 主网 `admin` / `slasher` 必须是多签；`VERIFIER_BOND_OPS_PRIVATE_KEY` 这条 EOA 通路
  不要带去主网。

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
5. （④-B1 后）主网要把 `VERIFIER_REQUIRE_VAULT_BOND` / `ARBITRATION_REQUIRE_VAULT_BOND`
   同样开着，并先把在岗节点 / 仲裁员的钱包 stake() 进金库。
6. 结算回滚（④-B2，2026-10-15 落地）：仲裁被推翻不再只罚庭 —— `/overturn` 当场按案件
   **推定**受害方与欠款额、写进 `settlement_reversals` 台账，响应里的 `settlement_reversal`
   回枚举（`recorded` / `not_moved` / `no_binding` / `self_dealing`），细节见
   `docs/ARBITRATION_SETTLEMENT_REVERSAL.md` §11。主网前要留意的两点：
   **① 赔款对象由后端推定**，接口不再接受「调用方随口指一个钱包」；
   **② `paid_amount` 只会被「已 settled 且回链核过」的罚没 tx 推动**，没有别的入口。
   测试网 `ARBITRATION_APPEAL_WINDOW_SECONDS = 3000`（用户 2026-10-15 拍板；本地默认 0 = 关）。
   真链演练记录见 §5.7。