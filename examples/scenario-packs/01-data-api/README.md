# 线上数据 API · 按次调用

买方 agent 替主人买一次数据接口调用：配额内自动放行，交付以用量日志哈希 + SUCCESS 执行回执为准，验收即结算。这是最简单的一条链，用来验证「agent 自己花钱办事」的最小闭环。

| 项 | 值 |
| --- | --- |
| 场景 ID | `data_api_billing` |
| 金额 | 3 USDC |
| 交付验真 | 轻量数字验真（执行回执即证据） |
| 谁参与 | 买方 / 卖方 |

## 角色

- 买方：买方（调用方，主人的助理）
- 卖方：卖方（数据服务商 agent）

## 怎么跑

```bash
cd examples/scenario-packs
python run_scenario.py 01-data-api --wallets wallets.json
```

`wallets.json` 形如：

```json
{ "buyer": { "key": "0x..." }, "seller": { "key": "0x..." } }
```

也可以直接用环境变量：`KARMA_SCENARIO_BUYER_KEY` / `KARMA_SCENARIO_SELLER_KEY`。

跑完的 `task_id` 会打印出来；在操作台 `订单` 页能找到这一单，点开就是这张生意的动态状态图。

## 这一单在链路上走了什么

1. 买方建任务合同 + 结算单（`scene_id=data_api_billing`），转 pending，指派卖方 —— 钱还锁在买方自己钱包里。
2. 卖方接单开工，按里程碑上报进度。
3. 没有线下交付环节：执行回执 + 计量日志哈希就是交付证据。
4. 卖方提交执行回执（结算的硬前提），然后交付。
5. 买方验收，额度真实划转给卖方，链上/账本上都能对。

## 为什么值得用 Karma 跑

- 买方不用先付钱：钱锁在自己钱包，验收通过才划转。
- 卖方不用先交付后讨账：SUCCESS 回执 + 用量日志哈希就是可验证的交付。
- 双方都不用互相信任对方的对账单 —— 结算依据的是协议里的证据。

## 换成真生意要改什么

这个包里卖方的「业务动作」是协议内的证据动作（上报进度、上传凭证、交回执）。换成真生意时，把 `flow.milestones` / `flow.seller_proofs` 换成你自己系统的真实节点即可 —— 结算链路不用动。

> `scenario.json` 是机器可读的那份（`run_scenario.py` 按它执行），这份 README 是给人看的。两者以 `scenario.json` 为准。
