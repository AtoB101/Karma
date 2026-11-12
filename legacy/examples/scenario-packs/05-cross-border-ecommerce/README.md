# 跨境电商 · 报关清关全链路

深圳仓发 40 台设备到洛杉矶。走「实物三方 + 单证」验真：出口报关 → 物流接件核验 → 进口清关放行 → 目的地派送拍照 → 主人确认结算。

| 项 | 值 |
| --- | --- |
| 场景 ID | `cross_border_ecommerce` |
| 金额 | 8 USDC |
| 交付验真 | 实物三方验真（卖方 → 物流 → 买方） |
| 谁参与 | 买方 / 卖方 / 物流 |

## 角色

- 买方：买方（采购方）
- 卖方：卖方（出口商 agent）
- 物流：物流（跨境货代 / 承运 agent，必须与买卖双方不同）

## 怎么跑

```bash
cd examples/scenario-packs
python run_scenario.py 05-cross-border-ecommerce --wallets wallets.json
```

`wallets.json` 形如：

```json
{ "buyer": { "key": "0x..." }, "seller": { "key": "0x..." }, "logistics": { "key": "0x..." } }
```

也可以直接用环境变量：`KARMA_SCENARIO_BUYER_KEY` / `KARMA_SCENARIO_SELLER_KEY` / `KARMA_SCENARIO_LOGISTICS_KEY`。

跑完的 `task_id` 会打印出来；在操作台 `订单` 页能找到这一单，点开就是这张生意的动态状态图。

## 这一单在链路上走了什么

1. 买方建任务合同 + 结算单（`scene_id=cross_border_ecommerce`），转 pending，指派卖方 —— 钱还锁在买方自己钱包里。
2. 卖方接单开工，按里程碑上报进度。
3. 交付验真：卖方发出 → 物流接件核验（货不对板当场记录，双方共担）→ 送达拍照（带时间戳与 HMAC 的系统标签），以及单证凭证 `customs_declaration` / `customs_clearance` → 买方确认。
4. 卖方提交执行回执（结算的硬前提），然后交付。
5. 买方验收（这两类场景按规则必须主人本人点头），额度真实划转给卖方，链上/账本上都能对。

## 为什么值得用 Karma 跑

- 跨境最容易出事的是单证与货不对板：报关单、清关放行、送达拍照三段都进证据链。
- 时效长、金额大，所以结算是主人确认制，agent 只能在额度内自动推进执行。
- 清关卡住时可以走争议 / 部分结算，不必等全额才能了结。

## 换成真生意要改什么

这个包里卖方的「业务动作」是协议内的证据动作（上报进度、上传凭证、交回执）。换成真生意时，把 `flow.milestones` / `flow.seller_proofs` 换成你自己系统的真实节点即可 —— 结算链路不用动。

> `scenario.json` 是机器可读的那份（`run_scenario.py` 按它执行），这份 README 是给人看的。两者以 `scenario.json` 为准。
