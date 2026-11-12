# Karma 场景包 · 五个能跑完的生意

这五个包不是 PPT：每一个都能在真实 Karma 网络上从「买方下单」一路跑到「钱划给卖方」，
中间每一步都打印真实 HTTP 结果。跑完在操作台 `订单` 页就能看到这一单，点开是这张生意的动态状态图。

| # | 场景 | scene_id | 验真方式 | 金额 |
| --- | --- | --- | --- | --- |
| 1 | 线上数据 API | `data_api_billing` | 轻量数字（执行回执即证据） | 3 USDC |
| 2 | 外卖 | `food_delivery` | 实物三方（卖方 → 物流 → 买方） | 5 USDC |
| 3 | 打车 | `ride_hailing` | 行程轨迹 | 4 USDC |
| 4 | 订酒店 | `hotel_booking` | 票务回执（主人确认才结算） | 6 USDC |
| 5 | 跨境电商 | `cross_border_ecommerce` | 实物三方 + 报关清关单证 | 8 USDC |

## 一键跑

```bash
cd examples/scenario-packs

# 全部五个场景依次跑一遍
python run_all.py --wallets wallets.json

# 或者单个场景
python run_scenario.py 03-ride-hailing --wallets wallets.json
```

`wallets.json`：

```json
{
  "buyer":     { "key": "0x..." },
  "seller":    { "key": "0x..." },
  "logistics": { "key": "0x..." }
}
```

`logistics` 只有实物场景（外卖、跨境电商）用得上，但建议都配上 —— 交付验真要求
物流身份必须和买卖双方不同（防串通）。

不写文件也行，用环境变量：

```
KARMA_SCENARIO_BUYER_KEY / KARMA_SCENARIO_SELLER_KEY / KARMA_SCENARIO_LOGISTICS_KEY
```

## 一笔生意在协议里到底怎么走

```
买方                        Karma 协议                            卖方
 │  ①建结算单（钱留在自己钱包）→  │                                    │
 │  ②指派卖方                  →  │  状态 accepted                       │
 │                             ←  │  ③卖方开工          in_progress  ←  │
 │                             ←  │  ④进度上报 + 交付凭证                │
 │                             ←  │  ⑤执行回执（结算硬前提）              │
 │  ⑥验收 /（部分场景要主人点头）→ │  ~ 结算 ~ 真钱从买方锁仓划给卖方      │
```

关键点：

- **钱一直在买方自己的钱包里**。锁仓是「承诺」，不是「转账」；验收通过才划转。
- **卖方拿到的不是「信任」，是可验证的证据**：回执哈希、轨迹哈希、带 HMAC 的送达照片、报关单证。
- **别信任何一方自己的对账单**：结算依据是协议里锁定的验收标准和证据。
- **不碰私钥**：跑这些包只需要钱包做 SIWE 会话签名，不涉及助记词、不导出私钥、不代签交易。

## 目录

```
run_scenario.py            单个场景一键跑
run_all.py                 五个场景依次跑
_lib/karma_flow.py         共享客户端（SIWE 会话 + 结算状态机 + 交付验真 + 结算）
01-data-api/               scenario.json（机器可读） + README.md（人读）
02-food-delivery/
03-ride-hailing/
04-hotel-booking/
05-cross-border-ecommerce/
```

## 想接自己的生意

每个包里 `scenario.json` 的 `flow.milestones` / `flow.seller_proofs` 就是「这个生意要上报哪些节点、
哪些凭证」。把卖方那侧换成你自己系统的真实动作，结算链路一行都不用改。
