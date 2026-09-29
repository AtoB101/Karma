# scripts/regression — 资金路径回归

部署之后自动跑一遍：**钱有没有按状态机真的走完**。全走生产 API，不改库、不打桩、
不绕过任何闸；链上那一段直接读交易回执，确认「谁 -> 谁、多少钱」。

## 跑什么

| 场景 | 路径 | 链上要看到的 |
| --- | --- | --- |
| `settle` | 下单 → 交付 → 执行回执 → 买方确认 → 放款 | 买方钱包 → 卖方钱包 的转账，金额 = 订单额 |
| `dispute` | 下单 → 交付 → 开争议 → 越权全挡 → 仲裁裁决 → 罚没 | 卖方钱包 → 买方钱包 的转账，金额 = 质押额 |

两个场景都断言：

- 该成功的一步必须成功（< 400）；越权必须被挡（争议中 buyer-accept 409 / 卖方 submit 409 / 卖方 regret 403）；
- 结算单上的链上事实必须回写（`onchain_status` / `onchain_binding_id` / `tx_hash`）——
  争议单也一样，不能停在「链上一片空白」；
- 卖方收付中心必须看得见这一单，binding 状态跟链上一致，且带 bind / submit / finalize 三笔 tx；
- 买方额度账本必须跟着动：`reserved` 下单加、结算放回、`burned` 核销；
  争议时进 `disputed`，裁决落地后放回。

## 三个脚本

- `money_path_regression.py` —— 主脚本，打 API，出报告 JSON，退出码 0/1。任何机器都能跑。
- `chain_assert.py` —— 按报告里的期望去读链上 receipt（Web3 直连），核对转账方向与金额。
  在能连 RPC 的地方跑；生产上就是 `karma-api` 容器里。
- `report_alert.py` —— 失败时往操作台写一条站内提醒（`console_notices`，
  kind=`money_regression_failed`），操作台进来看得到红点。只在服务器容器里跑。

## 手工跑

```bash
export KARMA_OWNER_API_KEY=... KARMA_BUYER_ID=kid_... KARMA_BUYER_WALLET=0x... \
       KARMA_BUYER_PK=... KARMA_SELLER_ID=kid_... KARMA_SELLER_PK=...
python scripts/regression/money_path_regression.py --scenario all --out /tmp/report.json

# 链上核对（容器里；--buyer-wallet / --seller-wallet 是这两个身份的钱包）
docker cp scripts/regression/chain_assert.py karma-api:/tmp/ && \
docker cp /tmp/report.json karma-api:/tmp/reg_report.json && \
docker exec -w /app karma-api python /tmp/chain_assert.py \
    --report /tmp/reg_report.json --buyer-wallet 0xBuyer --seller-wallet 0xSeller
```

## 部署后自动跑

`work/work_deploy.py`（本机部署入口）在 `karma deploy` 之后调
`work/run_money_regression.py`：跑回归 → 容器内做链上核对 → 失败就写站内提醒 +
落 `outputs/regression/` 报告，并以非零码退出。

产物：

- `outputs/regression/latest.json` —— 最近一次的报告（逐条断言 + 原始步骤 + 链上核对）
- `outputs/regression/history.jsonl` —— 每次跑一行（时间 / 结论 / task_id）
- `outputs/regression/alerts.log` —— 失败历史

可选：设 `KARMA_ALERT_WEBHOOK`，失败时同时往那个地址 POST 一条 `{"text": ...}`。

## 它会动真钱（测试网）

每一轮都会真建单、真上链：买方预留在链上被占住，结算/罚没时真的划 USDC；
卖方的质押会真的被划走（罚没场景）。跑完 runtime key 会当场注销，卖方 agent 复用同一把
（存在 `KARMA_REG_STATE` 指向的状态文件里），不会每跑一次堆一个 agent。
