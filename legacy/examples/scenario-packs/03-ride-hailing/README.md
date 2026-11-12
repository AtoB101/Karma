# 打车 · 行程轨迹验真

机场到市区的一趟车。走「行程轨迹」验真：行程完成 → 轨迹/里程哈希 → 最终车费，对照锁定的起终点；短静默窗后自动结算。

| 项 | 值 |
| --- | --- |
| 场景 ID | `ride_hailing` |
| 金额 | 4 USDC |
| 交付验真 | 行程轨迹验真 |
| 谁参与 | 买方 / 卖方 |

## 角色

- 买方：买方（乘客）
- 卖方：卖方（司机 / 车队 agent）

## 怎么跑

```bash
cd examples/scenario-packs
python run_scenario.py 03-ride-hailing --wallets wallets.json
```

`wallets.json` 形如：

```json
{ "buyer": { "key": "0x..." }, "seller": { "key": "0x..." } }
```

也可以直接用环境变量：`KARMA_SCENARIO_BUYER_KEY` / `KARMA_SCENARIO_SELLER_KEY`。

跑完的 `task_id` 会打印出来；在操作台 `订单` 页能找到这一单，点开就是这张生意的动态状态图。

## 这一单在链路上走了什么

1. 买方建任务合同 + 结算单（`scene_id=ride_hailing`），转 pending，指派卖方 —— 钱还锁在买方自己钱包里。
2. 卖方接单开工，按里程碑上报进度。
3. 交付验真：行程完成 → 轨迹/里程哈希 → 最终车费，对照锁定起终点 → 买方确认。
4. 卖方提交执行回执（结算的硬前提），然后交付。
5. 买方验收，额度真实划转给卖方，链上/账本上都能对。

## 为什么值得用 Karma 跑

- 预估价与实际车费对不上时，轨迹哈希可核 —— 绕路骗不了人。
- 司机不用等乘客付款；乘客不用怕司机绕路。
- 短静默窗（15 分钟）后自动结算，双方都不需要盯着手机。

## 换成真生意要改什么

这个包里卖方的「业务动作」是协议内的证据动作（上报进度、上传凭证、交回执）。换成真生意时，把 `flow.milestones` / `flow.seller_proofs` 换成你自己系统的真实节点即可 —— 结算链路不用动。

> `scenario.json` 是机器可读的那份（`run_scenario.py` 按它执行），这份 README 是给人看的。两者以 `scenario.json` 为准。
