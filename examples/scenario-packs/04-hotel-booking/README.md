# 订酒店 · 确认号回执验真

订 2 晚酒店。走「票务回执」验真：卖方出确认号 / 邮件回执 → 买方确认房态无误 → 结算。酒店属于必须主人点头的场景，结算是 OWNER_CONFIRM。

| 项 | 值 |
| --- | --- |
| 场景 ID | `hotel_booking` |
| 金额 | 6 USDC |
| 交付验真 | 票务回执验真 |
| 谁参与 | 买方 / 卖方 |

## 角色

- 买方：买方（出行的人）
- 卖方：卖方（酒店 / OTA agent）

## 怎么跑

```bash
cd examples/scenario-packs
python run_scenario.py 04-hotel-booking --wallets wallets.json
```

`wallets.json` 形如：

```json
{ "buyer": { "key": "0x..." }, "seller": { "key": "0x..." } }
```

也可以直接用环境变量：`KARMA_SCENARIO_BUYER_KEY` / `KARMA_SCENARIO_SELLER_KEY`。

跑完的 `task_id` 会打印出来；在操作台 `订单` 页能找到这一单，点开就是这张生意的动态状态图。

## 这一单在链路上走了什么

1. 买方建任务合同 + 结算单（`scene_id=hotel_booking`），转 pending，指派卖方 —— 钱还锁在买方自己钱包里。
2. 卖方接单开工，按里程碑上报进度。
3. 交付验真：卖方出具确认号 / 回执（`email_receipt`）→ 买方确认。
4. 卖方提交执行回执（结算的硬前提），然后交付。
5. 买方验收（这两类场景按规则必须主人本人点头），额度真实划转给卖方，链上/账本上都能对。

## 为什么值得用 Karma 跑

- 订酒店金额大、易扯皮，所以结算是主人确认制：agent 不能自作主张把尾款付掉。
- 确认号回执是可核的交付证据，后期可接 OTA / PMS 直接核验。
- 房态没锁住就不会进入结算，钱不会被提前划走。

## 换成真生意要改什么

这个包里卖方的「业务动作」是协议内的证据动作（上报进度、上传凭证、交回执）。换成真生意时，把 `flow.milestones` / `flow.seller_proofs` 换成你自己系统的真实节点即可 —— 结算链路不用动。

> `scenario.json` 是机器可读的那份（`run_scenario.py` 按它执行），这份 README 是给人看的。两者以 `scenario.json` 为准。
