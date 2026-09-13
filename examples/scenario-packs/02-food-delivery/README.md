# 外卖 · 商家出餐 → 骑手送达

写字楼订 12 份工作餐。走「实物三方」验真：商家出餐 → 骑手接单核验货品一致 → 送达拍照（带系统防伪标签）→ 买方确认，然后才结算。

| 项 | 值 |
| --- | --- |
| 场景 ID | `food_delivery` |
| 金额 | 5 USDC |
| 交付验真 | 实物三方验真（卖方 → 物流 → 买方） |
| 谁参与 | 买方 / 卖方 / 物流 |

## 角色

- 买方：买方（点餐的公司）
- 卖方：卖方（商家 agent）
- 物流：物流（骑手 / 配送 agent，必须与买卖双方不同）

## 怎么跑

```bash
cd examples/scenario-packs
python run_scenario.py 02-food-delivery --wallets wallets.json
```

`wallets.json` 形如：

```json
{ "buyer": { "key": "0x..." }, "seller": { "key": "0x..." }, "logistics": { "key": "0x..." } }
```

也可以直接用环境变量：`KARMA_SCENARIO_BUYER_KEY` / `KARMA_SCENARIO_SELLER_KEY` / `KARMA_SCENARIO_LOGISTICS_KEY`。

跑完的 `task_id` 会打印出来；在操作台 `订单` 页能找到这一单，点开就是这张生意的动态状态图。

## 这一单在链路上走了什么

1. 买方建任务合同 + 结算单（`scene_id=food_delivery`），转 pending，指派卖方 —— 钱还锁在买方自己钱包里。
2. 卖方接单开工，按里程碑上报进度。
3. 交付验真：卖方发出 → 物流接件核验（货不对板当场记录，双方共担）→ 送达拍照（带时间戳与 HMAC 的系统标签） → 买方确认。
4. 卖方提交执行回执（结算的硬前提），然后交付。
5. 买方验收，额度真实划转给卖方，链上/账本上都能对。

## 为什么值得用 Karma 跑

- 骑手接件要核验：收到错件当场记录，损失按标准在物流与商家之间分担，不再是扯皮。
- 送达拍照是带时间戳与 HMAC 的系统标签照片，翻拍挪用验不过。
- 买方 30 分钟不确认且三方链路正确 → 默认确认，商家不会被恶意拖延。

## 换成真生意要改什么

这个包里卖方的「业务动作」是协议内的证据动作（上报进度、上传凭证、交回执）。换成真生意时，把 `flow.milestones` / `flow.seller_proofs` 换成你自己系统的真实节点即可 —— 结算链路不用动。

> `scenario.json` 是机器可读的那份（`run_scenario.py` 按它执行），这份 README 是给人看的。两者以 `scenario.json` 为准。
